"""Tests for webhook callback feature (Issue #104).

Covers:
- Schema validation: HTTPS-only enforcement, optional field
- Callback delivery: success, retry on 5xx, all retries exhausted
- SSRF protection: private IP rejection, DNS-pinned connections
- No-op when callback_url is None
- Audit logging for CALLBACK_SENT and CALLBACK_DELIVERY_FAILED
- ExportJobSchema includes callback_url
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from pydantic import ValidationError

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import ExportJob, JobStatus
from app.schemas.jobs import ExportJobSchema, JobCreate
from app.services.callback_service import (
    _do_deliver,
    _resolve_safe,
    _sanitize_url_for_log,
    build_payload,
    deliver_callback,
)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestCallbackUrlSchemaValidation:
    """JobCreate.callback_url must be HTTPS or absent."""

    def test_https_url_accepted(self):
        body = JobCreate(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/source",
            callback_url="https://example.com/webhook",
        )
        assert body.callback_url == "https://example.com/webhook"

    def test_http_url_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            JobCreate(
                project_id="P1",
                evidence_number="EV1",
                source_path="/data/source",
                callback_url="http://example.com/webhook",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("callback_url",) for e in errors)
        assert "HTTPS" in str(exc_info.value)

    def test_none_accepted(self):
        body = JobCreate(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/source",
        )
        assert body.callback_url is None

    def test_scheme_only_rejected(self):
        """'https://' with no hostname is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            JobCreate(
                project_id="P1",
                evidence_number="EV1",
                source_path="/data/source",
                callback_url="https://",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("callback_url",) for e in errors)

    def test_no_hostname_rejected(self):
        """A URL with a path but no hostname is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            JobCreate(
                project_id="P1",
                evidence_number="EV1",
                source_path="/data/source",
                callback_url="https:///path/only",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("callback_url",) for e in errors)

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped before validation."""
        body = JobCreate(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/source",
            callback_url="  https://example.com/hook  ",
        )
        assert body.callback_url == "https://example.com/hook"

    def test_userinfo_rejected(self):
        """callback_url with embedded credentials is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            JobCreate(
                project_id="P1",
                evidence_number="EV1",
                source_path="/data/source",
                callback_url="https://user:pass@example.com/hook",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("callback_url",) for e in errors)
        assert "credentials" in str(exc_info.value).lower()

    def test_userinfo_username_only_rejected(self):
        """callback_url with only a username (no password) is rejected."""
        with pytest.raises(ValidationError) as exc_info:
            JobCreate(
                project_id="P1",
                evidence_number="EV1",
                source_path="/data/source",
                callback_url="https://user@example.com/hook",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("callback_url",) for e in errors)

    def test_http_422_via_api(self, client, db):
        db.add(UsbDrive(
            device_identifier="USB-CB-001",
            current_state=DriveState.AVAILABLE,
            current_project_id="PROJ-CB",
        ))
        db.commit()
        resp = client.post("/jobs", json={
            "project_id": "PROJ-CB",
            "evidence_number": "EV-CB",
            "source_path": "/data/source",
            "callback_url": "http://insecure.example.com/hook",
        })
        assert resp.status_code == 422

    def test_https_accepted_via_api(self, client, db):
        db.add(UsbDrive(
            device_identifier="USB-CB-002",
            current_state=DriveState.AVAILABLE,
            current_project_id="PROJ-CB2",
        ))
        db.commit()
        resp = client.post("/jobs", json={
            "project_id": "PROJ-CB2",
            "evidence_number": "EV-CB2",
            "source_path": "/data/source",
            "callback_url": "https://example.com/webhook",
        })
        assert resp.status_code == 200
        assert resp.json()["callback_url"] == "https://example.com/webhook"


# ---------------------------------------------------------------------------
# ExportJobSchema includes callback_url
# ---------------------------------------------------------------------------


class TestExportJobSchemaCallbackUrl:

    def test_callback_url_in_response(self, db):
        job = ExportJob(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/source",
            status=JobStatus.PENDING,
            total_bytes=0,
            copied_bytes=0,
            file_count=0,
            thread_count=4,
            callback_url="https://example.com/hook",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        schema = ExportJobSchema.model_validate(job)
        assert schema.callback_url == "https://example.com/hook"

    def test_callback_url_null_when_absent(self, db):
        job = ExportJob(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/source",
            status=JobStatus.PENDING,
            total_bytes=0,
            copied_bytes=0,
            file_count=0,
            thread_count=4,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        schema = ExportJobSchema.model_validate(job)
        assert schema.callback_url is None


# ---------------------------------------------------------------------------
# _sanitize_url_for_log
# ---------------------------------------------------------------------------


class TestSanitizeUrlForLog:

    def test_strips_userinfo(self):
        result = _sanitize_url_for_log("https://user:pass@example.com/hook")
        assert result == "https://example.com/hook"
        assert "user" not in result
        assert "pass" not in result

    def test_strips_query_string(self):
        result = _sanitize_url_for_log("https://example.com/hook?token=secret123")
        assert result == "https://example.com/hook"
        assert "token" not in result

    def test_strips_fragment(self):
        result = _sanitize_url_for_log("https://example.com/hook#section")
        assert result == "https://example.com/hook"

    def test_preserves_port(self):
        result = _sanitize_url_for_log("https://example.com:8443/hook")
        assert result == "https://example.com:8443/hook"

    def test_preserves_plain_url(self):
        result = _sanitize_url_for_log("https://example.com/webhook")
        assert result == "https://example.com/webhook"

    def test_unparseable_returns_placeholder(self):
        with patch("app.services.callback_service.urlparse", side_effect=ValueError("bad")):
            result = _sanitize_url_for_log(":::bad")
        assert result == "<unparseable>"


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


class TestBuildPayload:

    def test_completed_payload(self):
        job = MagicMock(spec=ExportJob)
        job.id = 42
        job.project_id = "PROJ-001"
        job.evidence_number = "EV-001"
        job.status = JobStatus.COMPLETED
        job.source_path = "/data/evidence"
        job.total_bytes = 1024
        job.copied_bytes = 1024
        job.file_count = 10
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        payload = build_payload(job)
        assert payload["event"] == "JOB_COMPLETED"
        assert payload["job_id"] == 42
        assert payload["status"] == "COMPLETED"
        assert payload["completed_at"] == "2026-01-01T00:00:00+00:00"

    def test_failed_payload(self):
        job = MagicMock(spec=ExportJob)
        job.id = 7
        job.project_id = "PROJ-002"
        job.evidence_number = "EV-002"
        job.status = JobStatus.FAILED
        job.source_path = "/data/src"
        job.total_bytes = 500
        job.copied_bytes = 200
        job.file_count = 5
        job.completed_at = None

        payload = build_payload(job)
        assert payload["event"] == "JOB_FAILED"
        assert "completed_at" not in payload

    @pytest.mark.parametrize("status", [
        JobStatus.PENDING,
        JobStatus.RUNNING,
        JobStatus.VERIFYING,
    ])
    def test_rejects_non_terminal_status(self, status):
        job = MagicMock(spec=ExportJob)
        job.status = status
        with pytest.raises(ValueError, match="terminal status"):
            build_payload(job)


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


class TestSSRFProtection:

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_loopback_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]
        with pytest.raises(ValueError, match="non-globally-routable"):
            _resolve_safe("localhost")

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_private_ip_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("10.0.0.5", 0)),
        ]
        with pytest.raises(ValueError, match="non-globally-routable"):
            _resolve_safe("internal.corp")

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_public_ip_allowed(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        assert _resolve_safe("example.com") == "93.184.216.34"

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_unresolvable_host_blocked(self, mock_getaddrinfo):
        import socket as _socket
        mock_getaddrinfo.side_effect = _socket.gaierror("Name resolution failed")
        with pytest.raises(ValueError, match="DNS resolution failed"):
            _resolve_safe("nonexistent.invalid")

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_unspecified_address_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("0.0.0.0", 0)),
        ]
        with pytest.raises(ValueError, match="non-globally-routable"):
            _resolve_safe("zero.example")

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_multicast_address_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("224.0.0.1", 0)),
        ]
        with pytest.raises(ValueError, match="non-globally-routable"):
            _resolve_safe("multicast.example")

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_ipv6_loopback_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (10, 1, 6, "", ("::1", 0, 0, 0)),
        ]
        with pytest.raises(ValueError, match="non-globally-routable"):
            _resolve_safe("ip6-localhost")

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_mixed_public_private_blocked(self, mock_getaddrinfo):
        """If any resolved address is private, the entire set is rejected
        (prevents DNS rebinding with mixed records)."""
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]
        with pytest.raises(ValueError, match="non-globally-routable"):
            _resolve_safe("rebind.example")


# ---------------------------------------------------------------------------
# deliver_callback
# ---------------------------------------------------------------------------


class TestDeliverCallback:

    @staticmethod
    def _make_db_job(db, *, callback_url="https://example.com/hook",
                     status=JobStatus.COMPLETED):
        """Create a *persisted* ExportJob so FK-dependent AuditLog rows
        survive even when foreign-key enforcement is enabled."""
        job = ExportJob(
            project_id="PROJ-001",
            evidence_number="EV-001",
            source_path="/data/evidence",
            callback_url=callback_url,
            status=status,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        # Populate optional attributes expected by build_payload / tests.
        job.total_bytes = 1024
        job.copied_bytes = 1024
        job.file_count = 10
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return job

    @staticmethod
    def _make_mock_job(*, callback_url="https://example.com/hook",
                       status=JobStatus.COMPLETED):
        """Return a lightweight mock job for tests that never touch the DB
        (no-op paths, production executor path)."""
        job = MagicMock(spec=ExportJob)
        job.id = 1
        job.project_id = "PROJ-001"
        job.evidence_number = "EV-001"
        job.status = status
        job.source_path = "/data/evidence"
        job.total_bytes = 1024
        job.copied_bytes = 1024
        job.file_count = 10
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job.callback_url = callback_url
        return job

    def test_noop_when_no_callback_url(self, db):
        """deliver_callback is a no-op when callback_url is None."""
        job = self._make_mock_job(callback_url=None)
        deliver_callback(job, db)
        logs = db.query(AuditLog).all()
        assert len(logs) == 0

    @pytest.mark.parametrize("status", [
        JobStatus.PENDING,
        JobStatus.RUNNING,
        JobStatus.VERIFYING,
    ])
    def test_noop_for_non_terminal_status(self, db, status):
        """deliver_callback is a no-op when the job is not COMPLETED/FAILED."""
        job = self._make_mock_job(status=status)
        deliver_callback(job, db)
        logs = db.query(AuditLog).all()
        assert len(logs) == 0

    def test_malformed_url_audit_record(self, db):
        """A malformed callback_url that cannot be parsed must produce a
        CALLBACK_DELIVERY_FAILED audit record."""
        job = self._make_db_job(db, callback_url="not-a-url-at-all")

        with patch("app.services.callback_service.urlparse", side_effect=ValueError("bad url")):
            deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "Malformed" in logs[0].details["reason"]
        assert logs[0].details["callback_url"] == "<unparseable>"

    @patch("app.services.callback_service._resolve_safe",
           side_effect=ValueError("non-globally-routable address: 10.0.0.5"))
    @patch("app.services.callback_service.settings")
    def test_ssrf_blocks_delivery(self, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        job = self._make_db_job(db)

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "SSRF" in logs[0].details["reason"]

    @patch("app.services.callback_service.settings")
    def test_empty_hostname_blocked(self, mock_settings, db):
        """A callback URL with an empty hostname is rejected with an audit record."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        job = self._make_db_job(db, callback_url="https:///no-host")

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "empty hostname" in logs[0].details["reason"]

    def test_non_https_blocked_at_runtime(self, db):
        """A plain-HTTP callback URL stored in the DB is rejected at delivery
        time (defense-in-depth behind the schema validator)."""
        job = self._make_db_job(db, callback_url="http://example.com/hook")

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "scheme" in logs[0].details["reason"].lower()

    def test_userinfo_blocked_at_runtime(self, db):
        """A callback URL with embedded credentials is rejected at delivery time
        (defense-in-depth behind the schema validator)."""
        job = self._make_db_job(db, callback_url="https://user:pass@example.com/hook")

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "credentials" in logs[0].details["reason"].lower()
        assert "user" not in logs[0].details["callback_url"]
        assert "pass" not in logs[0].details["callback_url"]

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_audit_url_redacted(self, mock_client_cls, mock_settings, mock_resolve, db):
        """Audit logs must never contain query tokens or userinfo."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        url = "https://example.com/hook?token=secret123&sig=abc"
        _do_deliver(job.id, url, {"event": "JOB_COMPLETED"}, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_SENT",
        ).all()
        assert len(logs) == 1
        logged_url = logs[0].details["callback_url"]
        assert logged_url == "https://example.com/hook"
        assert "token" not in logged_url
        assert "secret" not in logged_url

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_successful_delivery(self, mock_client_cls, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        call_args = mock_client_instance.post.call_args
        posted_url = call_args[0][0]
        assert "93.184.216.34" in posted_url
        assert call_args[1]["headers"] == {"Host": "example.com"}
        assert call_args[1]["extensions"] == {
            "sni_hostname": b"example.com",
        }

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_SENT",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["status_code"] == 200
        assert logs[0].details["attempt"] == 1

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    @patch("app.services.callback_service.time.sleep")
    def test_retry_on_5xx_then_success(self, mock_sleep, mock_client_cls, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_200 = MagicMock()
        resp_200.status_code = 200

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.side_effect = [resp_500, resp_200]
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        assert mock_client_instance.post.call_count == 2
        mock_sleep.assert_called_once()

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_SENT",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["attempt"] == 2

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    @patch("app.services.callback_service.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep, mock_client_cls, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        resp_503 = MagicMock()
        resp_503.status_code = 503

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = resp_503
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        assert mock_client_instance.post.call_count == 4
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["attempts"] == 4
        assert "503" in logs[0].details["reason"]

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    @patch("app.services.callback_service.time.sleep")
    def test_network_error_retries(self, mock_sleep, mock_client_cls, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        assert mock_client_instance.post.call_count == 4
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_4xx_no_retry(self, mock_client_cls, mock_settings, mock_resolve, db):
        """4xx responses are not retried — they are treated as non-transient."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        resp_404 = MagicMock()
        resp_404.status_code = 404

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = resp_404
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        mock_client_instance.post.assert_called_once()
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["status_code"] == 404
        assert "rejected" in logs[0].details["reason"]

    @patch("app.services.callback_service.settings")
    def test_ssrf_allowed_when_configured(self, mock_settings, db):
        """When callback_allow_private_ips is True, _resolve_safe is skipped
        and httpx connects to the original URL (no DNS pinning)."""
        mock_settings.callback_allow_private_ips = True
        mock_settings.callback_timeout_seconds = 5

        with patch("app.services.callback_service.httpx.Client") as mock_client_cls, \
             patch("app.services.callback_service._resolve_safe") as mock_resolve:
            resp_200 = MagicMock()
            resp_200.status_code = 200
            mock_client_instance = MagicMock()
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client_instance.post.return_value = resp_200
            mock_client_cls.return_value = mock_client_instance

            job = self._make_db_job(db)
            deliver_callback(job, db)

            mock_resolve.assert_not_called()
            call_args = mock_client_instance.post.call_args
            posted_url = call_args[0][0]
            assert "example.com" in posted_url
            logs = db.query(AuditLog).filter(
                AuditLog.job_id == job.id,
                AuditLog.action == "CALLBACK_SENT",
            ).all()
            assert len(logs) == 1

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_dns_pinning_prevents_rebinding(self, mock_client_cls, mock_settings, mock_resolve, db):
        """The resolved IP from _resolve_safe must be used for the actual
        connection, preventing DNS rebinding (TOCTOU) attacks."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        # The outbound HTTP POST must target the pinned IP, not the hostname.
        call_args = mock_client_instance.post.call_args
        posted_url = call_args[0][0]
        assert "93.184.216.34" in posted_url
        assert "example.com" not in posted_url

        # Host header and SNI must carry the original hostname for
        # virtual-hosting and proper TLS certificate verification.
        assert call_args[1]["headers"] == {"Host": "example.com"}
        assert call_args[1]["extensions"] == {
            "sni_hostname": b"example.com",
        }

    @patch("app.services.callback_service._resolve_safe", return_value="2001:db8::1")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_ipv6_pinning(self, mock_client_cls, mock_settings, mock_resolve, db):
        """IPv6 addresses must be bracket-wrapped in the pinned URL."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        call_args = mock_client_instance.post.call_args
        posted_url = call_args[0][0]
        assert "[2001:db8::1]" in posted_url

    def test_production_path_uses_bounded_executor(self):
        """When db is None (production), deliver_callback submits to a
        bounded ThreadPoolExecutor rather than spawning an unbounded thread."""
        job = self._make_mock_job()
        with patch("app.services.callback_service._get_executor") as mock_get_exec, \
             patch("app.services.callback_service._deliver_callback_sync"):
            mock_executor = MagicMock()
            mock_get_exec.return_value = mock_executor

            deliver_callback(job)  # db=None → production path

            mock_executor.submit.assert_called_once()


