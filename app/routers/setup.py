"""First-run setup wizard endpoints.

These endpoints provide an API-based alternative to ``sudo python -m app.setup``
for bootstrapping an ECUBE installation.  They are guarded by a **first-run
check**: once at least one admin user exists in ``user_roles``, the
``POST /setup/initialize`` endpoint returns ``409 Conflict``.

The ``GET /setup/status`` endpoint is **unauthenticated** so that a setup
wizard UI can check whether initialization is needed before any users exist.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
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
        if "already exists" in exc.message:
            # Add to ecube-admins group anyway.
            try:
                os_user_service.set_user_groups(body.username, ["ecube-admins"])
            except os_user_service.OSUserError:
                pass
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create admin user: {exc.message}",
            )

    # Step 3: Seed database with admin role.
    db.add(UserRole(username=body.username, role="admin"))
    db.commit()

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
