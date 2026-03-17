"""Session middleware configuration for ECUBE.

Supports two backends:

* **cookie** (default) — uses Starlette's ``SessionMiddleware`` with signed
  cookies (``itsdangerous``-based).  Session data is stored entirely
  client-side in the cookie payload.
* **redis** — stores session payloads server-side in Redis and sends only an
  opaque session-id cookie to the browser.  Requires the ``redis`` package.

Backend selection is driven by ``settings.session_backend``.  If the Redis
backend is requested but the connection cannot be established, the application
gracefully falls back to cookie-based sessions and logs a warning.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis session middleware
# ---------------------------------------------------------------------------

class RedisSessionMiddleware:
    """ASGI middleware that stores session data in Redis.

    Only an opaque session-id is sent to the browser as a cookie.  The full
    session payload lives in Redis, keyed as ``ecube:session:<id>``.
    """

    _KEY_PREFIX = "ecube:session:"

    def __init__(
        self,
        app: ASGIApp,
        redis_client: Any,
        *,
        session_cookie: str = "ecube_session",
        max_age: int = 3600,
        same_site: str = "lax",
        https_only: bool = True,
        domain: str | None = None,
    ) -> None:
        self.app = app
        self.redis = redis_client
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.same_site = same_site
        self.https_only = https_only
        self.domain = domain

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        session_id: str | None = None
        initial_data: dict = {}

        # --- Load existing session from Redis --------------------------------
        cookie_value = connection.cookies.get(self.session_cookie)
        if cookie_value and self._is_valid_session_id(cookie_value):
            key = self._KEY_PREFIX + cookie_value
            try:
                raw = await self.redis.get(key)
                if raw is not None:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        session_id = cookie_value
                        initial_data = data
                    else:
                        logger.warning(
                            "Session data in Redis is not a dict; "
                            "starting fresh session",
                        )
            except Exception:
                logger.warning(
                    "Failed to load session from Redis; starting fresh session",
                    exc_info=True,
                )

        scope["session"] = dict(initial_data)
        # Snapshot the initial state so we can detect *any* change at
        # response time — including nested mutations, setdefault, etc.
        initial_snapshot = json.dumps(initial_data, sort_keys=True)

        # --- Intercept the response to persist session -----------------------
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session: dict = scope["session"]
                current_snapshot = json.dumps(dict(session), sort_keys=True)

                if not session and session_id is not None:
                    # Session was cleared — delete from Redis and expire cookie
                    try:
                        await self.redis.delete(self._KEY_PREFIX + session_id)
                    except Exception:
                        pass
                    headers = MutableHeaders(scope=message)
                    cookie = self._build_cookie(session_id, delete=True)
                    headers.append("set-cookie", cookie)

                elif current_snapshot != initial_snapshot or (
                    session and session_id is None
                ):
                    # Session data was added / changed — persist to Redis.
                    # Only issue a Set-Cookie when persistence succeeds;
                    # otherwise the client would hold a session-id with no
                    # server-side data, causing "lost session" on the next
                    # request.
                    sid = session_id or secrets.token_urlsafe(32)
                    key = self._KEY_PREFIX + sid
                    try:
                        payload = json.dumps(dict(session))
                        await self.redis.setex(key, self.max_age, payload)
                    except Exception:
                        logger.warning(
                            "Failed to persist session %s to Redis",
                            sid,
                            exc_info=True,
                        )
                    else:
                        headers = MutableHeaders(scope=message)
                        cookie = self._build_cookie(sid)
                        headers.append("set-cookie", cookie)

            await send(message)

        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _is_valid_session_id(value: str) -> bool:
        """Reject obviously bogus session-id cookies.

        ``secrets.token_urlsafe(32)`` produces a 43-character URL-safe
        base64 string.  We accept anything between 22 and 128 characters
        containing only URL-safe base64 characters to allow for future
        changes while rejecting garbage / injection attempts.
        """
        import re
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{22,128}", value))

    def _build_cookie(self, session_id: str, *, delete: bool = False) -> str:
        parts = [f"{self.session_cookie}={session_id}"]
        parts.append("path=/")
        if delete:
            parts.append("max-age=0")
        else:
            parts.append(f"max-age={self.max_age}")
        if self.https_only:
            parts.append("secure")
        parts.append("httponly")
        parts.append(f"samesite={self.same_site}")
        if self.domain:
            parts.append(f"domain={self.domain}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Redis connection helper
# ---------------------------------------------------------------------------

def _redact_url(url: str) -> str:
    """Return *url* with any userinfo (username/password) replaced by ``***``."""
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password:
            # Rebuild netloc as ***@host:port
            host_port = parsed.hostname or ""
            if parsed.port:
                host_port += f":{parsed.port}"
            redacted_netloc = f"***@{host_port}"
            return urlunparse(parsed._replace(netloc=redacted_netloc))
        return url
    except Exception:
        return "<unparseable>"


async def _try_redis_backend() -> "object | None":
    """Attempt to connect to Redis and return an async client object.

    Returns ``None`` when Redis is unavailable or the ``redis`` package is
    not installed, allowing the caller to fall back to cookie-based sessions.
    """
    try:
        import redis.asyncio as aioredis  # optional dependency
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

    safe_url = _redact_url(url)

    client = None
    try:
        client = aioredis.Redis.from_url(
            url,
            socket_connect_timeout=settings.redis_connection_timeout,
            socket_keepalive=settings.redis_socket_keepalive,
        )
        await client.ping()
        logger.info("Redis session backend connected: %s", safe_url)
        return client
    except Exception:
        # Close the client if it was created, to avoid leaking connections.
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        logger.warning(
            "Redis session backend unavailable (url=%s); "
            "falling back to cookie-based sessions",
            safe_url,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Session proxy — always mounted at import time (no network I/O)
# ---------------------------------------------------------------------------

class _SessionProxy:
    """Thin ASGI proxy that delegates to a cookie or Redis session backend.

    Mounted at import time with a cookie backend (no network I/O).  During
    lifespan startup, :func:`init_session_backend` sets
    ``app.state.session_redis_client``; the proxy detects this on the first
    HTTP request and transparently upgrades to the Redis backend.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        secret_key: str,
        session_cookie: str = "ecube_session",
        max_age: int = 3600,
        same_site: str = "lax",
        https_only: bool = True,
        domain: str | None = None,
    ) -> None:
        self.app = app  # next ASGI app in the middleware chain
        self._session_kwargs = dict(
            session_cookie=session_cookie,
            max_age=max_age,
            same_site=same_site,
            https_only=https_only,
            domain=domain,
        )
        self._secret_key = secret_key
        # Start with cookie-based sessions (no network I/O required).
        self._cookie_backend: ASGIApp = SessionMiddleware(
            app,
            secret_key=secret_key,
            **self._session_kwargs,
        )
        self._redis_backend: ASGIApp | None = None
        self._using_redis = False

    def _ensure_redis_backend(self, redis_client: Any) -> None:
        """Lazily build the Redis backend the first time it's needed."""
        if self._redis_backend is None:
            self._redis_backend = RedisSessionMiddleware(
                self.app, redis_client=redis_client, **self._session_kwargs,
            )
            self._using_redis = True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # For non-HTTP scopes (e.g. lifespan), always pass through.
        if scope["type"] not in ("http", "websocket"):
            await self._cookie_backend(scope, receive, send)
            return

        # Check if a Redis client was provided during lifespan startup.
        if not self._using_redis:
            fastapi_app = scope.get("app")
            redis_client = (
                getattr(fastapi_app.state, "session_redis_client", None)
                if fastapi_app is not None
                else None
            )
            if redis_client is not None:
                self._ensure_redis_backend(redis_client)

        if self._using_redis:
            await self._redis_backend(scope, receive, send)  # type: ignore[arg-type]
        else:
            await self._cookie_backend(scope, receive, send)


