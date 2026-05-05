"""Tests for POST /auth/token local login endpoint."""

import json
import sys
from unittest.mock import MagicMock, patch

import jwt

import pytest

from app.config import settings
from app.main import app as fastapi_app
from app.models.users import UserRole
from app.routers.auth import _get_os_user, _get_pam, _get_password_policy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


# ---------------------------------------------------------------------------
# Successful authentication
# ---------------------------------------------------------------------------


def test_login_success_returns_token(unauthenticated_client, db):
    """Valid credentials yield a JWT with expected claims."""
    db.add(UserRole(username="testuser", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["evidence-team", "users"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
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


def test_login_success_includes_password_expiry_warning_metadata(unauthenticated_client, db):
    db.add(UserRole(username="warnuser", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["evidence-team"]

    mock_policy = MagicMock()
    mock_policy.get_password_expiration_info.return_value = MagicMock(
        warning_active=True,
        days_until_expiration=7,
    )

    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    fastapi_app.dependency_overrides[_get_password_policy] = lambda: mock_policy

    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "warnuser", "password": "secret"},
    )

    assert resp.status_code == 200
    assert resp.json()["password_expiration_warning_days"] == 7


def test_login_success_token_is_usable(unauthenticated_client, db):
    """A token obtained from /auth/token can authenticate subsequent requests."""
    db.add(UserRole(username="admin-user", role="admin"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["admins"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
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
    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "baduser", "password": "wrong"},
    )

    assert resp.status_code == 401
    assert "invalid" in resp.json()["message"].lower()


def test_login_password_expired_returns_structured_401(unauthenticated_client):
    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    mock_pam.code = 12
    mock_pam.reason = "Authentication token is no longer valid; new one required"
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "expireduser", "password": "wrong"},
    )

    assert resp.status_code == 401
    body = resp.json()
    assert body["reason"] == "password_expired"
    assert "expired" in body["message"].lower()


def test_login_account_expired_returns_structured_401(unauthenticated_client):
    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    mock_pam.code = 13
    mock_pam.reason = "User account has expired"
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "lockedout", "password": "wrong"},
    )

    assert resp.status_code == 401
    body = resp.json()
    assert body["reason"] == "account_expired"
    assert "account" in body["message"].lower()


def test_login_without_roles_returns_403(unauthenticated_client):
    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["ecube-processors"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "norole", "password": "secret"},
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "FORBIDDEN"
    assert "not assigned any ecube roles" in body["message"].lower()


def test_login_local_mode_uses_group_mapping_when_db_roles_missing(unauthenticated_client):
    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["ecube-processors"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    with patch.object(settings, "role_resolver", "local"), patch(
        "app.routers.auth.get_role_resolver",
    ) as mock_resolver_fn:
        mock_resolver_fn.return_value.resolve.return_value = ["processor"]

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "mappedlocal", "password": "secret"},
        )

    assert resp.status_code == 200
    claims = _decode_token(resp.json()["access_token"])
    assert claims["roles"] == ["processor"]


def test_login_db_roles_override_resolver_mapping(unauthenticated_client, db):
    db.add(UserRole(username="dboverride", role="auditor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["ecube-admins"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

    with patch("app.routers.auth.get_role_resolver") as mock_resolver_fn:
        mock_resolver_fn.return_value.resolve.return_value = ["admin"]

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "dboverride", "password": "secret"},
        )

    assert resp.status_code == 200
    claims = _decode_token(resp.json()["access_token"])
    assert claims["roles"] == ["auditor"]


def test_login_missing_username_returns_422(unauthenticated_client):
    mock_pam = MagicMock()
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"password": "secret"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "trace_id" in body
    assert "body -> username" in body["message"]


def test_login_missing_password_returns_422(unauthenticated_client):
    mock_pam = MagicMock()
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "testuser"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "trace_id" in body
    assert "body -> password" in body["message"]


def test_login_empty_username_returns_422(unauthenticated_client):
    mock_pam = MagicMock()
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "", "password": "secret"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "trace_id" in body
    assert "body -> username" in body["message"]


def test_login_empty_password_returns_422(unauthenticated_client):
    mock_pam = MagicMock()
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "testuser", "password": ""},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "trace_id" in body
    assert "body -> password" in body["message"]


# ---------------------------------------------------------------------------
# Token expiration
# ---------------------------------------------------------------------------


