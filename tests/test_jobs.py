from unittest.mock import patch

from app.models.hardware import UsbDrive, DriveState
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus
from app.models.audit import AuditLog


def test_create_job(client, db):
    drive = UsbDrive(
        device_identifier="USB-CREATE-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/data/evidence",
            "thread_count": 4,
            "created_by": "investigator",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "PROJ-001"
    assert data["status"] == "PENDING"


def test_get_job(client, db):
    db.add(UsbDrive(
        device_identifier="USB-GET-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    ))
    db.commit()

    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/data/evidence",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_not_found(client, db):
    response = client.get("/jobs/999")
    assert response.status_code == 404


def test_start_job(client, db):
    db.add(UsbDrive(
        device_identifier="USB-START-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    ))
    db.commit()

    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    with patch("app.services.copy_engine.run_copy_job") as mock_copy:
        mock_copy.return_value = None
        response = client.post(f"/jobs/{job_id}/start", json={"thread_count": 2})
    assert response.status_code == 200


def test_start_already_running_job(client, db):
    from app.models.jobs import ExportJob, JobStatus

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path="/data",
        status=JobStatus.RUNNING,
    )
    db.add(job)
    db.commit()

    response = client.post(f"/jobs/{job.id}/start", json={})
    assert response.status_code == 409


def test_create_job_conflict_when_drive_has_different_project(client, db):
    drive = UsbDrive(
        device_identifier="USB-PRJ-CONFLICT",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-AAA",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-BBB",
            "evidence_number": "EV-009",
            "source_path": "/data/evidence",
            "drive_id": drive.id,
        },
    )

    assert response.status_code == 403


def test_create_job_conflict_when_drive_already_in_use(client, db):
    drive = UsbDrive(
        device_identifier="USB-IN-USE",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-010",
            "source_path": "/data/evidence",
            "drive_id": drive.id,
        },
    )

    assert response.status_code == 409


def test_verify_job(client, db):
    db.add(UsbDrive(
        device_identifier="USB-VERIFY-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    ))
    db.commit()

    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp",
        },
    )
    assert create_response.status_code == 200
    job_id = create_response.json()["id"]

    with patch("app.services.copy_engine.run_verify_job") as mock_verify:
        mock_verify.return_value = None
        response = client.post(f"/jobs/{job_id}/verify")
    assert response.status_code == 200
    assert response.json()["status"] == "VERIFYING"


# ---------------------------------------------------------------------------
# Issue #105 — enriched job response fields
# ---------------------------------------------------------------------------


def test_job_response_includes_timestamps(client, db):
    """created_at, started_at, completed_at should be present in the response."""
    db.add(UsbDrive(
        device_identifier="USB-TS-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-TS",
    ))
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-TS",
            "evidence_number": "EV-TS",
            "source_path": "/data",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "created_at" in data
    assert data["created_at"] is not None
    assert data["started_at"] is None
    assert data["completed_at"] is None


def test_job_response_includes_started_by(client, db):
    """started_by should be null on create and populated after start."""
    db.add(UsbDrive(
        device_identifier="USB-SB-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-SB",
    ))
    db.commit()

    create_resp = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-SB",
            "evidence_number": "EV-SB",
            "source_path": "/tmp",
        },
    )
    assert create_resp.status_code == 200
    job_id = create_resp.json()["id"]
    assert create_resp.json()["started_by"] is None

    with patch("app.services.copy_engine.run_copy_job"):
        start_resp = client.post(f"/jobs/{job_id}/start", json={})
    assert start_resp.status_code == 200
    assert start_resp.json()["started_by"] == "test-user"
    assert start_resp.json()["started_at"] is not None


