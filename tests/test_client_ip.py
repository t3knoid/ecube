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
