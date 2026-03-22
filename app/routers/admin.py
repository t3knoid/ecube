"""Administrative endpoints for log file access and OS user/group management.

Log endpoints allow authenticated users to list and download application log
files.  OS user/group endpoints allow ``admin``-role users to create, list,
delete, reset passwords, and modify group memberships for OS users, as well
as create, list, and delete OS groups through the API.

Security considerations
-----------------------
* **Path traversal protection**: the ``{filename}`` parameter is validated
  against ``os.path.basename`` and must match a real file inside the
  configured log directory.  Attempts to escape the directory (e.g.
  ``../../etc/passwd``) are rejected with ``400 Bad Request``.
* **Authentication required**: both log endpoints require a valid JWT bearer
  token (enforced at the router level via ``get_current_user``).  No
  additional role restriction is applied — all authenticated users may
  access log files.
* **Admin-only OS management**: all ``/admin/os-users`` and ``/admin/os-groups``
  endpoints are gated with ``require_roles("admin")``.
* **Password handling**: passwords are never logged, stored in the database,
  or returned in API responses.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user, require_roles
from app.config import settings
from app.routing import LocalOnlyRoute
from app.database import get_db
from app.repositories.audit_repository import AuditRepository, best_effort_audit
from app.repositories.hardware_repository import HubRepository, PortRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.admin import (
    AddOSGroupsRequest,
    CreateOSGroupRequest,
    CreateOSUserRequest,
    LogFileInfo,
    LogFilesResponse,
    OSGroupListResponse,
    OSGroupResponse,
    OSUserListResponse,
    OSUserResponse,
    ResetPasswordRequest,
    SetOSGroupsRequest,
)
from app.schemas.hardware import HubUpdateRequest, PortEnableRequest, PortUpdateRequest, UsbHubSchema, UsbPortSchema
from app.infrastructure import get_os_user_provider
from app.infrastructure.os_user_protocol import OSUserError, OsUserProvider
from app.schemas.errors import R_400, R_401, R_403, R_404, R_409, R_422, R_500, R_504
from app.services.os_user_service import validate_group_name, validate_username
from app.constants import GROUPNAME_PATTERN, USERNAME_PATTERN
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)


def _get_provider() -> OsUserProvider:
    return get_os_user_provider()


def _raise_os_error(exc: OSUserError, *, context: str = "OS operation") -> None:
    """Map an :class:`OSUserError` to an appropriate HTTP error and raise it.

    * ``"already exists"`` → 409 Conflict
    * ``"Group ... does not exist"`` → 422 Unprocessable Entity
    * other ``"does not exist"`` → 404 Not Found
    * ``"timed out"``      → 504 Gateway Timeout
    * everything else      → 500 Internal Server Error
    """
    msg = exc.message or str(exc) or f"{context} failed"
    lowered = msg.lower()
    stripped = msg.lstrip()

    if "already exists" in lowered:
        raise HTTPException(status_code=409, detail=msg)
    if "does not exist" in lowered:
        # Distinguish between missing groups (input validation) and other entities.
        # Messages for group validation errors are expected to start with "Group ".
        if stripped.lower().startswith("group "):
            # Request body referenced a non-existent group: the endpoint exists,
            # but the provided value is invalid.
            raise HTTPException(status_code=422, detail=msg)
        raise HTTPException(status_code=404, detail=msg)
    if "timed out" in lowered:
        raise HTTPException(status_code=504, detail=msg)

    logger.error("%s failed: %s", context, msg, exc_info=True)
    raise HTTPException(status_code=500, detail=msg)


router = APIRouter(prefix="/admin", tags=["admin"])


def _log_directory() -> Optional[str]:
    """Return the configured log directory, or ``None`` if logging to file is
    not enabled."""
    if not settings.log_file:
        return None
    return os.path.dirname(os.path.abspath(settings.log_file))


def _safe_filename(filename: str) -> str:
    """Validate *filename* to prevent path traversal.

    Returns the sanitised basename if valid; raises ``HTTPException(400)``
    otherwise.
    """
    safe = os.path.basename(filename)
    if not safe or safe != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: path traversal is not allowed",
        )
    return safe


@router.get("/logs", response_model=LogFilesResponse, responses={**R_401, **R_404})
def list_log_files(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List available log files with metadata (size, timestamps).

    Requires authentication (all authenticated users have access; no role
    restriction).

    Returns ``200`` with file list, or ``404`` if file-based logging is not
    configured.
    """
    log_dir = _log_directory()
    if not log_dir or not os.path.isdir(log_dir):
        raise HTTPException(
            status_code=404,
            detail="File-based logging is not configured or log directory does not exist",
        )

    files: List[LogFileInfo] = []
    base_name = os.path.basename(settings.log_file)  # type: ignore[arg-type]
    for entry in sorted(os.listdir(log_dir)):
        # Only expose log files that share the base name prefix (e.g.
        # "app.log", "app.log.1", "app.log.2").
        if not entry.startswith(base_name):
            continue
        full = os.path.join(log_dir, entry)
        if not os.path.isfile(full):
            continue
        stat = os.stat(full)
        files.append(
            LogFileInfo(
                name=entry,
                size=stat.st_size,
                created=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    total_size = sum(f.size for f in files)

    # Record access in audit trail.
    try:
        AuditRepository(db).add(
            action="LOG_FILES_LISTED",
            user=current_user.username,
            details={"file_count": len(files), "total_size": total_size},
            client_ip=get_client_ip(request),
        )
    except Exception:
        logger.debug("Failed to record log file list access in audit trail", exc_info=True)

    return LogFilesResponse(
        log_files=files,
        total_size=total_size,
        log_directory=log_dir,
    )


@router.get("/logs/{filename}", responses={**R_400, **R_401, **R_404, **R_422})
def download_log_file(
    filename: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Download a specific log file.

    Requires authentication (all authenticated users have access; no role
    restriction).

    The ``{filename}`` parameter is validated to prevent path traversal.
    """
    log_dir = _log_directory()
    if not log_dir or not os.path.isdir(log_dir):
        raise HTTPException(
            status_code=404,
            detail="File-based logging is not configured or log directory does not exist",
        )

    safe = _safe_filename(filename)
    full_path = os.path.join(log_dir, safe)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Log file not found")

    # Record access in audit trail.
    try:
        AuditRepository(db).add(
            action="LOG_FILE_DOWNLOADED",
            user=current_user.username,
            details={"filename": safe},
            client_ip=get_client_ip(request),
        )
    except Exception:
        logger.debug("Failed to record log file download in audit trail", exc_info=True)

    return FileResponse(
        path=full_path,
        filename=safe,
        media_type="text/plain",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_path_username(username: str) -> str:
    """Validate a username path parameter."""
    try:
        validate_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return username


# Sub-router for OS user/group endpoints.  The custom route class
# ensures that non-local deployments get a clean 404 *before* any auth
# dependency resolution, so callers never see 401/403 for endpoints
# that conceptually don't exist in that deployment mode.
_os_router = APIRouter(
    route_class=LocalOnlyRoute,
)


# ---------------------------------------------------------------------------
# OS user management endpoints — all require admin role
# ---------------------------------------------------------------------------


@_os_router.post("/os-users", response_model=OSUserResponse, status_code=201, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500, **R_504})
def create_os_user(
    body: CreateOSUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserResponse:
    """Create an OS user, set password, and optionally add to groups."""
    provider = _get_provider()
    try:
        os_user = provider.create_user(
            username=body.username,
            password=body.password,
            groups=body.groups,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Create OS user")

    # Assign ECUBE DB roles if requested.
    if body.roles:
        repo = UserRoleRepository(db)
        deduplicated = sorted(set(body.roles))
        try:
            repo.set_roles(body.username, deduplicated)
        except ValueError as exc:
            # Invalid role name — shouldn't reach here (schema validates), but
            # guard defensively.  The OS user was already created; delete it to
            # avoid leaving partial state.
            try:
                provider.delete_user(body.username, _skip_managed_check=True)
            except Exception:
                logger.exception(
                    "Failed to clean up OS user '%s' after role validation error",
                    body.username,
                )
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception:
            # DB failure — OS user exists but role assignment failed.
            db.rollback()
            try:
                provider.delete_user(body.username, _skip_managed_check=True)
            except Exception:
                logger.exception(
                    "Failed to clean up OS user '%s' after DB error in set_roles",
                    body.username,
                )
            logger.exception(
                "Failed to assign roles to OS user '%s'", body.username
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    f"OS user '{body.username}' was created but role assignment "
                    "failed. The user has been removed. Please retry."
                ),
            )

    best_effort_audit(db, "OS_USER_CREATED", current_user.username, {
        "target_user": body.username,
        "groups": body.groups or [],
        "roles": list(body.roles) if body.roles else [],
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return OSUserResponse(
        username=os_user.username,
        uid=os_user.uid,
        gid=os_user.gid,
        home=os_user.home,
        shell=os_user.shell,
        groups=os_user.groups,
    )


@_os_router.get("/os-users", response_model=OSUserListResponse, responses={**R_401, **R_403, **R_404})
def list_os_users(
    _current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserListResponse:
    """List OS users filtered to ECUBE-relevant groups."""
    users = _get_provider().list_users(ecube_only=True)
    return OSUserListResponse(
        users=[
            OSUserResponse(
                username=u.username,
                uid=u.uid,
                gid=u.gid,
                home=u.home,
                shell=u.shell,
                groups=u.groups,
            )
            for u in users
        ]
    )


@_os_router.delete("/os-users/{username}", status_code=200, responses={**R_401, **R_403, **R_404, **R_422, **R_500, **R_504})
def delete_os_user(
    request: Request,
    username: str = Path(..., pattern=USERNAME_PATTERN),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Delete an OS user and remove their DB role assignments."""
    _validate_path_username(username)

    try:
        _get_provider().delete_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Delete OS user")

    # Clean up DB role assignments (best-effort: OS user is already gone).
    try:
        UserRoleRepository(db).delete_roles(username)
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to delete DB roles for OS user '%s' after OS deletion. "
            "Stale rows may remain in user_roles.",
            username,
        )

    best_effort_audit(db, "OS_USER_DELETED", current_user.username, {
        "target_user": username,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return {"message": f"User '{username}' deleted"}


@_os_router.put("/os-users/{username}/password", status_code=200, responses={**R_401, **R_403, **R_404, **R_422, **R_500, **R_504})
def reset_os_user_password(
    username: str = Path(..., pattern=USERNAME_PATTERN),
    *,
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Reset an OS user's password via ``chpasswd``."""
    _validate_path_username(username)

    try:
        _get_provider().reset_password(username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Reset OS password")

    best_effort_audit(db, "OS_PASSWORD_RESET", current_user.username, {
        "target_user": username,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return {"message": f"Password reset for user '{username}'"}


@_os_router.put("/os-users/{username}/groups", response_model=OSUserResponse, responses={**R_401, **R_403, **R_404, **R_422, **R_500, **R_504})
def set_os_user_groups(
    username: str = Path(..., pattern=USERNAME_PATTERN),
    *,
    body: SetOSGroupsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserResponse:
    """Modify an OS user's group memberships."""
    _validate_path_username(username)

    try:
        os_user = _get_provider().set_user_groups(username, body.groups)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Set OS user groups")

    best_effort_audit(db, "OS_USER_GROUPS_MODIFIED", current_user.username, {
        "target_user": username,
        "groups": body.groups,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return OSUserResponse(
        username=os_user.username,
        uid=os_user.uid,
        gid=os_user.gid,
        home=os_user.home,
        shell=os_user.shell,
        groups=os_user.groups,
    )


@_os_router.post("/os-users/{username}/groups", response_model=OSUserResponse, responses={**R_401, **R_403, **R_404, **R_422, **R_500, **R_504})
def add_os_user_groups(
    username: str = Path(..., pattern=USERNAME_PATTERN),
    *,
    body: AddOSGroupsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserResponse:
    """Add an OS user to additional groups without removing existing memberships."""
    _validate_path_username(username)

    try:
        os_user = _get_provider().add_user_to_groups(username, body.groups)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Add OS user to groups")

    best_effort_audit(db, "OS_USER_GROUPS_APPENDED", current_user.username, {
        "target_user": username,
        "groups_added": body.groups,
        "resulting_groups": os_user.groups,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return OSUserResponse(
        username=os_user.username,
        uid=os_user.uid,
        gid=os_user.gid,
        home=os_user.home,
        shell=os_user.shell,
        groups=os_user.groups,
    )


# ---------------------------------------------------------------------------
# OS group management endpoints — all require admin role
# ---------------------------------------------------------------------------


@_os_router.post("/os-groups", response_model=OSGroupResponse, status_code=201, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500, **R_504})
def create_os_group(
    body: CreateOSGroupRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSGroupResponse:
    """Create a new OS group on the host system."""
    try:
        os_group = _get_provider().create_group(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Create OS group")

    best_effort_audit(db, "OS_GROUP_CREATED", current_user.username, {
        "group_name": body.name,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return OSGroupResponse(
        name=os_group.name,
        gid=os_group.gid,
        members=os_group.members,
    )


@_os_router.get("/os-groups", response_model=OSGroupListResponse, responses={**R_401, **R_403, **R_404})
def list_os_groups(
    _current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSGroupListResponse:
    """List OS groups filtered to ECUBE-relevant names."""
    groups = _get_provider().list_groups(ecube_only=True)
    return OSGroupListResponse(
        groups=[
            OSGroupResponse(name=g.name, gid=g.gid, members=g.members)
            for g in groups
        ]
    )


@_os_router.delete("/os-groups/{name}", status_code=200, responses={**R_401, **R_403, **R_404, **R_422, **R_500, **R_504})
def delete_os_group(
    request: Request,
    name: str = Path(..., pattern=GROUPNAME_PATTERN),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Delete an OS group from the host system."""
    try:
        validate_group_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        _get_provider().delete_group(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        _raise_os_error(exc, context="Delete OS group")

    best_effort_audit(db, "OS_GROUP_DELETED", current_user.username, {
        "group_name": name,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return {"message": f"Group '{name}' deleted"}


# ---------------------------------------------------------------------------
# Port enablement endpoints — admin or manager role
# ---------------------------------------------------------------------------


@router.get("/ports", response_model=List[UsbPortSchema], responses={**R_401, **R_403})
def list_ports(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> List[UsbPortSchema]:
    """List all USB ports with their enabled state."""
    ports = PortRepository(db).list_all()
    return [UsbPortSchema.model_validate(p) for p in ports]


@router.patch("/ports/{port_id}", response_model=UsbPortSchema, responses={**R_401, **R_403, **R_404, **R_422})
def toggle_port_enabled(
    port_id: int,
    body: PortEnableRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> UsbPortSchema:
    """Enable or disable a USB port for ECUBE use."""
    port = PortRepository(db).set_enabled(port_id, body.enabled)
    if port is None:
        raise HTTPException(status_code=404, detail="Port not found")

    action = "PORT_ENABLED" if body.enabled else "PORT_DISABLED"
    best_effort_audit(db, action, current_user.username, {
        "port_id": port.id,
        "system_path": port.system_path,
        "hub_id": port.hub_id,
        "enabled": body.enabled,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return UsbPortSchema.model_validate(port)


# ---------------------------------------------------------------------------
# Hub Management
# ---------------------------------------------------------------------------


@router.get("/hubs", response_model=List[UsbHubSchema], responses={**R_401, **R_403})
def list_hubs(
    db: Session = Depends(get_db),
    _current_user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> List[UsbHubSchema]:
    """List all USB hubs with enriched hardware metadata."""
    hubs = HubRepository(db).list_all()
    return [UsbHubSchema.model_validate(h) for h in hubs]


@router.patch("/hubs/{hub_id}", response_model=UsbHubSchema, responses={**R_401, **R_403, **R_404, **R_422})
def update_hub_label(
    hub_id: int,
    body: HubUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> UsbHubSchema:
    """Set or update the location_hint label on a USB hub."""
    hub_repo = HubRepository(db)
    existing = hub_repo.get(hub_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Hub not found")

    old_value = existing.location_hint
    hub = hub_repo.update_location_hint(hub_id, body.location_hint)
    if hub is None:
        raise HTTPException(status_code=404, detail="Hub not found")

    best_effort_audit(db, "HUB_LABEL_UPDATED", current_user.username, {
        "hub_id": hub.id,
        "system_identifier": hub.system_identifier,
        "field": "location_hint",
        "old_value": old_value,
        "new_value": body.location_hint,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return UsbHubSchema.model_validate(hub)


@router.patch("/ports/{port_id}/label", response_model=UsbPortSchema, responses={**R_401, **R_403, **R_404, **R_422})
def update_port_label(
    port_id: int,
    body: PortUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin", "manager")),
) -> UsbPortSchema:
    """Set or update the friendly_label on a USB port."""
    port_repo = PortRepository(db)
    existing = port_repo.get(port_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Port not found")

    old_value = existing.friendly_label
    port = port_repo.update_friendly_label(port_id, body.friendly_label)
    if port is None:
        raise HTTPException(status_code=404, detail="Port not found")

    best_effort_audit(db, "PORT_LABEL_UPDATED", current_user.username, {
        "port_id": port.id,
        "system_path": port.system_path,
        "field": "friendly_label",
        "old_value": old_value,
        "new_value": body.friendly_label,
        "path": str(request.url.path),
    }, client_ip=get_client_ip(request))

    return UsbPortSchema.model_validate(port)


# Include the OS sub-router under the /admin prefix.
router.include_router(_os_router)
