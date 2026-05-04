from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi

from app import API_VERSION, __version__
from app.auth import get_current_user
from app.config import settings
from app.routers import (
    admin,
    audit,
    auth,
    browse,
    configuration,
    database_setup,
    drives,
    files,
    introspection,
    jobs,
    mounts,
    setup,
    telemetry,
    users,
)
from app.schemas.introspection import (
    HealthLiveResponse,
    HealthNotReadyResponse,
    HealthReadyResponse,
    HealthResponse,
    VersionResponse,
)


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
        "name": "browse",
        "description": "Directory browsing — paginated listing of files and folders within active mount points.",
    },
    {
        "name": "setup",
        "description": "First-run setup wizard — system initialization and status check.",
    },
]

_UNAUTHENTICATED_PATHS = {
    "/health",
    "/auth/token",
    "/setup/status",
    "/setup/initialize",
    "/introspection/version",
    "/setup/database/system-info",
    "/health/ready",
    "/health/live",
}
_CONDITIONAL_AUTH_PATHS = {
    "/setup/database/test-connection",
    "/setup/database/provision",
    "/setup/database/provision-status",
}


def build_ecube_openapi_schema(
    app: FastAPI,
    *,
    root_path_override: Optional[str] = None,
) -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    root_path = root_path_override if root_path_override is not None else settings.api_root_path

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        contact=app.contact,
        license_info=app.license_info,
        tags=app.openapi_tags,
        routes=app.routes,
        servers=[{"url": root_path}] if root_path else None,
    )

    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {}).update({
        "HTTPBearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "JWT token for authentication. Include in Authorization header as 'Bearer <token>'.",
        }
    })

    for path, path_item in openapi_schema["paths"].items():
        if path in _UNAUTHENTICATED_PATHS:
            continue
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                if path in _CONDITIONAL_AUTH_PATHS:
                    operation["security"] = [{"HTTPBearer": []}, {}]
                elif "security" not in operation:
                    operation["security"] = [{"HTTPBearer": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


def _register_schema_only_routes(app: FastAPI) -> None:
    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/live", response_model=HealthLiveResponse)
    def health_live() -> dict[str, str]:
        return {"status": "alive", "timestamp": "1970-01-01T00:00:00Z"}

    @app.get(
        "/health/ready",
        response_model=HealthReadyResponse,
        responses={503: {"model": HealthNotReadyResponse, "description": "Service is not ready"}},
    )
    def health_ready() -> dict[str, Any]:
        return {
            "status": "ready",
            "timestamp": "1970-01-01T00:00:00Z",
            "checks": {
                "database": "healthy",
                "file_system": "mounted",
                "usb_discovery": "initialized",
            },
        }

    @app.get("/introspection/version", response_model=VersionResponse)
    def introspection_version() -> dict[str, str]:
        return {"version": __version__, "api_version": API_VERSION}


def create_openapi_app() -> FastAPI:
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
        root_path=settings.api_root_path,
    )

    _register_schema_only_routes(app)

    app.include_router(auth.router)
    app.include_router(setup.router)
    app.include_router(database_setup.router)
    app.include_router(drives.router, dependencies=[Depends(get_current_user)])
    app.include_router(mounts.router, dependencies=[Depends(get_current_user)])
    app.include_router(browse.router, dependencies=[Depends(get_current_user)])
    app.include_router(jobs.router, dependencies=[Depends(get_current_user)])
    app.include_router(files.router, dependencies=[Depends(get_current_user)])
    app.include_router(introspection.router, dependencies=[Depends(get_current_user)])
    app.include_router(audit.router, dependencies=[Depends(get_current_user)])
    app.include_router(admin.router, dependencies=[Depends(get_current_user)])
    app.include_router(configuration.router, dependencies=[Depends(get_current_user)])
    app.include_router(telemetry.router, dependencies=[Depends(get_current_user)])
    app.include_router(users.router, dependencies=[Depends(get_current_user)])
    app.openapi = lambda: build_ecube_openapi_schema(app)
    return app


def load_openapi_schema() -> dict[str, Any]:
    return create_openapi_app().openapi()