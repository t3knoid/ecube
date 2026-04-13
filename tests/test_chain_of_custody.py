from datetime import datetime, timezone
from typing import cast

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest


def _seed_drive(db, *, device_identifier: str, project_id: str | None = None, state: DriveState = DriveState.IN_USE) -> UsbDrive:
    drive = UsbDrive(
        device_identifier=device_identifier,
        current_state=state,
        current_project_id=project_id,
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()
    db.refresh(drive)
    return drive


def _as_int(value) -> int:
    return cast(int, value)


def _seed_job_and_assignment(db, *, drive_id: int, project_id: str) -> ExportJob:
    job = ExportJob(
        project_id=project_id,
        evidence_number="EV-001",
        source_path="/evidence/src",
        status=JobStatus.COMPLETED,
        file_count=4,
        copied_bytes=4096,
        created_by="processor-user",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_id = _as_int(job.id)
    assignment = DriveAssignment(drive_id=drive_id, job_id=job_id)
    db.add(assignment)

    manifest = Manifest(job_id=job_id, manifest_path=f"/tmp/manifest_{job_id}.json", format="JSON")
    db.add(manifest)
    db.commit()
    return job


def _seed_audit(db, *, action: str, drive_id: int | None = None, job_id: int | None = None, project_id: str | None = None, details: dict | None = None):
    row = AuditLog(
        action=action,
        user="manager-user",
        drive_id=drive_id,
        job_id=job_id,
        project_id=project_id,
        details=details or {},
    )
    db.add(row)
    db.commit()
    return row


class TestChainOfCustodyGet:
    def test_get_requires_authentication(self, unauthenticated_client):
        response = unauthenticated_client.get("/audit/chain-of-custody", params={"project_id": "CASE-R"})
        assert response.status_code == 401

    def test_get_denies_processor_role(self, client):
        response = client.get("/audit/chain-of-custody", params={"project_id": "CASE-R"})
        assert response.status_code == 403

    def test_requires_selector(self, auditor_client):
        response = auditor_client.get("/audit/chain-of-custody")
        assert response.status_code == 422

    def test_drive_id_is_authoritative_over_drive_sn(self, auditor_client, db):
        drive_one = _seed_drive(db, device_identifier="COC-DRIVE-ONE", project_id="PRJ-1")
        drive_two = _seed_drive(db, device_identifier="COC-DRIVE-TWO", project_id="PRJ-2")
        drive_one_id = _as_int(drive_one.id)
        drive_two_id = _as_int(drive_two.id)

        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_one_id, project_id="PRJ-1", details={"drive_id": drive_one_id})
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_two_id, project_id="PRJ-2", details={"drive_id": drive_two_id})

        response = auditor_client.get(
            "/audit/chain-of-custody",
            params={"drive_id": drive_one_id, "drive_sn": drive_two.device_identifier},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["selector_mode"] == "DRIVE_ID"
        assert len(payload["reports"]) == 1
        assert payload["reports"][0]["drive_id"] == drive_one_id

    def test_drive_sn_not_found(self, auditor_client):
        response = auditor_client.get("/audit/chain-of-custody", params={"drive_sn": "missing-sn"})
        assert response.status_code == 404

    def test_project_selector_returns_per_drive_sections(self, auditor_client, db):
        drive_one = _seed_drive(db, device_identifier="COC-PROJECT-A", project_id="CASE-1")
        drive_two = _seed_drive(db, device_identifier="COC-PROJECT-B", project_id="CASE-1")
        drive_one_id = _as_int(drive_one.id)
        drive_two_id = _as_int(drive_two.id)

        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_one_id, project_id="CASE-1", details={"drive_id": drive_one_id})
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_two_id, project_id="CASE-1", details={"drive_id": drive_two_id})

        response = auditor_client.get("/audit/chain-of-custody", params={"project_id": "CASE-1"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["selector_mode"] == "PROJECT"
        assert [report["drive_id"] for report in payload["reports"]] == [drive_one_id, drive_two_id]

    def test_project_mismatch_with_drive_returns_conflict(self, auditor_client, db):
        drive = _seed_drive(db, device_identifier="COC-MISMATCH", project_id="CASE-A")
        drive_id = _as_int(drive.id)

        response = auditor_client.get(
            "/audit/chain-of-custody",
            params={"drive_id": drive_id, "project_id": "CASE-B"},
        )
        assert response.status_code == 409

    def test_drive_report_contains_lifecycle_and_manifest_summary(self, auditor_client, db):
        drive = _seed_drive(db, device_identifier="COC-LIFECYCLE", project_id="CASE-L", state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)
        job = _seed_job_and_assignment(db, drive_id=drive_id, project_id="CASE-L")
        job_id = _as_int(job.id)

        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-L", details={"drive_id": drive_id, "project_id": "CASE-L"})
        _seed_audit(db, action="JOB_CREATED", drive_id=drive_id, job_id=job_id, project_id="CASE-L", details={"project_id": "CASE-L"})
        _seed_audit(db, action="JOB_STARTED", drive_id=drive_id, job_id=job_id, project_id="CASE-L", details={"drive_id": drive_id})
        _seed_audit(db, action="JOB_COMPLETED", job_id=job_id, details={"status": "COMPLETED"})
        _seed_audit(db, action="MANIFEST_CREATED", drive_id=drive_id, job_id=job_id, details={"manifest_path": "/tmp/manifest.json"})
        _seed_audit(db, action="DRIVE_EJECT_PREPARED", drive_id=drive_id, project_id="CASE-L", details={"drive_id": drive_id})

        response = auditor_client.get("/audit/chain-of-custody", params={"drive_id": drive_id})
        assert response.status_code == 200
        report = response.json()["reports"][0]

        event_types = [event["event_type"] for event in report["chain_of_custody_events"]]
        assert "DRIVE_INITIALIZED" in event_types
        assert "JOB_CREATED" in event_types
        assert "JOB_STARTED" in event_types
        assert "JOB_COMPLETED" in event_types
        assert "MANIFEST_CREATED" in event_types
        assert "DRIVE_EJECT_PREPARED" in event_types

        assert report["manifest_summary"]
        manifest = report["manifest_summary"][0]
        assert manifest["job_id"] == job_id
        assert manifest["manifest_count"] == 1

    def test_prepare_eject_without_handoff_does_not_set_delivery_time(self, auditor_client, db):
        drive = _seed_drive(db, device_identifier="COC-NO-HANDOFF", project_id="CASE-H", state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)

        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-H", details={"drive_id": drive_id})
        _seed_audit(db, action="DRIVE_EJECT_PREPARED", drive_id=drive_id, project_id="CASE-H", details={"drive_id": drive_id})

        response = auditor_client.get("/audit/chain-of-custody", params={"drive_id": drive_id})
        assert response.status_code == 200
        report = response.json()["reports"][0]
        assert report["custody_complete"] is False
        assert report["delivery_time"] is None


class TestChainOfCustodyHandoff:
    def test_handoff_is_idempotent_by_contract_tuple(self, manager_client, db):
        drive = _seed_drive(db, device_identifier="COC-IDEMP", project_id="CASE-ID", state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)
        delivery_time = datetime(2026, 4, 10, 14, 22, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        payload = {
            "drive_id": drive_id,
            "project_id": "CASE-ID",
            "possessor": "Jane Reviewer",
            "delivery_time": delivery_time,
            "received_by": "External Counsel",
            "receipt_ref": "COC-2026-0410-07",
            "notes": "Sealed evidence bag #A771",
        }

        first = manager_client.post("/audit/chain-of-custody/handoff", json=payload)
        assert first.status_code == 200
        second = manager_client.post("/audit/chain-of-custody/handoff", json=payload)
        assert second.status_code == 200

        first_json = first.json()
        second_json = second.json()
        assert first_json["event_id"] == second_json["event_id"]

        rows = db.query(AuditLog).filter(AuditLog.action == "COC_HANDOFF_CONFIRMED", AuditLog.drive_id == drive_id).all()
        assert len(rows) == 1

    def test_handoff_project_mismatch_returns_conflict(self, manager_client, db):
        drive = _seed_drive(db, device_identifier="COC-CONFLICT", project_id="CASE-X")
        drive_id = _as_int(drive.id)

        response = manager_client.post(
            "/audit/chain-of-custody/handoff",
            json={
                "drive_id": drive_id,
                "project_id": "CASE-Y",
                "possessor": "Recipient",
                "delivery_time": datetime(2026, 4, 10, 14, 22, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        assert response.status_code == 409

    def test_handoff_requires_manager_or_admin_role(self, unauthenticated_client, client, auditor_client, db):
        drive = _seed_drive(db, device_identifier="COC-ROLE", project_id="CASE-R")
        drive_id = _as_int(drive.id)

        payload = {
            "drive_id": drive_id,
            "project_id": "CASE-R",
            "possessor": "Recipient",
            "delivery_time": datetime(2026, 4, 10, 14, 22, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        # No token — must get 401
        assert unauthenticated_client.post("/audit/chain-of-custody/handoff", json=payload).status_code == 401

        # Processor role — insufficient, must get 403
        assert client.post("/audit/chain-of-custody/handoff", json=payload).status_code == 403

        # Auditor is read-only — write must be denied
        assert auditor_client.post("/audit/chain-of-custody/handoff", json=payload).status_code == 403

    def test_handoff_rejects_non_utc_delivery_time(self, manager_client, db):
        drive = _seed_drive(db, device_identifier="COC-TZ", project_id="CASE-TZ")
        drive_id = _as_int(drive.id)

        response = manager_client.post(
            "/audit/chain-of-custody/handoff",
            json={
                "drive_id": drive_id,
                "project_id": "CASE-TZ",
                "possessor": "Recipient",
                "delivery_time": "2026-04-10T14:22:31+02:00",
            },
        )
        assert response.status_code == 422

    def test_handoff_transitions_drive_to_archived(self, manager_client, db):
        drive = _seed_drive(db, device_identifier="COC-ARCHIVE", project_id="CASE-ARCHIVE")
        drive_id = _as_int(drive.id)

        # Verify drive is IN_USE before handoff
        drive_before = db.get(UsbDrive, drive_id)
        assert drive_before.current_state == DriveState.IN_USE

        response = manager_client.post(
            "/audit/chain-of-custody/handoff",
            json={
                "drive_id": drive_id,
                "project_id": "CASE-ARCHIVE",
                "possessor": "Recipient",
                "delivery_time": datetime(2026, 4, 10, 14, 22, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        assert response.status_code == 200

        # Verify drive is ARCHIVED after handoff
        drive_after = db.get(UsbDrive, drive_id)
        assert drive_after.current_state == DriveState.ARCHIVED

    def test_archived_drives_excluded_from_coc_by_drive_id(self, manager_client, db):
        drive = _seed_drive(db, device_identifier="COC-ARCHIVED-EXCLUDE", project_id="CASE-ARCHIVED-EXC")
        drive_id = _as_int(drive.id)

        # Archive the drive
        drive.current_state = DriveState.ARCHIVED
        db.commit()

        # Try to retrieve CoC for archived drive
        response = manager_client.get(
            "/audit/chain-of-custody",
            params={"drive_id": drive_id}
        )
        assert response.status_code == 410

    def test_archived_drives_excluded_from_coc_by_project_id(self, manager_client, db):
        # Create two drives in same project: one active, one archived
        active_drive = _seed_drive(db, device_identifier="COC-ACTIVE-2", project_id="CASE-PROJECT-2")
        archived_drive = _seed_drive(db, device_identifier="COC-ARCHIVED-2", project_id="CASE-PROJECT-2")

        # Archive one drive
        archived_drive.current_state = DriveState.ARCHIVED
        db.commit()

        # Retrieve CoC by project_id
        response = manager_client.get(
            "/audit/chain-of-custody",
            params={"project_id": "CASE-PROJECT-2"}
        )
        assert response.status_code == 200
        data = response.json()

        # Verify only active drive is included
        assert len(data["reports"]) == 1
        report = data["reports"][0]
        assert report["drive_id"] == _as_int(active_drive.id)
        assert _as_int(archived_drive.id) not in [r["drive_id"] for r in data["reports"]]

    def test_archived_drive_excluded_from_coc_by_drive_sn(self, manager_client, db):
        drive = _seed_drive(db, device_identifier="COC-ARCHIVED-SN", project_id="CASE-ARCHIVED-SN")
        drive.current_state = DriveState.ARCHIVED
        db.commit()

        response = manager_client.get(
            "/audit/chain-of-custody",
            params={"drive_sn": "COC-ARCHIVED-SN"},
        )
        assert response.status_code == 410
