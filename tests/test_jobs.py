from unittest.mock import patch

from app.models.hardware import UsbDrive, DriveState
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus
from app.models.audit import AuditLog


def test_create_job(client, db):
    drive = UsbDrive(
        device_identifier="USB-CREATE-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
        mount_path="/mnt/ecube/create-001",
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
    assert data["target_mount_path"] == "/mnt/ecube/create-001"


def test_create_job_conflict_when_assigned_drive_not_mounted(client, db):
    drive = UsbDrive(
        device_identifier="USB-NOT-MOUNTED-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
        mount_path=None,
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-NOMOUNT",
            "source_path": "/data/evidence",
            "drive_id": drive.id,
        },
    )

    assert response.status_code == 409
    assert "not mounted" in response.json()["message"].lower()


def test_create_job_explicit_unbound_drive_writes_project_bound_audit(client, db):
    drive = UsbDrive(
        device_identifier="USB-EXPLICIT-UNBOUND-001",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
        mount_path="/mnt/ecube/explicit-unbound-001",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-BOUND",
            "evidence_number": "EV-BOUND-001",
            "source_path": "/data/evidence",
            "drive_id": drive.id,
        },
    )

    assert response.status_code == 200
    audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_PROJECT_BOUND").first()
    assert audit is not None
    assert audit.details["drive_id"] == drive.id
    assert audit.details["project_id"] == "PROJ-BOUND"


