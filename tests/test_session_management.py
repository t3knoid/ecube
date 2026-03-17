"""Tests for configurable session storage (issue #57).

Covers:
- Cookie configuration settings (AC1)
- Backend selection and graceful fallback (AC2, AC5)
- Redis configuration validation (AC3)
- SessionMiddleware integration (AC4)
- Cookie attributes in responses (AC7)
- Logging of session events (AC8)
- Redis backend stores data server-side (AC2)
"""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.session import RedisSessionMiddleware


# ---------------------------------------------------------------------------
# AC1 — Cookie configuration settings
# ---------------------------------------------------------------------------

class TestCookieConfigurationDefaults:
    """Verify default values for all session-related settings."""

    def test_default_backend(self):
        from app.config import Settings
        s = Settings()
        assert s.session_backend == "cookie"

    def test_default_cookie_name(self):
        from app.config import Settings
        s = Settings()
        assert s.session_cookie_name == "ecube_session"

    def test_default_expiration(self):
        from app.config import Settings
        s = Settings()
        assert s.session_cookie_expiration_seconds == 3600

    def test_default_domain_is_none(self):
        from app.config import Settings
        s = Settings()
        assert s.session_cookie_domain is None

    def test_default_secure(self):
        from app.config import Settings
        s = Settings()
        assert s.session_cookie_secure is True

    def test_default_httponly(self):
        from app.config import Settings
        s = Settings()
        assert s.session_cookie_httponly is True

    def test_default_samesite(self):
        from app.config import Settings
        s = Settings()
        assert s.session_cookie_samesite == "lax"


class TestCookieConfigurationOverrides:
    """Settings can be overridden via constructor (equivalent to env vars)."""

    def test_override_cookie_name(self):
        from app.config import Settings
        s = Settings(session_cookie_name="my_session")
        assert s.session_cookie_name == "my_session"

    def test_override_expiration(self):
        from app.config import Settings
        s = Settings(session_cookie_expiration_seconds=86400)
        assert s.session_cookie_expiration_seconds == 86400

    def test_override_domain(self):
        from app.config import Settings
        s = Settings(session_cookie_domain=".example.com")
        assert s.session_cookie_domain == ".example.com"

    def test_override_secure_false(self):
        from app.config import Settings
        s = Settings(session_cookie_secure=False)
        assert s.session_cookie_secure is False

    def test_override_httponly_false(self):
        from app.config import Settings
        s = Settings(session_cookie_httponly=False)
        assert s.session_cookie_httponly is False

    def test_override_samesite_strict(self):
        from app.config import Settings
        s = Settings(session_cookie_samesite="strict")
        assert s.session_cookie_samesite == "strict"

    def test_samesite_normalised_to_lowercase(self):
        from app.config import Settings
        s = Settings(session_cookie_samesite="Lax")
        assert s.session_cookie_samesite == "lax"


# ---------------------------------------------------------------------------
# AC2 / AC3 — Backend selection & Redis configuration
# ---------------------------------------------------------------------------

class TestBackendSelection:
    """Validate session_backend values and Redis config fields."""

    def test_backend_cookie(self):
        from app.config import Settings
        s = Settings(session_backend="cookie")
        assert s.session_backend == "cookie"

    def test_backend_redis(self):
        from app.config import Settings
        s = Settings(session_backend="redis")
        assert s.session_backend == "redis"

    def test_backend_invalid_rejected(self):
        from app.config import Settings
        with pytest.raises(Exception):
            Settings(session_backend="memcached")

    def test_redis_defaults(self):
        from app.config import Settings
        s = Settings()
        assert s.redis_url is None
        assert s.redis_connection_timeout == 5
        assert s.redis_socket_keepalive is True

    def test_redis_url_override(self):
        from app.config import Settings
        s = Settings(redis_url="redis://localhost:6379/1")
        assert s.redis_url == "redis://localhost:6379/1"


