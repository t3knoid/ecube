from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.config import settings
from app.logging_config import configure_logging
from app.models.audit import AuditLog
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

    @patch("app.services.configuration_service.database_service._write_env_settings")
    @patch("app.services.configuration_service.configure_logging")
    def test_update_configuration_logs_attempt_and_success(
        self,
        _mock_configure_logging,
        _mock_write_env,
        admin_client,
        db,
    ):
        target_level = "DEBUG" if settings.log_level != "DEBUG" else "INFO"

        resp = admin_client.put("/admin/configuration", json={"log_level": target_level})
        assert resp.status_code == 200, resp.json()

        attempt = (
            db.query(AuditLog)
            .filter(AuditLog.action == "CONFIGURATION_UPDATE_ATTEMPTED")
            .order_by(AuditLog.id.desc())
            .first()
        )
        updated = (
            db.query(AuditLog)
            .filter(AuditLog.action == "CONFIGURATION_UPDATED")
            .order_by(AuditLog.id.desc())
            .first()
        )

        assert attempt is not None
        assert updated is not None
        assert attempt.user == "admin-user"
        assert "log_level" in (attempt.details or {}).get("requested_settings", [])
        assert (attempt.details or {}).get("requested_values", {}).get("log_level") == target_level
        assert updated.user == "admin-user"
        changed_settings = (updated.details or {}).get("changed_settings", [])
        assert isinstance(changed_settings, list)
        changed_values = (updated.details or {}).get("changed_setting_values", {})
        if "log_level" in changed_values:
            assert changed_values["log_level"]["new_value"] == target_level

    @patch("app.services.configuration_service.database_service._write_env_settings")
    @patch("app.services.configuration_service.configure_logging")
    @patch("app.services.configuration_service.os.makedirs")
    @patch("app.services.configuration_service.open", create=True)
    def test_update_configuration_uses_requested_log_file_payload(
        self,
        _mock_open,
        _mock_makedirs,
        mock_configure_logging,
        mock_write_env,
        admin_client,
    ):
        resp = admin_client.put("/admin/configuration", json={"log_file": "/var/log/ecube/app.log"})
        assert resp.status_code == 200, resp.json()
        payload = resp.json()
        assert "log_file" in payload["changed_settings"]

        written = mock_write_env.call_args.args[0]
        assert written.get("LOG_FILE") == "/var/log/ecube/app.log"
        mock_configure_logging.assert_called_once()

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_first_log_file_write_logs_immediately(
        self,
        _mock_write_env,
        admin_client,
        tmp_path,
    ):
        original_values = {
            "log_level": settings.log_level,
            "log_format": settings.log_format,
            "log_file": settings.log_file,
            "log_file_max_bytes": settings.log_file_max_bytes,
            "log_file_backup_count": settings.log_file_backup_count,
        }

        settings.log_file = None
        configure_logging()

        log_path = tmp_path / "first-set.log"

        try:
            resp = admin_client.put("/admin/configuration", json={"log_file": str(log_path)})
            assert resp.status_code == 200, resp.json()
            payload = resp.json()
            assert "log_file" in payload["changed_settings"]

            assert log_path.exists()
            content = log_path.read_text(encoding="utf-8")
            assert "CONFIGURATION_LOGGING_REINITIALIZED" in content
            assert "CONFIGURATION_UPDATED" in content
        finally:
            settings.log_level = original_values["log_level"]
            settings.log_format = original_values["log_format"]
            settings.log_file = original_values["log_file"]
            settings.log_file_max_bytes = original_values["log_file_max_bytes"]
            settings.log_file_backup_count = original_values["log_file_backup_count"]
            try:
                configure_logging()
            except PermissionError:
                settings.log_file = None
                configure_logging()

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_recovers_named_app_loggers(
        self,
        _mock_write_env,
        admin_client,
        client,
        tmp_path,
    ):
        original_values = {
            "log_level": settings.log_level,
            "log_format": settings.log_format,
            "log_file": settings.log_file,
            "log_file_max_bytes": settings.log_file_max_bytes,
            "log_file_backup_count": settings.log_file_backup_count,
        }
        tracked_loggers = {
            name: logging.getLogger(name)
            for name in ("app.main", "app.logging_config", "app.services.audit_service")
        }
        original_logger_state = {
            name: {
                "disabled": logger.disabled,
                "propagate": logger.propagate,
                "level": logger.level,
                "handlers": list(logger.handlers),
            }
            for name, logger in tracked_loggers.items()
        }

        settings.log_file = None
        configure_logging()

        for logger in tracked_loggers.values():
            logger.disabled = True
            logger.propagate = False
            logger.setLevel(logging.ERROR)
            logger.handlers.clear()
            logger.addHandler(logging.NullHandler())

        log_path = tmp_path / "recover-named-loggers.log"

        try:
            resp = admin_client.put("/admin/configuration", json={"log_file": str(log_path)})
            assert resp.status_code == 200, resp.json()

            error_resp = client.post("/health")
            assert error_resp.status_code == 405

            for handler in logging.getLogger().handlers:
                try:
                    handler.flush()
                except Exception:
                    pass

            assert log_path.exists()
            content = log_path.read_text(encoding="utf-8")
            assert "Logging configured: level=INFO format=text file=" in content
            assert "CONFIGURATION_UPDATED" in content
            assert "405 HTTP_405" in content
        finally:
            settings.log_level = original_values["log_level"]
            settings.log_format = original_values["log_format"]
            settings.log_file = original_values["log_file"]
            settings.log_file_max_bytes = original_values["log_file_max_bytes"]
            settings.log_file_backup_count = original_values["log_file_backup_count"]

            for name, logger in tracked_loggers.items():
                logger.disabled = original_logger_state[name]["disabled"]
                logger.propagate = original_logger_state[name]["propagate"]
                logger.setLevel(original_logger_state[name]["level"])
                logger.handlers.clear()
                for handler in original_logger_state[name]["handlers"]:
                    logger.addHandler(handler)

            try:
                configure_logging()
            except PermissionError:
                settings.log_file = None
                configure_logging()

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
        db,
    ):
        mock_open.side_effect = PermissionError(13, "Permission denied")

        resp = admin_client.put("/admin/configuration", json={"log_file": "/var/log/ecube/denied.log"})
        assert resp.status_code == 422, resp.json()
        payload = resp.json()
        message = str(payload.get("detail") or payload.get("message") or "")
        assert "Unable to write log file" in message
        mock_write_env.assert_not_called()

        attempt = (
            db.query(AuditLog)
            .filter(AuditLog.action == "CONFIGURATION_UPDATE_ATTEMPTED")
            .order_by(AuditLog.id.desc())
            .first()
        )
        rejected = (
            db.query(AuditLog)
            .filter(AuditLog.action == "CONFIGURATION_UPDATE_REJECTED")
            .order_by(AuditLog.id.desc())
            .first()
        )

        assert attempt is not None
        assert rejected is not None
        assert "log_file" in (attempt.details or {}).get("requested_settings", [])
        assert "Unable to write log file" in str((rejected.details or {}).get("reason", ""))

    @patch("app.services.configuration_service.shutil.which", return_value="/usr/bin/systemctl")
    @patch("app.services.configuration_service.subprocess.run")
    def test_restart_success(self, mock_run, _mock_which, admin_client):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        resp = admin_client.post("/admin/configuration/restart", json={"confirm": True})
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["status"] == "restart_requested"
        assert data["service"] == "ecube"