def test_get_job(client, db):
    db.add(UsbDrive(
        device_identifier="USB-GET-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
        mount_path="/mnt/ecube/get-001",
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


def test_get_job_files_processor_allowed(client, db):
    job = ExportJob(
        project_id="PROJ-FILES-001",
        evidence_number="EV-FILES-001",
        source_path="/data/files",
        status=JobStatus.RUNNING,
    )
    db.add(job)
    db.flush()
    db.add(ExportFile(job_id=job.id, relative_path="doc/a.txt", status=FileStatus.DONE, checksum="sha256:a"))
    db.add(ExportFile(job_id=job.id, relative_path="doc/b.txt", status=FileStatus.ERROR, checksum=None))
    db.commit()

    response = client.get(f"/jobs/{job.id}/files")

    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.id
    assert len(data["files"]) == 2
    assert data["files"][0]["relative_path"] == "doc/a.txt"
    assert data["files"][0]["status"] == "DONE"
    assert data["files"][0]["checksum"] == "sha256:a"


def test_get_job_files_manager_allowed(manager_client, db):
    job = ExportJob(
        project_id="PROJ-FILES-002",
        evidence_number="EV-FILES-002",
        source_path="/data/files-2",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.flush()
    db.add(ExportFile(job_id=job.id, relative_path="set/file.bin", status=FileStatus.PENDING, checksum=None))
    db.commit()

    response = manager_client.get(f"/jobs/{job.id}/files")

    assert response.status_code == 200
    assert response.json()["job_id"] == job.id


def test_get_job_files_not_found(client, db):
    response = client.get("/jobs/999/files")
    assert response.status_code == 404


def test_get_job_files_requires_auth(unauthenticated_client, db):
    job = ExportJob(
        project_id="PROJ-FILES-003",
        evidence_number="EV-FILES-003",
        source_path="/data/files-3",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    response = unauthenticated_client.get(f"/jobs/{job.id}/files")
    assert response.status_code == 401


def test_start_job(client, db):
    db.add(UsbDrive(
        device_identifier="USB-START-001",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
        mount_path="/mnt/ecube/start-001",
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


def test_create_job_allows_explicit_mounted_in_use_drive(client, db):
    drive = UsbDrive(
        device_identifier="USB-IN-USE-MOUNTED",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        mount_path="/mnt/ecube/in-use-mounted",
    )
    db.add(drive)
    db.commit()

    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-010A",
            "source_path": "/data/evidence",
            "drive_id": drive.id,
        },
    )

    assert response.status_code == 200
    assert response.json()["target_mount_path"] == "/mnt/ecube/in-use-mounted"


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
        mount_path="/mnt/ecube/verify-001",
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
        mount_path="/mnt/ecube/ts-001",
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
        mount_path="/mnt/ecube/sb-001",
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
        mount_path="/mnt/ecube/auto-001",
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
        mount_path="/mnt/ecube/unbound-001",
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
    """When no usable drive exists (none bound to project, none unbound), return 409."""
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
        mount_path="/mnt/ecube/explicit-001",
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
        mount_path="/mnt/ecube/bound-pref",
    )
    unbound = UsbDrive(
        device_identifier="USB-UNBOUND-PREF",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
        mount_path="/mnt/ecube/unbound-pref",
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
        mount_path="/mnt/ecube/other-proj",
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


# ---------------------------------------------------------------------------
# GET /jobs — list endpoint
# ---------------------------------------------------------------------------


def test_list_jobs_returns_empty_when_no_jobs(client, db):
    """GET /jobs should return an empty list when no jobs exist."""
    response = client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_jobs_returns_created_jobs(client, db):
    """GET /jobs should return jobs that have been created."""
    for i in range(3):
        db.add(ExportJob(
            project_id=f"PROJ-LIST-{i}",
            evidence_number=f"EV-LIST-{i}",
            source_path="/data",
            status=JobStatus.PENDING,
        ))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


def test_list_jobs_default_limit(client, db):
    """Default limit is 200 — creating fewer should return all."""
    for i in range(5):
        db.add(ExportJob(
            project_id="PROJ-LIM",
            evidence_number=f"EV-LIM-{i}",
            source_path="/data",
            status=JobStatus.PENDING,
        ))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    assert len(response.json()) == 5


def test_list_jobs_custom_limit(client, db):
    """GET /jobs?limit=2 should return at most 2 jobs."""
    for i in range(5):
        db.add(ExportJob(
            project_id="PROJ-CL",
            evidence_number=f"EV-CL-{i}",
            source_path="/data",
            status=JobStatus.PENDING,
        ))
    db.commit()

    response = client.get("/jobs", params={"limit": 2})
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_jobs_limit_below_minimum_returns_422(client, db):
    """limit=0 violates ge=1 constraint and should return 422."""
    response = client.get("/jobs", params={"limit": 0})
    assert response.status_code == 422


def test_list_jobs_limit_above_maximum_returns_422(client, db):
    """limit=1001 violates le=1000 constraint and should return 422."""
    response = client.get("/jobs", params={"limit": 1001})
    assert response.status_code == 422


def test_list_jobs_includes_files_succeeded_and_failed(client, db):
    """Bulk enrichment should populate files_succeeded and files_failed."""
    job = ExportJob(
        project_id="PROJ-BULK-FC",
        evidence_number="EV-BULK-FC",
        source_path="/data",
        status=JobStatus.COMPLETED,
    )
    db.add(job)
    db.flush()
    db.add(ExportFile(job_id=job.id, relative_path="a.txt", status=FileStatus.DONE))
    db.add(ExportFile(job_id=job.id, relative_path="b.txt", status=FileStatus.DONE))
    db.add(ExportFile(job_id=job.id, relative_path="c.txt", status=FileStatus.ERROR, error_message="fail"))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["files_succeeded"] == 2
    assert data[0]["files_failed"] == 1


def test_list_jobs_includes_error_summary_for_failed_jobs(client, db):
    """Bulk enrichment should produce error_summary when files have errors."""
    job = ExportJob(
        project_id="PROJ-BULK-ES",
        evidence_number="EV-BULK-ES",
        source_path="/data",
        status=JobStatus.FAILED,
    )
    db.add(job)
    db.flush()
    db.add(ExportFile(
        job_id=job.id, relative_path="bad.bin",
        status=FileStatus.ERROR, error_message="checksum mismatch",
    ))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["error_summary"] is not None
    assert "1 file failed" in data[0]["error_summary"]
    assert "checksum mismatch" in data[0]["error_summary"]


def test_list_jobs_includes_drive_info(client, db):
    """Bulk enrichment should include nested drive info."""
    drive = UsbDrive(
        device_identifier="USB-BULK-DRV",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-BULK-DRV",
        capacity_bytes=32_000_000_000,
        filesystem_type="exfat",
    )
    db.add(drive)
    db.flush()
    job = ExportJob(
        project_id="PROJ-BULK-DRV",
        evidence_number="EV-BULK-DRV",
        source_path="/data",
        status=JobStatus.RUNNING,
    )
    db.add(job)
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["drive"] is not None
    assert data[0]["drive"]["device_identifier"] == "USB-BULK-DRV"
    assert data[0]["drive"]["capacity_bytes"] == 32_000_000_000


def test_list_jobs_no_drive_returns_null_drive(client, db):
    """Jobs without assignments should have drive=null in list."""
    db.add(ExportJob(
        project_id="PROJ-NODRIVE-LIST",
        evidence_number="EV-NODRIVE-LIST",
        source_path="/data",
        status=JobStatus.PENDING,
    ))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["drive"] is None


def test_list_jobs_mixed_success_and_failure(client, db):
    """List response should correctly enrich a mix of successful and failed jobs."""
    job_ok = ExportJob(
        project_id="PROJ-MIX",
        evidence_number="EV-MIX-OK",
        source_path="/data",
        status=JobStatus.COMPLETED,
    )
    job_fail = ExportJob(
        project_id="PROJ-MIX",
        evidence_number="EV-MIX-FAIL",
        source_path="/data",
        status=JobStatus.FAILED,
    )
    db.add_all([job_ok, job_fail])
    db.flush()
    db.add(ExportFile(job_id=job_ok.id, relative_path="ok.txt", status=FileStatus.DONE))
    db.add(ExportFile(job_id=job_fail.id, relative_path="err.txt", status=FileStatus.ERROR, error_message="io error"))
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2

    by_evidence = {j["evidence_number"]: j for j in data}
    assert by_evidence["EV-MIX-OK"]["files_succeeded"] == 1
    assert by_evidence["EV-MIX-OK"]["files_failed"] == 0
    assert by_evidence["EV-MIX-OK"]["error_summary"] is None
    assert by_evidence["EV-MIX-FAIL"]["files_succeeded"] == 0
    assert by_evidence["EV-MIX-FAIL"]["files_failed"] == 1
    assert by_evidence["EV-MIX-FAIL"]["error_summary"] is not None


def test_list_jobs_processor_client_ip_redacted(client, db):
    """Processor role (default client) should see client_ip=null in list."""
    job = ExportJob(
        project_id="PROJ-REDACT-LIST",
        evidence_number="EV-REDACT-LIST",
        source_path="/data",
        status=JobStatus.PENDING,
        client_ip="10.0.0.42",
    )
    db.add(job)
    db.commit()

    response = client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["client_ip"] is None


def test_list_jobs_admin_client_ip_visible(admin_client, db):
    """Admin role should see actual client_ip in list."""
    job = ExportJob(
        project_id="PROJ-ADMIN-LIST",
        evidence_number="EV-ADMIN-LIST",
        source_path="/data",
        status=JobStatus.PENDING,
        client_ip="10.0.0.42",
    )
    db.add(job)
    db.commit()

    response = admin_client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert data[0]["client_ip"] == "10.0.0.42"


def test_list_jobs_unauthenticated_returns_401(unauthenticated_client, db):
    """GET /jobs without auth should return 401."""
    response = unauthenticated_client.get("/jobs")
    assert response.status_code == 401


def test_list_jobs_auditor_allowed(auditor_client, db):
    """Auditor role should be able to list jobs and see client_ip."""
    job = ExportJob(
        project_id="PROJ-AUDITOR-LIST",
        evidence_number="EV-AUDITOR-LIST",
        source_path="/data",
        status=JobStatus.PENDING,
        client_ip="10.0.0.99",
    )
    db.add(job)
    db.commit()

    response = auditor_client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    matched = [j for j in data if j["evidence_number"] == "EV-AUDITOR-LIST"]
    assert len(matched) == 1
    # auditor is in _IP_VISIBLE_ROLES — client_ip should be visible
    assert matched[0]["client_ip"] == "10.0.0.99"


def test_list_jobs_manager_client_ip_redacted(manager_client, db):
    """Manager role should be able to list jobs but client_ip is redacted."""
    job = ExportJob(
        project_id="PROJ-MANAGER-LIST",
        evidence_number="EV-MANAGER-LIST",
        source_path="/data",
        status=JobStatus.PENDING,
        client_ip="10.0.0.88",
    )
    db.add(job)
    db.commit()

    response = manager_client.get("/jobs")
    assert response.status_code == 200
    data = response.json()
    matched = [j for j in data if j["evidence_number"] == "EV-MANAGER-LIST"]
    assert len(matched) == 1
    # manager is NOT in _IP_VISIBLE_ROLES — client_ip should be redacted
    assert matched[0]["client_ip"] is None


def test_create_job_auditor_forbidden(auditor_client, db):
    """Auditor role should be rejected from creating jobs (403)."""
    response = auditor_client.post("/jobs", json={
        "project_id": "PROJ-AUDIT-DENY",
        "evidence_number": "EV-AUDIT-DENY",
        "source_path": "/data/evidence",
    })
    assert response.status_code == 403


def test_start_job_auditor_forbidden(auditor_client, db):
    """Auditor role should be rejected from starting jobs (403)."""
    job = ExportJob(
        project_id="PROJ-START-DENY",
        evidence_number="EV-START-DENY",
        source_path="/data/evidence",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    response = auditor_client.post(f"/jobs/{job.id}/start", json={
        "target_mount_path": "/mnt/usb/1",
    })
    assert response.status_code == 403


def test_create_job_unauthenticated_returns_401(unauthenticated_client, db):
    """POST /jobs without auth should return 401."""
    response = unauthenticated_client.post("/jobs", json={
        "project_id": "PROJ-NOAUTH",
        "evidence_number": "EV-NOAUTH",
        "source_path": "/data/evidence",
    })
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# _build_error_summary edge cases
# ---------------------------------------------------------------------------


def test_error_summary_singular_file_failed(client, db):
    """Error summary should use singular 'file' for exactly 1 failure."""
    job = ExportJob(
        project_id="PROJ-SINGULAR",
        evidence_number="EV-SINGULAR",
        source_path="/data",
        status=JobStatus.FAILED,
    )
    db.add(job)
    db.flush()
    db.add(ExportFile(
        job_id=job.id, relative_path="one.bin",
        status=FileStatus.ERROR, error_message="bad sector",
    ))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert "1 file failed" in data["error_summary"]
    # Verify it does NOT say "1 files failed"
    assert "1 files failed" not in data["error_summary"]


def test_error_summary_truncates_at_1024_chars(client, db):
    """Error summary must not exceed 1024 characters."""
    job = ExportJob(
        project_id="PROJ-TRUNC",
        evidence_number="EV-TRUNC",
        source_path="/data",
        status=JobStatus.FAILED,
    )
    db.add(job)
    db.flush()
    # Create 5 error files with very long messages to force truncation
    for i in range(5):
        db.add(ExportFile(
            job_id=job.id, relative_path=f"{'x' * 80}_{i}.bin",
            status=FileStatus.ERROR,
            error_message=f"{'A' * 200} error {i}",
        ))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["error_summary"] is not None
    assert len(data["error_summary"]) <= 1024


def test_error_summary_shows_unreported_count(client, db):
    """When more errors exist than the limit, show '... and N more'."""
    job = ExportJob(
        project_id="PROJ-MORE",
        evidence_number="EV-MORE",
        source_path="/data",
        status=JobStatus.FAILED,
    )
    db.add(job)
    db.flush()
    # Create 8 error files; the limit is 5 so 3 should be unreported
    for i in range(8):
        db.add(ExportFile(
            job_id=job.id, relative_path=f"f{i}.bin",
            status=FileStatus.ERROR, error_message=f"err{i}",
        ))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert "and 3 more" in data["error_summary"]


def test_error_summary_no_error_rows_still_shows_count(client, db):
    """Error files with null error_message produce count-only summary."""
    job = ExportJob(
        project_id="PROJ-NULLMSG",
        evidence_number="EV-NULLMSG",
        source_path="/data",
        status=JobStatus.FAILED,
    )
    db.add(job)
    db.flush()
    db.add(ExportFile(job_id=job.id, relative_path="a.bin", status=FileStatus.ERROR))
    db.add(ExportFile(job_id=job.id, relative_path="b.bin", status=FileStatus.ERROR))
    db.commit()

    response = client.get(f"/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["error_summary"] is not None
    assert "2 files failed" in data["error_summary"]
