from datetime import datetime, timezone
from typing import cast

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest


def _seed_drive(
    db,
    *,
    device_identifier: str,
    project_id: str | None = None,
    state: DriveState = DriveState.IN_USE,
    manufacturer: str | None = None,
    product_name: str | None = None,
) -> UsbDrive:
    drive = UsbDrive(
        device_identifier=device_identifier,
        manufacturer=manufacturer,
        product_name=product_name,
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
    assignment = DriveAssignment(drive_id=drive_id, job_id=job_id, file_count=4, copied_bytes=4096)
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

    def test_drive_id_unbound_without_project_id_returns_422(self, auditor_client, db):
        """A drive with no current_project_id (e.g. freshly formatted) must require
        an explicit project_id for DRIVE_ID selectors to prevent cross-lifecycle bleed."""
        drive = _seed_drive(db, device_identifier="COC-UNBOUND-ID", project_id=None, state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)

        response = auditor_client.get("/audit/chain-of-custody", params={"drive_id": drive_id})
        assert response.status_code == 422
        assert "project_id" in response.json()["message"].lower()

    def test_drive_sn_unbound_without_project_id_returns_422(self, auditor_client, db):
        """Same guard via DRIVE_SN selector path."""
        drive = _seed_drive(db, device_identifier="COC-UNBOUND-SN", project_id=None, state=DriveState.AVAILABLE)

        response = auditor_client.get("/audit/chain-of-custody", params={"drive_sn": drive.device_identifier})
        assert response.status_code == 422
        assert "project_id" in response.json()["message"].lower()

    def test_drive_id_unbound_with_explicit_project_id_scopes_to_historical_lifecycle(self, auditor_client, db):
        """An unbound drive with an explicit project_id must return events scoped to
        that project only — covering the post-format historical lookup use case."""
        # Drive has been reformatted (current_project_id cleared to None).
        drive = _seed_drive(db, device_identifier="COC-UNBOUND-HIST", project_id=None, state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)

        # Seed prior-lifecycle events (CASE-OLD) and an unrelated project (CASE-OTHER).
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-OLD")
        _seed_audit(db, action="DRIVE_EJECT_PREPARED", drive_id=drive_id, project_id="CASE-OLD")
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-OTHER")

        response = auditor_client.get(
            "/audit/chain-of-custody",
            params={"drive_id": drive_id, "project_id": "CASE-OLD"},
        )
        assert response.status_code == 200
        report = response.json()["reports"][0]
        assert report["project_id"] == "CASE-OLD"
        event_types = [e["event_type"] for e in report["chain_of_custody_events"]]
        assert "DRIVE_INITIALIZED" in event_types
        assert "DRIVE_EJECT_PREPARED" in event_types
        # Events tagged to CASE-OTHER must not appear.
        project_ids_in_events = {
            e["details"].get("project_id") for e in report["chain_of_custody_events"] if e["details"]
        }
        assert "CASE-OTHER" not in project_ids_in_events

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

    def test_project_selector_normalizes_case_and_whitespace(self, auditor_client, db):
        drive = _seed_drive(db, device_identifier="COC-PROJECT-NORM", project_id="CASE-1")
        drive_id = _as_int(drive.id)

        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-1", details={"drive_id": drive_id})

        response = auditor_client.get(
            "/audit/chain-of-custody",
            params={"project_id": " case-1 "},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["selector_mode"] == "PROJECT"
        assert payload["project_id"] == "CASE-1"
        assert [report["drive_id"] for report in payload["reports"]] == [drive_id]

    def test_project_mismatch_with_drive_returns_conflict(self, auditor_client, db):
        drive = _seed_drive(db, device_identifier="COC-MISMATCH", project_id="CASE-A")
        drive_id = _as_int(drive.id)

        response = auditor_client.get(
            "/audit/chain-of-custody",
            params={"drive_id": drive_id, "project_id": "CASE-B"},
        )
        assert response.status_code == 409

    def test_drive_report_contains_lifecycle_and_manifest_summary(self, auditor_client, db):
        drive = _seed_drive(
            db,
            device_identifier="COC-LIFECYCLE",
            project_id="CASE-L",
            state=DriveState.AVAILABLE,
            manufacturer="SanDisk",
            product_name="Extreme Pro",
        )
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

        assert report["drive_manufacturer"] == "SanDisk"
        assert report["drive_model"] == "Extreme Pro"

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
        assert manifest["total_files"] == 4
        assert manifest["total_bytes"] == 4096

    def test_project_report_uses_drive_assignment_totals_for_multi_drive_jobs(self, auditor_client, db):
        drive_one = _seed_drive(db, device_identifier="COC-MULTI-ONE", project_id="CASE-MULTI", state=DriveState.AVAILABLE)
        drive_two = _seed_drive(db, device_identifier="COC-MULTI-TWO", project_id="CASE-MULTI", state=DriveState.AVAILABLE)
        drive_one_id = _as_int(drive_one.id)
        drive_two_id = _as_int(drive_two.id)

        job = ExportJob(
            project_id="CASE-MULTI",
            evidence_number="EV-002",
            source_path="/evidence/src",
            status=JobStatus.COMPLETED,
            file_count=10,
            copied_bytes=10_000,
            created_by="processor-user",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = _as_int(job.id)

        db.add_all(
            [
                DriveAssignment(drive_id=drive_one_id, job_id=job_id, file_count=4, copied_bytes=4_000),
                DriveAssignment(drive_id=drive_two_id, job_id=job_id, file_count=6, copied_bytes=6_000),
                Manifest(job_id=job_id, manifest_path=f"/tmp/manifest_{job_id}.json", format="JSON"),
            ]
        )
        db.commit()

        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_one_id, project_id="CASE-MULTI", details={"drive_id": drive_one_id})
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_two_id, project_id="CASE-MULTI", details={"drive_id": drive_two_id})
        _seed_audit(db, action="JOB_CREATED", drive_id=drive_one_id, job_id=job_id, project_id="CASE-MULTI", details={"project_id": "CASE-MULTI"})
        _seed_audit(db, action="JOB_CREATED", drive_id=drive_two_id, job_id=job_id, project_id="CASE-MULTI", details={"project_id": "CASE-MULTI"})
        _seed_audit(db, action="JOB_COMPLETED", job_id=job_id, project_id="CASE-MULTI", details={"status": "COMPLETED"})

        response = auditor_client.get("/audit/chain-of-custody", params={"project_id": "CASE-MULTI"})
        assert response.status_code == 200

        payload = response.json()
        reports = {report["drive_id"]: report for report in payload["reports"]}
        assert reports[drive_one_id]["manifest_summary"][0]["total_files"] == 4
        assert reports[drive_one_id]["manifest_summary"][0]["total_bytes"] == 4_000
        assert reports[drive_two_id]["manifest_summary"][0]["total_files"] == 6
        assert reports[drive_two_id]["manifest_summary"][0]["total_bytes"] == 6_000

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

    def test_drive_report_excludes_prior_project_events_after_reformat(self, auditor_client, db):
        """After a drive is reformatted and reassigned, the CoC report for the
        new project must not include events or jobs from the prior project."""
        # Simulate a drive that was used for CASE-PRIOR, ejected, reformatted,
        # then re-initialized for CASE-CURRENT.  We model this purely via DB
        # state: the drive's current_project_id is CASE-CURRENT.
        drive = _seed_drive(db, device_identifier="COC-REFORMAT", project_id="CASE-CURRENT", state=DriveState.IN_USE)
        drive_id = _as_int(drive.id)

        # Prior-lifecycle events (different project).
        prior_job = _seed_job_and_assignment(db, drive_id=drive_id, project_id="CASE-PRIOR")
        prior_job_id = _as_int(prior_job.id)
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-PRIOR")
        _seed_audit(db, action="JOB_CREATED", drive_id=drive_id, job_id=prior_job_id, project_id="CASE-PRIOR")
        _seed_audit(db, action="JOB_COMPLETED", job_id=prior_job_id, project_id="CASE-PRIOR")
        _seed_audit(db, action="DRIVE_EJECT_PREPARED", drive_id=drive_id, project_id="CASE-PRIOR")

        # Current-lifecycle events.
        current_job = _seed_job_and_assignment(db, drive_id=drive_id, project_id="CASE-CURRENT")
        current_job_id = _as_int(current_job.id)
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-CURRENT")
        _seed_audit(db, action="JOB_CREATED", drive_id=drive_id, job_id=current_job_id, project_id="CASE-CURRENT")
        _seed_audit(db, action="JOB_COMPLETED", job_id=current_job_id, project_id="CASE-CURRENT")

        response = auditor_client.get("/audit/chain-of-custody", params={"drive_id": drive_id})
        assert response.status_code == 200
        report = response.json()["reports"][0]

        event_types = [e["event_type"] for e in report["chain_of_custody_events"]]
        job_ids_in_report = [m["job_id"] for m in report["manifest_summary"]]

        # Current-lifecycle events must appear.
        assert event_types.count("DRIVE_INITIALIZED") == 1
        assert event_types.count("JOB_CREATED") == 1
        assert current_job_id in job_ids_in_report

        # Prior-lifecycle job must be absent from manifest summary.
        assert prior_job_id not in job_ids_in_report

        # The lone DRIVE_EJECT_PREPARED was for the prior project and must be excluded.
        assert "DRIVE_EJECT_PREPARED" not in event_types

    def test_project_selector_includes_reassigned_drive_with_historical_events(self, auditor_client, db):
        """A drive reformatted and reassigned away from a project must still appear
        in that project's PROJECT-scoped CoC report (it historically participated),
        but only its events tagged to that project are shown."""
        # Drive was used for CASE-HIST, then reformatted and rebound to CASE-NEW.
        drive = _seed_drive(db, device_identifier="COC-HIST", project_id="CASE-NEW", state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)

        # Events from the CASE-HIST lifecycle.
        hist_job = _seed_job_and_assignment(db, drive_id=drive_id, project_id="CASE-HIST")
        hist_job_id = _as_int(hist_job.id)
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=drive_id, project_id="CASE-HIST")
        _seed_audit(db, action="JOB_CREATED", drive_id=drive_id, job_id=hist_job_id, project_id="CASE-HIST")
        _seed_audit(db, action="JOB_COMPLETED", job_id=hist_job_id, project_id="CASE-HIST")

        # The PROJECT selector for CASE-HIST should surface this drive even though
        # drive.current_project_id is now CASE-NEW.
        response = auditor_client.get("/audit/chain-of-custody", params={"project_id": "CASE-HIST"})
        assert response.status_code == 200
        payload = response.json()

        drive_ids_in_report = [r["drive_id"] for r in payload["reports"]]
        assert drive_id in drive_ids_in_report

        # The report for this drive must be scoped to CASE-HIST events only.
        report = next(r for r in payload["reports"] if r["drive_id"] == drive_id)
        assert report["project_id"] == "CASE-HIST"
        event_types = [e["event_type"] for e in report["chain_of_custody_events"]]
        assert "DRIVE_INITIALIZED" in event_types
        assert hist_job_id in [m["job_id"] for m in report["manifest_summary"]]


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

    def test_idempotency_does_not_match_across_projects(self, manager_client, db):
        """A prior-project handoff record must not satisfy the idempotency check
        for a new handoff submission scoped to a different project on the same drive."""
        # The same drive was used for two different projects sequentially.
        # We seed a COC_HANDOFF_CONFIRMED row manually for CASE-OLD to represent
        # a prior-lifecycle handoff that happens to share the same contract tuple.
        drive = _seed_drive(db, device_identifier="COC-IDEMP-PROJ", project_id="CASE-NEW", state=DriveState.IN_USE)
        drive_id = _as_int(drive.id)
        delivery_time_str = datetime(2026, 4, 10, 14, 22, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        # Inject a prior-project handoff record for CASE-OLD with the same
        # possessor / delivery_time / receipt_ref that the new request will use.
        _seed_audit(
            db,
            action="COC_HANDOFF_CONFIRMED",
            drive_id=drive_id,
            project_id="CASE-OLD",
            details={
                "drive_id": drive_id,
                "project_id": "CASE-OLD",
                "possessor": "Officer Smith",
                "delivery_time": delivery_time_str,
                "receipt_ref": "RCP-OLD-001",
            },
        )

        payload = {
            "drive_id": drive_id,
            "project_id": "CASE-NEW",
            "possessor": "Officer Smith",
            "delivery_time": delivery_time_str,
            "receipt_ref": "RCP-OLD-001",
        }
        response = manager_client.post("/audit/chain-of-custody/handoff", json=payload)
        assert response.status_code == 200

        # Must create a NEW audit event for CASE-NEW, not reuse the CASE-OLD one.
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.action == "COC_HANDOFF_CONFIRMED", AuditLog.drive_id == drive_id)
            .all()
        )
        assert len(rows) == 2
        new_row = next(r for r in rows if r.project_id == "CASE-NEW")
        assert new_row is not None
        # Response project_id must reflect CASE-NEW, not the stale CASE-OLD record.
        assert response.json()["project_id"] == "CASE-NEW"

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

    def test_handoff_rejected_when_drive_has_no_project_binding(self, manager_client, db):
        """A handoff for a drive with no current_project_id and no caller-supplied
        project_id must be rejected with 422; without a project context the
        handoff cannot be scoped and idempotency cannot be safely enforced."""
        drive = _seed_drive(db, device_identifier="COC-UNBOUND", project_id=None, state=DriveState.AVAILABLE)
        drive_id = _as_int(drive.id)

        response = manager_client.post(
            "/audit/chain-of-custody/handoff",
            json={
                "drive_id": drive_id,
                "possessor": "Officer Jones",
                "delivery_time": datetime(2026, 4, 10, 14, 22, 31, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        assert response.status_code == 422

    def test_project_selector_excludes_denial_events(self, manager_client, db):
        """Denial audit events (e.g. PROJECT_ISOLATION_VIOLATION) record the
        drive_id of a drive that was *denied* access.  These must NOT cause the
        drive to appear in a PROJECT-scoped CoC report."""
        # Drive actually participating in project P-REAL
        real_drive = _seed_drive(db, device_identifier="COC-REAL", project_id="P-REAL")
        real_drive_id = _as_int(real_drive.id)
        _seed_job_and_assignment(db, drive_id=real_drive_id, project_id="P-REAL")
        _seed_audit(db, action="DRIVE_INITIALIZED", drive_id=real_drive_id, project_id="P-REAL")

        # A totally different drive that got a denial event logged against P-REAL
        denied_drive = _seed_drive(db, device_identifier="COC-DENIED", project_id="P-OTHER")
        denied_drive_id = _as_int(denied_drive.id)
        _seed_audit(
            db,
            action="PROJECT_ISOLATION_VIOLATION",
            drive_id=denied_drive_id,
            project_id="P-REAL",
            details={"reason": "drive bound to P-OTHER"},
        )

        response = manager_client.get(
            "/audit/chain-of-custody",
            params={"project_id": "P-REAL"},
        )
        assert response.status_code == 200
        data = response.json()
        returned_ids = {r["drive_id"] for r in data["reports"]}
        assert real_drive_id in returned_ids
        assert denied_drive_id not in returned_ids, (
            "Denial events must not pull unrelated drives into a project CoC report"
        )
