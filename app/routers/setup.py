"""First-run setup wizard endpoints.

These endpoints provide an API-based alternative to ``sudo python -m app.setup``
for bootstrapping an ECUBE installation.  They are guarded by a **first-run
check**: once at least one admin user exists in ``user_roles``, the
``POST /setup/initialize`` endpoint returns ``409 Conflict``.

A cross-process guard (the ``system_initialization`` table with a single-row
constraint) ensures that only one worker can successfully complete
initialization, even when running multiple uvicorn workers.  A process-local
thread lock provides an additional optimization to avoid redundant OS
operations within the same process.

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

from app.config import settings
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

router = APIRouter(prefix="/setup", tags=["setup"])

# Serialize concurrent initialization attempts so only one runs at a time.
_init_lock = threading.Lock()


def _ensure_local_mode() -> None:
    """Block setup endpoints when the role resolver is not ``local``.

    In LDAP/OIDC deployments, OS user/group management is handled by the
    directory service and the setup wizard must not create local accounts.
    """
    if getattr(settings, "role_resolver", "local") != "local":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )


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
    _ensure_local_mode()
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
    _ensure_local_mode()
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

    # Step 1: Create ECUBE OS groups.
    try:
        groups_created = os_user_service.ensure_ecube_groups()
    except os_user_service.OSUserError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create OS groups: {exc.message}",
        )

    # Step 2: Create the admin OS user.
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

    # Step 3: Seed database with admin role and mark system as initialized.
    # The single-row constraint on system_initialization ensures that even
    # if two workers race past the has_any_admin() check and both complete
    # OS operations, only one can successfully commit.
    db.add(SystemInitialization(
        id=1,
        initialized_by=body.username,
        initialized_at=datetime.now(timezone.utc),
    ))
    db.add(UserRole(username=body.username, role="admin"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System was initialized by another process.",
        )

    # Step 4: Audit log.
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
