"""Tests for GET /audit endpoint.

Covers:
- Basic listing returns all audit log entries.
- Filtering by user, action, job_id, since, until.
- Pagination (limit, offset).
- Role restrictions: admin, manager, auditor allowed; processor denied.
- Response schema matches AuditLogSchema.
"""

import time

import jwt
import pytest
from sqlalchemy import text

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.audit import AuditLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_entries(db, entries):
    """Insert AuditLog rows directly and return them."""
    result = []
    for kwargs in entries:
        obj = AuditLog(**kwargs)
        db.add(obj)
    db.commit()
    result = db.query(AuditLog).order_by(AuditLog.id).all()
    return result


# ---------------------------------------------------------------------------
# Basic listing
# ---------------------------------------------------------------------------


class TestAuditListBasic:
    def test_empty_db_returns_empty_list(self, admin_client):
        response = admin_client.get("/audit")
        assert response.status_code == 200
        data = response.json()
        # Startup reconciliation may emit a USB_DISCOVERY_SYNC entry;
        # filter it out to verify no user-created entries exist.
        user_entries = [e for e in data if e["action"] != "USB_DISCOVERY_SYNC"]
        assert user_entries == []

    def test_returns_seeded_entries(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "details": {}},
                {"action": "DRIVE_INITIALIZED", "user": "alba", "details": {}},
            ],
        )
        response = admin_client.get("/audit")
        assert response.status_code == 200
        data = response.json()
        # Filter out startup reconciliation entries.
        data = [e for e in data if e["action"] != "USB_DISCOVERY_SYNC"]
        assert len(data) == 2
        actions = {d["action"] for d in data}
        assert actions == {"JOB_CREATED", "DRIVE_INITIALIZED"}

    def test_response_schema_fields(self, admin_client, db):
        _seed_entries(db, [{"action": "TEST_ACTION", "user": "user1", "details": {"k": "v"}}])
        response = admin_client.get("/audit")
        assert response.status_code == 200
        entry = response.json()[0]
        assert "id" in entry
        assert "action" in entry
        assert "user" in entry
        assert "job_id" in entry
        assert "details" in entry
        assert "timestamp" in entry


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class TestAuditFilters:
    def test_filter_by_user(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "ACTION_A", "user": "griffin", "details": {}},
                {"action": "ACTION_B", "user": "alba", "details": {}},
                {"action": "ACTION_C", "user": "griffin", "details": {}},
            ],
        )
        response = admin_client.get("/audit?user=griffin")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(d["user"] == "griffin" for d in data)

    def test_filter_by_action(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "details": {}},
                {"action": "DRIVE_INITIALIZED", "user": "griffin", "details": {}},
                {"action": "JOB_CREATED", "user": "alba", "details": {}},
            ],
        )
        response = admin_client.get("/audit?action=JOB_CREATED")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(d["action"] == "JOB_CREATED" for d in data)

    def test_filter_by_job_id(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "job_id": 1, "details": {}},
                {"action": "JOB_STARTED", "user": "griffin", "job_id": 1, "details": {}},
                {"action": "JOB_CREATED", "user": "alba", "job_id": 2, "details": {}},
            ],
        )
        response = admin_client.get("/audit?job_id=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(d["job_id"] == 1 for d in data)

    def test_filter_by_since(self, admin_client, db):
        from datetime import datetime, timezone

        early = AuditLog(action="EARLY", user="u", details={})
        db.add(early)
        db.flush()
        # set timestamp manually to a known past time
        db.execute(
            text(
                "UPDATE audit_logs SET timestamp = '2020-01-01 00:00:00' WHERE id = :id"
            ),
            {"id": early.id},
        )
        db.commit()

        late = AuditLog(action="LATE", user="u", details={})
        db.add(late)
        db.flush()
        db.execute(
            text(
                "UPDATE audit_logs SET timestamp = '2024-01-01 00:00:00' WHERE id = :id"
            ),
            {"id": late.id},
        )
        db.commit()

        response = admin_client.get("/audit?since=2023-01-01T00:00:00")
        assert response.status_code == 200
        data = response.json()
        actions = {d["action"] for d in data}
        assert "LATE" in actions
        assert "EARLY" not in actions

    def test_filter_by_until(self, admin_client, db):
        early = AuditLog(action="EARLY", user="u", details={})
        db.add(early)
        db.flush()
        db.execute(
            text(
                "UPDATE audit_logs SET timestamp = '2020-01-01 00:00:00' WHERE id = :id"
            ),
            {"id": early.id},
        )
        db.commit()

        late = AuditLog(action="LATE", user="u", details={})
        db.add(late)
        db.flush()
        db.execute(
            text(
                "UPDATE audit_logs SET timestamp = '2024-01-01 00:00:00' WHERE id = :id"
            ),
            {"id": late.id},
        )
        db.commit()

        response = admin_client.get("/audit?until=2021-01-01T00:00:00")
        assert response.status_code == 200
        data = response.json()
        actions = {d["action"] for d in data}
        assert "EARLY" in actions
        assert "LATE" not in actions

    def test_combined_filters(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "job_id": 1, "details": {}},
                {"action": "JOB_CREATED", "user": "alba", "job_id": 2, "details": {}},
                {"action": "JOB_STARTED", "user": "griffin", "job_id": 1, "details": {}},
            ],
        )
        response = admin_client.get("/audit?user=griffin&action=JOB_CREATED")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["user"] == "griffin"
        assert data[0]["action"] == "JOB_CREATED"

    def test_no_match_returns_empty(self, admin_client, db):
        _seed_entries(db, [{"action": "JOB_CREATED", "user": "griffin", "details": {}}])
        response = admin_client.get("/audit?user=nobody")
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestAuditPagination:
    def test_limit(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(5)])
        response = admin_client.get("/audit?limit=3")
        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_offset(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(5)])
        response_all = admin_client.get("/audit?limit=1000")
        all_ids = [d["id"] for d in response_all.json()]

        response_offset = admin_client.get("/audit?offset=2&limit=1000")
        offset_ids = [d["id"] for d in response_offset.json()]

        assert offset_ids == all_ids[2:]

    def test_limit_and_offset(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(10)])
        response = admin_client.get("/audit?limit=3&offset=2")
        assert response.status_code == 200
        assert len(response.json()) == 3


# ---------------------------------------------------------------------------
# Role restrictions
# ---------------------------------------------------------------------------


class TestAuditRoleRestrictions:
    def test_admin_can_access(self, admin_client, db):
        response = admin_client.get("/audit")
        assert response.status_code == 200

    def test_manager_can_access(self, manager_client, db):
        response = manager_client.get("/audit")
        assert response.status_code == 200

    def test_auditor_can_access(self, auditor_client, db):
        response = auditor_client.get("/audit")
        assert response.status_code == 200

    def test_processor_cannot_access(self, client, db):
        """processor role must receive 403."""
        response = client.get("/audit")
        assert response.status_code == 403

    def test_unauthenticated_cannot_access(self, unauthenticated_client, db):
        response = unauthenticated_client.get("/audit")
        assert response.status_code == 401
