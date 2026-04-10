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
from typing import Literal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routing import LocalOnlyRoute
from app.database import get_db
from app.models.system import SystemInitialization
from app.models.users import UserRole
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.services import database_service
from app.schemas.admin import (
    SetupInitializeRequest,
    SetupInitializeResponse,
    SetupStatusResponse,
)
from app.infrastructure import get_os_user_provider
from app.infrastructure.os_user_protocol import OSUserError
from app.schemas.errors import R_400, R_404, R_409, R_422, R_500
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

# Serialize concurrent initialization attempts so only one runs at a time.
_init_lock = threading.Lock()


router = APIRouter(prefix="/setup", tags=["setup"], route_class=LocalOnlyRoute)


def _get_db_or_none():
    """Yield a DB session, or ``None`` when DB is not configured yet."""
    db_module = __import__("app.database", fromlist=["SessionLocal", "is_database_configured"])
    if not db_module.is_database_configured():
        yield None
        return

    try:
        db = db_module.SessionLocal()
    except Exception:
        yield None
        return

    try:
        yield db
    finally:
        db.close()


def _is_missing_table_error(exc: ProgrammingError) -> bool:
    """Return True when *exc* indicates an unmigrated/missing table."""
    msg = str(exc).lower()
    return (
        "relation" in msg and "does not exist" in msg
    ) or "undefinedtable" in msg


def _has_any_admin_with_auto_migrate(repo: UserRoleRepository, db: Session) -> bool:
    """Return admin-exists status, auto-running migrations when schema is missing."""
    try:
        return repo.has_any_admin()
    except ProgrammingError as exc:
        db.rollback()
        if not _is_missing_table_error(exc):
            raise

    # Missing table likely means first-run schema not migrated yet.
    try:
        migrations_applied = database_service.migrate_configured_database_schema()
        logger.info(
            "Auto-ran setup migrations during /setup/initialize; applied=%d",
            migrations_applied,
        )
    except Exception as migrate_exc:
        logger.error("Automatic schema migration failed during /setup/initialize")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Database schema is not initialized and automatic migration "
                f"failed: {migrate_exc}."
            ),
        )

    # Retry admin check after migration.
    try:
        return repo.has_any_admin()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Database migration completed, but setup state could not be "
                "verified. Please retry setup initialization."
            ),
        )