# ---------------------------------------------------------------------------
# AC4 — Session middleware is mounted on the app
# ---------------------------------------------------------------------------

class TestSessionMiddlewareMounted:
    """Ensure the real ECUBE ``app`` has a session middleware."""

    def test_session_middleware_present(self):
        from app.main import app as ecube_app

        middleware_classes = [
            m.cls for m in getattr(ecube_app, "user_middleware", [])
        ]
        has_session = (
            SessionMiddleware in middleware_classes
            or RedisSessionMiddleware in middleware_classes
        )
        assert has_session, (
            "Neither SessionMiddleware nor RedisSessionMiddleware found "
            "in middleware stack"
        )

    def test_health_endpoint_works(self, unauthenticated_client):
        resp = unauthenticated_client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# AC5 — Graceful degradation from Redis to cookie
# ---------------------------------------------------------------------------

class TestGracefulRedisFailover:
    """When Redis backend is requested but unavailable, fall back to cookie."""

    def test_fallback_when_redis_package_missing(self, caplog):
        from app.session import _try_redis_backend

        with patch.dict("sys.modules", {"redis": None}):
            with caplog.at_level(logging.WARNING):
                result = _try_redis_backend()
        assert result is None
        assert "not installed" in caplog.text or "falling back" in caplog.text

    def test_fallback_when_redis_url_not_set(self, caplog):
        from app.session import _try_redis_backend

        with patch("app.session.settings") as mock_settings:
            mock_settings.session_backend = "redis"
            mock_settings.redis_url = None
            with caplog.at_level(logging.WARNING):
                result = _try_redis_backend()
        assert result is None
        assert "REDIS_URL" in caplog.text

    def test_fallback_when_redis_connection_fails(self, caplog):
        from app.session import _try_redis_backend

        mock_redis_mod = MagicMock()
        mock_client = MagicMock()
        mock_client.ping.side_effect = ConnectionError("Connection refused")
        mock_redis_mod.Redis.from_url.return_value = mock_client

        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            with patch("app.session.settings") as mock_settings:
                mock_settings.session_backend = "redis"
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.redis_connection_timeout = 5
                mock_settings.redis_socket_keepalive = True
                with caplog.at_level(logging.WARNING):
                    result = _try_redis_backend()

        assert result is None
        assert "unavailable" in caplog.text

    def test_mount_session_middleware_redis_fallback(self, caplog):
        """mount_session_middleware gracefully falls back and sets backend_name."""
        from app.session import mount_session_middleware

        test_app = FastAPI()

        with patch("app.session.settings") as mock_settings:
            mock_settings.session_backend = "redis"
            mock_settings.redis_url = None
            mock_settings.secret_key = "test-secret"
            mock_settings.session_cookie_name = "ecube_session"
            mock_settings.session_cookie_expiration_seconds = 3600
            mock_settings.session_cookie_samesite = "lax"
            mock_settings.session_cookie_secure = False
            mock_settings.session_cookie_domain = None

            with caplog.at_level(logging.WARNING):
                mount_session_middleware(test_app)

        assert test_app.state.session_backend_name == "cookie"
        assert test_app.state.session_redis_client is None

    def test_fallback_mounts_cookie_middleware(self, caplog):
        """After fallback the mounted middleware is SessionMiddleware, not Redis."""
        from app.session import mount_session_middleware

        test_app = FastAPI()
        with patch("app.session.settings") as mock_settings:
            mock_settings.session_backend = "redis"
            mock_settings.redis_url = None
            mock_settings.secret_key = "test-secret"
            mock_settings.session_cookie_name = "ecube_session"
            mock_settings.session_cookie_expiration_seconds = 3600
            mock_settings.session_cookie_samesite = "lax"
            mock_settings.session_cookie_secure = False
            mock_settings.session_cookie_domain = None

            with caplog.at_level(logging.WARNING):
                mount_session_middleware(test_app)

        middleware_classes = [m.cls for m in test_app.user_middleware]
        assert SessionMiddleware in middleware_classes
        assert RedisSessionMiddleware not in middleware_classes


