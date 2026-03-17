"""Session middleware configuration for ECUBE.

Supports two backends:

* **cookie** (default) — uses Starlette's ``SessionMiddleware`` with signed
  cookies (``itsdangerous``-based).
* **redis** — stores session payloads in Redis and sends only a session-id
  cookie to the browser.  Requires the ``redis`` package.

Backend selection is driven by ``settings.session_backend``.  If the Redis
backend is requested but the connection cannot be established, the application
gracefully falls back to cookie-based sessions and logs a warning.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.middleware.sessions import SessionMiddleware

from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _try_redis_backend() -> "object | None":
    """Attempt to connect to Redis and return a backend object.

    Returns ``None`` when Redis is unavailable or the ``redis`` package is
    not installed, allowing the caller to fall back to cookie-based sessions.
    """
    try:
        import redis as redis_lib  # optional dependency
    except ImportError:
        logger.warning(
            "SESSION_BACKEND=redis but the 'redis' package is not installed; "
            "falling back to cookie-based sessions"
        )
        return None

    url = settings.redis_url
    if not url:
        logger.warning(
            "SESSION_BACKEND=redis but REDIS_URL is not set; "
            "falling back to cookie-based sessions"
        )
        return None

    try:
        client = redis_lib.Redis.from_url(
            url,
            socket_connect_timeout=settings.redis_connection_timeout,
            socket_keepalive=settings.redis_socket_keepalive,
        )
        client.ping()
        logger.info("Redis session backend connected: %s", url)
        return client
    except Exception:
        logger.warning(
            "Redis session backend unavailable (url=%s); "
            "falling back to cookie-based sessions",
            url,
            exc_info=True,
        )
        return None


def mount_session_middleware(application: "FastAPI") -> None:
    """Add ``SessionMiddleware`` to *application* using the configured backend.

    Called once during application startup (lifespan).
    """
    backend_name = settings.session_backend
    redis_client = None

    if backend_name == "redis":
        redis_client = _try_redis_backend()
        if redis_client is None:
            backend_name = "cookie"  # graceful fallback

    logger.info("Session backend: %s", backend_name)

    application.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_cookie_expiration_seconds,
        same_site=settings.session_cookie_samesite,
        https_only=settings.session_cookie_secure,
        domain=settings.session_cookie_domain,
    )

    # Stash on app.state so other code can interact with the backend.
    application.state.session_backend_name = backend_name
    application.state.session_redis_client = redis_client
