import asyncio
import logging
import os
import threading
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import BaseRoute, Match

from app.auth import get_current_user
from app import API_VERSION, __version__
from app.config import (
    DEFAULT_DEMO_ACCOUNTS,
    DEFAULT_DEMO_LOGIN_MESSAGE,
    DEFAULT_READINESS_MOUNT_CHECK_TIMEOUT_SECONDS,
    settings,
)
from app import database as db_module
from app.infrastructure import get_drive_discovery, get_drive_mount, get_mount_provider
from app.exceptions import AuthenticationError, AuthorizationError, ConflictError, ECUBEException
from app.utils.sanitize import is_encoding_error, sanitize_error_message
from app.logging_config import configure_logging
from app.models.network import NetworkMount
from app.openapi import build_ecube_openapi_schema, tags_metadata
from app.routers import admin, audit, auth, browse, configuration, database_setup, drives, files, introspection, jobs, mounts, password_policy, setup, telemetry, users
from app.schemas.errors import ErrorResponse
from app.schemas.introspection import HealthLiveResponse, HealthNotReadyResponse, HealthReadyResponse, HealthResponse, VersionResponse
from app.session import close_session_backend, init_session_backend, mount_session_middleware
from app.utils.client_ip import get_client_ip
from app.repositories.audit_repository import best_effort_audit
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError

# Configure logging before anything else.
configure_logging()

logger = logging.getLogger(__name__)

_USB_DISCOVERY_READY_CACHE: dict[type, float] = {}
_USB_DISCOVERY_READY_CACHE_LOCK = threading.Lock()

_SETUP_REDIRECT_EXEMPT_PATHS = frozenset({
    "/setup",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/health/live",
    "/health/ready",
})