# ---------------------------------------------------------------------------
# AC2 — Redis backend actually stores data server-side
# ---------------------------------------------------------------------------

class _FakeRedis(dict):
    """Minimal in-memory Redis stand-in for testing."""

    def get(self, key):
        return super().get(key)

    def setex(self, key, ttl, value):
        self[key] = value

    def delete(self, key):
        self.pop(key, None)

    def ping(self):
        return True


class TestRedisBackendStoresServerSide:
    """Verify RedisSessionMiddleware stores payloads in Redis, not cookies."""

    @staticmethod
    def _make_app(fake_redis):
        inner = FastAPI()

        @inner.get("/set")
        async def set_session(request: Request):
            request.session["user"] = "alice"
            return JSONResponse({"ok": True})

        @inner.get("/get")
        async def get_session(request: Request):
            return JSONResponse({"user": request.session.get("user")})

        @inner.get("/clear")
        async def clear_session(request: Request):
            request.session.clear()
            return JSONResponse({"cleared": True})

        inner.add_middleware(
            RedisSessionMiddleware,
            redis_client=fake_redis,
            session_cookie="sid",
            max_age=3600,
            same_site="lax",
            https_only=False,
        )
        return inner

    def test_session_data_stored_in_redis(self):
        fake = _FakeRedis()
        app = self._make_app(fake)
        client = TestClient(app)

        resp = client.get("/set")
        assert resp.status_code == 200

        # Session data should be in our fake Redis store
        assert len(fake) == 1
        key = next(iter(fake))
        assert key.startswith("ecube:session:")
        stored = json.loads(fake[key])
        assert stored == {"user": "alice"}

    def test_cookie_contains_only_session_id(self):
        fake = _FakeRedis()
        app = self._make_app(fake)
        client = TestClient(app)

        resp = client.get("/set")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "sid=" in cookie_header
        # The cookie value must NOT contain the session payload
        assert "alice" not in cookie_header

    def test_session_round_trip(self):
        fake = _FakeRedis()
        app = self._make_app(fake)
        client = TestClient(app)

        # Write session
        client.get("/set")
        # Read it back (cookie is forwarded automatically by TestClient)
        resp = client.get("/get")
        assert resp.json() == {"user": "alice"}

    def test_session_clear_deletes_from_redis(self):
        fake = _FakeRedis()
        app = self._make_app(fake)
        client = TestClient(app)

        client.get("/set")
        assert len(fake) == 1

        client.get("/clear")
        assert len(fake) == 0

    def test_empty_session_not_stored(self):
        """A request that never writes to the session produces no Redis key."""
        fake = _FakeRedis()
        app = self._make_app(fake)
        client = TestClient(app)

        client.get("/get")
        assert len(fake) == 0

    def test_redis_set_failure_does_not_crash(self):
        """If Redis write fails, the request still succeeds."""
        failing = MagicMock()
        failing.get.return_value = None
        failing.setex.side_effect = ConnectionError("write failed")
        app = self._make_app(failing)
        client = TestClient(app)

        resp = client.get("/set")
        assert resp.status_code == 200

    def test_redis_get_failure_starts_empty_session(self):
        """If Redis read fails, the session starts empty."""
        failing = MagicMock()
        failing.get.side_effect = ConnectionError("read failed")
        failing.setex = MagicMock()
        app = self._make_app(failing)
        client = TestClient(app, cookies={"sid": "bogus-id"})

        resp = client.get("/get")
        assert resp.status_code == 200
        assert resp.json() == {"user": None}


