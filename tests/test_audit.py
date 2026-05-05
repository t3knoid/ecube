"""Tests for GET /audit endpoint.

Covers:
- Basic listing returns all audit log entries.
- Filtering by user, action, job_id, since, until.
- Pagination (limit, offset).
- Role restrictions: admin, manager, processor, auditor allowed.
- Response schema matches AuditLogSchema.
"""

import pytest
from sqlalchemy import text

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive


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


def _user_created_entries(entries):
    """Exclude startup reconciliation rows emitted by the system actor."""
    return [entry for entry in entries if entry.get("user") != "system"]


def _audit_entries(response):
    return response.json()["entries"]


# ---------------------------------------------------------------------------
# Basic listing
# ---------------------------------------------------------------------------


class TestAuditListBasic:
    def test_empty_db_returns_empty_list(self, admin_client):
        response = admin_client.get("/audit")
        assert response.status_code == 200
        data = _audit_entries(response)
        user_entries = _user_created_entries(data)
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
        data = _audit_entries(response)
        data = _user_created_entries(data)
        assert len(data) == 2
        actions = {d["action"] for d in data}
        assert actions == {"JOB_CREATED", "DRIVE_INITIALIZED"}

    def test_response_schema_fields(self, admin_client, db):
        _seed_entries(db, [{"action": "TEST_ACTION", "user": "user1", "details": {"k": "v"}}])
        response = admin_client.get("/audit")
        assert response.status_code == 200
        entry = _audit_entries(response)[0]
        assert "id" in entry
        assert "action" in entry
        assert "user" in entry
        assert "project_id" in entry
        assert "drive_id" in entry
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
        data = _audit_entries(response)
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
        data = _audit_entries(response)
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
        data = _audit_entries(response)
        assert len(data) == 2
        assert all(d["job_id"] == 1 for d in data)

    def test_filter_by_project_id(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "project_id": "PRJ-1", "details": {}},
                {"action": "JOB_STARTED", "user": "griffin", "project_id": "PRJ-1", "details": {}},
                {"action": "JOB_CREATED", "user": "alba", "project_id": "PRJ-2", "details": {}},
            ],
        )
        response = admin_client.get("/audit?project_id=PRJ-1")
        assert response.status_code == 200
        data = _audit_entries(response)
        assert len(data) == 2
        assert all(d["project_id"] == "PRJ-1" for d in data)

    def test_filter_by_project_id_normalizes_case_and_whitespace(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "project_id": "PRJ-1", "details": {}},
                {"action": "JOB_STARTED", "user": "griffin", "project_id": "PRJ-1", "details": {}},
                {"action": "JOB_CREATED", "user": "alba", "project_id": "PRJ-2", "details": {}},
            ],
        )

        response = admin_client.get("/audit", params={"project_id": " prj-1 "})

        assert response.status_code == 200
        data = _audit_entries(response)
        assert len(data) == 2
        assert all(d["project_id"] == "PRJ-1" for d in data)

    def test_filter_by_project_id_sanitizes_invalid_chars(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "project_id": "PRJ-1", "details": {}},
                {"action": "JOB_CREATED", "user": "alba", "project_id": "PRJ-2", "details": {}},
            ],
        )
        response = admin_client.get("/audit", params={"project_id": "PRJ-1\x00"})
        assert response.status_code == 200
        data = _audit_entries(response)
        assert len(data) == 1
        assert data[0]["project_id"] == "PRJ-1"

    def test_filter_by_project_id_rejects_empty_after_sanitize(self, admin_client):
        response = admin_client.get("/audit", params={"project_id": "\x00"})
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "ENCODING_ERROR"

    def test_filter_by_drive_id(self, admin_client, db):
        drive_1 = UsbDrive(device_identifier="AUDIT-FILTER-DRIVE-1", current_state=DriveState.AVAILABLE)
        drive_2 = UsbDrive(device_identifier="AUDIT-FILTER-DRIVE-2", current_state=DriveState.AVAILABLE)
        db.add_all([drive_1, drive_2])
        db.commit()

        _seed_entries(
            db,
            [
                {"action": "DRIVE_INITIALIZED", "user": "griffin", "drive_id": drive_1.id, "details": {}},
                {"action": "DRIVE_EJECT_PREPARED", "user": "griffin", "drive_id": drive_1.id, "details": {}},
                {"action": "DRIVE_INITIALIZED", "user": "alba", "drive_id": drive_2.id, "details": {}},
            ],
        )
        response = admin_client.get(f"/audit?drive_id={drive_1.id}")
        assert response.status_code == 200
        data = _audit_entries(response)
        assert len(data) == 2
        assert all(d["drive_id"] == drive_1.id for d in data)

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
        data = _audit_entries(response)
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
        data = _audit_entries(response)
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
        data = _audit_entries(response)
        assert len(data) == 1
        assert data[0]["user"] == "griffin"
        assert data[0]["action"] == "JOB_CREATED"

    def test_no_match_returns_empty(self, admin_client, db):
        _seed_entries(db, [{"action": "JOB_CREATED", "user": "griffin", "details": {}}])
        response = admin_client.get("/audit?user=nobody")
        assert response.status_code == 200
        assert response.json()["entries"] == []

    def test_search_matches_visible_audit_fields(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "project_id": "PRJ-100", "job_id": 41, "details": {"safe_note": "Export created"}},
                {"action": "DRIVE_INITIALIZED", "user": "alba", "project_id": "PRJ-200", "job_id": 52, "details": {"safe_note": "Drive prepared"}},
            ],
        )

        response = admin_client.get("/audit", params={"search": "griff"})

        assert response.status_code == 200
        entries = response.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["user"] == "griffin"

    def test_search_matches_client_ip_for_admin(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "LOGIN", "user": "griffin", "client_ip": "10.88.88.88", "details": {}},
                {"action": "LOGIN", "user": "alba", "client_ip": "10.77.77.77", "details": {}},
            ],
        )

        response = admin_client.get("/audit", params={"search": "10.88.88.88"})

        assert response.status_code == 200
        entries = response.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["user"] == "griffin"
        assert entries[0]["client_ip"] == "10.88.88.88"

    def test_search_does_not_match_client_ip_for_manager(self, manager_client, db):
        _seed_entries(
            db,
            [
                {"action": "LOGIN", "user": "griffin", "client_ip": "10.88.88.88", "details": {}},
            ],
        )

        response = manager_client.get("/audit", params={"search": "10.88.88.88"})

        assert response.status_code == 200
        assert response.json()["entries"] == []


