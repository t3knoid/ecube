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
from typing import TYPE_CHECKING, Any, MutableMapping
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

class _RedisSessionDict(dict):
    """A dict subclass that tracks whether it has been modified."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._modified = False
        super().__init__(*args, **kwargs)

    # Track mutations -------------------------------------------------------
    def __setitem__(self, key: Any, value: Any) -> None:
        self._modified = True
        super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        self._modified = True
        super().__delitem__(key)

    def clear(self) -> None:
        self._modified = True
        super().clear()

    def pop(self, *args: Any) -> Any:
        self._modified = True
        return super().pop(*args)

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._modified = True
        super().update(*args, **kwargs)

    @property
    def is_modified(self) -> bool:
        return self._modified


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
        if cookie_value:
            session_id = cookie_value
            key = self._KEY_PREFIX + session_id
            try:
                raw = self.redis.get(key)
                if raw is not None:
                    initial_data = json.loads(raw)
            except Exception:
                logger.warning(
                    "Failed to load session %s from Redis; starting empty session",
                    session_id,
                    exc_info=True,
                )

        scope["session"] = _RedisSessionDict(initial_data)

        # --- Intercept the response to persist session -----------------------
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session: _RedisSessionDict = scope["session"]

                if not session and session_id is not None:
                    # Session was cleared — delete from Redis and expire cookie
                    try:
                        self.redis.delete(self._KEY_PREFIX + session_id)
                    except Exception:
                        pass
                    headers = MutableHeaders(scope=message)
                    cookie = self._build_cookie(session_id, delete=True)
                    headers.append("set-cookie", cookie)

                elif session.is_modified or (session and session_id is None):
                    # Session data was added / changed — persist to Redis
                    sid = session_id or secrets.token_urlsafe(32)
                    key = self._KEY_PREFIX + sid
                    try:
                        self.redis.setex(key, self.max_age, json.dumps(dict(session)))
                    except Exception:
                        logger.warning(
                            "Failed to persist session %s to Redis",
                            sid,
                            exc_info=True,
                        )
                    headers = MutableHeaders(scope=message)
                    cookie = self._build_cookie(sid)
                    headers.append("set-cookie", cookie)

            await send(message)

        await self.app(scope, receive, send_wrapper)

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


def _try_redis_backend() -> "object | None":
    """Attempt to connect to Redis and return a client object.

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

    safe_url = _redact_url(url)

    try:
        client = redis_lib.Redis.from_url(
            url,
            socket_connect_timeout=settings.redis_connection_timeout,
            socket_keepalive=settings.redis_socket_keepalive,
        )
        client.ping()
        logger.info("Redis session backend connected: %s", safe_url)
        return client
    except Exception:
        logger.warning(
            "Redis session backend unavailable (url=%s); "
            "falling back to cookie-based sessions",
            safe_url,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Public API — called once from app/main.py
# ---------------------------------------------------------------------------

def mount_session_middleware(application: "FastAPI") -> None:
    """Add session middleware to *application* using the configured backend.

    * ``cookie`` → Starlette ``SessionMiddleware`` (signed cookie payloads).
    * ``redis``  → :class:`RedisSessionMiddleware`` (server-side storage,
      session-id cookie only).

    Called once during application startup (lifespan).
    """
    backend_name = settings.session_backend
    redis_client = None

    if backend_name == "redis":
        redis_client = _try_redis_backend()
        if redis_client is None:
            backend_name = "cookie"  # graceful fallback

    logger.info("Session backend: %s", backend_name)

    if backend_name == "redis":
        application.add_middleware(
            RedisSessionMiddleware,
            redis_client=redis_client,
            session_cookie=settings.session_cookie_name,
            max_age=settings.session_cookie_expiration_seconds,
            same_site=settings.session_cookie_samesite,
            https_only=settings.session_cookie_secure,
            domain=settings.session_cookie_domain,
        )
    else:
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
