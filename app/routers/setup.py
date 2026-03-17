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

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services import os_user_service

logger = logging.getLogger(__name__)

# Serialize concurrent initialization attempts so only one runs at a time.
_init_lock = threading.Lock()


router = APIRouter(prefix="/setup", tags=["setup"], route_class=LocalOnlyRoute)


@router.get("/status", response_model=SetupStatusResponse)
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
)
def initialize_system(
    body: SetupInitializeRequest,
    db: Session = Depends(get_db),
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
        return _do_initialize(body, db)
    finally:
        _init_lock.release()


def _do_initialize(
    body: SetupInitializeRequest,
    db: Session,
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
            detail="System was initialized by another process.",
        )

    # From here on, this worker owns initialization.  If OS operations fail,
    # we must remove the lock row so that setup can be retried.
    try:
        groups_created = _run_os_setup(body)
    except HTTPException:
        _release_init_lock(db)
        raise
    except Exception:
        _release_init_lock(db)
        logger.exception("Unexpected error during OS setup")
        raise HTTPException(
            status_code=500,
            detail="Unexpected error during system initialization.",
        )

    # Step 4: Seed admin role now that OS setup succeeded.
    try:
        db.add(UserRole(username=body.username, role="admin"))
        db.commit()
    except Exception:
        # If seeding the admin role fails, roll back and release the
        # initialization lock so that setup can be retried safely.
        db.rollback()
        _release_init_lock(db)
        logger.exception("Failed to seed admin role for %s", body.username)
        raise HTTPException(
            status_code=500,
            detail="OS setup succeeded but failed to seed admin role in the database.",
        )

    # Step 5: Audit log.
    try:
        AuditRepository(db).add(
            action="SYSTEM_INITIALIZED",
            user=body.username,
            details={
                "groups_created": groups_created,
                "admin_user": body.username,
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for SYSTEM_INITIALIZED")

    return SetupInitializeResponse(
        message="Setup complete",
        username=body.username,
        groups_created=groups_created,
    )


def _release_init_lock(db: Session) -> None:
    """Delete the system_initialization row so setup can be retried."""
    try:
        db.query(SystemInitialization).filter(
            SystemInitialization.id == 1,
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to release initialization lock")


def _run_os_setup(
    body: SetupInitializeRequest,
) -> list[str]:
    """Execute OS-level setup: create groups and the admin user.

    Returns the list of groups created.
    Raises :class:`HTTPException` on failure.
    """
    # Step 2: Create ECUBE OS groups.
    try:
        groups_created = os_user_service.ensure_ecube_groups()
    except os_user_service.OSUserError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create OS groups: {exc.message}",
        )

    # Step 3: Create the admin OS user.
    try:
        os_user_service.create_user(
            username=body.username,
            password=body.password,
            groups=["ecube-admins"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except os_user_service.OSUserError as exc:
        # User may already exist (e.g. re-running setup after partial failure).
        if "already exists" not in exc.message:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create admin user: {exc.message}",
            )
        # Recover: append to ecube-admins (preserving existing groups) and
        # reset the password so the caller's credentials are guaranteed valid.
        try:
            os_user_service.add_user_to_groups(body.username, ["ecube-admins"])
        except os_user_service.OSUserError as grp_exc:
            raise HTTPException(
                status_code=500,
                detail=f"User exists but failed to add to ecube-admins: {grp_exc.message}",
            )
        try:
            os_user_service.reset_password(body.username, body.password)
        except (os_user_service.OSUserError, ValueError) as pw_exc:
            raise HTTPException(
                status_code=500,
                detail=f"User exists but failed to reset password: {pw_exc}",
            )

    return groups_created
