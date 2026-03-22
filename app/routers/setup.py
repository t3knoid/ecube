"""First-run setup wizard endpoints.

These endpoints provide an API-based alternative to ``sudo python -m app.setup``
for bootstrapping an ECUBE installation.  They are guarded by a **first-run
check**: once at least one admin user exists in ``user_roles``, the
``POST /setup/initialize`` endpoint returns ``409 Conflict``.

A cross-process guard (the ``system_initialization`` table with a single-row
``CHECK (id = 1)`` constraint) ensures that only one worker can win
initialization across multiple uvicorn workers.  The guard is acquired
**before** any OS side-effects: the row is inserted and committed first; if
OS operations subsequently fail, the row is deleted so that setup can be
retried.  A process-local thread lock provides an additional optimization to
avoid redundant OS work within the same process.

The ``GET /setup/status`` endpoint is **unauthenticated** so that a setup
wizard UI can check whether initialization is needed before any users exist.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routing import LocalOnlyRoute
from app.database import get_db
from app.models.system import SystemInitialization
from app.models.users import UserRole
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.admin import (
    SetupInitializeRequest,
    SetupInitializeResponse,
    SetupStatusResponse,
)
from app.infrastructure import get_os_user_provider
from app.infrastructure.os_user_protocol import OSUserError
from app.schemas.errors import R_404, R_409, R_422, R_500
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

# Serialize concurrent initialization attempts so only one runs at a time.
_init_lock = threading.Lock()


router = APIRouter(prefix="/setup", tags=["setup"], route_class=LocalOnlyRoute)


@router.get("/status", response_model=SetupStatusResponse, responses={**R_404, **R_500})
def get_setup_status(
    db: Session = Depends(get_db),
) -> SetupStatusResponse:
    """Check whether the system has been initialized.

    Returns ``{"initialized": false}`` when no admin user exists in the
    database, indicating that ``POST /setup/initialize`` can be called.

    This endpoint is **unauthenticated** — it is safe to call before any
    users exist.
    """
    repo = UserRoleRepository(db)
    return SetupStatusResponse(initialized=repo.has_any_admin())


@router.post(
    "/initialize",
    response_model=SetupInitializeResponse,
    status_code=200,
    responses={**R_404, **R_409, **R_422, **R_500},
)
def initialize_system(
    body: SetupInitializeRequest,
    *,
    db: Session = Depends(get_db),
    request: Request,
) -> SetupInitializeResponse:
    """Perform first-run system initialization.

    Creates OS groups, creates the admin OS user, sets the password, adds
    the user to ``ecube-admins``, and seeds the database with the admin role.

    **First-run guard:** Returns ``409 Conflict`` if an admin user already
    exists in the database.

    This endpoint is **unauthenticated** — it can only succeed once, before
    any admin exists.
    """
    repo = UserRoleRepository(db)
    if repo.has_any_admin():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System is already initialized. An admin user exists.",
        )

    if not _init_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initialization is already in progress.",
        )
    try:
        # Re-check under the lock to prevent TOCTOU races.
        if repo.has_any_admin():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="System is already initialized. An admin user exists.",
            )
        return _do_initialize(body, db, client_ip=get_client_ip(request))
    finally:
        _init_lock.release()


def _do_initialize(
    body: SetupInitializeRequest,
    db: Session,
    client_ip: Optional[str] = None,
) -> SetupInitializeResponse:

    # Step 1: Acquire the cross-process guard BEFORE any OS side-effects.
    # The single-row CHECK constraint ensures only one worker can succeed.
    db.add(SystemInitialization(
        id=1,
        initialized_by=body.username,
        initialized_at=datetime.now(timezone.utc),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "System initialization is already in progress or has completed. "
                "If a previous attempt failed, the lock row may need to be "
                "removed manually: DELETE FROM system_initialization WHERE id = 1;"
            ),
        )

    # From here on, this worker owns initialization.  If OS operations fail,
    # we must remove the lock row so that setup can be retried.
    try:
        groups_created = _run_os_setup(body)
    except HTTPException as exc:
        if not _release_init_lock(db):
            exc.detail += _LOCK_STUCK_SUFFIX
        raise
    except Exception:
        lock_released = _release_init_lock(db)
        logger.exception("Unexpected error during OS setup")
        detail = (
            "An unexpected error occurred during system initialization. "
            "OS groups or the admin user may have been partially created. "
        )
        if lock_released:
            detail += (
                "The initialization lock has been released so you can "
                "safely retry POST /setup/initialize."
            )
        else:
            detail += _LOCK_STUCK_SUFFIX
        raise HTTPException(status_code=500, detail=detail)

    # Step 4: Seed admin role now that OS setup succeeded.
    try:
        db.add(UserRole(username=body.username, role="admin"))
        db.commit()
    except Exception:
        # If seeding the admin role fails, roll back and release the
        # initialization lock so that setup can be retried safely.
        db.rollback()
        lock_released = _release_init_lock(db)
        logger.exception("Failed to seed admin role for %s", body.username)
        detail = (
            f"OS setup completed successfully (user '{body.username}' was created "
            "and ECUBE groups exist), but writing the admin role to the database "
            "failed. The user exists on the host but has no ECUBE role assignment. "
        )
        if lock_released:
            detail += (
                "The initialization lock has been released so you can "
                "safely retry POST /setup/initialize. The retry will "
                "detect the existing OS user and reset its password."
            )
        else:
            detail += _LOCK_STUCK_SUFFIX
        raise HTTPException(status_code=500, detail=detail)

    # Step 5: Audit log.
    try:
        AuditRepository(db).add(
            action="SYSTEM_INITIALIZED",
            user=body.username,
            details={
                "groups_created": groups_created,
                "admin_user": body.username,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for SYSTEM_INITIALIZED")

    return SetupInitializeResponse(
        message="Setup complete",
        username=body.username,
        groups_created=groups_created,
    )


_LOCK_STUCK_SUFFIX = (
    " Additionally, the initialization lock could not be released."
    " Manual intervention required:"
    " DELETE FROM system_initialization WHERE id = 1;"
)


def _release_init_lock(db: Session) -> bool:
    """Delete the system_initialization row so setup can be retried.

    Returns ``True`` if the lock was successfully released, ``False`` if the
    delete failed (the row is stuck and manual cleanup is required).
    """
    try:
        db.query(SystemInitialization).filter(
            SystemInitialization.id == 1,
        ).delete()
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.critical(
            "Failed to release initialization lock row"
            " (system_initialization.id=1). Future /setup/initialize calls"
            " will return 409 until the row is manually deleted:"
            " DELETE FROM system_initialization WHERE id = 1;",
            exc_info=True,
        )
        return False


def _run_os_setup(
    body: SetupInitializeRequest,
) -> list[str]:
    """Execute OS-level setup: create groups and the admin user.

    Returns the list of groups created.
    Raises :class:`HTTPException` on failure.
    """
    provider = get_os_user_provider()

    # Step 2: Create ECUBE OS groups.
    try:
        groups_created = provider.ensure_ecube_groups()
    except OSUserError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create OS groups: {exc.message}",
        )

    # Step 3: Create the admin OS user.
    try:
        provider.create_user(
            username=body.username,
            password=body.password,
            groups=["ecube-admins"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        # User may already exist (e.g. re-running setup after partial failure).
        if "already exists" not in exc.message:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create admin user: {exc.message}",
            )
        # Recover: append to ecube-admins (preserving existing groups) and
        # reset the password so the caller's credentials are guaranteed valid.
        try:
            provider.add_user_to_groups(
                body.username, ["ecube-admins"], _skip_managed_check=True,
            )
        except OSUserError as grp_exc:
            raise HTTPException(
                status_code=500,
                detail=f"User exists but failed to add to ecube-admins: {grp_exc.message}",
            )
        try:
            provider.reset_password(
                body.username, body.password, _skip_managed_check=True,
            )
        except (OSUserError, ValueError) as pw_exc:
            raise HTTPException(
                status_code=500,
                detail=f"User exists but failed to reset password: {pw_exc}",
            )

    return groups_created
