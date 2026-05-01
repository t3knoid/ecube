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

    def test_update_accepts_copy_job_timeout(self):
        req = ConfigurationUpdateRequest(copy_job_timeout=120)
        assert req.copy_job_timeout == 120

    def test_update_accepts_startup_analysis_batch_size(self):
        req = ConfigurationUpdateRequest(startup_analysis_batch_size=250)
        assert req.startup_analysis_batch_size == 250

    def test_update_accepts_nfs_client_version(self):
        req = ConfigurationUpdateRequest(nfs_client_version="4.2")
        assert req.nfs_client_version == "4.2"

    def test_update_accepts_job_detail_files_page_size(self):
        req = ConfigurationUpdateRequest(job_detail_files_page_size=60)
        assert req.job_detail_files_page_size == 60

    def test_update_accepts_callback_default_url(self):
        req = ConfigurationUpdateRequest(callback_default_url="https://example.com/default-webhook")
        assert req.callback_default_url == "https://example.com/default-webhook"

    def test_update_accepts_callback_proxy_url(self):
        req = ConfigurationUpdateRequest(callback_proxy_url="http://proxy.example.com:8080")
        assert req.callback_proxy_url == "http://proxy.example.com:8080"

    def test_update_accepts_callback_hmac_secret(self):
        req = ConfigurationUpdateRequest(callback_hmac_secret="super-secret")
        assert req.callback_hmac_secret == "super-secret"

    def test_update_accepts_callback_payload_contract(self):
        req = ConfigurationUpdateRequest(
            callback_payload_fields=["event", "project_id", "completion_result"],
            callback_payload_field_map={
                "type": "event",
                "summary": "project=${project_id};result=${completion_result}",
            },
        )
        assert req.callback_payload_fields == ["event", "project_id", "completion_result"]
        assert req.callback_payload_field_map == {
            "type": "event",
            "summary": "project=${project_id};result=${completion_result}",
        }

    def test_update_allows_clearing_callback_default_url_with_blank(self):
        req = ConfigurationUpdateRequest(callback_default_url="   ")
        assert req.callback_default_url is None

    def test_update_rejects_non_https_callback_default_url(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(callback_default_url="http://example.com/webhook")

    def test_update_rejects_callback_proxy_url_with_credentials(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(callback_proxy_url="http://user:pass@proxy.example.com:8080")

    def test_update_rejects_setting_and_clearing_callback_hmac_secret_together(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(
                callback_hmac_secret="super-secret",
                clear_callback_hmac_secret=True,
            )

    def test_update_rejects_callback_payload_field_outside_allowlist(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(
                callback_payload_fields=["event"],
                callback_payload_field_map={"project": "project_id"},
            )

    def test_update_rejects_callback_payload_map_without_explicit_allowlist(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(
                callback_payload_field_map={"project": "project_id"},
            )

    def test_update_rejects_callback_payload_template_with_unknown_token(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(
                callback_payload_fields=["event"],
                callback_payload_field_map={"summary": "job=${job_id}"},
            )

    def test_update_rejects_job_detail_files_page_size_below_minimum(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(job_detail_files_page_size=10)

    def test_update_rejects_startup_analysis_batch_size_below_minimum(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(startup_analysis_batch_size=0)

    def test_update_rejects_startup_analysis_batch_size_above_maximum(self):
        with pytest.raises(ValidationError):
            ConfigurationUpdateRequest(startup_analysis_batch_size=5001)


class TestConfigurationEndpoints:
    def test_get_configuration_admin_allowed(self, admin_client):
        resp = admin_client.get("/admin/configuration")
        assert resp.status_code == 200
        data = resp.json()
        keys = {item["key"] for item in data["settings"]}
        assert "log_level" in keys
        assert "nfs_client_version" in keys
        assert "db_pool_recycle_seconds" in keys
        assert "startup_analysis_batch_size" in keys
        assert "copy_job_timeout" in keys
        assert "job_detail_files_page_size" in keys
        assert "callback_default_url" in keys
        assert "callback_proxy_url" in keys
        assert "callback_payload_fields" in keys
        assert "callback_payload_field_map" in keys
        assert "callback_hmac_secret_configured" in keys
        assert "callback_hmac_secret" not in keys

    def test_get_configuration_returns_default_enabled_log_file(self, admin_client):
        resp = admin_client.get("/admin/configuration")
        assert resp.status_code == 200

        settings_map = {item["key"]: item["value"] for item in resp.json()["settings"]}
        assert settings_map["log_file"] == "/var/log/ecube/app.log"

    def test_get_configuration_returns_callback_default_url_none_by_default(self, admin_client):
        resp = admin_client.get("/admin/configuration")
        assert resp.status_code == 200

        settings_map = {item["key"]: item["value"] for item in resp.json()["settings"]}
        assert settings_map["callback_default_url"] is None

    def test_get_configuration_returns_callback_payload_contract(self, admin_client):
        original_fields = settings.callback_payload_fields
        original_map = settings.callback_payload_field_map
        settings.callback_payload_fields = ["event", "project_id"]
        settings.callback_payload_field_map = {"type": "event", "project": "project_id"}
        try:
            resp = admin_client.get("/admin/configuration")
            assert resp.status_code == 200

            settings_map = {item["key"]: item["value"] for item in resp.json()["settings"]}
            assert settings_map["callback_payload_fields"] == ["event", "project_id"]
            assert settings_map["callback_payload_field_map"] == {
                "type": "event",
                "project": "project_id",
            }
        finally:
            settings.callback_payload_fields = original_fields
            settings.callback_payload_field_map = original_map

    def test_get_configuration_returns_callback_hmac_secret_status_only(self, admin_client):
        original_secret = settings.callback_hmac_secret
        settings.callback_hmac_secret = "stored-secret"
        try:
            resp = admin_client.get("/admin/configuration")
            assert resp.status_code == 200

            settings_map = {item["key"]: item["value"] for item in resp.json()["settings"]}
            assert settings_map["callback_hmac_secret_configured"] is True
            assert "callback_hmac_secret" not in settings_map
        finally:
            settings.callback_hmac_secret = original_secret

    def test_get_configuration_non_admin_forbidden(self, client):
        resp = client.get("/admin/configuration")
        assert resp.status_code == 403

    def test_update_configuration_rejects_startup_analysis_batch_size_above_maximum(self, admin_client):
        resp = admin_client.put(
            "/admin/configuration",
            json={"startup_analysis_batch_size": 5001},
        )
        assert resp.status_code == 422, resp.json()

    @patch("app.services.configuration_service.database_service._write_env_settings")
    @patch("app.services.configuration_service.configure_logging")
    def test_update_configuration_restart_required_metadata(
        self,
        mock_configure_logging,
        mock_write_env,
        admin_client,
    ):
        target_level = "DEBUG" if settings.log_level != "DEBUG" else "INFO"
        payload = {
            "log_level": target_level,
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
    def test_update_configuration_persists_startup_analysis_batch_size(
        self,
        mock_write_env,
        admin_client,
    ):
        original_value = settings.startup_analysis_batch_size
        try:
            resp = admin_client.put(
                "/admin/configuration",
                json={"startup_analysis_batch_size": 128},
            )
            assert resp.status_code == 200, resp.json()

            payload = resp.json()
            assert "startup_analysis_batch_size" in payload["changed_settings"]
            assert payload["restart_required"] is False

            written = mock_write_env.call_args.args[0]
            assert written.get("STARTUP_ANALYSIS_BATCH_SIZE") == "128"
        finally:
            settings.startup_analysis_batch_size = original_value

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_persists_callback_default_url(
        self,
        mock_write_env,
        admin_client,
    ):
        original_value = settings.callback_default_url
        try:
            resp = admin_client.put(
                "/admin/configuration",
                json={"callback_default_url": "https://example.com/default-webhook"},
            )
            assert resp.status_code == 200, resp.json()

            payload = resp.json()
            assert "callback_default_url" in payload["changed_settings"]
            assert payload["restart_required"] is False

            written = mock_write_env.call_args.args[0]
            assert written.get("CALLBACK_DEFAULT_URL") == "https://example.com/default-webhook"
        finally:
            settings.callback_default_url = original_value

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_persists_callback_proxy_url(
        self,
        mock_write_env,
        admin_client,
    ):
        original_value = settings.callback_proxy_url
        try:
            resp = admin_client.put(
                "/admin/configuration",
                json={"callback_proxy_url": "http://proxy.example.com:8080"},
            )
            assert resp.status_code == 200, resp.json()

            payload = resp.json()
            assert "callback_proxy_url" in payload["changed_settings"]

            written = mock_write_env.call_args.args[0]
            assert written.get("CALLBACK_PROXY_URL") == "http://proxy.example.com:8080"
        finally:
            settings.callback_proxy_url = original_value

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_persists_callback_payload_contract(
        self,
        mock_write_env,
        admin_client,
    ):
        original_fields = settings.callback_payload_fields
        original_map = settings.callback_payload_field_map
        try:
            resp = admin_client.put(
                "/admin/configuration",
                json={
                    "callback_payload_fields": ["event", "project_id", "completion_result"],
                    "callback_payload_field_map": {
                        "type": "event",
                        "project": "project_id",
                        "summary": "project=${project_id};result=${completion_result}",
                    },
                },
            )
            assert resp.status_code == 200, resp.json()

            payload = resp.json()
            assert "callback_payload_fields" in payload["changed_settings"]
            assert "callback_payload_field_map" in payload["changed_settings"]

            written = mock_write_env.call_args.args[0]
            assert written.get("CALLBACK_PAYLOAD_FIELDS") == '["event","project_id","completion_result"]'
            assert written.get("CALLBACK_PAYLOAD_FIELD_MAP") == (
                '{"type":"event","project":"project_id","summary":"project=${project_id};result=${completion_result}"}'
            )
        finally:
            settings.callback_payload_fields = original_fields
            settings.callback_payload_field_map = original_map

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_persists_callback_hmac_secret_without_leaking_it(
        self,
        mock_write_env,
        admin_client,
        db,
    ):
        original_secret = settings.callback_hmac_secret
        try:
            resp = admin_client.put(
                "/admin/configuration",
                json={"callback_hmac_secret": "super-secret"},
            )
            assert resp.status_code == 200, resp.json()

            payload = resp.json()
            assert "callback_hmac_secret" in payload["changed_settings"]
            changed_values = payload["changed_setting_values"]["callback_hmac_secret"]
            assert changed_values["old_value"] is False
            assert changed_values["new_value"] is True

            written = mock_write_env.call_args.args[0]
            assert written.get("CALLBACK_HMAC_SECRET") == "super-secret"

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
            assert (attempt.details or {}).get("requested_values", {}).get("callback_hmac_secret") == "[redacted]"
            updated_secret = (updated.details or {}).get("changed_setting_values", {}).get("callback_hmac_secret", {})
            assert updated_secret.get("old_value") is False
            assert updated_secret.get("new_value") is True
        finally:
            settings.callback_hmac_secret = original_secret

    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_clears_callback_hmac_secret(
        self,
        mock_write_env,
        admin_client,
    ):
        original_secret = settings.callback_hmac_secret
        settings.callback_hmac_secret = "stored-secret"
        try:
            resp = admin_client.put(
                "/admin/configuration",
                json={"clear_callback_hmac_secret": True},
            )
            assert resp.status_code == 200, resp.json()

            payload = resp.json()
            changed_values = payload["changed_setting_values"]["callback_hmac_secret"]
            assert changed_values["old_value"] is True
            assert changed_values["new_value"] is False

            written = mock_write_env.call_args.args[0]
            assert written.get("CALLBACK_HMAC_SECRET") == ""
        finally:
            settings.callback_hmac_secret = original_secret

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
        resp = admin_client.put("/admin/configuration", json={"log_file": "/var/log/ecube/custom.log"})
        assert resp.status_code == 200, resp.json()
        payload = resp.json()
        assert "log_file" in payload["changed_settings"]

        written = mock_write_env.call_args.args[0]
        assert written.get("LOG_FILE") == "/var/log/ecube/custom.log"
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
            expected_logging_marker = (
                f"Logging configured: level={original_values['log_level']} "
                f"format={original_values['log_format']} file_logging=enabled"
            )
            assert expected_logging_marker in content
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

    @patch("app.services.configuration_service.configure_logging")
    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_env_write_failure_keeps_runtime_settings_unchanged(
        self,
        mock_write_env,
        mock_configure_logging,
        admin_client,
    ):
        original_log_level = settings.log_level
        target_level = "DEBUG" if original_log_level != "DEBUG" else "INFO"
        mock_write_env.side_effect = RuntimeError("disk full")

        resp = admin_client.put("/admin/configuration", json={"log_level": target_level})

        assert resp.status_code == 500
        assert settings.log_level == original_log_level
        mock_configure_logging.assert_not_called()

    @patch("app.services.configuration_service._apply_runtime_changes")
    @patch("app.services.configuration_service.database_service._write_env_settings")
    def test_update_configuration_runtime_apply_failure_rolls_back_env_and_settings(
        self,
        mock_write_env,
        mock_apply_runtime,
        admin_client,
    ):
        original_log_level = settings.log_level
        target_level = "DEBUG" if original_log_level != "DEBUG" else "INFO"

        mock_apply_runtime.side_effect = RuntimeError("runtime apply failed")

        resp = admin_client.put("/admin/configuration", json={"log_level": target_level})

        assert resp.status_code == 500
        assert settings.log_level == original_log_level
        # First call writes new env values; second call writes rollback values.
        assert mock_write_env.call_count == 2

    @patch("app.routers.configuration.configuration_service.update_configuration")
    def test_update_configuration_generic_500_does_not_leak_internal_error(
        self,
        mock_update,
        admin_client,
    ):
        mock_update.side_effect = RuntimeError("internal path /tmp/secret")

        resp = admin_client.put("/admin/configuration", json={"log_level": "DEBUG"})

        assert resp.status_code == 500
        payload = resp.json()
        assert payload["message"] == "Configuration update failed"
        assert payload["code"] == "HTTP_500"

    @patch("app.routers.configuration.configuration_service.request_service_restart")
    def test_restart_generic_500_does_not_leak_internal_error(
        self,
        mock_restart,
        admin_client,
    ):
        mock_restart.side_effect = Exception("service detail /var/run")

        resp = admin_client.post("/admin/configuration/restart", json={"confirm": True})

        assert resp.status_code == 500
        payload = resp.json()
        assert payload["message"] == "Configuration restart request failed"
        assert payload["code"] == "HTTP_500"
