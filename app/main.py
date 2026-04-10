import asyncio
import logging
import os
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Generator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import BaseRoute, Match

from app.auth import get_current_user
from app import API_VERSION, __version__
from app.config import DEFAULT_READINESS_MOUNT_CHECK_TIMEOUT_SECONDS, settings
from app import database as db_module
from app.infrastructure import get_drive_discovery, get_mount_provider
from app.exceptions import AuthenticationError, AuthorizationError, ConflictError, ECUBEException
from app.utils.sanitize import is_encoding_error
from app.logging_config import configure_logging
from app.models.network import NetworkMount
from app.routers import admin, audit, auth, configuration, database_setup, drives, files, introspection, jobs, mounts, setup, telemetry, users
from app.schemas.errors import ErrorResponse
from app.schemas.introspection import HealthLiveResponse, HealthNotReadyResponse, HealthReadyResponse, HealthResponse, VersionResponse
from app.session import close_session_backend, init_session_backend, mount_session_middleware
from app.utils.client_ip import get_client_ip
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

# Configure logging before anything else.
configure_logging()

logger = logging.getLogger(__name__)


def _is_missing_table_error(exc: Exception) -> bool:
    """Return True when *exc* indicates a missing/unmigrated table."""
    msg = str(exc).lower()
    return (
        ("relation" in msg and "does not exist" in msg)
        or "undefinedtable" in msg
        or "no such table" in msg
    )


def _probe_usb_sysfs_available() -> bool:
    """Return True when the configured USB sysfs path is accessible.

    This avoids false "initialized" readiness when discovery falls back to an
    empty topology due to unreadable/missing sysfs.
    """
    usb_path = settings.sysfs_usb_devices_path
    if not os.path.isdir(usb_path):
        return False
    if not os.access(usb_path, os.R_OK | os.X_OK):
        return False
    try:
        os.listdir(usb_path)
    except OSError:
        return False
    return True


def _not_ready_response(
    *,
    reason: str,
    details: str,
    timestamp: str,
    checks: dict[str, str],
) -> JSONResponse:
    """Build the standard ``/health/ready`` non-ready response payload."""
    return JSONResponse(
        status_code=503,
        content={
            "status": "not_ready",
            "reason": reason,
            "details": details,
            "timestamp": timestamp,
            "checks": checks,
        },
    )


def _resolve_readiness_mount_timeout(remaining_budget: float | None) -> float:
    """Return a positive per-mount timeout for readiness mount checks.

    Non-positive configured values are treated as invalid and replaced with:
    - remaining budget when total-budget mode is active
    - otherwise the documented default readiness timeout
    """
    configured_timeout = settings.readiness_mount_check_timeout_seconds
    if configured_timeout <= 0:
        if remaining_budget is not None:
            configured_timeout = remaining_budget
        else:
            configured_timeout = DEFAULT_READINESS_MOUNT_CHECK_TIMEOUT_SECONDS

    if remaining_budget is not None:
        return min(configured_timeout, remaining_budget)
    return configured_timeout