# ---------------------------------------------------------------------------
# Executor lifecycle
# ---------------------------------------------------------------------------


class TestExecutorLifecycle:

    def test_get_executor_returns_thread_pool(self):
        """_get_executor returns a ThreadPoolExecutor."""
        from concurrent.futures import ThreadPoolExecutor as _TPE
        from app.services.callback_service import _get_executor, _shutdown_executor
        import app.services.callback_service as _mod

        # Reset module state for a clean test.
        old = _mod._executor
        _mod._executor = None
        try:
            with patch.object(_mod, "settings") as mock_settings:
                mock_settings.callback_max_workers = 2
                pool = _get_executor()
                assert isinstance(pool, _TPE)
                assert pool._max_workers == 2
        finally:
            # Restore previous state; shut down the pool we created.
            if _mod._executor is not None:
                _mod._executor.shutdown(wait=False)
            _mod._executor = old


# ---------------------------------------------------------------------------
# Backpressure (semaphore-gated pending queue)
# ---------------------------------------------------------------------------


class TestBackpressure:
    """Tests for the BoundedSemaphore-based backpressure mechanism."""

    def test_delivery_dropped_when_queue_full(self):
        """When the semaphore is exhausted, deliver_callback drops and audits."""
        import app.services.callback_service as _mod
        from app.services.callback_service import _get_pending_semaphore

        job = MagicMock(spec=ExportJob)
        job.id = 42
        job.callback_url = "https://example.com/hook"
        job.status = JobStatus.COMPLETED

        # Force semaphore to have 0 permits so the next acquire fails.
        old_sem = _mod._pending_semaphore
        _mod._pending_semaphore = __import__("threading").BoundedSemaphore(1)
        _mod._pending_semaphore.acquire()  # consume the single permit
        try:
            with patch.object(_mod, "_audit_dropped_delivery") as mock_audit, \
                 patch.object(_mod, "_get_executor") as mock_exec, \
                 patch.object(_mod, "build_payload", return_value={"event": "JOB_COMPLETED"}):
                deliver_callback(job)  # db=None → production path

                # Should NOT have submitted to the executor.
                mock_exec.return_value.submit.assert_not_called()

                # Should have written a drop audit record.
                mock_audit.assert_called_once()
                args = mock_audit.call_args
                assert args[0][0] == 42  # job_id
                assert "example.com" in args[0][1]  # safe_url
        finally:
            _mod._pending_semaphore = old_sem

    def test_delivery_proceeds_when_permits_available(self):
        """When permits are available, deliver_callback submits normally."""
        import app.services.callback_service as _mod

        job = MagicMock(spec=ExportJob)
        job.id = 7
        job.callback_url = "https://example.com/hook"
        job.status = JobStatus.COMPLETED

        old_sem = _mod._pending_semaphore
        _mod._pending_semaphore = __import__("threading").BoundedSemaphore(5)
        try:
            with patch.object(_mod, "_get_executor") as mock_exec, \
                 patch.object(_mod, "_audit_dropped_delivery") as mock_audit, \
                 patch.object(_mod, "build_payload", return_value={"event": "JOB_COMPLETED"}):
                mock_executor = MagicMock()
                mock_exec.return_value = mock_executor

                deliver_callback(job)  # db=None

                mock_executor.submit.assert_called_once()
                mock_audit.assert_not_called()
        finally:
            _mod._pending_semaphore = old_sem

    def test_semaphore_released_after_delivery(self):
        """_deliver_callback_sync releases the semaphore even on failure."""
        import app.services.callback_service as _mod
        from app.services.callback_service import _deliver_callback_sync

        old_sem = _mod._pending_semaphore
        sem = __import__("threading").BoundedSemaphore(2)
        sem.acquire()  # 1 permit left
        _mod._pending_semaphore = sem
        try:
            with patch("app.database.SessionLocal") as mock_sl, \
                 patch.object(_mod, "_do_deliver", side_effect=RuntimeError("boom")):
                mock_db = MagicMock()
                mock_sl.return_value = mock_db

                # Should raise but still release the semaphore.
                with pytest.raises(RuntimeError):
                    _deliver_callback_sync(1, "https://example.com/hook", {})

                mock_db.close.assert_called_once()

                # Semaphore should be back to 2 permits (both should acquire).
                assert sem.acquire(blocking=False)
                assert sem.acquire(blocking=False)
        finally:
            _mod._pending_semaphore = old_sem

    def test_get_pending_semaphore_creates_bounded_semaphore(self):
        """_get_pending_semaphore returns a BoundedSemaphore sized by config."""
        import app.services.callback_service as _mod
        from app.services.callback_service import _get_pending_semaphore

        old_sem = _mod._pending_semaphore
        _mod._pending_semaphore = None
        try:
            with patch.object(_mod, "settings") as mock_settings:
                mock_settings.callback_max_pending = 3
                sem = _get_pending_semaphore()
                # Verify we can acquire exactly 3 times.
                assert sem.acquire(blocking=False)
                assert sem.acquire(blocking=False)
                assert sem.acquire(blocking=False)
                assert not sem.acquire(blocking=False)  # 4th should fail
        finally:
            _mod._pending_semaphore = old_sem


# ---------------------------------------------------------------------------
# Migration test
# ---------------------------------------------------------------------------


class TestCallbackUrlMigration:

    def test_callback_url_column_exists(self, db):
        """The callback_url column should exist on export_jobs."""
        job = ExportJob(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/src",
            callback_url="https://example.com/hook",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.callback_url == "https://example.com/hook"

    def test_callback_url_nullable(self, db):
        """callback_url should default to None."""
        job = ExportJob(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/src",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.callback_url is None