def test_token_expiration_uses_config(unauthenticated_client, monkeypatch, db):
    """Token exp claim reflects TOKEN_EXPIRE_MINUTES setting."""
    monkeypatch.setattr(settings, "token_expire_minutes", 30)

    db.add(UserRole(username="testuser", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = []
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
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

    db.add(UserRole(username="testuser", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = ["evidence-team"]
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
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

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam

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


def test_change_password_accepts_expired_password_and_returns_token(unauthenticated_client, db):
    from app.models.audit import AuditLog

    db.add(UserRole(username="expireduser", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    mock_pam.code = 12
    mock_pam.reason = "Authentication token is no longer valid; new one required"
    mock_pam.get_user_groups.return_value = ["ecube-processors"]

    mock_provider = MagicMock()
    mock_provider.reset_password.return_value = None

    mock_policy = MagicMock()
    mock_policy.get_password_expiration_info.return_value = None

    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    fastapi_app.dependency_overrides[_get_os_user] = lambda: mock_provider
    fastapi_app.dependency_overrides[_get_password_policy] = lambda: mock_policy

    resp = unauthenticated_client.post(
        "/auth/change-password",
        json={
            "username": "expireduser",
            "current_password": "Old#123456",
            "new_password": "NewStrong#123456",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["token_type"] == "bearer"
    mock_provider.reset_password.assert_called_once_with("expireduser", "NewStrong#123456")

    logs = db.query(AuditLog).filter(AuditLog.action == "PASSWORD_CHANGED").all()
    assert any(log.user == "expireduser" for log in logs)


def test_change_password_rejects_invalid_current_password(unauthenticated_client):
    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    mock_pam.code = None
    mock_pam.reason = "Authentication failure"

    mock_provider = MagicMock()
    mock_policy = MagicMock()
    mock_policy.get_password_expiration_info.return_value = None

    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    fastapi_app.dependency_overrides[_get_os_user] = lambda: mock_provider
    fastapi_app.dependency_overrides[_get_password_policy] = lambda: mock_policy

    resp = unauthenticated_client.post(
        "/auth/change-password",
        json={
            "username": "expireduser",
            "current_password": "wrong",
            "new_password": "NewStrong#123456",
        },
    )

    assert resp.status_code == 401
    assert "invalid" in resp.json()["message"].lower()
    mock_provider.reset_password.assert_not_called()


def test_change_password_returns_422_for_pam_policy_violation(unauthenticated_client):
    from app.infrastructure.os_user_protocol import OSUserError

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = False
    mock_pam.code = 12
    mock_pam.reason = "Authentication token is no longer valid; new one required"

    mock_provider = MagicMock()
    mock_provider.reset_password.side_effect = OSUserError(
        "Command failed (exit 1): chpasswd: PAM: BAD PASSWORD: The password fails the dictionary check"
    )

    mock_policy = MagicMock()
    mock_policy.get_password_expiration_info.return_value = None

    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    fastapi_app.dependency_overrides[_get_os_user] = lambda: mock_provider
    fastapi_app.dependency_overrides[_get_password_policy] = lambda: mock_policy

    resp = unauthenticated_client.post(
        "/auth/change-password",
        json={
            "username": "expireduser",
            "current_password": "Old#123456",
            "new_password": "password",
        },
    )

    assert resp.status_code == 422
    assert resp.json()["message"] == "New password cannot be based on a dictionary word or common password."


# ---------------------------------------------------------------------------
# No auth required
# ---------------------------------------------------------------------------


def test_auth_token_endpoint_requires_no_auth(unauthenticated_client, db):
    """The /auth/token endpoint must be accessible without a bearer token."""
    db.add(UserRole(username="noauth", role="processor"))
    db.commit()

    mock_pam = MagicMock()
    mock_pam.authenticate.return_value = True
    mock_pam.get_user_groups.return_value = []
    fastapi_app.dependency_overrides[_get_pam] = lambda: mock_pam
    resp = unauthenticated_client.post(
        "/auth/token",
        json={"username": "noauth", "password": "test"},
    )

    assert resp.status_code == 200


def test_auth_public_config_returns_safe_defaults_when_demo_disabled(unauthenticated_client, monkeypatch):
    """Public auth metadata should return empty safe defaults outside demo mode."""
    monkeypatch.setattr(settings, "demo_mode", False, raising=False)
    monkeypatch.setattr(settings, "demo_login_message", "Demo-only message", raising=False)
    monkeypatch.setattr(settings, "demo_shared_password", "demo", raising=False)
    monkeypatch.setattr(
        settings,
        "demo_accounts",
        [{"username": "demo_admin", "label": "Admin demo", "description": "Explore admin workflows"}],
        raising=False,
    )

    resp = unauthenticated_client.get("/auth/public-config")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "demo_mode_enabled": False,
        "default_nfs_client_version": settings.nfs_client_version,
        "nfs_client_version_options": ["4.2", "4.1", "4.0", "3"],
        "login_message": None,
        "shared_password": None,
        "demo_accounts": [],
        "password_change_allowed": True,
    }


def test_auth_public_config_returns_public_demo_password_and_safe_account_metadata(unauthenticated_client, monkeypatch):
    """Public auth metadata should expose the shared demo password and safe account fields only."""
    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_login_message", "Use the demo accounts below.", raising=False)
    monkeypatch.setattr(settings, "demo_shared_password", "demo", raising=False)
    monkeypatch.setattr(
        settings,
        "demo_accounts",
        [
            {
                "username": "demo_manager",
                "label": "Manager demo",
                "description": "Explore drive lifecycle and job visibility.",
                "password": "must-not-leak",
            }
        ],
        raising=False,
    )
    monkeypatch.setattr(settings, "demo_disable_password_change", True, raising=False)

    resp = unauthenticated_client.get("/auth/public-config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["demo_mode_enabled"] is True
    assert body["default_nfs_client_version"] == settings.nfs_client_version
    assert body["nfs_client_version_options"] == ["4.2", "4.1", "4.0", "3"]
    assert body["login_message"] == "Use the demo accounts below."
    assert body["shared_password"] == "demo"
    assert body["password_change_allowed"] is False
    assert body["demo_accounts"] == [
        {
            "username": "demo_manager",
            "label": "Manager demo",
            "description": "Explore drive lifecycle and job visibility.",
        }
    ]
    assert "must-not-leak" not in resp.text


def test_auth_public_config_uses_built_in_demo_defaults_when_only_demo_mode_is_enabled(
    unauthenticated_client, monkeypatch, tmp_path
):
    policy_path = tmp_path / "pwquality.conf"
    policy_path.write_text("minlen = 16\nminclass = 4\n", encoding="utf-8")

    monkeypatch.setattr(settings, "demo_mode", True, raising=False)
    monkeypatch.setattr(settings, "demo_login_message", "", raising=False)
    monkeypatch.setattr(settings, "demo_shared_password", "", raising=False)
    monkeypatch.setattr(settings, "demo_accounts", [], raising=False)
    monkeypatch.setattr(settings, "demo_disable_password_change", True, raising=False)
    monkeypatch.setattr(settings, "pwquality_conf_path", str(policy_path), raising=False)

    resp = unauthenticated_client.get("/auth/public-config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["demo_mode_enabled"] is True
    assert body["login_message"] == "Use the shared demo accounts below."
    assert len(body["shared_password"]) >= 16
    assert any(ch.islower() for ch in body["shared_password"])
    assert any(ch.isupper() for ch in body["shared_password"])
    assert any(ch.isdigit() for ch in body["shared_password"])
    assert any(not ch.isalnum() for ch in body["shared_password"])
    assert body["password_change_allowed"] is False
    assert body["demo_accounts"] == [
        {
            "username": "demo_admin",
            "label": "Admin demo",
            "description": "Full demo access for guided product walkthroughs.",
        },
        {
            "username": "demo_manager",
            "label": "Manager demo",
            "description": "Drive lifecycle, mounts, and job visibility.",
        },
        {
            "username": "demo_processor",
            "label": "Processor demo",
            "description": "Create and review sanitized export activity.",
        },
        {
            "username": "demo_auditor",
            "label": "Auditor demo",
            "description": "Read-only audit and verification review.",
        },
    ]


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


@pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX grp/pwd modules")
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


@pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX pwd module")
def test_get_user_groups_handles_unknown_user():
    """get_user_groups should return empty list for unknown users."""
    import pwd
    from app.services.pam_service import get_user_groups

    with patch.object(pwd, "getpwnam", side_effect=KeyError("unknown")):
        groups = get_user_groups("nonexistent")

    assert groups == []


@pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX pwd/grp modules")
def test_linux_pam_authenticator_uses_configured_service_and_fallback(monkeypatch):
    """Authenticator should try configured PAM service then fallback."""
    from app.services.pam_service import LinuxPamAuthenticator

    class _PamObj:
        def __init__(self):
            self.code = 0
            self.reason = ""
            self.calls = []

        def authenticate(self, username, password, service="login"):
            self.calls.append((username, password, service))
            if service == "login":
                self.code = 7
                self.reason = "Authentication failure"
                return False
            if service == "sudo":
                self.code = 0
                self.reason = "Success"
                return True
            return False

    pam_obj = _PamObj()

    class _PamModule:
        def pam(self):
            return pam_obj

    monkeypatch.setitem(sys.modules, "pam", _PamModule())
    monkeypatch.setattr(settings, "pam_service_name", "ecube")
    monkeypatch.setattr(settings, "pam_fallback_services", ["sudo"])

    auth = LinuxPamAuthenticator()
    assert auth.authenticate("admin", "secret") is True
    assert pam_obj.calls == [
        ("admin", "secret", "ecube"),
        ("admin", "secret", "sudo"),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX pwd/grp modules")
def test_linux_pam_authenticator_deduplicates_service_chain(monkeypatch):
    """Duplicate fallback services should be called only once."""
    from app.services.pam_service import LinuxPamAuthenticator

    class _PamObj:
        def __init__(self):
            self.calls = []

        def authenticate(self, username, password, service="login"):
            self.calls.append(service)
            return False

    pam_obj = _PamObj()

    class _PamModule:
        def pam(self):
            return pam_obj

    monkeypatch.setitem(sys.modules, "pam", _PamModule())
    monkeypatch.setattr(settings, "pam_service_name", "ecube")
    monkeypatch.setattr(settings, "pam_fallback_services", ["ecube", "sudo", "sudo"])

    auth = LinuxPamAuthenticator()
    assert auth.authenticate("admin", "secret") is False
    assert pam_obj.calls == ["ecube", "sudo"]
