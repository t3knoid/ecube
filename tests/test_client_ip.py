"""Tests for client IP tracking in audit logs and job records (issue #106)."""

from unittest.mock import MagicMock, patch

import pytest

from app.utils.client_ip import get_client_ip
from app.models.audit import AuditLog
from app.models.jobs import ExportJob


# ---------------------------------------------------------------------------
# get_client_ip() — unit tests for the extraction utility
# ---------------------------------------------------------------------------


def _make_request(headers=None, client_host="192.168.1.50"):
    """Build a minimal mock Request with the given headers and client host."""
    req = MagicMock()
    req.headers = headers or {}
    req.client = MagicMock()
    req.client.host = client_host
    return req


class TestGetClientIpDirectConnection:
    """When trust_proxy_headers is False (default), always return client.host."""

    @patch("app.utils.client_ip.settings")
    def test_returns_direct_connection_ip(self, mock_settings):
        mock_settings.trust_proxy_headers = False
        request = _make_request(client_host="10.0.0.1")
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_ignores_forwarded_header_when_untrusted(self, mock_settings):
        mock_settings.trust_proxy_headers = False
        request = _make_request(
            headers={"X-Forwarded-For": "203.0.113.50, 70.41.3.18"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_ignores_real_ip_header_when_untrusted(self, mock_settings):
        mock_settings.trust_proxy_headers = False
        request = _make_request(
            headers={"X-Real-IP": "203.0.113.50"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_returns_unknown_when_no_client(self, mock_settings):
        mock_settings.trust_proxy_headers = False
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert get_client_ip(request) == "unknown"


class TestGetClientIpProxyHeaders:
    """When trust_proxy_headers is True, honour X-Forwarded-For / X-Real-IP."""

    @patch("app.utils.client_ip.settings")
    def test_uses_x_forwarded_for_first_entry(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Forwarded-For": "203.0.113.50, 70.41.3.18"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "203.0.113.50"

    @patch("app.utils.client_ip.settings")
    def test_uses_x_forwarded_for_single_entry(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Forwarded-For": "  198.51.100.42  "},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "198.51.100.42"

    @patch("app.utils.client_ip.settings")
    def test_uses_x_real_ip_when_no_forwarded_for(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Real-IP": "198.51.100.42"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "198.51.100.42"

    @patch("app.utils.client_ip.settings")
    def test_falls_back_to_client_host_when_no_proxy_headers(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(headers={}, client_host="10.0.0.1")
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_x_forwarded_for_takes_precedence_over_x_real_ip(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={
                "X-Forwarded-For": "203.0.113.50",
                "X-Real-IP": "198.51.100.42",
            },
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "203.0.113.50"


class TestGetClientIpValidation:
    """Malformed proxy header values must fall through to client.host."""

    @patch("app.utils.client_ip.settings")
    def test_malformed_forwarded_for_falls_back(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Forwarded-For": "not-an-ip, 70.41.3.18"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_malformed_real_ip_falls_back(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Real-IP": "garbage-value"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_malformed_forwarded_valid_real_ip(self, mock_settings):
        """If X-Forwarded-For is invalid but X-Real-IP is valid, use X-Real-IP."""
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={
                "X-Forwarded-For": "bogus",
                "X-Real-IP": "198.51.100.42",
            },
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "198.51.100.42"

    @patch("app.utils.client_ip.settings")
    def test_oversized_value_falls_back(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Forwarded-For": "A" * 500},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_empty_forwarded_for_falls_back(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Forwarded-For": ""},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "10.0.0.1"

    @patch("app.utils.client_ip.settings")
    def test_ipv6_address_accepted(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        request = _make_request(
            headers={"X-Forwarded-For": "2001:db8::1"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(request) == "2001:db8::1"


# ---------------------------------------------------------------------------
# Model columns — verify client_ip is present
# ---------------------------------------------------------------------------


class TestAuditLogModel:
    def test_client_ip_column_exists(self, db):
        log = AuditLog(action="TEST", client_ip="10.0.0.1")
        db.add(log)
        db.commit()
        db.refresh(log)
        assert log.client_ip == "10.0.0.1"

    def test_client_ip_nullable(self, db):
        log = AuditLog(action="TEST")
        db.add(log)
        db.commit()
        db.refresh(log)
        assert log.client_ip is None


class TestExportJobModel:
    def test_client_ip_column_exists(self, db):
        job = ExportJob(
            source_path="/data/source",
            evidence_number="EV-001",
            project_id="PRJ-1",
            created_by="test-user",
            client_ip="172.16.0.5",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.client_ip == "172.16.0.5"

    def test_client_ip_nullable(self, db):
        job = ExportJob(
            source_path="/data/source",
            evidence_number="EV-002",
            project_id="PRJ-1",
            created_by="test-user",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.client_ip is None


# ---------------------------------------------------------------------------
# Audit repository — client_ip passed through
# ---------------------------------------------------------------------------


class TestAuditRepositoryClientIp:
    def test_add_stores_client_ip(self, db):
        from app.repositories.audit_repository import AuditRepository

        repo = AuditRepository(db)
        entry = repo.add(action="TEST_ACTION", user="someone", client_ip="10.10.10.10")
        assert entry.client_ip == "10.10.10.10"

    def test_add_defaults_to_none(self, db):
        from app.repositories.audit_repository import AuditRepository

        repo = AuditRepository(db)
        entry = repo.add(action="TEST_ACTION", user="someone")
        assert entry.client_ip is None

    def test_best_effort_audit_stores_client_ip(self, db):
        from app.repositories.audit_repository import best_effort_audit

        best_effort_audit(db, "TEST_ACTION", "someone", client_ip="10.20.30.40")
        entry = db.query(AuditLog).filter(AuditLog.action == "TEST_ACTION").first()
        assert entry is not None
        assert entry.client_ip == "10.20.30.40"


# ---------------------------------------------------------------------------
# Schema — client_ip field in responses
# ---------------------------------------------------------------------------


class TestAuditLogSchema:
    def test_client_ip_in_schema(self):
        from app.schemas.audit import AuditLogSchema

        fields = AuditLogSchema.model_fields
        assert "client_ip" in fields

    def test_schema_serializes_client_ip(self, db):
        log = AuditLog(action="TEST", client_ip="10.0.0.1")
        db.add(log)
        db.commit()
        db.refresh(log)

        from app.schemas.audit import AuditLogSchema

        schema = AuditLogSchema.model_validate(log)
        assert schema.client_ip == "10.0.0.1"


class TestExportJobSchema:
    def test_client_ip_in_schema(self):
        from app.schemas.jobs import ExportJobSchema

        fields = ExportJobSchema.model_fields
        assert "client_ip" in fields


# ---------------------------------------------------------------------------
# Role-based redaction — client_ip hidden from non-admin/auditor roles
# ---------------------------------------------------------------------------


class TestJobClientIpRedaction:
    """Verify that client_ip is only visible to admin and auditor roles."""

    def _create_job(self, http_client):
        return http_client.post(
            "/jobs",
            json={
                "project_id": "PROJ-IP",
                "evidence_number": "EV-IP",
                "source_path": "/data/evidence",
            },
        )

    def test_admin_sees_client_ip(self, admin_client, db):
        resp = self._create_job(admin_client)
        assert resp.status_code == 200
        job_id = resp.json()["id"]

        get_resp = admin_client.get(f"/jobs/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["client_ip"] is not None

    def test_processor_client_ip_redacted(self, client, db):
        resp = self._create_job(client)
        assert resp.status_code == 200
        # Processor should not see the IP, even on the create response
        assert resp.json()["client_ip"] is None

    def test_processor_get_job_client_ip_redacted(self, admin_client, client, db):
        # Admin creates job (IP stored), processor reads it back
        resp = self._create_job(admin_client)
        job_id = resp.json()["id"]

        get_resp = client.get(f"/jobs/{job_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["client_ip"] is None

    def test_auditor_sees_client_ip(self, auditor_client, db):
        # Auditor can't create jobs, but can read them.
        # Use a direct DB insert so auditor can GET.
        job = ExportJob(
            source_path="/data/src",
            evidence_number="EV-AUD",
            project_id="PROJ-AUD",
            created_by="someone",
            client_ip="10.99.99.99",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        get_resp = auditor_client.get(f"/jobs/{job.id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["client_ip"] == "10.99.99.99"

    def test_manager_client_ip_redacted(self, manager_client, db):
        resp = self._create_job(manager_client)
        assert resp.status_code == 200
        assert resp.json()["client_ip"] is None


# ---------------------------------------------------------------------------
# Role-based redaction — audit log client_ip hidden from manager
# ---------------------------------------------------------------------------


class TestAuditLogClientIpRedaction:
    """Verify that client_ip in /audit responses is only visible to admin and auditor."""

    def _insert_audit_entry(self, db):
        entry = AuditLog(action="TEST_REDACT", user="tester", client_ip="10.88.88.88")
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    def test_admin_sees_audit_client_ip(self, admin_client, db):
        self._insert_audit_entry(db)
        resp = admin_client.get("/audit", params={"action": "TEST_REDACT"})
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) >= 1
        assert entries[0]["client_ip"] == "10.88.88.88"

    def test_auditor_sees_audit_client_ip(self, auditor_client, db):
        self._insert_audit_entry(db)
        resp = auditor_client.get("/audit", params={"action": "TEST_REDACT"})
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) >= 1
        assert entries[0]["client_ip"] == "10.88.88.88"

    def test_manager_audit_client_ip_redacted(self, manager_client, db):
        self._insert_audit_entry(db)
        resp = manager_client.get("/audit", params={"action": "TEST_REDACT"})
        assert resp.status_code == 200
        entries = resp.json()
        assert len(entries) >= 1
        assert entries[0]["client_ip"] is None