class TestMountSessionMiddlewareRedis:
    """mount_session_middleware mounts RedisSessionMiddleware when Redis works."""

    def test_redis_backend_mounts_redis_middleware(self, caplog):
        from app.session import mount_session_middleware

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True

        mock_redis_mod = MagicMock()
        mock_redis_mod.Redis.from_url.return_value = mock_redis

        test_app = FastAPI()
        with patch.dict("sys.modules", {"redis": mock_redis_mod}):
            with patch("app.session.settings") as mock_settings:
                mock_settings.session_backend = "redis"
                mock_settings.redis_url = "redis://localhost:6379/0"
                mock_settings.redis_connection_timeout = 5
                mock_settings.redis_socket_keepalive = True
                mock_settings.session_cookie_name = "ecube_session"
                mock_settings.session_cookie_expiration_seconds = 3600
                mock_settings.session_cookie_samesite = "lax"
                mock_settings.session_cookie_secure = False
                mock_settings.session_cookie_domain = None

                with caplog.at_level(logging.INFO):
                    mount_session_middleware(test_app)

        assert test_app.state.session_backend_name == "redis"
        assert test_app.state.session_redis_client is mock_redis

        middleware_classes = [m.cls for m in test_app.user_middleware]
        assert RedisSessionMiddleware in middleware_classes
        assert SessionMiddleware not in middleware_classes
        assert "Session backend: redis" in caplog.text


# ---------------------------------------------------------------------------
# AC7 — Cookie attribute validation (cookie backend)
# ---------------------------------------------------------------------------

