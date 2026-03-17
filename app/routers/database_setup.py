"""Database provisioning and settings management API endpoints.

Provides endpoints for testing PostgreSQL connectivity, provisioning the
application database, checking connection status, and updating database
settings.  All endpoints live under ``/setup/database/``.

Security:
    - ``test-connection`` and ``provision`` allow unauthenticated access during
      initial setup (no admin exists) but require the ``admin`` role after.
    - ``status`` and ``settings`` always require the ``admin`` role.
    - Admin credentials are transient — never persisted or logged.
    - Passwords are redacted from all responses and audit records.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import OperationalError as SAOperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user, require_roles, _try_log_authorization_denied
from app.database import get_db
from app.exceptions import AuthorizationError, DatabaseStatusUnknownError
from app.routing import LocalOnlyRoute
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.database import (
    DatabaseProvisionRequest,
    DatabaseProvisionResponse,
    DatabaseSettingsUpdateRequest,
    DatabaseSettingsUpdateResponse,
    DatabaseStatusResponse,
    DatabaseTestConnectionRequest,
    DatabaseTestConnectionResponse,
)
from app.services import database_service
from app.services.audit_service import log_and_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup/database", tags=["setup"], route_class=LocalOnlyRoute)

_ADMIN_ONLY = require_roles("admin")
_bearer_scheme = HTTPBearer(auto_error=False)


def _get_db_or_none():
    """Yield a DB session, or ``None`` when the database is unreachable.

    Used by provisioning endpoints where the database may not exist yet.
    """
    try:
        db = __import__("app.database", fromlist=["SessionLocal"]).SessionLocal()
    except Exception:
        yield None
        return
    try:
        yield db
    finally:
        db.close()


def _require_admin_or_initial_setup(
    request: Request,
    db: Optional[Session] = Depends(_get_db_or_none),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> Optional[CurrentUser]:
    """Allow unauthenticated access during initial setup (no admin exists).

    Once the system is initialized (at least one admin user exists), this
    dependency requires a valid token with the ``admin`` role.

    Returns ``None`` during initial setup, or a ``CurrentUser`` with admin
    role after setup.

    **Fail-closed policy:** If the database is unreachable and no valid admin
    JWT is provided, the endpoint returns ``503 Service Unavailable`` rather
    than granting unauthenticated access.  This prevents an attacker from
    exploiting a transient DB outage to bypass authentication.  When a valid
    admin JWT is presented, the request proceeds even without DB connectivity
    (the JWT is self-contained).
    """
    # --- Try to determine initialization state from the database ---
    db_checked = False
    has_admin = False
    if db is not None:
        try:
            repo = UserRoleRepository(db)
            has_admin = repo.has_any_admin()
            db_checked = True
        except ProgrammingError:
            # ProgrammingError with "undefined table" / "relation does not
            # exist" means the schema hasn't been migrated yet.
            # Treat as initial setup so bootstrapping isn't blocked.
            db.rollback()
            db_checked = True
            has_admin = False
        except SAOperationalError:
            # Connectivity / permission error that surfaced through
            # SQLAlchemy.  Try a lightweight probe to distinguish
            # "reachable but broken query" from "truly unreachable".
            db.rollback()
            try:
                db.execute(__import__("sqlalchemy").text("SELECT 1"))
                # DB is reachable but the admin query failed for an
                # operational reason (e.g. permission denied on the
                # table).  Fail closed — do NOT assume initial setup.
            except Exception:
                logger.debug(
                    "Admin check failed (DB unreachable)",
                    exc_info=True,
                )
        except Exception:
            # Any other unexpected error (import bug, attribute error,
            # etc.) — do NOT treat as initial setup.  Leave db_checked
            # False so the fail-closed path below fires.
            db.rollback()
            logger.debug(
                "Admin check failed (unexpected error)",
                exc_info=True,
            )

    if db_checked and not has_admin:
        # Positively confirmed: no admin exists → initial setup mode
        return None

    # --- DB unreachable or admin exists: require authentication ---
    if db_checked and has_admin:
        # System is initialized — must have a valid admin JWT
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        current_user = get_current_user(request, credentials, db)
        if not any(r == "admin" for r in current_user.roles):
            _try_log_authorization_denied(
                db=db,
                actor=current_user.username,
                path=str(request.url.path),
                method=request.method,
                required_roles=["admin"],
                user_roles=current_user.roles,
            )
            raise AuthorizationError(
                "This action requires the admin role"
            )
        return current_user

    # DB is unreachable — fail closed unless a valid admin JWT is provided
    if credentials is not None:
        try:
            current_user = get_current_user(request, credentials, db)
        except Exception:
            pass  # Invalid token — fall through to 503
        else:
            if any(r == "admin" for r in current_user.roles):
                return current_user
            # Authenticated but not admin — definitive denial (403, not 503)
            _try_log_authorization_denied(
                db=db,
                actor=current_user.username,
                path=str(request.url.path),
                method=request.method,
                required_roles=["admin"],
                user_roles=current_user.roles,
            )
            raise AuthorizationError(
                "This action requires the admin role"
            )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Database is unavailable and initialization state cannot be "
            "verified. Provide a valid admin token or ensure the database "
            "is reachable."
        ),
    )


@router.post(
    "/test-connection",
    response_model=DatabaseTestConnectionResponse,
)
def test_database_connection(
    body: DatabaseTestConnectionRequest,
    db: Optional[Session] = Depends(_get_db_or_none),
    current_user: Optional[CurrentUser] = Depends(_require_admin_or_initial_setup),
) -> DatabaseTestConnectionResponse:
    """Test connectivity to a PostgreSQL server.

    **Authentication:** During initial setup (no admin user exists), this
    endpoint accepts unauthenticated requests.  Once the system is
    initialized, a valid admin JWT is required.
    """
    try:
        server_version = database_service.test_connection(
            host=body.host,
            port=body.port,
            username=body.admin_username,
            password=body.admin_password,
        )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Best-effort audit (may fail if DB doesn't exist yet)
    try:
        if db is not None:
            log_and_audit(
                db,
                action="DATABASE_CONNECTION_TEST",
                actor_id=current_user.username if current_user else "setup",
                metadata={"host": body.host, "port": body.port, "result": "ok"},
            )
        else:
            raise RuntimeError("no db session")
    except Exception:
        logger.info(
            "DATABASE_CONNECTION_TEST host=%s port=%s result=ok",
            body.host, body.port,
        )

    return DatabaseTestConnectionResponse(
        status="ok",
        server_version=server_version,
    )


@router.post(
    "/provision",
    response_model=DatabaseProvisionResponse,
)
def provision_database(
    body: DatabaseProvisionRequest,
    db: Optional[Session] = Depends(_get_db_or_none),
    current_user: Optional[CurrentUser] = Depends(_require_admin_or_initial_setup),
) -> DatabaseProvisionResponse:
    """Create the application user, database, and run Alembic migrations.

    **Authentication:** During initial setup (no admin user exists), this
    endpoint accepts unauthenticated requests.  Once the system is
    initialized, a valid admin JWT is required.

    Returns ``409 Conflict`` if the database has already been provisioned,
    unless ``force`` is set to ``true`` in the request body (admin-only).
    """
    if body.force and current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The 'force' option requires an authenticated admin user.",
        )

    if not body.force:
        try:
            already_provisioned = database_service.is_database_provisioned()
        except DatabaseStatusUnknownError:
            # Connectivity failure — fail closed so a transient outage
            # cannot be misinterpreted as "not provisioned".
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Cannot determine database provisioning state. "
                    "The database may be temporarily unreachable."
                ),
            )

        if already_provisioned:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Database is already provisioned. "
                    "Set 'force' to true to re-provision."
                ),
            )

    try:
        migrations_applied = database_service.provision_database(
            host=body.host,
            port=body.port,
            admin_username=body.admin_username,
            admin_password=body.admin_password,
            app_database=body.app_database,
            app_username=body.app_username,
            app_password=body.app_password,
        )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    # Best-effort audit
    try:
        if db is not None:
            log_and_audit(
                db,
                action="DATABASE_PROVISIONED",
                actor_id=current_user.username if current_user else "setup",
                metadata={
                    "host": body.host,
                    "port": body.port,
                    "database": body.app_database,
                    "user": body.app_username,
                    "migrations_applied": migrations_applied,
                },
            )
        else:
            raise RuntimeError("no db session")
    except Exception:
        logger.info(
            "DATABASE_PROVISIONED host=%s port=%s database=%s user=%s migrations=%d",
            body.host, body.port, body.app_database, body.app_username,
            migrations_applied,
        )

    return DatabaseProvisionResponse(
        status="provisioned",
        database=body.app_database,
        user=body.app_username,
        migrations_applied=migrations_applied,
    )


@router.get(
    "/status",
    response_model=DatabaseStatusResponse,
)
def get_database_status(
    current_user: CurrentUser = Depends(_ADMIN_ONLY),
) -> DatabaseStatusResponse:
    """Report the current database connection health and migration state."""
    status_data = database_service.get_database_status()
    return DatabaseStatusResponse(**status_data)


@router.put(
    "/settings",
    response_model=DatabaseSettingsUpdateResponse,
)
def update_database_settings(
    body: DatabaseSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_ONLY),
) -> DatabaseSettingsUpdateResponse:
    """Update database connection settings.

    Validates new settings via a test connection before committing.
    Re-initialises the connection pool without a service restart.
    """
    try:
        result = database_service.update_database_settings(
            host=body.host,
            port=body.port,
            app_database=body.app_database,
            app_username=body.app_username,
            app_password=body.app_password,
            pool_size=body.pool_size,
            pool_max_overflow=body.pool_max_overflow,
        )
    except ConnectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    # Audit (never log password)
    try:
        log_and_audit(
            db,
            action="DATABASE_SETTINGS_UPDATED",
            actor_id=current_user.username,
            metadata={
                "host": result["host"],
                "port": result["port"],
                "database": result["database"],
            },
        )
    except Exception:
        logger.info(
            "DATABASE_SETTINGS_UPDATED host=%s port=%s database=%s actor=%s",
            result["host"], result["port"], result["database"],
            current_user.username,
        )

    return DatabaseSettingsUpdateResponse(**result)
