"""Tests for webhook callback feature (Issue #104).

Covers:
- Schema validation: HTTPS-only enforcement, optional field
- Callback delivery: success, retry on 5xx, all retries exhausted
- SSRF protection: private IP rejection, DNS-pinned connections
- No-op when callback_url is None
- Audit logging for CALLBACK_SENT and CALLBACK_DELIVERY_FAILED
- ExportJobSchema includes callback_url
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus
from app.schemas.jobs import ExportJobSchema, JobCreate
from app.services.callback_service import (
    _do_deliver,
    _count_file_outcomes,
    _resolve_safe,
    _sanitize_url_for_log,
    build_callback_payload,
    build_payload,
    deliver_callback,
)
from app.utils.sanitize import sanitize_audit_details


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
            mount_path="/mnt/ecube/callback-002",
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

    def test_explicit_lifecycle_event_supports_non_terminal_jobs(self):
        job = SimpleNamespace(
            id=42,
            project_id="PROJ-LIFECYCLE",
            evidence_number="EV-LIFECYCLE",
            created_by="creator",
            started_by="operator",
            status=JobStatus.RUNNING,
            source_path="/data/lifecycle",
            total_bytes=2048,
            copied_bytes=512,
            file_count=4,
            active_duration_seconds=11,
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            started_at=datetime(2026, 5, 1, 12, 5, tzinfo=timezone.utc),
            completed_at=None,
            files=[],
            assignments=[],
        )

        payload = build_payload(
            job,
            event="JOB_STARTED",
            event_actor="processor",
            event_at=datetime(2026, 5, 1, 12, 5, 30, tzinfo=timezone.utc),
            event_details={"thread_count": 4},
        )

        assert payload["event"] == "JOB_STARTED"
        assert payload["status"] == "RUNNING"
        assert payload["created_by"] == "creator"
        assert payload["event_actor"] == "processor"
        assert payload["event_at"] == "2026-05-01T12:05:30+00:00"
        assert payload["event_details"] == {"thread_count": 4}
        assert "completion_result" not in payload

    def test_count_file_outcomes_uses_aggregate_query_for_mapped_jobs(self, db):
        job = ExportJob(
            project_id="PROJ-CALLBACK-COUNTS",
            evidence_number="EV-CALLBACK-COUNTS",
            source_path="/data/evidence",
            status=JobStatus.COMPLETED,
            file_count=3,
        )
        db.add(job)
        db.flush()
        db.add(ExportFile(job_id=job.id, relative_path="ok.txt", status=FileStatus.DONE))
        db.add(ExportFile(job_id=job.id, relative_path="bad.txt", status=FileStatus.ERROR))
        db.add(ExportFile(job_id=job.id, relative_path="slow.txt", status=FileStatus.TIMEOUT))
        db.commit()
        db.refresh(job)

        with patch("app.services.callback_service.FileRepository.count_done_errors_and_timeouts", return_value=(1, 1, 1)) as mock_count:
            counts = _count_file_outcomes(job)

        mock_count.assert_called_once_with(job.id)
        assert counts == (1, 1, 1)

    def test_completed_payload(self):
        job = MagicMock(spec=ExportJob)
        job.id = 42
        job.project_id = "PROJ-001"
        job.evidence_number = "EV-001"
        job.started_by = "operator1"
        job.status = JobStatus.COMPLETED
        job.source_path = "/data/evidence"
        job.total_bytes = 1024
        job.copied_bytes = 1024
        job.file_count = 10
        job.active_duration_seconds = 75
        job.started_at = datetime(2025, 12, 31, 23, 58, 45, tzinfo=timezone.utc)
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job.files = [
            ExportFile(status=FileStatus.DONE),
            ExportFile(status=FileStatus.DONE),
        ]

        payload = build_payload(job)
        assert payload["event"] == "JOB_COMPLETED"
        assert payload["job_id"] == 42
        assert payload["started_by"] == "operator1"
        assert payload["status"] == "COMPLETED"
        assert payload["started_at"] == "2025-12-31T23:58:45+00:00"
        assert payload["completed_at"] == "2026-01-01T00:00:00+00:00"
        assert payload["active_duration_seconds"] == 75
        assert payload["files_succeeded"] == 2
        assert payload["files_failed"] == 0
        assert payload["files_timed_out"] == 0
        assert payload["completion_result"] == "success"

    def test_completed_payload_includes_active_drive_metadata(self, db):
        drive = UsbDrive(
            device_identifier="SER-12345",
            manufacturer="SanDisk",
            product_name="Extreme Pro",
            current_state=DriveState.IN_USE,
            current_project_id="PROJ-DRIVE",
        )
        job = ExportJob(
            project_id="PROJ-DRIVE",
            evidence_number="EV-DRIVE",
            started_by="operator-drive",
            source_path="/data/evidence",
            status=JobStatus.COMPLETED,
            total_bytes=1024,
            copied_bytes=1024,
            file_count=1,
            active_duration_seconds=42,
            started_at=datetime(2025, 12, 31, 23, 59, 18, tzinfo=timezone.utc),
            completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        db.add_all([drive, job])
        db.flush()
        db.add(DriveAssignment(job_id=job.id, drive_id=drive.id))
        db.add(ExportFile(job_id=job.id, relative_path="ok.txt", status=FileStatus.DONE))
        db.commit()
        db.refresh(job)

        payload = build_payload(job)

        assert payload["drive_id"] == drive.id
        assert payload["started_by"] == "operator-drive"
        assert payload["started_at"] == "2025-12-31T23:59:18+00:00"
        assert payload["active_duration_seconds"] == 42
        assert payload["drive_manufacturer"] == "SanDisk"
        assert payload["drive_model"] == "Extreme Pro"
        assert payload["drive_serial_number"] == "SER-12345"

    def test_completed_payload_marks_partial_success(self):
        job = MagicMock(spec=ExportJob)
        job.id = 43
        job.project_id = "PROJ-001"
        job.evidence_number = "EV-001"
        job.started_by = "operator1"
        job.status = JobStatus.COMPLETED
        job.source_path = "/data/evidence"
        job.total_bytes = 1024
        job.copied_bytes = 900
        job.file_count = 3
        job.active_duration_seconds = 15
        job.started_at = datetime(2025, 12, 31, 23, 59, 45, tzinfo=timezone.utc)
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job.files = [
            ExportFile(status=FileStatus.DONE),
            ExportFile(status=FileStatus.ERROR),
            ExportFile(status=FileStatus.TIMEOUT),
        ]

        payload = build_payload(job)

        assert payload["event"] == "JOB_COMPLETED"
        assert payload["files_succeeded"] == 1
        assert payload["files_failed"] == 1
        assert payload["files_timed_out"] == 1
        assert payload["completion_result"] == "partial_success"

    def test_failed_payload(self):
        job = MagicMock(spec=ExportJob)
        job.id = 7
        job.project_id = "PROJ-002"
        job.evidence_number = "EV-002"
        job.started_by = "operator2"
        job.status = JobStatus.FAILED
        job.source_path = "/data/src"
        job.total_bytes = 500
        job.copied_bytes = 200
        job.file_count = 5
        job.active_duration_seconds = 120
        job.started_at = datetime(2025, 12, 31, 23, 58, tzinfo=timezone.utc)
        job.completed_at = None
        job.files = [ExportFile(status=FileStatus.ERROR)]

        payload = build_payload(job)
        assert payload["event"] == "JOB_FAILED"
        assert payload["started_at"] == "2025-12-31T23:58:00+00:00"
        assert payload["active_duration_seconds"] == 120
        assert payload["files_failed"] == 1
        assert payload["completion_result"] == "failed"
        assert "completed_at" not in payload

    def test_build_payload_falls_back_to_in_memory_files_for_unmapped_objects(self):
        job = SimpleNamespace(
            id=44,
            project_id="PROJ-LOCAL",
            evidence_number="EV-LOCAL",
            started_by="operator-local",
            status=JobStatus.COMPLETED,
            source_path="/data/local",
            total_bytes=123,
            copied_bytes=123,
            file_count=2,
            active_duration_seconds=9,
            started_at=datetime(2025, 12, 31, 23, 59, 51, tzinfo=timezone.utc),
            completed_at=None,
            files=[
                ExportFile(status=FileStatus.DONE),
                ExportFile(status=FileStatus.ERROR),
            ],
        )

        payload = build_payload(job)

        assert payload["files_succeeded"] == 1
        assert payload["files_failed"] == 1
        assert payload["files_timed_out"] == 0
        assert payload["started_by"] == "operator-local"
        assert payload["started_at"] == "2025-12-31T23:59:51+00:00"
        assert payload["active_duration_seconds"] == 9
        assert payload["completion_result"] == "partial_success"

    def test_build_payload_falls_back_to_in_memory_active_assignment(self):
        drive = SimpleNamespace(
            id=99,
            manufacturer="Western Digital",
            product_name="My Passport",
            serial_number="WD-0001",
        )
        active_assignment = SimpleNamespace(
            id=2,
            assigned_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            released_at=None,
            drive=drive,
        )
        released_assignment = SimpleNamespace(
            id=1,
            assigned_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            released_at=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            drive=SimpleNamespace(
                id=1,
                manufacturer="Ignore",
                product_name="Old",
                serial_number="OLD-1",
            ),
        )
        job = SimpleNamespace(
            id=45,
            project_id="PROJ-LOCAL",
            evidence_number="EV-LOCAL",
            started_by="operator-local",
            status=JobStatus.COMPLETED,
            source_path="/data/local",
            total_bytes=123,
            copied_bytes=123,
            file_count=1,
            active_duration_seconds=18,
            started_at=datetime(2025, 12, 31, 23, 59, 42, tzinfo=timezone.utc),
            completed_at=None,
            files=[ExportFile(status=FileStatus.DONE)],
            assignments=[released_assignment, active_assignment],
        )

        payload = build_payload(job)

        assert payload["drive_id"] == 99
        assert payload["started_by"] == "operator-local"
        assert payload["started_at"] == "2025-12-31T23:59:42+00:00"
        assert payload["active_duration_seconds"] == 18
        assert payload["drive_manufacturer"] == "Western Digital"
        assert payload["drive_model"] == "My Passport"
        assert payload["drive_serial_number"] == "WD-0001"

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
            started_by="operator-db",
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
        job.active_duration_seconds = 33
        job.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
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
        job.started_by = "operator-mock"
        job.status = status
        job.source_path = "/data/evidence"
        job.total_bytes = 1024
        job.copied_bytes = 1024
        job.file_count = 10
        job.active_duration_seconds = 33
        job.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job.completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        job.callback_url = callback_url
        return job

    def test_noop_when_no_callback_url(self, db):
        """deliver_callback is a no-op when callback_url is None."""
        job = self._make_mock_job(callback_url=None)
        with patch("app.services.callback_service.settings.callback_default_url", None):
            deliver_callback(job, db)
        logs = db.query(AuditLog).all()
        assert len(logs) == 0

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.httpx.Client")
    def test_uses_system_default_callback_url_when_job_callback_missing(self, mock_client_cls, mock_resolve, db):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db, callback_url=None)

        with patch("app.services.callback_service.settings.callback_allow_private_ips", False), \
             patch("app.services.callback_service.settings.callback_timeout_seconds", 5), \
             patch("app.services.callback_service.settings.callback_default_url", "https://default.example.com/hook"):
            deliver_callback(job, db)

        call_args = mock_client_instance.post.call_args
        posted_url = call_args[0][0]
        assert "93.184.216.34" in posted_url
        headers = call_args[1]["headers"]
        assert headers["Host"] == "default.example.com"
        assert headers["Content-Type"] == "application/json"
        assert "X-ECUBE-Signature" not in headers

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.httpx.Client")
    def test_job_callback_url_overrides_system_default(self, mock_client_cls, mock_resolve, db):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db, callback_url="https://job.example.com/hook")

        with patch("app.services.callback_service.settings.callback_allow_private_ips", False), \
             patch("app.services.callback_service.settings.callback_timeout_seconds", 5), \
             patch("app.services.callback_service.settings.callback_default_url", "https://default.example.com/hook"):
            deliver_callback(job, db)

        call_args = mock_client_instance.post.call_args
        headers = call_args[1]["headers"]
        assert headers["Host"] == "job.example.com"
        assert headers["Content-Type"] == "application/json"
        assert "X-ECUBE-Signature" not in headers

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.httpx.Client")
    def test_callback_logs_info_for_dispatch_and_success(self, mock_client_cls, _mock_resolve, db, caplog):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)

        with patch("app.services.callback_service.settings.callback_allow_private_ips", False), \
             patch("app.services.callback_service.settings.callback_timeout_seconds", 5), \
             caplog.at_level(logging.INFO, logger="app.services.callback_service"):
            deliver_callback(job, db)

        messages = [record.getMessage() for record in caplog.records]
        assert "Dispatching callback" in messages
        assert "Callback delivered" in messages

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

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.httpx.Client")
    def test_non_terminal_lifecycle_event_is_delivered_when_explicit_event_provided(
        self,
        mock_client_cls,
        _mock_resolve,
        db,
    ):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db, status=JobStatus.RUNNING)
        job.created_by = "creator"
        job.completed_at = None

        with patch("app.services.callback_service.settings.callback_allow_private_ips", False), \
             patch("app.services.callback_service.settings.callback_timeout_seconds", 5):
            deliver_callback(
                job,
                db,
                event="JOB_STARTED",
                event_actor="processor",
                event_details={"thread_count": 4},
            )

        sent_payload = json.loads(mock_client_instance.post.call_args.kwargs["content"].decode("utf-8"))
        assert sent_payload["event"] == "JOB_STARTED"
        assert sent_payload["status"] == "RUNNING"
        assert sent_payload["event_actor"] == "processor"
        assert sent_payload["event_details"] == {"thread_count": 4}

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

    @pytest.mark.parametrize("allow_private", [False, True])
    @patch("app.services.callback_service.settings")
    def test_empty_hostname_blocked(self, mock_settings, db, allow_private):
        """A callback URL with an empty hostname is rejected regardless of
        callback_allow_private_ips."""
        mock_settings.callback_allow_private_ips = allow_private
        mock_settings.callback_timeout_seconds = 5
        job = self._make_db_job(db, callback_url="https:///no-host")

        deliver_callback(job, db)

        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert "empty hostname" in logs[0].details["reason"].lower()

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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        expected_url = sanitize_audit_details({"callback_url": "https://example.com/hook"})["callback_url"]
        assert logged_url == expected_url
        assert "token" not in logged_url
        assert "secret" not in logged_url

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_successful_delivery(self, mock_client_cls, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        headers = call_args[1]["headers"]
        assert headers["Host"] == "example.com"
        assert headers["Content-Type"] == "application/json"
        assert "X-ECUBE-Signature" not in headers
        assert call_args[1]["extensions"] == {
            "sni_hostname": b"example.com",
        }
        delivered_payload = json.loads(call_args[1]["content"].decode("utf-8"))
        assert delivered_payload["job_id"] == job.id
        assert delivered_payload["status"] == job.status.value
        assert delivered_payload["event"] == "JOB_COMPLETED"
        mock_client_cls.assert_called_with(
            timeout=5,
            follow_redirects=False,
            trust_env=False,
        )

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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
    def test_3xx_redirect_rejected(self, mock_client_cls, mock_settings, mock_resolve, db):
        """3xx redirects are treated as permanent failure — not followed and
        not retried — to prevent redirect-based SSRF bypass."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

        resp_302 = MagicMock()
        resp_302.status_code = 302

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = resp_302
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        # No retry — single attempt only.
        mock_client_instance.post.assert_called_once()
        logs = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_DELIVERY_FAILED",
        ).all()
        assert len(logs) == 1
        assert logs[0].details["status_code"] == 302
        assert "redirect" in logs[0].details["reason"].lower()

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_4xx_no_retry(self, mock_client_cls, mock_settings, mock_resolve, db):
        """4xx responses are not retried — they are treated as non-transient."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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
        headers = call_args[1]["headers"]
        assert headers["Host"] == "example.com"
        assert headers["Content-Type"] == "application/json"
        assert call_args[1]["extensions"] == {
            "sni_hostname": b"example.com",
        }

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_dns_pinning_host_header_includes_nondefault_port(
        self, mock_client_cls, mock_settings, mock_resolve, db,
    ):
        """When the callback URL uses a non-default port, the Host header
        must include it so virtual-host routing works on the receiver."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db, callback_url="https://example.com:8443/hook")
        deliver_callback(job, db)

        call_args = mock_client_instance.post.call_args
        posted_url = call_args[0][0]
        assert "93.184.216.34:8443" in posted_url

        # Host header must include the port for non-default ports.
        headers = call_args[1]["headers"]
        assert headers["Host"] == "example.com:8443"
        assert headers["Content-Type"] == "application/json"
        # SNI carries just the hostname (port is not part of TLS SNI).
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
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

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

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_idn_hostname_sni_encoding(self, mock_client_cls, mock_settings, mock_resolve, db):
        """Internationalized domain names must be IDNA-encoded for TLS SNI
        so callback delivery doesn't crash on non-ASCII hostnames."""
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = None

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        # U+00FC = ü → IDNA ACE form is "xn--bcher-kva.example.com"
        idn_url = "https://b\u00fccher.example.com/hook"
        job = self._make_db_job(db, callback_url=idn_url)
        deliver_callback(job, db)

        call_args = mock_client_instance.post.call_args
        sni = call_args[1]["extensions"]["sni_hostname"]
        # Must be valid ASCII bytes (IDNA-encoded), not raw UTF-8.
        assert sni == "b\u00fccher.example.com".encode("idna")
        assert sni == b"xn--bcher-kva.example.com"

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_includes_hmac_signature_header_when_secret_is_configured(
        self, mock_client_cls, mock_settings, mock_resolve, db,
    ):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = "super-secret"
        mock_settings.callback_proxy_url = None

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
        payload_bytes = call_args[1]["content"]
        headers = call_args[1]["headers"]
        expected_signature = "sha256=" + hmac.new(
            b"super-secret",
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        assert headers["X-ECUBE-Signature"] == expected_signature
        assert headers["Content-Type"] == "application/json"
        delivered_payload = json.loads(payload_bytes.decode("utf-8"))
        assert delivered_payload["job_id"] == job.id
        assert delivered_payload["status"] == job.status.value
        assert delivered_payload["event"] == "JOB_COMPLETED"

    @patch("app.services.callback_service.settings")
    def test_build_callback_payload_applies_allowlist_and_mapping(self, mock_settings, db):
        mock_settings.callback_payload_fields = [
            "event",
            "project_id",
            "started_by",
            "completion_result",
            "files_failed",
            "started_at",
            "completed_at",
            "active_duration_seconds",
            "drive_id",
            "drive_manufacturer",
        ]
        mock_settings.callback_payload_field_map = {
            "type": "event",
            "project": "project_id",
            "operator": "started_by",
            "started": "started_at",
            "ended": "completed_at",
            "duration_seconds": "active_duration_seconds",
            "destination_drive_id": "drive_id",
            "summary": "project=${project_id};result=${completion_result};failed=${files_failed}",
            "vendor": "drive_manufacturer",
        }

        drive = UsbDrive(
            device_identifier="SER-777",
            manufacturer="Samsung",
            product_name="T7",
            current_state=DriveState.IN_USE,
            current_project_id="PROJ-001",
        )
        db.add(drive)
        db.flush()

        job = self._make_db_job(db)
        db.add(DriveAssignment(job_id=job.id, drive_id=drive.id))
        db.commit()
        db.refresh(job)
        payload = build_callback_payload(job)

        assert payload == {
            "type": "JOB_COMPLETED",
            "project": job.project_id,
            "operator": job.started_by,
            "started": "2026-01-01T00:00:00+00:00",
            "ended": "2026-01-01T00:00:00+00:00",
            "duration_seconds": 33,
            "destination_drive_id": drive.id,
            "summary": f"project={job.project_id};result=success;failed=0",
            "vendor": "Samsung",
        }

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    def test_signed_callback_receiver_validates_raw_request_body(self, mock_settings, mock_resolve, db):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = "super-secret"
        mock_settings.callback_proxy_url = None
        mock_settings.callback_payload_fields = ["event", "project_id", "completion_result"]
        mock_settings.callback_payload_field_map = {
            "type": "event",
            "project": "project_id",
            "summary": "project=${project_id};result=${completion_result}",
        }

        receiver_app = FastAPI()
        captured: dict[str, object] = {}

        @receiver_app.post("/hook")
        async def receive_callback(request: Request):
            body = await request.body()
            signature = request.headers.get("x-ecube-signature", "")
            expected_signature = "sha256=" + hmac.new(
                b"super-secret",
                body,
                hashlib.sha256,
            ).hexdigest()
            captured["signature"] = signature
            captured["expected_signature"] = expected_signature
            captured["body"] = body
            captured["json"] = await request.json()
            return {"valid": signature == expected_signature}

        class _ClientWrapper:
            def __init__(self, client: TestClient):
                self._client = client

            def __enter__(self):
                return self._client

            def __exit__(self, exc_type, exc, tb):
                self._client.close()
                return False

        with patch(
            "app.services.callback_service.httpx.Client",
            side_effect=lambda **_: _ClientWrapper(TestClient(receiver_app, base_url="https://93.184.216.34")),
        ):
            job = self._make_db_job(db)
            deliver_callback(job, db)

        assert captured["signature"] == captured["expected_signature"]
        assert json.loads(captured["body"].decode("utf-8")) == {
            "type": "JOB_COMPLETED",
            "project": job.project_id,
            "summary": f"project={job.project_id};result=success",
        }

        log_entry = db.query(AuditLog).filter(
            AuditLog.job_id == job.id,
            AuditLog.action == "CALLBACK_SENT",
        ).one()
        assert log_entry.details["payload_fields"] == ["event", "project_id", "completion_result"]
        assert log_entry.details["payload_mapping_keys"] == ["type", "project", "summary"]

    @patch("app.services.callback_service._resolve_safe", return_value="93.184.216.34")
    @patch("app.services.callback_service.settings")
    @patch("app.services.callback_service.httpx.Client")
    def test_uses_configured_callback_proxy_url(
        self, mock_client_cls, mock_settings, mock_resolve, db,
    ):
        mock_settings.callback_allow_private_ips = False
        mock_settings.callback_timeout_seconds = 5
        mock_settings.callback_hmac_secret = None
        mock_settings.callback_proxy_url = "http://proxy.example.com:8080"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.post.return_value = mock_response
        mock_client_cls.return_value = mock_client_instance

        job = self._make_db_job(db)
        deliver_callback(job, db)

        mock_client_cls.assert_called_with(
            timeout=5,
            follow_redirects=False,
            trust_env=False,
            proxy="http://proxy.example.com:8080",
        )

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

    def test_get_executor_returns_thread_pool(self, monkeypatch):
        """_get_executor returns a ThreadPoolExecutor."""
        from concurrent.futures import ThreadPoolExecutor as _TPE
        from app.services.callback_service import _get_executor, _shutdown_executor
        import app.services.callback_service as _mod

        # Reset module state for a clean test.
        monkeypatch.setattr(_mod, "_executor", None)
        with patch.object(_mod, "settings") as mock_settings:
            mock_settings.callback_max_workers = 2
            pool = _get_executor()
            assert isinstance(pool, _TPE)
            assert pool._max_workers == 2
        # Shut down the pool we created so it doesn't leak.
        if _mod._executor is not None:
            _mod._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Backpressure (semaphore-gated pending queue)
# ---------------------------------------------------------------------------


class TestBackpressure:
    """Tests for the BoundedSemaphore-based backpressure mechanism."""

    def test_delivery_dropped_when_queue_full(self, monkeypatch):
        """When the semaphore is exhausted, deliver_callback drops and audits."""
        import app.services.callback_service as _mod
        from app.services.callback_service import _get_pending_semaphore

        job = MagicMock(spec=ExportJob)
        job.id = 42
        job.callback_url = "https://example.com/hook"
        job.status = JobStatus.COMPLETED

        # Force semaphore to have 0 permits so the next acquire fails.
        sem = __import__("threading").BoundedSemaphore(1)
        sem.acquire()  # consume the single permit
        monkeypatch.setattr(_mod, "_pending_semaphore", sem)
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

    def test_delivery_proceeds_when_permits_available(self, monkeypatch):
        """When permits are available, deliver_callback submits normally."""
        import app.services.callback_service as _mod

        job = MagicMock(spec=ExportJob)
        job.id = 7
        job.callback_url = "https://example.com/hook"
        job.status = JobStatus.COMPLETED

        monkeypatch.setattr(_mod, "_pending_semaphore", __import__("threading").BoundedSemaphore(5))
        with patch.object(_mod, "_get_executor") as mock_exec, \
             patch.object(_mod, "_audit_dropped_delivery") as mock_audit, \
             patch.object(_mod, "build_payload", return_value={"event": "JOB_COMPLETED"}):
            mock_executor = MagicMock()
            mock_exec.return_value = mock_executor

            deliver_callback(job)  # db=None

            mock_executor.submit.assert_called_once()
            mock_audit.assert_not_called()

    def test_semaphore_released_after_delivery(self, monkeypatch):
        """_deliver_callback_sync releases the semaphore even on failure."""
        import app.services.callback_service as _mod
        from app.services.callback_service import _deliver_callback_sync

        sem = __import__("threading").BoundedSemaphore(2)
        sem.acquire()  # 1 permit left
        monkeypatch.setattr(_mod, "_pending_semaphore", sem)
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

    def test_get_pending_semaphore_creates_bounded_semaphore(self, monkeypatch):
        """_get_pending_semaphore returns a BoundedSemaphore sized by config."""
        import app.services.callback_service as _mod
        from app.services.callback_service import _get_pending_semaphore

        monkeypatch.setattr(_mod, "_pending_semaphore", None)
        with patch.object(_mod, "settings") as mock_settings:
            mock_settings.callback_max_pending = 3
            sem = _get_pending_semaphore()
            # Verify we can acquire exactly 3 times.
            assert sem.acquire(blocking=False)
            assert sem.acquire(blocking=False)
            assert sem.acquire(blocking=False)
            assert not sem.acquire(blocking=False)  # 4th should fail


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
