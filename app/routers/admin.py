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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user, require_roles
from app.config import settings
from app.routing import LocalOnlyRoute
from app.database import get_db
from app.repositories.audit_repository import AuditRepository
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
from app.services import os_user_service

logger = logging.getLogger(__name__)


def _raise_os_error(exc: os_user_service.OSUserError, *, context: str = "OS operation") -> None:
    """Map an :class:`OSUserError` to an appropriate HTTP error and raise it.

    * ``"already exists"`` → 409 Conflict
    * ``"does not exist"`` → 404 Not Found
    * ``"timed out"``      → 504 Gateway Timeout
    * everything else      → 500 Internal Server Error
    """
    msg = exc.message or str(exc) or f"{context} failed"
    lowered = msg.lower()

    if "already exists" in lowered:
        raise HTTPException(status_code=409, detail=msg)
    if "does not exist" in lowered:
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


@router.get("/logs", response_model=LogFilesResponse)
def list_log_files(
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
        )
    except Exception:
        logger.debug("Failed to record log file list access in audit trail", exc_info=True)

    return LogFilesResponse(
        log_files=files,
        total_size=total_size,
        log_directory=log_dir,
    )


@router.get("/logs/{filename}")
def download_log_file(
    filename: str,
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
        os_user_service.validate_username(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return username


def _audit(db: Session, action: str, actor: str, details: dict) -> None:
    """Best-effort audit log.  Never raises."""
    try:
        AuditRepository(db).add(action=action, user=actor, details=details)
    except Exception:
        logger.exception("Failed to write audit log for %s", action)


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


@_os_router.post("/os-users", response_model=OSUserResponse, status_code=201)
def create_os_user(
    body: CreateOSUserRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserResponse:
    """Create an OS user, set password, and optionally add to groups."""
    try:
        os_user = os_user_service.create_user(
            username=body.username,
            password=body.password,
            groups=body.groups,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Create OS user")

    # Assign ECUBE DB roles if requested.
    if body.roles:
        repo = UserRoleRepository(db)
        deduplicated = sorted(set(body.roles))
        repo.set_roles(body.username, deduplicated)

    _audit(db, "OS_USER_CREATED", current_user.username, {
        "target_user": body.username,
        "groups": body.groups or [],
        "roles": list(body.roles) if body.roles else [],
        "path": str(request.url.path),
    })

    return OSUserResponse(
        username=os_user.username,
        uid=os_user.uid,
        gid=os_user.gid,
        home=os_user.home,
        shell=os_user.shell,
        groups=os_user.groups,
    )


@_os_router.get("/os-users", response_model=OSUserListResponse)
def list_os_users(
    _current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserListResponse:
    """List OS users filtered to ECUBE-relevant groups."""
    users = os_user_service.list_users(ecube_only=True)
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


@_os_router.delete("/os-users/{username}", status_code=200)
def delete_os_user(
    username: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Delete an OS user and remove their DB role assignments."""
    _validate_path_username(username)

    try:
        os_user_service.delete_user(username)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Delete OS user")

    # Clean up DB role assignments.
    UserRoleRepository(db).delete_roles(username)

    _audit(db, "OS_USER_DELETED", current_user.username, {
        "target_user": username,
        "path": str(request.url.path),
    })

    return {"message": f"User '{username}' deleted"}


@_os_router.put("/os-users/{username}/password", status_code=200)
def reset_os_user_password(
    username: str,
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Reset an OS user's password via ``chpasswd``."""
    _validate_path_username(username)

    try:
        os_user_service.reset_password(username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Reset OS password")

    _audit(db, "OS_PASSWORD_RESET", current_user.username, {
        "target_user": username,
        "path": str(request.url.path),
    })

    return {"message": f"Password reset for user '{username}'"}


@_os_router.put("/os-users/{username}/groups", response_model=OSUserResponse)
def set_os_user_groups(
    username: str,
    body: SetOSGroupsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserResponse:
    """Modify an OS user's group memberships."""
    _validate_path_username(username)

    try:
        os_user = os_user_service.set_user_groups(username, body.groups)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Set OS user groups")

    _audit(db, "OS_USER_GROUPS_MODIFIED", current_user.username, {
        "target_user": username,
        "groups": body.groups,
        "path": str(request.url.path),
    })

    return OSUserResponse(
        username=os_user.username,
        uid=os_user.uid,
        gid=os_user.gid,
        home=os_user.home,
        shell=os_user.shell,
        groups=os_user.groups,
    )


@_os_router.post("/os-users/{username}/groups", response_model=OSUserResponse)
def add_os_user_groups(
    username: str,
    body: AddOSGroupsRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSUserResponse:
    """Add an OS user to additional groups without removing existing memberships."""
    _validate_path_username(username)

    try:
        os_user = os_user_service.add_user_to_groups(username, body.groups)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Add OS user to groups")

    _audit(db, "OS_USER_GROUPS_APPENDED", current_user.username, {
        "target_user": username,
        "groups_added": body.groups,
        "resulting_groups": os_user.groups,
        "path": str(request.url.path),
    })

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


@_os_router.post("/os-groups", response_model=OSGroupResponse, status_code=201)
def create_os_group(
    body: CreateOSGroupRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSGroupResponse:
    """Create a new OS group on the host system."""
    try:
        os_group = os_user_service.create_group(body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Create OS group")

    _audit(db, "OS_GROUP_CREATED", current_user.username, {
        "group_name": body.name,
        "path": str(request.url.path),
    })

    return OSGroupResponse(
        name=os_group.name,
        gid=os_group.gid,
        members=os_group.members,
    )


@_os_router.get("/os-groups", response_model=OSGroupListResponse)
def list_os_groups(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> OSGroupListResponse:
    """List OS groups filtered to ECUBE-relevant names."""
    groups = os_user_service.list_groups(ecube_only=True)
    return OSGroupListResponse(
        groups=[
            OSGroupResponse(name=g.name, gid=g.gid, members=g.members)
            for g in groups
        ]
    )


@_os_router.delete("/os-groups/{name}", status_code=200)
def delete_os_group(
    name: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> dict:
    """Delete an OS group from the host system."""
    try:
        os_user_service.validate_group_name(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        os_user_service.delete_group(name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        _raise_os_error(exc, context="Delete OS group")

    _audit(db, "OS_GROUP_DELETED", current_user.username, {
        "group_name": name,
        "path": str(request.url.path),
    })

    return {"message": f"Group '{name}' deleted"}


# Include the OS sub-router under the /admin prefix.
router.include_router(_os_router)