# OpenAPI tags with descriptions for organizing endpoints
tags_metadata = [
    {
        "name": "auth",
        "description": "Authentication — local login and token issuance.",
    },
    {
        "name": "drives",
        "description": "USB drive lifecycle management — initialization, state transitions, and eject preparation.",
    },
    {
        "name": "jobs",
        "description": "Export job creation, execution, and monitoring — file copying, verification, and manifest generation.",
    },
    {
        "name": "mounts",
        "description": "Network mount management — NFS/SMB mount lifecycle and validation.",
    },
    {
        "name": "audit",
        "description": "Audit log access and filtering — immutable records of all system operations.",
    },
    {
        "name": "introspection",
        "description": "System introspection — USB topology, configuration state, and diagnostic information.",
    },
    {
        "name": "files",
        "description": "File audit operations — hash computation and file comparison.",
    },
    {
        "name": "users",
        "description": "User role management — assign, update, and remove ECUBE role assignments.",
    },
    {
        "name": "admin",
        "description": "Administration — log file access, OS user and group management.",
    },
    {
        "name": "setup",
        "description": "First-run setup wizard — system initialization and status check.",
    },
]


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("ECUBE application starting")

    db_runtime_ready = False
    if not (settings.database_url or "").strip():
        logger.info("DATABASE_URL is not configured; skipping DB startup tasks")
    else:
        try:
            from app.services import database_service

            db_runtime_ready = database_service.is_database_provisioned()
            if not db_runtime_ready:
                logger.info("Database is configured but schema is not provisioned; skipping DB startup tasks")
        except Exception:
            logger.exception("Failed to determine database provisioning state during startup")

    # ------------------------------------------------------------------
    # Startup: initialise session backend (Redis ping if configured)
    # ------------------------------------------------------------------
    await init_session_backend(application)

    # ------------------------------------------------------------------
    # Startup: purge expired audit logs
    # ------------------------------------------------------------------
    if db_runtime_ready and settings.audit_log_retention_days > 0:
        try:
            from app.database import SessionLocal
            from app.services.audit_service import purge_expired_audit_logs

            db = SessionLocal()
            try:
                purged = purge_expired_audit_logs(db, settings.audit_log_retention_days)
                if purged:
                    logger.info("Startup audit cleanup: purged %d records", purged)
            finally:
                db.close()
        except Exception:
            logger.exception("Audit log cleanup failed during startup")

    # ------------------------------------------------------------------
    # Startup: reconcile stale mounts, jobs, and USB drives
    # ------------------------------------------------------------------
    if db_runtime_ready:
        try:
            from app.database import SessionLocal
            from app.services.reconciliation_service import run_startup_reconciliation
            from app.infrastructure import get_mount_provider, get_drive_discovery, get_filesystem_detector, get_os_user_provider

            db = SessionLocal()
            try:
                run_startup_reconciliation(
                    db,
                    get_mount_provider(),
                    os_user_provider=get_os_user_provider() if settings.role_resolver == "local" else None,
                    topology_source=get_drive_discovery().discover_topology,
                    filesystem_detector=get_filesystem_detector(),
                )
            finally:
                db.close()
        except Exception:
            logger.exception("Startup reconciliation failed")

    # ------------------------------------------------------------------
    # Startup: prime psutil CPU baseline (runs in background thread so it
    # does not block the server from accepting requests).
    # ------------------------------------------------------------------
    def _log_prime_failure(task: "asyncio.Task[None]") -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "CPU sampler priming failed; cpu_percent will report 0.0 initially",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    prime_task: "asyncio.Task[None] | None" = None
    try:
        from app.routers.introspection import prime_cpu_sampler
        prime_task = asyncio.create_task(asyncio.to_thread(prime_cpu_sampler))
        prime_task.add_done_callback(_log_prime_failure)
    except Exception:
        logger.exception("CPU sampler priming setup failed")

    # ------------------------------------------------------------------
    # Background: periodic USB discovery
    # ------------------------------------------------------------------
    discovery_task = None
    if db_runtime_ready and settings.usb_discovery_interval > 0:
        async def _usb_discovery_loop() -> None:
            from app.database import SessionLocal
            from app.services.discovery_service import run_discovery_sync
            from app.infrastructure import get_filesystem_detector

            interval = settings.usb_discovery_interval
            while True:
                await asyncio.sleep(interval)
                try:
                    db = SessionLocal()
                    try:
                        run_discovery_sync(
                            db,
                            actor="system",
                            filesystem_detector=get_filesystem_detector(),
                        )
                    finally:
                        db.close()
                except asyncio.CancelledError:
                    # Propagate cancellation so the task can be awaited cleanly on shutdown.
                    raise
                except Exception:
                    logger.exception("Periodic USB discovery failed")

        discovery_task = asyncio.create_task(_usb_discovery_loop())

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    if prime_task is not None and not prime_task.done():
        # prime_cpu_sampler runs a short blocking call in a thread.  Cancelling
        # the Task only cancels the Future wrapper — the underlying thread
        # continues regardless.  Await with a short timeout instead so we don't
        # misrepresent the cancellation and give the sampler a chance to finish
        # cleanly without blocking shutdown for long.
        try:
            await asyncio.wait_for(asyncio.shield(prime_task), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass

    if discovery_task is not None:
        discovery_task.cancel()
        try:
            await discovery_task
        except asyncio.CancelledError:
            pass

    await close_session_backend(application)

    logger.info("ECUBE application shutting down")


app = FastAPI(
    title="ECUBE",
    description="Evidence Copying & USB Based Export Platform — Secure evidence export solution for encrypted USB drives.",
    version=__version__,
    contact={
        "name": settings.api_contact_name,
        "email": settings.api_contact_email,
        "url": "https://ecube.local",
    },
    license_info={
        "name": "Proprietary",
        "url": "https://ecube.local/license",
    },
    openapi_tags=tags_metadata,
    lifespan=lifespan,
    root_path=settings.api_root_path,
)

# Mount session middleware (cookie or Redis backend).
mount_session_middleware(app)

# CORS — needed for development (Vite on a separate port) and Swagger UI.
if settings.cors_allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def fallback_status_logging(request: Request, call_next):
    """Log 405 and 413 responses that bypass exception handlers.

    Some 405 responses are produced directly by Starlette routing and do not
    always traverse our ``StarletteHTTPException`` handler. Similarly, 413
    (Payload Too Large) responses may come from Uvicorn's ASGI request limits.
    Add fallback log lines for observability.
    """
    response = await call_next(request)
    if "X-Trace-Id" not in response.headers:
        if response.status_code == 405:
            logger.info("405 HTTP_405 path=%s method=%s", request.url.path, request.method)
        elif response.status_code == 413:
            logger.warning("413 PAYLOAD_TOO_LARGE path=%s method=%s", request.url.path, request.method)
    return response


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@app.get("/health/live", response_model=HealthLiveResponse)
def health_live():
    """Return process liveness for orchestrator probes without dependency checks."""
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"status": "alive", "timestamp": timestamp}