def test_completed_job_with_all_fields(client, db):
    """A completed job with files and a drive should include all enriched fields."""
    drive = UsbDrive(
        device_identifier="USB-ENRICH-001",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-ENRICH",
        capacity_bytes=64_000_000_000,
        filesystem_type="exfat",
    )
    db.add(drive)
    db.flush()

    job = ExportJob(
        project_id="PROJ-ENRICH",
        evidence_number="EV-ENRICH",
        source_path="/data/evidence",
        target_mount_path="/media/usb0",
        status=JobStatus.COMPLETED,
        total_bytes=1000,
        copied_bytes=1000,
        file_count=3,
        created_by="creator",
        started_by="starter",
    )
    db.add(job)
    db.flush()

    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.add(ExportFile(job_id=job.id, relative_path="a.txt", status=FileStatus.DONE, size_bytes=400))
    db.add(ExportFile(job_id=job.id, relative_path="b.txt", status=FileStatus.DONE, size_bytes=600))
    db.add(ExportFile(job_id=job.id, relative_path="c.txt", status=FileStatus.DONE, size_bytes=0))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()

    # Timestamps
    assert data["created_at"] is not None

    # User fields
    assert data["created_by"] == "creator"
    assert data["started_by"] == "starter"

    # File counts
    assert data["files_succeeded"] == 3
    assert data["files_failed"] == 0

    # Error summary should be null on success
    assert data["error_summary"] is None

    # Drive info
    assert data["drive"] is not None
    assert data["drive"]["id"] == drive.id
    assert data["drive"]["device_identifier"] == "USB-ENRICH-001"
    assert data["drive"]["capacity_bytes"] == 64_000_000_000
    assert data["drive"]["filesystem_type"] == "exfat"
    assert data["drive"]["current_state"] == "IN_USE"
    assert data["drive"]["current_project_id"] == "PROJ-ENRICH"


def test_failed_job_with_error_summary(client, db):
    """A failed job should include files_failed count and error_summary."""
    job = ExportJob(
        project_id="PROJ-FAIL",
        evidence_number="EV-FAIL",
        source_path="/data",
        status=JobStatus.FAILED,
        total_bytes=1000,
        copied_bytes=500,
        file_count=4,
    )
    db.add(job)
    db.flush()

    db.add(ExportFile(job_id=job.id, relative_path="ok1.txt", status=FileStatus.DONE, size_bytes=200))
    db.add(ExportFile(job_id=job.id, relative_path="ok2.txt", status=FileStatus.DONE, size_bytes=300))
    db.add(ExportFile(
        job_id=job.id, relative_path="report.zip", status=FileStatus.ERROR,
        error_message="disk full",
    ))
    db.add(ExportFile(
        job_id=job.id, relative_path="archive.tar.gz", status=FileStatus.ERROR,
        error_message="permission denied",
    ))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["files_succeeded"] == 2
    assert data["files_failed"] == 2
    assert data["error_summary"] is not None
    assert "2 files failed" in data["error_summary"]
    assert "disk full" in data["error_summary"]
    assert "permission denied" in data["error_summary"]


def test_job_with_no_drive_assigned(client, db):
    """A job with no drive assignment should have drive=null."""
    job = ExportJob(
        project_id="PROJ-NODRIVE",
        evidence_number="EV-NODRIVE",
        source_path="/data",
        status=JobStatus.PENDING,
        total_bytes=0,
        copied_bytes=0,
        file_count=0,
    )
    db.add(job)
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["drive"] is None
    assert data["files_succeeded"] == 0
    assert data["files_failed"] == 0
    assert data["error_summary"] is None


def test_failed_job_error_summary_without_messages(client, db):
    """Error summary should still be set when error files lack error_message."""
    job = ExportJob(
        project_id="PROJ-NOMSG",
        evidence_number="EV-NOMSG",
        source_path="/data",
        status=JobStatus.FAILED,
        total_bytes=500,
        copied_bytes=0,
        file_count=2,
    )
    db.add(job)
    db.flush()

    db.add(ExportFile(job_id=job.id, relative_path="a.bin", status=FileStatus.ERROR))
    db.add(ExportFile(job_id=job.id, relative_path="b.bin", status=FileStatus.ERROR, error_message=None))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["files_failed"] == 2
    assert data["error_summary"] is not None
    assert "2 files failed" in data["error_summary"]