class TestCookieAttributes:
    """Verify cookie flags are applied correctly by the cookie middleware."""

    def _make_app(self, **session_overrides):
        """Build a minimal FastAPI app with SessionMiddleware."""
        inner_app = FastAPI()

        @inner_app.get("/set-session")
        async def set_session(request: Request):
            request.session["user"] = "alice"
            return JSONResponse({"ok": True})

        defaults = dict(
            secret_key="test-secret-key-for-signing",
            session_cookie="ecube_session",
            max_age=3600,
            same_site="lax",
            https_only=False,
            domain=None,
        )
        defaults.update(session_overrides)
        inner_app.add_middleware(SessionMiddleware, **defaults)
        return inner_app

    def test_cookie_name_in_response(self):
        app = self._make_app(session_cookie="my_cookie")
        client = TestClient(app)
        resp = client.get("/set-session")
        assert resp.status_code == 200
        cookie_header = resp.headers.get("set-cookie", "")
        assert "my_cookie=" in cookie_header

    def test_cookie_httponly_flag(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.get("/set-session")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "httponly" in cookie_header.lower()

    def test_cookie_samesite_strict(self):
        app = self._make_app(same_site="strict")
        client = TestClient(app)
        resp = client.get("/set-session")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "samesite=strict" in cookie_header.lower()

    def test_cookie_samesite_lax(self):
        app = self._make_app(same_site="lax")
        client = TestClient(app)
        resp = client.get("/set-session")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "samesite=lax" in cookie_header.lower()

    def test_cookie_max_age(self):
        app = self._make_app(max_age=86400)
        client = TestClient(app)
        resp = client.get("/set-session")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "max-age=86400" in cookie_header.lower()

    def test_cookie_path(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.get("/set-session")
        cookie_header = resp.headers.get("set-cookie", "")
        assert "path=/" in cookie_header.lower()


# ---------------------------------------------------------------------------
# AC7 — Cookie attributes for Redis backend
# ---------------------------------------------------------------------------

class TestRedisBackendCookieAttributes:
    """Verify cookie flags from RedisSessionMiddleware."""

    @staticmethod
    def _make_app(fake_redis, **overrides):
        inner = FastAPI()

        @inner.get("/set-session")
        async def set_session(request: Request):
            request.session["user"] = "alice"
            return JSONResponse({"ok": True})

        defaults = dict(
            redis_client=fake_redis,
            session_cookie="ecube_session",
            max_age=3600,
            same_site="lax",
            https_only=False,
        )
        defaults.update(overrides)
        inner.add_middleware(RedisSessionMiddleware, **defaults)
        return inner

    def test_cookie_name(self):
        app = self._make_app(_FakeRedis(), session_cookie="my_redis_sid")
        resp = TestClient(app).get("/set-session")
        assert "my_redis_sid=" in resp.headers.get("set-cookie", "")

    def test_cookie_httponly(self):
        app = self._make_app(_FakeRedis())
        resp = TestClient(app).get("/set-session")
        assert "httponly" in resp.headers.get("set-cookie", "").lower()

    def test_cookie_samesite(self):
        app = self._make_app(_FakeRedis(), same_site="strict")
        resp = TestClient(app).get("/set-session")
        assert "samesite=strict" in resp.headers.get("set-cookie", "").lower()

    def test_cookie_max_age(self):
        app = self._make_app(_FakeRedis(), max_age=86400)
        resp = TestClient(app).get("/set-session")
        assert "max-age=86400" in resp.headers.get("set-cookie", "").lower()

    def test_cookie_path(self):
        app = self._make_app(_FakeRedis())
        resp = TestClient(app).get("/set-session")
        assert "path=/" in resp.headers.get("set-cookie", "").lower()


# ---------------------------------------------------------------------------
# AC8 — Logging of session events
# ---------------------------------------------------------------------------

class TestSessionEventLogging:
    """Session backend selection is logged on startup."""

    def test_logs_cookie_backend(self, caplog):
        from app.session import mount_session_middleware

        test_app = FastAPI()
        with patch("app.session.settings") as mock_settings:
            mock_settings.session_backend = "cookie"
            mock_settings.secret_key = "test-secret"
            mock_settings.session_cookie_name = "ecube_session"
            mock_settings.session_cookie_expiration_seconds = 3600
            mock_settings.session_cookie_samesite = "lax"
            mock_settings.session_cookie_secure = False
            mock_settings.session_cookie_domain = None

            with caplog.at_level(logging.INFO):
                mount_session_middleware(test_app)

        assert "Session backend: cookie" in caplog.text

    def test_logs_redis_fallback(self, caplog):
        from app.session import mount_session_middleware

        test_app = FastAPI()
        with patch("app.session.settings") as mock_settings:
            mock_settings.session_backend = "redis"
            mock_settings.redis_url = None
            mock_settings.secret_key = "test-secret"
            mock_settings.session_cookie_name = "ecube_session"
            mock_settings.session_cookie_expiration_seconds = 3600
            mock_settings.session_cookie_samesite = "lax"
            mock_settings.session_cookie_secure = False
            mock_settings.session_cookie_domain = None

            with caplog.at_level(logging.INFO):
                mount_session_middleware(test_app)

        assert "Session backend: cookie" in caplog.text
        assert "REDIS_URL" in caplog.text


# ---------------------------------------------------------------------------
# 11. URL credential redaction
# ---------------------------------------------------------------------------
class TestRedactUrl:
    """Verify _redact_url strips credentials from Redis URLs."""

    def test_redacts_user_and_password(self):
        from app.session import _redact_url

        assert _redact_url("redis://alice:s3cret@db.host:6379/0") == "redis://***@db.host:6379/0"

    def test_redacts_password_only(self):
        from app.session import _redact_url

        assert _redact_url("redis://:s3cret@db.host:6379/0") == "redis://***@db.host:6379/0"

    def test_redacts_user_only(self):
        from app.session import _redact_url

        assert _redact_url("redis://alice@db.host:6379/0") == "redis://***@db.host:6379/0"

    def test_no_credentials_unchanged(self):
        from app.session import _redact_url

        assert _redact_url("redis://db.host:6379/0") == "redis://db.host:6379/0"

    def test_no_port_with_credentials(self):
        from app.session import _redact_url

        assert _redact_url("redis://alice:pass@db.host/2") == "redis://***@db.host/2"

    def test_unparseable_returns_placeholder(self):
        from app.session import _redact_url

        # Force an exception inside _redact_url
        with patch("app.session.urlparse", side_effect=ValueError("bad")):
            assert _redact_url("redis://host:6379") == "<unparseable>"
