from __future__ import annotations

from unittest.mock import MagicMock

from app.main import app as fastapi_app
from app.models.audit import AuditLog
from app.routers.password_policy import _get_provider
from app.infrastructure.password_policy_protocol import PasswordPolicyError
from app.services.password_policy_service import LinuxPasswordPolicyProvider


def test_password_policy_provider_returns_defaults_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.password_policy_service.settings.use_sudo", False)
    monkeypatch.setattr("app.services.password_policy_service.settings.pwquality_conf_path", str(tmp_path / "missing.conf"))

    provider = LinuxPasswordPolicyProvider()
    settings = provider.get_policy_settings()

    assert settings["minlen"] == 14
    assert settings["minclass"] == 3
    assert settings["retry"] == 3


def test_password_policy_provider_update_preserves_other_lines(monkeypatch, tmp_path):
    policy_path = tmp_path / "pwquality.conf"
    policy_path.write_text("# existing\nminlen = 12\ncustom_key = keep\n", encoding="utf-8")

    monkeypatch.setattr("app.services.password_policy_service.settings.use_sudo", False)
    monkeypatch.setattr("app.services.password_policy_service.settings.pwquality_conf_path", str(policy_path))

    provider = LinuxPasswordPolicyProvider()
    previous_values, next_values = provider.update_policy_settings({"minlen": 18, "retry": 4})

    assert previous_values["minlen"] == 12
    assert next_values["minlen"] == 18
    updated = policy_path.read_text(encoding="utf-8")
    assert "custom_key = keep" in updated
    assert "minlen = 18" in updated
    assert "retry = 4" in updated
    assert "enforce_for_root = 1" in updated


def test_get_password_policy_admin_endpoint_reads_current_values(admin_client, monkeypatch, tmp_path):
    policy_path = tmp_path / "pwquality.conf"
    policy_path.write_text("minlen = 20\nminclass = 4\n", encoding="utf-8")

    monkeypatch.setattr("app.services.password_policy_service.settings.use_sudo", False)
    monkeypatch.setattr("app.services.password_policy_service.settings.pwquality_conf_path", str(policy_path))

    resp = admin_client.get("/admin/password-policy")

    assert resp.status_code == 200
    body = resp.json()
    assert body["minlen"] == 20
    assert body["minclass"] == 4
    assert body["retry"] == 3


def test_put_password_policy_updates_file_and_audits(admin_client, db, monkeypatch, tmp_path):
    policy_path = tmp_path / "pwquality.conf"
    policy_path.write_text("minlen = 14\nretry = 3\n", encoding="utf-8")

    monkeypatch.setattr("app.services.password_policy_service.settings.use_sudo", False)
    monkeypatch.setattr("app.services.password_policy_service.settings.pwquality_conf_path", str(policy_path))

    resp = admin_client.put("/admin/password-policy", json={"minlen": 18, "retry": 5})

    assert resp.status_code == 200
    body = resp.json()
    assert body["minlen"] == 18
    assert body["retry"] == 5

    updated = policy_path.read_text(encoding="utf-8")
    assert "minlen = 18" in updated
    assert "retry = 5" in updated

    logs = db.query(AuditLog).filter(AuditLog.action == "PASSWORD_POLICY_UPDATED").all()
    assert len(logs) == 1
    assert logs[0].details["previous_values"]["minlen"] == 14
    assert logs[0].details["new_values"]["minlen"] == 18


def test_put_password_policy_rejects_enforce_for_root_zero(admin_client):
    resp = admin_client.put("/admin/password-policy", json={"enforce_for_root": 0})

    assert resp.status_code == 422
    assert "enforce_for_root" in resp.json()["message"]


def test_get_password_policy_sanitizes_provider_failure(admin_client):
    mock_provider = MagicMock()
    mock_provider.get_policy_settings.side_effect = PasswordPolicyError(
        "sudo: /usr/local/bin/ecube-write-pwquality-conf: Permission denied"
    )
    fastapi_app.dependency_overrides[_get_provider] = lambda: mock_provider

    resp = admin_client.get("/admin/password-policy")

    assert resp.status_code == 503
    assert resp.json()["message"] == "Permission or authentication failure"


def test_put_password_policy_sanitizes_provider_failure(admin_client):
    mock_provider = MagicMock()
    mock_provider.update_policy_settings.side_effect = PasswordPolicyError(
        "sudo: /usr/local/bin/ecube-write-pwquality-conf: Permission denied"
    )
    fastapi_app.dependency_overrides[_get_provider] = lambda: mock_provider

    resp = admin_client.put("/admin/password-policy", json={"minlen": 18})

    assert resp.status_code == 503
    assert resp.json()["message"] == "Permission or authentication failure"