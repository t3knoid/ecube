"""Tests for webhook callback feature (Issue #104).

Covers:
- Schema validation: HTTPS-only enforcement, optional field
- Callback delivery: success, retry on 5xx, all retries exhausted
- SSRF protection: private IP rejection
- No-op when callback_url is None
- Audit logging for CALLBACK_SENT and CALLBACK_DELIVERY_FAILED
- ExportJobSchema includes callback_url
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import ExportJob, JobStatus
from app.schemas.jobs import ExportJobSchema, JobCreate
from app.services.callback_service import (
    _is_private_ip,
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
        with pytest.raises(Exception) as exc_info:
            JobCreate(
                project_id="P1",
                evidence_number="EV1",
                source_path="/data/source",
                callback_url="http://example.com/webhook",
            )
        assert "HTTPS" in str(exc_info.value)

    def test_none_accepted(self):
        body = JobCreate(
            project_id="P1",
            evidence_number="EV1",
            source_path="/data/source",
        )
        assert body.callback_url is None

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


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


class TestSSRFProtection:

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_loopback_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]
        assert _is_private_ip("localhost") is True

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_private_ip_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("10.0.0.5", 0)),
        ]
        assert _is_private_ip("internal.corp") is True

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_public_ip_allowed(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        assert _is_private_ip("example.com") is False

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_unresolvable_host_blocked(self, mock_getaddrinfo):
        import socket as _socket
        mock_getaddrinfo.side_effect = _socket.gaierror("Name resolution failed")
        assert _is_private_ip("nonexistent.invalid") is True

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_unspecified_address_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("0.0.0.0", 0)),
        ]
        assert _is_private_ip("zero.example") is True

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_multicast_address_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("224.0.0.1", 0)),
        ]
        assert _is_private_ip("multicast.example") is True

    @patch("app.services.callback_service.socket.getaddrinfo")
    def test_ipv6_loopback_blocked(self, mock_getaddrinfo):
        mock_getaddrinfo.return_value = [
            (10, 1, 6, "", ("::1", 0, 0, 0)),
        ]
        assert _is_private_ip("ip6-localhost") is True


# ---------------------------------------------------------------------------
# deliver_callback
# ---------------------------------------------------------------------------


class TestDeliverCallback:

    def _make_job(self, callback_url="https://example.com/hook"):
        job = MagicMock(spec=ExportJob)
        job.id = 1
        job.project_id = "PROJ-001"
        job.evidence_number = "EV-001"
        job.status = JobStatus.COMPLETED
        job.source_path = "/data/evidence"
        job.total_bytes = 1024
        job.copied_bytes = 1024
        job.file_count = 10
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job.callback_url = callback_url
        return job

    def test_noop_when_no_callback_url(self, db):
        """deliver_callback is a no-op when callback_url is None."""
        job = self._make_job(callback_url=None)
        deliver_callback(job, db)
        # No audit log should exist
        logs = db.query(AuditLog).filter(AuditLog.job_id == 1).all()
        assert len(logs) == 0

    def test_malformed_url_audit_record(self, db):
        """A malformed callback_url that cannot be parsed must produce a
        CALLBACK_DELIVERY_FAILED audit record."""
        job = self._make_job(callback_url="not-a-url-at-all")

        # Force urlparse to raise so we exercise the except branch
        with patch("app.services.callback_service.urlparse", side_effect=ValueError("bad url")):
            deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "Malformed" in logs[0].details["reason"]

    @patch("app.services.callback_service._is_private_ip", return_value=True)
    @patch("app.services.callback_service.settings")
    def test_ssrf_blocks_delivery(self, mock_settings, mock_priv, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        job = self._make_job()

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "SSRF" in logs[0].details["reason"]

    @patch("app.services.callback_service.settings")
    def test_empty_hostname_blocked(self, mock_settings, db):
        """A callback URL with an empty hostname is rejected with an audit record."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        job = self._make_job(callback_url="https:///no-host")

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "empty hostname" in logs[0].details["reason"]

    @patch("app.services.callback_service._is_private_ip", return_value=False)
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_successful_delivery(self, mock_client_cls, mock_settings, mock_priv, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_job()
        deliver_callback(job, db)

        mock_client_instance.post.assert_called_once()
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_SENT",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["status_code"] == 200
        assert logs[0].details["attempt"] == 1

    @patch("app.services.callback_service._is_private_ip", return_value=False)
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    @patch("app.services.callback_service.time.sleep")
    def test_retry_on_5xx_then_success(self, mock_sleep, mock_client_cls, mock_settings, mock_priv, db):
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

        job = self._make_job()
        deliver_callback(job, db)

        assert mock_client_instance.post.call_count == 2
        mock_sleep.assert_called_once()

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_SENT",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["attempt"] == 2

    @patch("app.services.callback_service._is_private_ip", return_value=False)
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    @patch("app.services.callback_service.time.sleep")
    def test_all_retries_exhausted(self, mock_sleep, mock_client_cls, mock_settings, mock_priv, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        resp_503 = MagicMock()
        resp_503.status_code = 503

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = resp_503
        mock_client_cls.return_value = mock_client_instance

        job = self._make_job()
        deliver_callback(job, db)

        assert mock_client_instance.post.call_count == 3
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["attempts"] == 3
        assert "503" in logs[0].details["reason"]

    @patch("app.services.callback_service._is_private_ip", return_value=False)
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    @patch("app.services.callback_service.time.sleep")
    def test_network_error_retries(self, mock_sleep, mock_client_cls, mock_settings, mock_priv, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client_instance

        job = self._make_job()
        deliver_callback(job, db)

        assert mock_client_instance.post.call_count == 3
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1

    @patch("app.services.callback_service._is_private_ip", return_value=False)
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_4xx_no_retry(self, mock_client_cls, mock_settings, mock_priv, db):
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

        job = self._make_job()
        deliver_callback(job, db)

        # Only one attempt — no retries for 4xx
        mock_client_instance.post.assert_called_once()
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == 1,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["status_code"] == 404
        assert "rejected" in logs[0].details["reason"]

    @patch("app.services.callback_service._is_private_ip", return_value=True)
    @patch("app.services.callback_service.settings")
    def test_ssrf_allowed_when_configured(self, mock_settings, mock_priv, db):
        """When callback_allow_private_ips is True, private IPs are not blocked."""
        mock_settings.callback_allow_private_ips = True
        mock_settings.callback_timeout_seconds = 5

        # Patch httpx to return 200 so delivery succeeds
        with patch("app.services.callback_service.httpx.Client") as mock_client_cls:
            resp_200 = MagicMock()
            resp_200.status_code = 200
            mock_client_instance = MagicMock()
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            mock_client_instance.post.return_value = resp_200
            mock_client_cls.return_value = mock_client_instance

            job = self._make_job()
            deliver_callback(job, db)

            mock_client_instance.post.assert_called_once()
            logs = db.query(AuditLog).filter(
                AuditLog.job_id == 1,
                AuditLog.action == "CALLBACK_SENT",
            ).all()
            assert len(logs) == 1


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
