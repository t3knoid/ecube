"""Tests for the structured logging facility.

Covers:
* ``JsonFormatter`` produces valid JSON with required fields
* ``TextFormatter`` produces human-readable output
* ``configure_logging`` sets up handlers correctly
* Log level filtering
* ``log_and_audit`` service helper
* ``/admin/logs`` and ``/admin/logs/{filename}`` endpoints
  – authentication enforcement (401 for unauthenticated)
    – admin-only listing/download; 403 for non-admin users
  – path traversal rejection
  – audit trail recording
  – 404 when file-logging not configured
* ``/admin/logs/view`` endpoint
    – admin-only access and denied-attempt auditing
    – allowlisted source enforcement
    – tail pagination and text filtering
    – sensitive value redaction
"""

import json
import logging
import os
import tempfile
from unittest.mock import patch

import pytest

from app.logging_config import JsonFormatter, TextFormatter, configure_logging


# ---------------------------------------------------------------------------
# JsonFormatter tests
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def test_produces_valid_json(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["module"] == "test.module"
        assert data["message"] == "hello world"
        assert "timestamp" in data

    def test_includes_trace_id_when_present(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="warn", args=(), exc_info=None,
        )
        record.trace_id = "abc-123"  # type: ignore[attr-defined]
        data = json.loads(formatter.format(record))
        assert data["trace_id"] == "abc-123"

    def test_includes_user_id_when_present(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="info", args=(), exc_info=None,
        )
        record.user_id = "user-42"  # type: ignore[attr-defined]
        data = json.loads(formatter.format(record))
        assert data["user_id"] == "user-42"

    def test_includes_extra_fields(self):
        formatter = JsonFormatter()
        logger = logging.getLogger("test.json.extra")
        logger.handlers.clear()
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        record = logger.makeRecord(
            name="test.json.extra",
            level=logging.INFO,
            fn="",
            lno=0,
            msg="state change",
            args=(),
            exc_info=None,
            extra={"drive_id": 7, "old_state": "AVAILABLE"},
        )
        data = json.loads(formatter.format(record))
        assert data["extra"]["drive_id"] == 7
        assert data["extra"]["old_state"] == "AVAILABLE"

    def test_no_extra_when_empty(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.DEBUG, pathname="", lineno=0,
            msg="minimal", args=(), exc_info=None,
        )
        data = json.loads(formatter.format(record))
        assert "extra" not in data

    def test_timestamp_is_iso_8601(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="ts test", args=(), exc_info=None,
        )
        data = json.loads(formatter.format(record))
        # ISO 8601 with timezone indicator
        assert "T" in data["timestamp"]
        assert "+" in data["timestamp"] or "Z" in data["timestamp"]


# ---------------------------------------------------------------------------
# TextFormatter tests
# ---------------------------------------------------------------------------

class TestTextFormatter:
    def test_produces_readable_output(self):
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="app.services.drive_service",
            level=logging.WARNING,
            pathname="drive_service.py",
            lineno=42,
            msg="drive not found",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        assert "WARNING" in output
        assert "app.services.drive_service" in output
        assert "drive not found" in output


# ---------------------------------------------------------------------------
# configure_logging tests
# ---------------------------------------------------------------------------

class TestConfigureLogging:
    def test_sets_root_level(self):
        configure_logging(level="DEBUG", log_format="text")
        assert logging.getLogger().level == logging.DEBUG
        # Restore to avoid side-effects on other tests.
        configure_logging(level="INFO", log_format="text")

    def test_json_format_installs_json_formatter(self):
        configure_logging(level="INFO", log_format="json")
        root = logging.getLogger()
        assert any(isinstance(h.formatter, JsonFormatter) for h in root.handlers)
        # Restore
        configure_logging(level="INFO", log_format="text")

    def test_text_format_installs_text_formatter(self):
        configure_logging(level="INFO", log_format="text")
        root = logging.getLogger()
        assert any(isinstance(h.formatter, TextFormatter) for h in root.handlers)

    def test_file_handler_created_when_log_file_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "test.log")
            configure_logging(level="INFO", log_format="text", log_file=log_path)
            root = logging.getLogger()
            file_handlers = [
                h for h in root.handlers
                if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            assert len(file_handlers) == 1
            assert file_handlers[0].baseFilename == log_path
            # Close and remove file handlers before temp dir cleanup so that
            # Windows does not raise PermissionError on the open file.
            for h in list(file_handlers):
                h.close()
                root.removeHandler(h)
            # Restore
            configure_logging(level="INFO", log_format="text")

    def test_no_file_handler_when_log_file_not_set(self):
        configure_logging(level="INFO", log_format="text", log_file=None)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 0

    def test_log_level_filtering(self):
        """Verify that records below the configured level are filtered out."""
        configure_logging(level="WARNING", log_format="text")
        test_logger = logging.getLogger("test.level_filter")
        # WARNING and above should be effective
        assert test_logger.isEnabledFor(logging.WARNING)
        assert test_logger.isEnabledFor(logging.ERROR)
        assert not test_logger.isEnabledFor(logging.DEBUG)
        assert not test_logger.isEnabledFor(logging.INFO)
        # Restore
        configure_logging(level="INFO", log_format="text")


# ---------------------------------------------------------------------------
# log_and_audit integration tests
# ---------------------------------------------------------------------------

class TestLogAndAudit:
    def test_log_and_audit_writes_audit_and_log(self, db):
        from app.repositories.audit_repository import AuditRepository
        from app.services.audit_service import log_and_audit

        entry = log_and_audit(
            db,
            action="TEST_ACTION",
            actor_id="test-user",
            drive_id=1,
            project_id="PRJ-001",
            metadata={"key": "value"},
        )
        assert entry.action == "TEST_ACTION"
        assert entry.user == "test-user"
        assert entry.details["drive_id"] == 1
        assert entry.details["project_id"] == "PRJ-001"
        assert entry.details["key"] == "value"

        # Verify it was persisted
        logs = AuditRepository(db).query(action="TEST_ACTION")
        assert len(logs) == 1
        assert logs[0].user == "test-user"

    def test_log_and_audit_works_without_optional_fields(self, db):
        from app.services.audit_service import log_and_audit

        entry = log_and_audit(db, action="SIMPLE_ACTION")
        assert entry.action == "SIMPLE_ACTION"
        assert entry.user is None


# ---------------------------------------------------------------------------
# /admin/logs endpoint tests
# ---------------------------------------------------------------------------

class TestAdminLogsEndpoints:
    def test_list_logs_unauthenticated_returns_401(self, unauthenticated_client):
        resp = unauthenticated_client.get("/admin/logs")
        assert resp.status_code == 401

    def test_download_log_unauthenticated_returns_401(self, unauthenticated_client):
        resp = unauthenticated_client.get("/admin/logs/app.log")
        assert resp.status_code == 401

    def test_list_logs_returns_404_when_file_logging_not_configured(self, admin_client):
        """When LOG_FILE is not set, /admin/logs returns 404."""
        with patch("app.routers.admin.settings") as mock_settings:
            mock_settings.log_file = None
            resp = admin_client.get("/admin/logs")
            assert resp.status_code == 404

    def test_download_log_returns_404_when_file_logging_not_configured(self, admin_client):
        with patch("app.routers.admin.settings") as mock_settings:
            mock_settings.log_file = None
            resp = admin_client.get("/admin/logs/app.log")
            assert resp.status_code == 404

    def test_list_logs_returns_files(self, admin_client, db):
        """When file logging is configured, listing returns file metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("line one\nline two\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs")
                assert resp.status_code == 200
                data = resp.json()
                assert "log_files" in data
                assert len(data["log_files"]) == 1
                assert data["log_files"][0]["name"] == "app.log"
                assert data["log_files"][0]["size"] > 0
                assert data["total_size"] > 0
                assert data["log_directory"] == tmpdir

    def test_download_log_file_success(self, admin_client, db):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            content = b"test log content\n"
            with open(log_path, "wb") as f:
                f.write(content)

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs/app.log")
                assert resp.status_code == 200
                assert resp.content == content

    def test_download_rejects_path_traversal(self, admin_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("safe")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                # Patterns with slashes are rejected by _safe_filename (400)
                # or handled by FastAPI routing (404).  Either way, the
                # attacker cannot access files outside the log directory.
                traversal_patterns = [
                    ("../../../etc/passwd", {400, 404, 422}),
                    ("..%2f..%2fetc%2fpasswd", {400, 404}),
                ]
                for bad_name, expected_codes in traversal_patterns:
                    resp = admin_client.get(f"/admin/logs/{bad_name}")
                    assert resp.status_code in expected_codes, (
                        f"Expected one of {expected_codes} for {bad_name!r}, got {resp.status_code}"
                    )
                    # Crucially, the response body should NOT contain "safe"
                    # (the contents of our actual log file).
                    if hasattr(resp, "text"):
                        assert resp.text != "safe"

    def test_download_nonexistent_file_returns_404(self, admin_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs/nonexistent.log")
                assert resp.status_code == 404

    def test_download_rejects_non_allowlisted_file_in_log_directory(self, admin_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            other_path = os.path.join(tmpdir, "notes.txt")
            with open(log_path, "w") as f:
                f.write("log")
            with open(other_path, "w") as f:
                f.write("not a log")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs/notes.txt")
                assert resp.status_code == 404

    def test_list_logs_records_audit_trail(self, admin_client, db):
        """Accessing /admin/logs should record an audit entry."""
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                admin_client.get("/admin/logs")
                entries = AuditRepository(db).query(action="LOG_FILES_LISTED")
                assert len(entries) >= 1

    def test_download_log_records_audit_trail(self, admin_client, db):
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("data")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                admin_client.get("/admin/logs/app.log")
                entries = AuditRepository(db).query(action="LOG_FILE_DOWNLOADED")
                assert len(entries) >= 1
                assert entries[0].details["filename"] == "app.log"
                assert "action" not in entries[0].details

    def test_list_logs_non_admin_returns_403(self, manager_client, auditor_client, client):
        """Non-admin users should be denied access to /admin/logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                for c in [manager_client, auditor_client, client]:
                    resp = c.get("/admin/logs")
                    assert resp.status_code == 403, "Expected 403 for non-admin user"

    def test_list_logs_non_admin_records_denied_audit(self, manager_client, db):
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = manager_client.get("/admin/logs")
                assert resp.status_code == 403

                entries = AuditRepository(db).query(action="LOG_FILES_LIST_DENIED")
                assert len(entries) >= 1
                assert entries[0].details.get("reason") == "admin_role_required"

    def test_download_log_non_admin_returns_403(self, manager_client, auditor_client, client):
        """Non-admin users should be denied access to /admin/logs/{filename}."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                for c in [manager_client, auditor_client, client]:
                    resp = c.get("/admin/logs/app.log")
                    assert resp.status_code == 403, "Expected 403 for non-admin user"

    def test_download_log_non_admin_records_denied_audit(self, manager_client, db):
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = manager_client.get("/admin/logs/app.log")
                assert resp.status_code == 403

                entries = AuditRepository(db).query(action="LOG_FILE_DOWNLOAD_DENIED")
                assert len(entries) >= 1
                assert entries[0].details.get("reason") == "admin_role_required"
                assert entries[0].details.get("filename") == "app.log"

    def test_admin_can_list_logs(self, admin_client):
        """Admin users should be allowed to list logs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("x")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs")
                assert resp.status_code == 200

    def test_file_metadata_accuracy(self, admin_client, db):
        """Verify size and date fields are accurate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            content = "a" * 256
            with open(log_path, "w") as f:
                f.write(content)

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs")
                data = resp.json()
                file_info = data["log_files"][0]
                assert file_info["size"] == 256
                assert "created" in file_info
                assert "modified" in file_info

    def test_view_logs_unauthenticated_returns_401(self, unauthenticated_client):
        resp = unauthenticated_client.get("/admin/logs/view")
        assert resp.status_code == 401

    def test_view_logs_non_admin_returns_403_and_audits_denial(self, manager_client, db):
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("line\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = manager_client.get("/admin/logs/view")
                assert resp.status_code == 403

                entries = AuditRepository(db).query(action="LOG_LINES_VIEW_DENIED")
                assert len(entries) >= 1
                assert entries[0].details.get("reason") == "admin_role_required"

    def test_view_logs_unknown_source_returns_404_and_audits_denial(self, admin_client, db):
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("line\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get("/admin/logs/view", params={"source": "unknown"})
                assert resp.status_code == 404

                entries = AuditRepository(db).query(action="LOG_LINES_VIEW_DENIED")
                assert len(entries) >= 1
                assert entries[0].details.get("source") == "unknown"
                assert entries[0].details.get("reason") == "unknown_log_source"

    def test_view_logs_returns_404_when_logging_not_configured_and_audits_denial(self, admin_client, db):
        from app.repositories.audit_repository import AuditRepository

        with patch("app.routers.admin.settings") as mock_settings:
            mock_settings.log_file = None
            resp = admin_client.get("/admin/logs/view", params={"source": "app"})
            assert resp.status_code == 404

            entries = AuditRepository(db).query(action="LOG_LINES_VIEW_DENIED")
            assert len(entries) >= 1
            assert entries[0].details.get("source") == "app"
            assert entries[0].details.get("reason") == "log_source_unavailable"

    def test_view_logs_returns_tail_with_offset_and_has_more(self, admin_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                for i in range(1, 31):
                    f.write(f"line {i}\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get(
                    "/admin/logs/view",
                    params={"source": "app", "limit": 5, "offset": 2},
                )
                assert resp.status_code == 200
                data = resp.json()
                contents = [row["content"] for row in data["lines"]]
                assert contents == ["line 24", "line 25", "line 26", "line 27", "line 28"]
                assert data["returned"] == 5
                assert data["has_more"] is True

    def test_view_logs_search_filters_and_redacts_sensitive_values(self, admin_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("INFO healthy\n")
                f.write("ERROR password=hunter2 Authorization=Bearer abc.def.ghi\n")
                f.write('ERROR {"token":"secret-token"}\n')
                f.write("WARN done\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get(
                    "/admin/logs/view",
                    params={"source": "app", "search": "error", "limit": 10},
                )
                assert resp.status_code == 200
                data = resp.json()
                contents = [row["content"] for row in data["lines"]]
                assert len(contents) == 2
                joined = "\n".join(contents)
                assert "hunter2" not in joined
                assert "secret-token" not in joined
                assert "abc.def.ghi" not in joined
                assert "[REDACTED]" in joined

    def test_view_logs_records_audit_trail(self, admin_client, db):
        from app.repositories.audit_repository import AuditRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("line\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                resp = admin_client.get(
                    "/admin/logs/view",
                    params={"source": "app", "limit": 1},
                )
                assert resp.status_code == 200
                assert resp.json()["source"]["path"] == "app.log"

                entries = AuditRepository(db).query(action="LOG_LINES_VIEWED")
                assert len(entries) >= 1
                assert entries[0].details.get("source") == "app"
                assert entries[0].details.get("limit") == 1
                assert entries[0].details.get("log_file") == "app.log"
                assert "path" not in entries[0].details

    def test_view_logs_returns_lines_when_stat_fails(self, admin_client):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "app.log")
            with open(log_path, "w") as f:
                f.write("line\n")

            with patch("app.routers.admin.settings") as mock_settings:
                mock_settings.log_file = log_path
                with patch("app.routers.admin.os.stat", side_effect=FileNotFoundError):
                    resp = admin_client.get(
                        "/admin/logs/view",
                        params={"source": "app", "limit": 1},
                    )

                assert resp.status_code == 200
                data = resp.json()
                assert data["returned"] == 1
                assert data["lines"][0]["content"] == "line"
                assert data["source"]["path"] == "app.log"
                assert data["file_modified_at"] is None
