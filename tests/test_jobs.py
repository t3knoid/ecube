from unittest.mock import patch

from app.models.hardware import UsbDrive, DriveState
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus


def test_create_job(client, db):
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
    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/data/evidence",
        },
    )
    job_id = create_response.json()["id"]

    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id


def test_get_job_not_found(client, db):
    response = client.get("/jobs/999")
    assert response.status_code == 404


def test_start_job(client, db):
    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp",
        },
    )
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
    create_response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp",
        },
    )
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
    response = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-TS",
            "evidence_number": "EV-TS",
            "source_path": "/data",
        },
    )
    data = response.json()
    assert "created_at" in data
    assert data["created_at"] is not None
    assert data["started_at"] is None
    assert data["completed_at"] is None


def test_job_response_includes_started_by(client, db):
    """started_by should be null on create and populated after start."""
    create_resp = client.post(
        "/jobs",
        json={
            "project_id": "PROJ-SB",
            "evidence_number": "EV-SB",
            "source_path": "/tmp",
        },
    )
    job_id = create_resp.json()["id"]
    assert create_resp.json()["started_by"] is None

    with patch("app.services.copy_engine.run_copy_job"):
        start_resp = client.post(f"/jobs/{job_id}/start", json={})
    assert start_resp.status_code == 200
    assert start_resp.json()["started_by"] == "test-user"


def test_completed_job_with_all_fields(client, db):
    """A completed job with files and a drive should include all enriched fields."""
    drive = UsbDrive(
        device_identifier="USB-ENRICH-001",
        current_state=DriveState.AVAILABLE,
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
    assert data["drive"]["current_state"] == "AVAILABLE"
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
    data = response.json()

    assert data["drive"] is None
    assert data["files_succeeded"] == 0
    assert data["files_failed"] == 0
    assert data["error_summary"] is None