def _get_db_or_none() -> Generator[Session | None, None, None]:
    """Yield a DB session when configured, otherwise ``None``.

    This keeps readiness responses consistent even when DATABASE_URL is unset.
    """
    if not db_module.is_database_configured():
        yield None
        return

    db = db_module.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get(
    "/health/ready",
    response_model=HealthReadyResponse,
    responses={503: {"model": HealthNotReadyResponse, "description": "Service is not ready"}},
)
def health_ready(db: Session | None = Depends(_get_db_or_none)):
    """Check whether critical runtime dependencies are ready for traffic."""
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    if db is None:
        configured_db_url = (settings.database_url or "").strip()
        if configured_db_url:
            reason = "database_misconfigured"
            details = "Database is configured but failed to initialize."
        else:
            reason = "database_not_configured"
            details = "Database is not configured."
        return _not_ready_response(
            reason=reason,
            details=details,
            timestamp=timestamp,
            checks={
                "database": "unhealthy",
                "file_system": "unknown",
                "usb_discovery": "unknown",
            },
        )

    # 1) Database connectivity
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness probe dependency failed reason=database_connection_failed error_type=%s", type(exc).__name__)
        logger.debug("Readiness DB failure detail", exc_info=True)
        return _not_ready_response(
            reason="database_connection_failed",
            details="Database connectivity check failed.",
            timestamp=timestamp,
            checks={
                "database": "unhealthy",
                "file_system": "unknown",
                "usb_discovery": "unknown",
            },
        )

    # 2) Filesystem mount availability (using current mount provider checks)
    try:
        provider = get_mount_provider()
    except Exception as exc:
        logger.warning("Readiness probe dependency failed reason=mount_provider_unavailable error_type=%s", type(exc).__name__)
        logger.debug("Readiness mount provider resolution detail", exc_info=True)
        return _not_ready_response(
            reason="mount_provider_unavailable",
            details="Filesystem mount provider is not available.",
            timestamp=timestamp,
            checks={
                "database": "healthy",
                "file_system": "unknown",
                "usb_discovery": "unknown",
            },
        )

    try:
        configured_mounts = db.query(NetworkMount).all()
    except (ProgrammingError, OperationalError) as exc:
        db.rollback()
        if _is_missing_table_error(exc):
            logger.warning("Readiness probe mount metadata table is not available")
            return _not_ready_response(
                reason="mount_metadata_unavailable",
                details="Mount metadata is not available yet.",
                timestamp=timestamp,
                checks={
                    "database": "healthy",
                    "file_system": "unknown",
                    "usb_discovery": "unknown",
                },
            )
        logger.warning("Readiness probe dependency failed reason=mount_metadata_check_failed error_type=%s", type(exc).__name__)
        logger.debug("Readiness mount metadata failure detail", exc_info=True)
        return _not_ready_response(
            reason="mount_metadata_check_failed",
            details="Mount metadata readiness check failed.",
            timestamp=timestamp,
            checks={
                "database": "healthy",
                "file_system": "unknown",
                "usb_discovery": "unknown",
            },
        )

    mount_checks_deadline = None
    if settings.readiness_mount_checks_total_timeout_seconds > 0:
        mount_checks_deadline = (
            time.monotonic() + settings.readiness_mount_checks_total_timeout_seconds
        )

    for mount in configured_mounts:
        remaining_budget = None
        if mount_checks_deadline is not None:
            # Bound cumulative mount-check time so probe latency is predictable.
            remaining_budget = mount_checks_deadline - time.monotonic()
            if remaining_budget <= 0:
                logger.warning(
                    "Readiness probe dependency failed reason=filesystem_mount_checks_timed_out",
                )
                return _not_ready_response(
                    reason="filesystem_mount_checks_timed_out",
                    details="Filesystem mount checks exceeded readiness time budget.",
                    timestamp=timestamp,
                    checks={
                        "database": "healthy",
                        "file_system": "unknown",
                        "usb_discovery": "unknown",
                    },
                )

        per_mount_timeout = _resolve_readiness_mount_timeout(remaining_budget)

        try:
            result = provider.check_mounted(
                mount.local_mount_point,
                timeout_seconds=per_mount_timeout,
            )
        except Exception as exc:
            logger.warning(
                "Readiness probe dependency failed reason=filesystem_mount_check_error mount_point=%s error_type=%s",
                mount.local_mount_point,
                type(exc).__name__,
            )
            logger.debug("Readiness mount check failure detail", exc_info=True)
            return _not_ready_response(
                reason="filesystem_mount_check_error",
                details="A required filesystem mount readiness check encountered a runtime error.",
                timestamp=timestamp,
                checks={
                    "database": "healthy",
                    "file_system": "unknown",
                    "usb_discovery": "unknown",
                },
            )

        if result is False:
            logger.warning(
                "Readiness probe mount unavailable for mount_point=%s",
                mount.local_mount_point,
            )
            return _not_ready_response(
                reason="filesystem_mount_unavailable",
                details="A required filesystem mount is unavailable.",
                timestamp=timestamp,
                checks={
                    "database": "healthy",
                    "file_system": "unmounted",
                    "usb_discovery": "unknown",
                },
            )
        if result is None:
            logger.warning(
                "Readiness probe mount check returned unknown state for mount_point=%s",
                mount.local_mount_point,
            )
            return _not_ready_response(
                reason="filesystem_mount_check_failed",
                details="A required filesystem mount readiness check failed.",
                timestamp=timestamp,
                checks={
                    "database": "healthy",
                    "file_system": "unknown",
                    "usb_discovery": "unknown",
                },
            )

    # 3) USB discovery readiness signal (provider can enumerate topology)
    if not _probe_usb_sysfs_available():
        logger.warning(
            "Readiness probe dependency failed reason=usb_discovery_unavailable usb_path=%s",
            settings.sysfs_usb_devices_path,
        )
        return _not_ready_response(
            reason="usb_discovery_unavailable",
            details="USB discovery runtime path is not accessible.",
            timestamp=timestamp,
            checks={
                "database": "healthy",
                "file_system": "mounted",
                "usb_discovery": "unavailable",
            },
        )

    try:
        get_drive_discovery().discover_topology()
    except Exception as exc:
        logger.warning("Readiness probe dependency failed reason=usb_discovery_not_initialized error_type=%s", type(exc).__name__)
        logger.debug("Readiness USB discovery failure detail", exc_info=True)
        return _not_ready_response(
            reason="usb_discovery_not_initialized",
            details="USB discovery readiness check failed.",
            timestamp=timestamp,
            checks={
                "database": "healthy",
                "file_system": "mounted",
                "usb_discovery": "not_initialized",
            },
        )

    return {
        "status": "ready",
        "timestamp": timestamp,
        "checks": {
            "database": "healthy",
            "file_system": "mounted",
            "usb_discovery": "initialized",
        },
    }


