from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.schemas.configuration import ConfigurationUpdateRequest


class TestConfigurationSchemaValidation:
    def test_update_requires_at_least_one_field(self):
        with pytest.raises(ValidationError, match="At least one setting"):
            ConfigurationUpdateRequest()

    def test_update_accepts_log_level(self):
        req = ConfigurationUpdateRequest(log_level="DEBUG")
        assert req.log_level == "DEBUG"


class TestConfigurationEndpoints:
    def test_get_configuration_admin_allowed(self, admin_client):
        resp = admin_client.get("/admin/configuration")
        assert resp.status_code == 200
        data = resp.json()
        keys = {item["key"] for item in data["settings"]}
        assert "log_level" in keys
        assert "db_pool_recycle_seconds" in keys

    def test_get_configuration_non_admin_forbidden(self, client):
        resp = client.get("/admin/configuration")
        assert resp.status_code == 403

    @patch("app.services.configuration_service.database_service._write_env_settings")
    @patch("app.services.configuration_service.configure_logging")
    def test_update_configuration_restart_required_metadata(
        self,
        mock_configure_logging,
        mock_write_env,
        admin_client,
    ):
        payload = {
            "log_level": "DEBUG",
            "db_pool_recycle_seconds": 120,
        }
        resp = admin_client.put("/admin/configuration", json=payload)
        assert resp.status_code == 200, resp.json()

        data = resp.json()
        assert data["status"] == "updated"
        assert "log_level" in data["changed_settings"]
        assert "db_pool_recycle_seconds" in data["restart_required_settings"]
        assert data["restart_required"] is True

        mock_write_env.assert_called_once()
        mock_configure_logging.assert_called_once()

    def test_restart_requires_confirmation(self, admin_client):
        resp = admin_client.post("/admin/configuration/restart", json={"confirm": False})
        assert resp.status_code == 400

    @patch("app.services.configuration_service.database_service._write_env_settings")
    @patch("app.services.configuration_service.os.makedirs")
    @patch("app.services.configuration_service.open", create=True)
    def test_update_configuration_invalid_log_file_path_returns_422(
        self,
        mock_open,
        _mock_makedirs,
        mock_write_env,
        admin_client,
    ):
        mock_open.side_effect = PermissionError(13, "Permission denied")

        resp = admin_client.put("/admin/configuration", json={"log_file": "/var/log/ecube.log"})
        assert resp.status_code == 422, resp.json()
        payload = resp.json()
        message = str(payload.get("detail") or payload.get("message") or "")
        assert "Unable to write log file" in message
        mock_write_env.assert_not_called()

    @patch("app.services.configuration_service.shutil.which", return_value="/usr/bin/systemctl")
    @patch("app.services.configuration_service.subprocess.run")
    def test_restart_success(self, mock_run, _mock_which, admin_client):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        resp = admin_client.post("/admin/configuration/restart", json={"confirm": True})
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["status"] == "restart_requested"
        assert data["service"] == "ecube"