def _get_admin_usernames(repo: UserRoleRepository, db: Session) -> list[str]:
    """Return distinct usernames that have the admin role."""
    rows = (
        db.query(UserRole.username)
        .filter(UserRole.role == "admin")
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def _is_setup_initialized_by_os_state(admin_usernames: list[str]) -> bool:
    """Return True when at least one DB admin has a corresponding OS user.

    If admin role rows exist but none of those usernames exist on the host,
    treat setup as not initialized so the wizard can recover by recreating the
    OS admin account.
    """
    if not admin_usernames:
        return False

    try:
        provider = get_os_user_provider()
    except Exception:
        # Fail closed if provider cannot be instantiated.
        logger.error("Failed to load OS user provider while evaluating setup state")
        return True

    existing_admins: list[str] = []
    missing_admins: list[str] = []
    for username in admin_usernames:
        try:
            if provider.user_exists(username):
                existing_admins.append(username)
            else:
                missing_admins.append(username)
        except Exception:
            # Fail closed if OS lookup fails unexpectedly.
            logger.error(
                "OS user existence check failed for setup admin '%s'",
                username,
            )
            return True

    if existing_admins:
        return True

    logger.warning(
        "Setup recovery mode: admin role rows exist in DB but no matching OS "
        "admin accounts were found (admins=%s)",
        missing_admins,
    )
    return False


def _is_setup_initialized_with_auto_migrate(repo: UserRoleRepository, db: Session) -> bool:
    """Return setup initialization state with schema auto-migration support."""
    if not _has_any_admin_with_auto_migrate(repo, db):
        return False
    return _is_setup_initialized_by_os_state(_get_admin_usernames(repo, db))


def _recover_stale_init_lock(db: Session, admin_usernames: list[str]) -> None:
    """Delete stale ``system_initialization`` lock row for recoverable setup states."""
    if not admin_usernames:
        return
    deleted = (
        db.query(SystemInitialization)
        .filter(SystemInitialization.id == 1)
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
        logger.warning(
            "Recovered stale setup lock row (system_initialization.id=1) for "
            "admins without OS accounts: %s",
            admin_usernames,
        )
    else:
        db.rollback()


@router.get("/status", response_model=SetupStatusResponse, responses={**R_404, **R_500})
def get_setup_status(
    db: Optional[Session] = Depends(_get_db_or_none),
) -> SetupStatusResponse:
    """Check whether the system has been initialized.

    Returns ``{"initialized": false}`` when no admin user exists in the
    database, indicating that ``POST /setup/initialize`` can be called.

    This endpoint is **unauthenticated** — it is safe to call before any
    users exist.
    """
    if db is None:
        # First-run install before any database connection has been configured.
        return SetupStatusResponse(initialized=False)

    repo = UserRoleRepository(db)
    try:
        if not repo.has_any_admin():
            return SetupStatusResponse(initialized=False)
        return SetupStatusResponse(
            initialized=_is_setup_initialized_by_os_state(
                _get_admin_usernames(repo, db),
            ),
        )
    except ProgrammingError as exc:
        db.rollback()
        if _is_missing_table_error(exc):
            # Fresh install before /setup/database/provision has run.
            return SetupStatusResponse(initialized=False)
        raise


@router.post(
    "/initialize",
    response_model=SetupInitializeResponse,
    status_code=200,
    responses={**R_400, **R_404, **R_409, **R_422, **R_500},
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
    already_initialized = _is_setup_initialized_with_auto_migrate(repo, db)

    if already_initialized:
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
        already_initialized = _is_setup_initialized_with_auto_migrate(repo, db)

        if already_initialized:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="System is already initialized. An admin user exists.",
            )

        # Recovery path: DB admin role rows can remain after a previous failed
        # run while the OS account is missing. Clear stale lock row so
        # /setup/initialize can recreate the OS admin account.
        _recover_stale_init_lock(db, _get_admin_usernames(repo, db))

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
        groups_created, setup_status = _run_os_setup(body)
    except HTTPException as exc:
        if not _release_init_lock(db):
            exc.detail += _LOCK_STUCK_SUFFIX
        raise
    except Exception:
        lock_released = _release_init_lock(db)
        logger.error("Unexpected error during OS setup")
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
        existing_role = (
            db.query(UserRole)
            .filter(
                UserRole.username == body.username,
                UserRole.role == "admin",
            )
            .first()
        )
        if existing_role is None:
            db.add(UserRole(username=body.username, role="admin"))
        db.commit()
    except Exception:
        # If seeding the admin role fails, roll back and release the
        # initialization lock so that setup can be retried safely.
        db.rollback()
        lock_released = _release_init_lock(db)
        logger.error("Failed to seed admin role for %s", body.username)
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
                "setup_status": setup_status,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.error("Failed to write audit log for SYSTEM_INITIALIZED")

    message = "Setup complete"
    if setup_status == "reconciled_existing_user":
        message = (
            "Setup complete. Existing OS admin user was reconciled, "
            "added to ecube-admins, and synced to ECUBE as an admin."
        )

    return SetupInitializeResponse(
        status=setup_status,
        message=message,
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
) -> tuple[list[str], Literal["created_admin_user", "reconciled_existing_user"]]:
    """Execute OS-level setup: create groups and the admin user.

    Returns a tuple ``(groups_created, setup_status)`` where:

    - ``groups_created`` is the list of ECUBE OS groups created.
    - ``setup_status`` is ``"created_admin_user"`` when a new OS admin user
      is created, or ``"reconciled_existing_user"`` when an existing OS user
      is reconciled (added to ``ecube-admins`` and password reset).

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
        setup_status: Literal["created_admin_user", "reconciled_existing_user"] = "created_admin_user"
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OSUserError as exc:
        # User may already exist (e.g. re-running setup after partial failure).
        if "already exists" not in exc.message.lower():
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
        setup_status = "reconciled_existing_user"

    return groups_created, setup_status
