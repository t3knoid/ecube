import asyncio
import logging
import traceback
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from app.auth import get_current_user
from app import API_VERSION, __version__
from app.config import settings
from app.exceptions import AuthenticationError, AuthorizationError, ConflictError, ECUBEException
from app.utils.sanitize import is_encoding_error
from app.logging_config import configure_logging
from app.routers import admin, audit, auth, database_setup, drives, files, introspection, jobs, mounts, setup, users
from app.schemas.errors import ErrorResponse
from app.session import close_session_backend, init_session_backend, mount_session_middleware
from app.utils.client_ip import get_client_ip

# Configure logging before anything else.
configure_logging()

logger = logging.getLogger(__name__)

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

    # ------------------------------------------------------------------
    # Startup: initialise session backend (Redis ping if configured)
    # ------------------------------------------------------------------
    await init_session_backend(application)

    # ------------------------------------------------------------------
    # Startup: purge expired audit logs
    # ------------------------------------------------------------------
    if settings.audit_log_retention_days > 0:
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
    # Background: periodic USB discovery
    # ------------------------------------------------------------------
    discovery_task = None
    if settings.usb_discovery_interval > 0:
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
)

# Mount session middleware (cookie or Redis backend).
mount_session_middleware(app)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/introspection/version")
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
        "/introspection/version",
    }
    # Endpoints that accept an optional bearer token (unauthenticated during
    # initial setup, admin-required after the first admin user is created).
    _conditional_auth_paths = {
        "/setup/database/test-connection", "/setup/database/provision",
    }
    for path, path_item in openapi_schema["paths"].items():
        if path in _unauthenticated_paths:
            continue
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                if "security" not in operation:
                    if path in _conditional_auth_paths:
                        # Optional bearer: allow unauthenticated OR authenticated
                        operation["security"] = [{"HTTPBearer": []}, {}]
                    else:
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
app.include_router(users.router, dependencies=[Depends(get_current_user)])


def _error_response(status_code: int, code: str, message: str, trace_id: str | None = None) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, trace_id=trace_id)
    return JSONResponse(status_code=status_code, content=body.model_dump())


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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code_map = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    trace_id = str(uuid.uuid4())
    logger.info("%d %s trace_id=%s path=%s", exc.status_code, code, trace_id, request.url.path)
    if exc.status_code == 401:
        _try_log_auth_failure(request, reason=detail, trace_id=trace_id)
    return _error_response(exc.status_code, code, detail, trace_id)


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
