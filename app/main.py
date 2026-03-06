import logging
import traceback
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from app.auth import get_current_user
from app.exceptions import AuthenticationError, AuthorizationError, ConflictError, ECUBEException
from app.routers import audit, drives, files, introspection, jobs, mounts
from app.schemas.errors import ErrorResponse

logger = logging.getLogger(__name__)

# Security scheme configuration
security_bearer = HTTPBearer()

# OpenAPI tags with descriptions for organizing endpoints
tags_metadata = [
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
]

app = FastAPI(
    title="ECUBE",
    description="Evidence Copying & USB Based Export Platform — Secure evidence export solution for encrypted USB drives.",
    version="0.1.0",
    contact={
        "name": "ECUBE Support",
        "email": "support@ecube.local",
        "url": "https://ecube.local",
    },
    license_info={
        "name": "Proprietary",
        "url": "https://ecube.local/license",
    },
    openapi_tags=tags_metadata,
)


@app.get("/health")
def health():
    return {"status": "ok"}


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
        routes=app.routes,
    )

    # Define security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token for authentication. Include in Authorization header as 'Bearer <token>'.",
        }
    }

    # Apply security requirement to all endpoints except /health
    for path, path_item in openapi_schema["paths"].items():
        if path != "/health":
            for operation in path_item.values():
                if isinstance(operation, dict) and "responses" in operation:
                    if "security" not in operation:
                        operation["security"] = [{"HTTPBearer": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi



app.include_router(drives.router, dependencies=[Depends(get_current_user)])
app.include_router(mounts.router, dependencies=[Depends(get_current_user)])
app.include_router(jobs.router, dependencies=[Depends(get_current_user)])
app.include_router(files.router, dependencies=[Depends(get_current_user)])
app.include_router(introspection.router, dependencies=[Depends(get_current_user)])
app.include_router(audit.router, dependencies=[Depends(get_current_user)])


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
    logger.error(
        "Unhandled exception trace_id=%s path=%s\n%s",
        trace_id,
        request.url.path,
        traceback.format_exc(),
    )
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.", trace_id)