class TestAuditFilterOptions:
    def test_returns_distinct_action_user_and_job_options(self, admin_client, db):
        _seed_entries(
            db,
            [
                {"action": "JOB_CREATED", "user": "griffin", "job_id": 41, "details": {}},
                {"action": "JOB_CREATED", "user": "griffin", "job_id": 41, "details": {}},
                {"action": "JOB_COMPLETED", "user": "alba", "job_id": 52, "details": {}},
            ],
        )

        response = admin_client.get("/audit/options")

        assert response.status_code == 200
        body = response.json()
        assert "JOB_COMPLETED" in body["actions"]
        assert "JOB_CREATED" in body["actions"]
        assert body["actions"].count("JOB_CREATED") == 1
        assert "alba" in body["users"]
        assert "griffin" in body["users"]
        assert body["users"].count("griffin") == 1
        assert 41 in body["job_ids"]
        assert 52 in body["job_ids"]
        assert body["job_ids"].count(41) == 1

    def test_manager_can_access_filter_options(self, manager_client, db):
        response = manager_client.get("/audit/options")

        assert response.status_code == 200

    def test_auditor_can_access_filter_options(self, auditor_client, db):
        response = auditor_client.get("/audit/options")

        assert response.status_code == 200

    def test_processor_can_access_filter_options(self, client, db):
        response = client.get("/audit/options")

        assert response.status_code == 200

    def test_unauthenticated_cannot_access_filter_options(self, unauthenticated_client, db):
        response = unauthenticated_client.get("/audit/options")

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestAuditPagination:
    def test_limit(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(5)])
        response = admin_client.get("/audit?limit=3")
        assert response.status_code == 200
        body = response.json()
        assert len(body["entries"]) == 3
        assert body["limit"] == 3
        assert body["offset"] == 0
        assert body["total"] >= 5
        assert body["has_more"] is True

    def test_offset(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(5)])
        response_all = admin_client.get("/audit?limit=1000")
        all_ids = [d["id"] for d in _audit_entries(response_all)]

        response_offset = admin_client.get("/audit?offset=2&limit=1000")
        offset_ids = [d["id"] for d in _audit_entries(response_offset)]

        assert offset_ids == all_ids[2:]

    def test_limit_and_offset(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(10)])
        response = admin_client.get("/audit?limit=3&offset=2")
        assert response.status_code == 200
        body = response.json()
        assert len(body["entries"]) == 3
        assert body["offset"] == 2
        assert body["has_more"] is True

    def test_include_total_false_skips_exact_total_but_keeps_has_more(self, admin_client, db):
        _seed_entries(db, [{"action": f"ACT_{i}", "user": "u", "details": {}} for i in range(5)])

        response = admin_client.get("/audit?limit=2&include_total=false")

        assert response.status_code == 200
        body = response.json()
        assert len(body["entries"]) == 2
        assert body["total"] is None
        assert body["has_more"] is True


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

    def test_processor_can_access(self, client, db):
        response = client.get("/audit")
        assert response.status_code == 200

    def test_unauthenticated_cannot_access(self, unauthenticated_client, db):
        response = unauthenticated_client.get("/audit")
        assert response.status_code == 401
