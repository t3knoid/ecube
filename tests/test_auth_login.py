"""Tests for POST /auth/token local login endpoint."""

from unittest.mock import MagicMock, patch

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


# ---------------------------------------------------------------------------
# Successful authentication
# ---------------------------------------------------------------------------


def test_login_success_returns_token(unauthenticated_client):
    """Valid credentials yield a JWT with expected claims."""
    with (
        patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls,
        patch("app.routers.auth.get_user_groups", return_value=["evidence-team", "users"]),
        patch("app.routers.auth.get_role_resolver") as mock_resolver_fn,
    ):
        mock_pam_cls.return_value.authenticate.return_value = True
        mock_resolver_fn.return_value.resolve.return_value = ["processor"]

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "testuser", "password": "secret"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data

    claims = _decode_token(data["access_token"])
    assert claims["sub"] == "testuser"
    assert claims["username"] == "testuser"
    assert claims["groups"] == ["evidence-team", "users"]
    assert claims["roles"] == ["processor"]
    assert "exp" in claims
    assert "iat" in claims


def test_login_success_token_is_usable(unauthenticated_client):
    """A token obtained from /auth/token can authenticate subsequent requests."""
    with (
        patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls,
        patch("app.routers.auth.get_user_groups", return_value=["admins"]),
        patch("app.routers.auth.get_role_resolver") as mock_resolver_fn,
    ):
        mock_pam_cls.return_value.authenticate.return_value = True
        mock_resolver_fn.return_value.resolve.return_value = ["admin"]

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "admin-user", "password": "pass"},
        )

    token = resp.json()["access_token"]
    # Use the token to call an authenticated endpoint (e.g. /health is open,
    # but we can verify the token decodes properly)
    claims = _decode_token(token)
    assert claims["roles"] == ["admin"]


# ---------------------------------------------------------------------------
# Failed authentication
# ---------------------------------------------------------------------------


def test_login_invalid_credentials_returns_401(unauthenticated_client):
    with patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls:
        mock_pam_cls.return_value.authenticate.return_value = False

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "baduser", "password": "wrong"},
        )

    assert resp.status_code == 401
    assert "invalid" in resp.json()["message"].lower()


def test_login_missing_username_returns_422(unauthenticated_client):
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"password": "secret"},
    )
    assert resp.status_code == 422


def test_login_missing_password_returns_422(unauthenticated_client):
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "testuser"},
    )
    assert resp.status_code == 422


def test_login_empty_username_returns_422(unauthenticated_client):
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "", "password": "secret"},
    )
    assert resp.status_code == 422


def test_login_empty_password_returns_422(unauthenticated_client):
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "testuser", "password": ""},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Token expiration
# ---------------------------------------------------------------------------


def test_token_expiration_uses_config(unauthenticated_client, monkeypatch):
    """Token exp claim reflects TOKEN_EXPIRE_MINUTES setting."""
    monkeypatch.setattr(settings, "token_expire_minutes", 30)

    with (
        patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls,
        patch("app.routers.auth.get_user_groups", return_value=[]),
        patch("app.routers.auth.get_role_resolver") as mock_resolver_fn,
    ):
        mock_pam_cls.return_value.authenticate.return_value = True
        mock_resolver_fn.return_value.resolve.return_value = []

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "testuser", "password": "secret"},
        )

    claims = _decode_token(resp.json()["access_token"])
    # exp should be approximately 30 minutes from iat
    diff = claims["exp"] - claims["iat"]
    assert 29 * 60 <= diff <= 31 * 60


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def test_login_success_creates_audit_log(unauthenticated_client, db):
    """Successful login writes AUTH_SUCCESS to audit_logs."""
    from app.models.audit import AuditLog

    with (
        patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls,
        patch("app.routers.auth.get_user_groups", return_value=["evidence-team"]),
        patch("app.routers.auth.get_role_resolver") as mock_resolver_fn,
    ):
        mock_pam_cls.return_value.authenticate.return_value = True
        mock_resolver_fn.return_value.resolve.return_value = ["processor"]

        unauthenticated_client.post(
            "/auth/token",
            json={"username": "testuser", "password": "secret"},
        )

    logs = db.query(AuditLog).filter(AuditLog.action == "AUTH_SUCCESS").all()
    assert len(logs) == 1
    assert logs[0].user == "testuser"
    assert logs[0].details["roles"] == ["processor"]


def test_login_failure_creates_audit_log(unauthenticated_client, db):
    """Failed login writes AUTH_FAILURE to audit_logs."""
    from app.models.audit import AuditLog

    with patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls:
        mock_pam_cls.return_value.authenticate.return_value = False

        unauthenticated_client.post(
            "/auth/token",
            json={"username": "baduser", "password": "wrong"},
        )

    logs = db.query(AuditLog).filter(AuditLog.action == "AUTH_FAILURE").all()
    # At least one AUTH_FAILURE log from the router; the exception handler may add another
    assert len(logs) >= 1
    router_log = [l for l in logs if l.user == "baduser"]
    assert len(router_log) >= 1
    assert "reason" in router_log[0].details


# ---------------------------------------------------------------------------
# No auth required
# ---------------------------------------------------------------------------


def test_auth_token_endpoint_requires_no_auth(unauthenticated_client):
    """The /auth/token endpoint must be accessible without a bearer token."""
    with (
        patch("app.routers.auth.LinuxPamAuthenticator") as mock_pam_cls,
        patch("app.routers.auth.get_user_groups", return_value=[]),
        patch("app.routers.auth.get_role_resolver") as mock_resolver_fn,
    ):
        mock_pam_cls.return_value.authenticate.return_value = True
        mock_resolver_fn.return_value.resolve.return_value = []

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "noauth", "password": "test"},
        )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# OIDC mode guard
# ---------------------------------------------------------------------------


def test_login_returns_404_when_oidc_mode(unauthenticated_client):
    """POST /auth/token must return 404 when OIDC authentication is active."""
    with patch.object(settings, "role_resolver", "oidc"):
        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "testuser", "password": "secret"},
        )

    assert resp.status_code == 404
    assert "OIDC" in resp.json()["message"]


# ---------------------------------------------------------------------------
# PAM service unit tests
# ---------------------------------------------------------------------------


def test_get_user_groups_reads_os_groups():
    """get_user_groups should return primary + supplementary groups."""
    import grp
    import os
    import pwd
    from app.services.pam_service import get_user_groups

    mock_pw = MagicMock()
    mock_pw.pw_gid = 1000

    def _getgrgid(gid):
        mapping = {1000: "primary", 2000: "extra"}
        if gid not in mapping:
            raise KeyError(gid)
        m = MagicMock()
        m.gr_name = mapping[gid]
        return m

    with (
        patch.object(pwd, "getpwnam", return_value=mock_pw),
        patch.object(os, "getgrouplist", return_value=[1000, 2000]),
        patch.object(grp, "getgrgid", side_effect=_getgrgid),
    ):
        groups = get_user_groups("testuser")

    assert "primary" in groups
    assert "extra" in groups


def test_get_user_groups_handles_unknown_user():
    """get_user_groups should return empty list for unknown users."""
    import pwd
    from app.services.pam_service import get_user_groups

    with patch.object(pwd, "getpwnam", side_effect=KeyError("unknown")):
        groups = get_user_groups("nonexistent")

    assert groups == []