def _is_browser_navigation_request(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return request.method == "GET" and "text/html" in accept


def _should_redirect_to_setup(request: Request) -> bool:
    path = request.url.path
    original_path = str(request.scope.get("_original_path") or "")

    if path in _SETUP_REDIRECT_EXEMPT_PATHS:
        return False
    if path.startswith(("/setup/", "/assets/")):
        return False
    if path in {"/favicon.ico", "/robots.txt"}:
        return False
    if path.startswith("/api/") or original_path.startswith("/api/"):
        return False
    return True


def _is_missing_table_error(exc: Exception) -> bool:
    """Return True when *exc* indicates a missing/unmigrated table."""
    msg = str(exc).lower()
    return (
        ("relation" in msg and "does not exist" in msg)
        or "undefinedtable" in msg
        or "no such table" in msg
    )


def _classify_unhandled_exception(exc: Exception) -> dict[str, str]:
    """Return a safe failure classification and remediation hint."""
    raw_message = str(getattr(exc, "orig", exc) or exc).strip()
    lowered = raw_message.lower()

    if isinstance(exc, (ProgrammingError, OperationalError)) and any(
        token in lowered
        for token in ("column", "relation", "table", "no such", "undefinedcolumn", "undefinedtable")
    ):
        return {
            "category": "database_schema_drift",
            "summary": "Database schema mismatch detected",
            "recommended_action": "Run 'alembic upgrade head' to apply pending migrations.",
            "detail": "Missing or outdated database schema objects detected.",
        }

    if isinstance(exc, OperationalError) and any(
        token in lowered
        for token in (
            "connection refused",
            "could not connect",
            "server closed the connection",
            "connection not open",
            "unable to open database file",
            "could not translate host",
            "database is unavailable",
        )
    ):
        return {
            "category": "database_unavailable",
            "summary": "Database dependency is unavailable",
            "recommended_action": "Verify database connectivity, host configuration, and service availability.",
            "detail": "Database connection attempt failed.",
        }

    if isinstance(exc, PermissionError) or any(
        token in lowered for token in ("permission denied", "access denied", "not authorized")
    ):
        return {
            "category": "permission_failure",
            "summary": "Permission or authentication failure detected",
            "recommended_action": "Verify service permissions and configured credentials for the failing dependency.",
            "detail": sanitize_error_message(raw_message, "Permission or authentication failure"),
        }

    if any(
        token in lowered
        for token in (
            "no database url configured",
            "missing setting",
            "invalid configuration",
            "invalid value",
            "environment variable",
        )
    ):
        return {
            "category": "invalid_configuration",
            "summary": "Invalid application configuration detected",
            "recommended_action": "Review ECUBE configuration values and required environment settings.",
            "detail": "Application configuration validation failed.",
        }

    return {
        "category": "unexpected_backend_error",
        "summary": "Unhandled backend exception reached the global handler",
        "recommended_action": "Use the trace ID to inspect debug logs and verify dependency health.",
        "detail": sanitize_error_message(raw_message, "Unhandled backend exception"),
    }


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


def _is_usb_discovery_ready() -> bool:
    """Return True when USB discovery is ready without full scans on each probe.

    Successful readiness checks are cached for a short TTL to avoid repeated
    sysfs topology walks under frequent ``/health/ready`` polling.
    """
    ttl_seconds = settings.readiness_usb_discovery_cache_ttl_seconds
    now = time.monotonic()

    try:
        provider = get_drive_discovery()
    except Exception:
        return False

    provider_type = type(provider)
    if ttl_seconds > 0:
        with _USB_DISCOVERY_READY_CACHE_LOCK:
            expires_at = _USB_DISCOVERY_READY_CACHE.get(provider_type)
            if expires_at is not None and expires_at > now:
                return True

    probe_ready = getattr(provider, "probe_ready", None)
    try:
        if callable(probe_ready):
            probe_ready()
        else:
            provider.discover_topology()
    except Exception:
        return False

    if ttl_seconds > 0:
        with _USB_DISCOVERY_READY_CACHE_LOCK:
            _USB_DISCOVERY_READY_CACHE[provider_type] = now + ttl_seconds
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


def _startup_reconciliation_has_error(payload: Any) -> bool:
    if isinstance(payload, dict):
        if "error" in payload:
            return True
        return any(_startup_reconciliation_has_error(value) for value in payload.values())
    return False


def _startup_reconciliation_counts(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    counts: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            counts[key] = value
            continue
        nested = _startup_reconciliation_counts(value)
        if nested:
            counts[key] = nested
    return counts


def _log_demo_runtime_configuration() -> None:
    if not settings.is_demo_mode_enabled():
        return

    effective_accounts = settings.get_demo_accounts()
    login_message = settings.get_demo_login_message()
    shared_password = settings.get_demo_shared_password()
    password_change_disabled = settings.get_demo_disable_password_change()

    active_overrides: list[str] = []
    if login_message != DEFAULT_DEMO_LOGIN_MESSAGE:
        active_overrides.append("DEMO_LOGIN_MESSAGE")
    if settings.has_demo_shared_password_override():
        active_overrides.append("DEMO_SHARED_PASSWORD")
    if effective_accounts != DEFAULT_DEMO_ACCOUNTS:
        active_overrides.append("DEMO_ACCOUNTS")
    if password_change_disabled is not True:
        active_overrides.append("DEMO_DISABLE_PASSWORD_CHANGE")

    logger.info(
        "Demo mode enabled",
        extra={
            "active_overrides": active_overrides,
            "shared_password_configured": bool(shared_password),
            "account_count": len(effective_accounts),
            "password_change_allowed": not password_change_disabled,
        },
    )
    logger.debug(
        "Demo mode runtime configuration",
        extra={
            "login_message": login_message,
            "account_usernames": [str(account.get("username", "")).strip() for account in effective_accounts],
            "active_overrides": active_overrides,
            "shared_password_source": "override" if "DEMO_SHARED_PASSWORD" in active_overrides else "default",
            "login_message_source": "override" if "DEMO_LOGIN_MESSAGE" in active_overrides else "default",
            "accounts_source": "override" if "DEMO_ACCOUNTS" in active_overrides else "default",
            "password_change_policy_source": "override" if "DEMO_DISABLE_PASSWORD_CHANGE" in active_overrides else "default",
        },
    )


def _summarize_startup_reconciliation(results: dict[str, Any]) -> dict[str, Any]:
    if results.get("skipped"):
        return {
            "status": "skipped",
            "reason": "lock_held",
        }

    error_domains = [
        domain for domain, payload in results.items()
        if _startup_reconciliation_has_error(payload)
    ]
    return {
        "status": "partial_failure" if error_domains else "completed",
        "domains": sorted(results.keys()),
        "error_domains": error_domains,
        "counts": _startup_reconciliation_counts(results),
    }


def _record_startup_reconciliation_outcome(db: Session, results: dict[str, Any]) -> None:
    summary = _summarize_startup_reconciliation(results)
    if summary["status"] == "skipped":
        logger.info(
            "Startup reconciliation skipped",
            extra={"status": "skipped", "reason": summary["reason"]},
        )
        best_effort_audit(
            db,
            "STARTUP_RECONCILIATION_SKIPPED",
            user="system",
            details=summary,
        )
        return

    logger.info(
        "Startup reconciliation finished",
        extra={
            "status": summary["status"],
            "domains": summary["domains"],
            "error_domains": summary["error_domains"],
        },
    )
    best_effort_audit(
        db,
        "STARTUP_RECONCILIATION_COMPLETED",
        user="system",
        details=summary,
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

@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info("ECUBE application starting")
    _log_demo_runtime_configuration()

    db_runtime_ready = False
    if not (settings.database_url or "").strip():
        logger.info(
            "DATABASE_URL is not configured; skipping DB startup tasks. "
            "Visit the setup wizard at /setup to provision the database."
        )
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
    if db_runtime_ready:
        try:
            from app.database import SessionLocal
            from app.services.drive_service import normalize_unreleased_drive_states

            db = SessionLocal()
            try:
                normalized_rows = normalize_unreleased_drive_states(db)
                if normalized_rows:
                    logger.info(
                        "Startup drive-state normalization applied",
                        extra={"normalized_rows": normalized_rows},
                    )
            finally:
                db.close()
        except Exception as exc:
            failure = _classify_unhandled_exception(exc)
            logger.info(
                "Startup drive-state normalization failed",
                extra={
                    "category": failure["category"],
                    "recommended_action": failure["recommended_action"],
                },
            )
            logger.debug(
                "Startup drive-state normalization raw failure",
                extra={"category": failure["category"], "raw_error": str(exc)},
            )

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
                logger.info("Startup reconciliation starting")
                best_effort_audit(
                    db,
                    "STARTUP_RECONCILIATION_STARTED",
                    user="system",
                    details={"status": "started"},
                )
                try:
                    results = run_startup_reconciliation(
                        db,
                        get_mount_provider(),
                        drive_mount_provider=get_drive_mount(),
                        os_user_provider=get_os_user_provider() if settings.role_resolver == "local" else None,
                        topology_source=get_drive_discovery().discover_topology,
                        filesystem_detector=get_filesystem_detector(),
                    )
                except Exception as exc:
                    db.rollback()
                    failure = _classify_unhandled_exception(exc)
                    logger.info(
                        "Startup reconciliation failed",
                        extra={
                            "category": failure["category"],
                            "recommended_action": failure["recommended_action"],
                        },
                    )
                    logger.debug(
                        "Startup reconciliation raw failure",
                        extra={"category": failure["category"], "raw_error": str(exc)},
                    )
                    best_effort_audit(
                        db,
                        "STARTUP_RECONCILIATION_FAILED",
                        user="system",
                        details={
                            "status": "failed",
                            "category": failure["category"],
                        },
                    )
                else:
                    _record_startup_reconciliation_outcome(db, results)
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


# ---------------------------------------------------------------------------
# /api prefix stripping (standalone mode)
# ---------------------------------------------------------------------------
# When serving the frontend directly (no nginx), the UI sends all API requests
# to /api/... because that's what nginx used to proxy.  Rewrite them to /...
# so they match the actual FastAPI routes.
# ---------------------------------------------------------------------------
if settings.serve_frontend_path:
    from app.spa import add_strip_api_prefix_middleware
    add_strip_api_prefix_middleware(app)


@app.middleware("http")
async def fallback_status_logging(request: Request, call_next):
    """Log 405 and 413 responses that bypass exception handlers.

    Some 405 responses are produced directly by Starlette routing and do not
    always traverse our ``StarletteHTTPException`` handler. Similarly, 413
    (Payload Too Large) responses may come from Uvicorn's ASGI request limits.
    Add fallback log lines for observability.
    """
    if not db_module.is_database_configured() and _is_browser_navigation_request(request) and _should_redirect_to_setup(request):
        return RedirectResponse(url="/setup", status_code=307)

    request.state.trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    response = await call_next(request)
    if request.method == "GET" and request.url.path.endswith("/audit/chain-of-custody"):
        response.headers["Cache-Control"] = "no-store"
    if "X-Trace-Id" not in response.headers:
        response.headers["X-Trace-Id"] = request.state.trace_id

    if response.status_code in (405, 413):
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
    # Query mounts first; only resolve provider if there are mounts to check
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

    # Only check mounts and resolve provider if there are configured mounts
    if configured_mounts:
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
                    reason="filesystem_mount_check_unknown",
                    details="A required filesystem mount readiness check returned an indeterminate result.",
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

    if not _is_usb_discovery_ready():
        logger.warning("Readiness probe dependency failed reason=usb_discovery_not_initialized")
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
    return build_ecube_openapi_schema(app, root_path_override=settings.api_root_path)


app.openapi = custom_openapi



# Auth router — unauthenticated (login endpoint)
app.include_router(auth.router)

# Setup router — unauthenticated (first-run wizard; guarded by has_any_admin check)
app.include_router(setup.router)

# Database setup router — unauthenticated during initial setup, admin-only after
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
app.include_router(password_policy.router, dependencies=[Depends(get_current_user)])
app.include_router(telemetry.router, dependencies=[Depends(get_current_user)])
app.include_router(users.router, dependencies=[Depends(get_current_user)])


def _error_response(
    status_code: int,
    code: str,
    message: str,
    trace_id: str,
    *,
    reason: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, trace_id=trace_id, reason=reason)
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


def _log_exception_info(
    request: Request,
    *,
    status_code: int,
    code: str,
    summary: str,
    trace_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    safe_context: dict[str, Any] = {
        "status_code": status_code,
        "error_code": code,
        "trace_id": trace_id,
        "request_path": request.url.path,
        "request_method": request.method,
        "failure_summary": summary,
    }
    if extra:
        safe_context.update(extra)
    logger.info(
        f"Handled exception status={status_code} code={code} trace_id={trace_id} path={request.url.path}",
        extra=safe_context,
    )


def _safe_http_exception_summary(status_code: int, code: str, detail: str) -> str:
    default_summaries = {
        401: "Unauthorized request",
        403: "Forbidden request",
        404: "Requested resource was not found",
        409: "Request conflicts with the current resource state",
        410: "Requested resource is no longer available",
        413: "Request payload is too large",
    }
    return sanitize_error_message(detail, default_summaries.get(status_code, f"{code} request failed"))


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    _log_exception_info(
        request,
        status_code=401,
        code=exc.code,
        summary=exc.message,
        trace_id=trace_id,
        extra={"error_category": "authentication_failure"},
    )
    logger.warning("401 %s trace_id=%s path=%s", exc.code, trace_id, request.url.path)
    _try_log_auth_failure(request, reason=exc.message, trace_id=trace_id)
    return _error_response(401, exc.code, exc.message, trace_id, reason=exc.reason)


@app.exception_handler(AuthorizationError)
async def authorization_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    _log_exception_info(
        request,
        status_code=403,
        code=exc.code,
        summary=exc.message,
        trace_id=trace_id,
        extra={"error_category": "authorization_failure"},
    )
    logger.warning("403 %s trace_id=%s path=%s", exc.code, trace_id, request.url.path)
    return _error_response(403, exc.code, exc.message, trace_id)


@app.exception_handler(ConflictError)
async def conflict_error_handler(request: Request, exc: ConflictError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    _log_exception_info(
        request,
        status_code=409,
        code=exc.code,
        summary=exc.message,
        trace_id=trace_id,
        extra={"error_category": "conflict"},
    )
    logger.warning("409 %s trace_id=%s path=%s", exc.code, trace_id, request.url.path)
    return _error_response(409, exc.code, exc.message, trace_id)


@app.exception_handler(ECUBEException)
async def ecube_exception_handler(request: Request, exc: ECUBEException) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    _log_exception_info(
        request,
        status_code=exc.status_code,
        code=exc.code,
        summary=exc.message,
        trace_id=trace_id,
        extra={"error_category": "application_exception"},
    )
    logger.error("%d %s trace_id=%s path=%s", exc.status_code, exc.code, trace_id, request.url.path)
    return _error_response(exc.status_code, exc.code, exc.message, trace_id)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    messages = []
    for error in exc.errors():
        loc = " -> ".join(str(part) for part in error["loc"])
        messages.append(f"{loc}: {error['msg']}")
    detail = "; ".join(messages)
    _log_exception_info(
        request,
        status_code=422,
        code="VALIDATION_ERROR",
        summary="Request validation failed",
        trace_id=trace_id,
        extra={"error_category": "validation_failure"},
    )
    logger.info("422 VALIDATION_ERROR trace_id=%s path=%s", trace_id, request.url.path)
    return _error_response(422, "VALIDATION_ERROR", detail, trace_id)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code_map = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        410: "GONE",
        413: "PAYLOAD_TOO_LARGE",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    safe_summary = _safe_http_exception_summary(exc.status_code, code, detail)
    _log_exception_info(
        request,
        status_code=exc.status_code,
        code=code,
        summary=safe_summary,
        trace_id=trace_id,
        extra={"error_category": "http_exception"},
    )
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
    trace_id = getattr(request.state, "trace_id", None) or str(uuid.uuid4())
    if is_encoding_error(exc):
        _log_exception_info(
            request,
            status_code=422,
            code="ENCODING_ERROR",
            summary="Request contains invalid characters.",
            trace_id=trace_id,
            extra={"error_category": "encoding_error"},
        )
        logger.warning("422 ENCODING_ERROR trace_id=%s path=%s", trace_id, request.url.path, exc_info=exc)
        return _error_response(422, "ENCODING_ERROR", "Request contains invalid characters.", trace_id)
    classification = _classify_unhandled_exception(exc)
    safe_context = {
        "trace_id": trace_id,
        "request_path": request.url.path,
        "error_category": classification["category"],
        "error_type": type(exc).__name__,
        "failure_summary": classification["summary"],
    }
    logger.info(
        (
            "Unhandled backend exception category="
            f"{classification['category']} trace_id={trace_id} path={request.url.path} "
            f"summary={classification['summary']}"
        ),
        extra=safe_context,
    )
    logger.debug(
        (
            "Unhandled backend exception remediation category="
            f"{classification['category']} trace_id={trace_id} path={request.url.path} "
            f"recommended_action={classification['recommended_action']}"
        ),
        extra={
            **safe_context,
            "recommended_action": classification["recommended_action"],
            "detail": classification["detail"],
        },
    )
    logger.exception(
        f"Unhandled exception trace_id={trace_id} path={request.url.path}",
        extra=safe_context,
    )
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.", trace_id)


# ---------------------------------------------------------------------------
# Optional embedded frontend (--no-nginx / standalone mode)
# ---------------------------------------------------------------------------
# When SERVE_FRONTEND_PATH points to a Vite dist/ directory, serve the
# pre-built SPA directly from FastAPI — no nginx required.  Mounted last
# so all API routes take priority.
# ---------------------------------------------------------------------------
if settings.serve_frontend_path:
    import pathlib

    _frontend_dir = pathlib.Path(settings.serve_frontend_path)
    _index_html = _frontend_dir / "index.html"

    if not _frontend_dir.is_dir():
        logger.error(
            "SERVE_FRONTEND_PATH=%s does not exist or is not a directory — "
            "frontend will NOT be served. Requests to / will return 404. "
            "Run the installer to deploy the frontend, or check the path.",
            settings.serve_frontend_path,
        )
    elif not _index_html.is_file():
        logger.error(
            "SERVE_FRONTEND_PATH=%s exists but index.html is missing — "
            "frontend will NOT be served. Requests to / will return 404. "
            "Ensure the pre-built frontend was deployed to this directory.",
            settings.serve_frontend_path,
        )

    if _frontend_dir.is_dir() and _index_html.is_file():
        from app.spa import mount_spa_frontend
        mount_spa_frontend(app, _frontend_dir)

        logger.info("Serving frontend from %s (standalone mode)", _frontend_dir)
        _themes_dir = _frontend_dir / "themes"
        if _themes_dir.is_dir():
            _theme_files = sorted(f.name for f in _themes_dir.iterdir() if f.is_file())
            logger.info("Theme files found in %s: %s", _themes_dir, _theme_files)
        else:
            logger.warning("No themes/ directory found at %s", _themes_dir)
else:
    logger.warning(
        "SERVE_FRONTEND_PATH is not set — frontend will NOT be served. "
        "API-only mode; requests to / will return 404.",
    )