# ---------------------------------------------------------------------------
# Public API — called from app/main.py
# ---------------------------------------------------------------------------

def mount_session_middleware(application: "FastAPI") -> None:
    """Add the session middleware proxy to *application*.  **No network I/O.**

    The proxy starts with a cookie-based backend.  Call
    :func:`init_session_backend` during lifespan startup to optionally
    upgrade to a Redis backend.
    """
    application.add_middleware(
        _SessionProxy,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_cookie_expiration_seconds,
        same_site=settings.session_cookie_samesite,
        https_only=settings.session_cookie_secure,
        domain=settings.session_cookie_domain,
    )
    application.state.session_backend_name = "cookie"
    application.state.session_redis_client = None


async def init_session_backend(application: "FastAPI") -> None:
    """Initialise the session backend.  Called during lifespan startup.

    For the ``cookie`` backend this is a no-op.  For ``redis`` it attempts a
    connection and, on success, upgrades the session proxy to Redis-backed
    sessions.  On failure the cookie backend remains active (graceful fallback).
    """
    if settings.session_backend != "redis":
        logger.info("Session backend: cookie")
        return

    redis_client = await _try_redis_backend()
    if redis_client is None:
        logger.info("Session backend: cookie (Redis fallback)")
        return

    application.state.session_backend_name = "redis"
    application.state.session_redis_client = redis_client
    logger.info("Session backend: redis")


async def close_session_backend(application: "FastAPI") -> None:
    """Shut down the session backend.  Called during lifespan shutdown."""
    redis_client = getattr(application.state, "session_redis_client", None)
    if redis_client is not None:
        try:
            await redis_client.aclose()
            logger.info("Redis session client closed")
        except Exception:
            logger.warning(
                "Failed to close Redis session client", exc_info=True,
            )
        application.state.session_redis_client = None