@app.get("/introspection/version", response_model=VersionResponse)
def introspection_version():
    """Return application and API version information.

    No authentication required. Useful for deployment verification.
    """
    return {"version": __version__, "api_version": API_VERSION}


def custom_openapi():
    """Generate OpenAPI schema with security scheme definitions."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        contact=app.contact,
        license_info=app.license_info,
        tags=app.openapi_tags,
        routes=app.routes,
        servers=[{"url": settings.api_root_path}] if settings.api_root_path else None,
    )

    # Define security schemes (merge, don't overwrite)
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {}).update({
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token for authentication. Include in Authorization header as 'Bearer <token>'.",
        }
    })

    # Apply security requirement to all endpoints except unauthenticated routes
    _unauthenticated_paths = {
        "/health", "/auth/token", "/setup/status", "/setup/initialize",
        "/introspection/version", "/setup/database/system-info", "/health/ready", "/health/live",
    }
    # Endpoints that accept an optional bearer token (unauthenticated during
    # initial setup, admin-required after the first admin user is created).
    _conditional_auth_paths = {
        "/setup/database/test-connection", "/setup/database/provision",
        "/setup/database/provision-status",
    }
    for path, path_item in openapi_schema["paths"].items():
        if path in _unauthenticated_paths:
            continue
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                if path in _conditional_auth_paths:
                    # Optional bearer: allow unauthenticated OR authenticated.
                    # Set unconditionally — FastAPI may pre-populate security
                    # from the HTTPBearer dependency on these routes.
                    operation["security"] = [{"HTTPBearer": []}, {}]
                elif "security" not in operation:
                    operation["security"] = [{"HTTPBearer": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi



# Auth router — unauthenticated (login endpoint)
app.include_router(auth.router)

# Setup router — unauthenticated (first-run wizard; guarded by has_any_admin check)
app.include_router(setup.router)

# Database setup router — unauthenticated during initial setup, admin-only after
app.include_router(database_setup.router)

app.include_router(drives.router, dependencies=[Depends(get_current_user)])
app.include_router(mounts.router, dependencies=[Depends(get_current_user)])
app.include_router(jobs.router, dependencies=[Depends(get_current_user)])
app.include_router(files.router, dependencies=[Depends(get_current_user)])
app.include_router(introspection.router, dependencies=[Depends(get_current_user)])
app.include_router(audit.router, dependencies=[Depends(get_current_user)])
app.include_router(admin.router, dependencies=[Depends(get_current_user)])
app.include_router(configuration.router, dependencies=[Depends(get_current_user)])
app.include_router(telemetry.router, dependencies=[Depends(get_current_user)])
app.include_router(users.router, dependencies=[Depends(get_current_user)])


def _error_response(status_code: int, code: str, message: str, trace_id: str) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, trace_id=trace_id)
    response = JSONResponse(status_code=status_code, content=body.model_dump())
    # Surface trace IDs in headers so middleware can avoid duplicate fallback logs.
    response.headers["X-Trace-Id"] = trace_id
    return response


def _compute_allowed_methods(request: Request) -> str:
    """Compute the Allow header value for a 405 Method Not Allowed response."""
    methods: set[str] = set()
    for route in app.routes:
        if not isinstance(route, BaseRoute):
            continue
        match, _ = route.matches(request.scope)
        route_methods = getattr(route, "methods", None)
        if match != Match.NONE and route_methods:
            methods.update(route_methods)
    return ", ".join(sorted(methods))


def _try_log_auth_failure(request: Request, reason: str, trace_id: str) -> None:
    """Best-effort audit log for authentication failures.  Never raises."""
    db = getattr(request.state, "db", None)
    if db is None:
        return
    try:
        from app.repositories.audit_repository import AuditRepository

        AuditRepository(db).add(
            action="AUTH_FAILURE",
            details={
                "path": str(request.url.path),
                "method": request.method,
                "reason": reason,
                "trace_id": trace_id,
            },
            client_ip=get_client_ip(request),
        )
    except Exception:
        pass


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    logger.warning("401 %s trace_id=%s path=%s", exc.code, trace_id, request.url.path)
    _try_log_auth_failure(request, reason=exc.message, trace_id=trace_id)
    return _error_response(401, exc.code, exc.message, trace_id)


@app.exception_handler(AuthorizationError)
async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    logger.warning("403 %s trace_id=%s path=%s", exc.code, trace_id, request.url.path)
    return _error_response(403, exc.code, exc.message, trace_id)


@app.exception_handler(ConflictError)
async def conflict_error_handler(request: Request, exc: ConflictError) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    logger.warning("409 %s trace_id=%s path=%s", exc.code, trace_id, request.url.path)
    return _error_response(409, exc.code, exc.message, trace_id)


@app.exception_handler(ECUBEException)
async def ecube_exception_handler(request: Request, exc: ECUBEException) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    logger.error("%d %s trace_id=%s path=%s", exc.status_code, exc.code, trace_id, request.url.path)
    return _error_response(exc.status_code, exc.code, exc.message, trace_id)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    messages = []
    for error in exc.errors():
        loc = " -> ".join(str(part) for part in error["loc"])
        messages.append(f"{loc}: {error['msg']}")
    detail = "; ".join(messages)
    logger.info("422 VALIDATION_ERROR trace_id=%s path=%s", trace_id, request.url.path)
    return _error_response(422, "VALIDATION_ERROR", detail, trace_id)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code_map = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    trace_id = str(uuid.uuid4())
    log_level = logging.WARNING if exc.status_code == 413 else logging.INFO
    logger.log(log_level, "%d %s trace_id=%s path=%s", exc.status_code, code, trace_id, request.url.path)
    if exc.status_code == 401:
        _try_log_auth_failure(request, reason=detail, trace_id=trace_id)
    response = _error_response(exc.status_code, code, detail, trace_id)
    # Forward headers from the original exception (e.g. Allow for 405).
    if exc.headers:
        response.headers.update(exc.headers)
    # Compute Allow header for 405 as fallback if Starlette didn't provide it.
    if exc.status_code == 405 and "allow" not in response.headers:
        allowed = _compute_allowed_methods(request)
        if allowed:
            response.headers["Allow"] = allowed
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = str(uuid.uuid4())
    if is_encoding_error(exc):
        logger.warning("422 ENCODING_ERROR trace_id=%s path=%s", trace_id, request.url.path, exc_info=exc)
        return _error_response(422, "ENCODING_ERROR", "Request contains invalid characters.", trace_id)
    logger.error(
        "Unhandled exception trace_id=%s path=%s\n%s",
        trace_id,
        request.url.path,
        traceback.format_exc(),
    )
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.", trace_id)