def test_restart_failed_job_resets_completed_at(client, db):
    """Restarting a FAILED job should reset completed_at to null."""
    from datetime import datetime, timezone

    job = ExportJob(
        project_id="PROJ-RESTART",
        evidence_number="EV-RESTART",
        source_path="/data",
        status=JobStatus.FAILED,
        total_bytes=100,
        copied_bytes=50,
        file_count=1,
        completed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(job)
    db.commit()

    with patch("app.services.copy_engine.run_copy_job"):
        response = client.post(f"/jobs/{job.id}/start", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "RUNNING"
    assert data["completed_at"] is None
    assert data["started_at"] is not None


# ---------------------------------------------------------------------------
# Issue #102 — Auto-assign drive when drive_id is omitted
# ---------------------------------------------------------------------------


def test_auto_assign_single_project_bound_drive(client, db):
    """When exactly one AVAILABLE drive is bound to the project, auto-select it."""
    drive = UsbDrive(
        device_identifier="USB-AUTO-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-AUTO",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-AUTO",
            "evidence_number": "EV-AUTO-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["drive"] is not None
    assert data["drive"]["id"] == drive.id
    assert data["drive"]["current_state"] == "IN_USE"

    # Verify audit log
    audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_AUTO_ASSIGNED").first()
    assert audit is not None
    assert audit.details["drive_id"] == drive.id
    assert audit.details["selection"] == "project_bound"


def test_auto_assign_unbound_fallback(client, db):
    """When no project-bound drives exist, fall back to an unbound AVAILABLE drive."""
    drive = UsbDrive(
        device_identifier="USB-UNBOUND-001",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-NEW",
            "evidence_number": "EV-NEW-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["drive"] is not None
    assert data["drive"]["id"] == drive.id
    assert data["drive"]["current_state"] == "IN_USE"
    assert data["drive"]["current_project_id"] == "PROJ-NEW"

    # Verify DRIVE_PROJECT_BOUND audit entry
    bound_audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_PROJECT_BOUND").first()
    assert bound_audit is not None
    assert bound_audit.details["drive_id"] == drive.id
    assert bound_audit.details["project_id"] == "PROJ-NEW"

    # Verify DRIVE_AUTO_ASSIGNED audit entry
    assign_audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_AUTO_ASSIGNED").first()
    assert assign_audit is not None
    assert assign_audit.details["selection"] == "unbound_fallback"


def test_auto_assign_409_multiple_project_bound_drives(client, db):
    """When multiple AVAILABLE drives are bound to the project, return 409."""
    for i in range(2):
        db.add(UsbDrive(
            device_identifier=f"USB-MULTI-{i}",
            current_state=DriveState.AVAILABLE,
            current_project_id="PROJ-MULTI",
        ))
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-MULTI",
            "evidence_number": "EV-MULTI-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 409
    assert "Multiple drives assigned to project PROJ-MULTI" in response.json()["message"]


def test_auto_assign_409_no_drives_available(client, db):
    """When no AVAILABLE drives exist at all, return 409."""
    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-NONE",
            "evidence_number": "EV-NONE-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 409
    assert "No available drive for project PROJ-NONE" in response.json()["message"]


def test_auto_assign_skips_in_use_drives(client, db):
    """IN_USE drives should not be considered for auto-assignment."""
    db.add(UsbDrive(
        device_identifier="USB-INUSE-AUTO",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-SKIP",
    ))
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-SKIP",
            "evidence_number": "EV-SKIP-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 409
    assert "No available drive" in response.json()["message"]


def test_explicit_drive_id_still_works(client, db):
    """Providing drive_id explicitly should bypass auto-assignment."""
    drive = UsbDrive(
        device_identifier="USB-EXPLICIT-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-EXPLICIT",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-EXPLICIT",
            "evidence_number": "EV-EXPLICIT-001",
            "source_path": "/data/evidence",
            "drive_id": drive.id,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["drive"]["id"] == drive.id
    assert data["drive"]["current_state"] == "IN_USE"


def test_auto_assign_prefers_project_bound_over_unbound(client, db):
    """A project-bound AVAILABLE drive should be chosen over an unbound one."""
    bound = UsbDrive(
        device_identifier="USB-BOUND-PREF",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-PREF",
    )
    unbound = UsbDrive(
        device_identifier="USB-UNBOUND-PREF",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
    )
    db.add_all([bound, unbound])
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-PREF",
            "evidence_number": "EV-PREF-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["drive"]["id"] == bound.id


def test_auto_assign_409_no_unbound_when_no_project_match(client, db):
    """When no project-bound drives and no unbound drives exist, return 409."""
    # Only drives with different projects exist
    db.add(UsbDrive(
        device_identifier="USB-OTHER-PROJ",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-OTHER",
    ))
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-WANTED",
            "evidence_number": "EV-WANT-001",
            "source_path": "/data/evidence",
        },
    )
    assert response.status_code == 409
    assert "No available drive" in response.json()["message"]
