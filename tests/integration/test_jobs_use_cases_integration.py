from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest


@pytest.mark.integration
def test_create_job_persists_and_audits(integration_client, integration_db):
    drive = UsbDrive(device_identifier="IT-DRV-AUTO-001", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-001",
            "evidence_number": "EV-001",
            "source_path": "/tmp/source",
            "thread_count": 4,
            "created_by": "integration-user",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PENDING"

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "JOB_CREATED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.job_id == data["id"]


@pytest.mark.integration
def test_create_job_with_drive_assignment_marks_drive_in_use(integration_client, integration_db):
    drive = UsbDrive(device_identifier="IT-DRV-JOB-001", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-002",
            "evidence_number": "EV-002",
            "source_path": "/tmp/source",
            "drive_id": drive.id,
        },
    )
    assert response.status_code == 200
    job_id = response.json()["id"]

    updated_drive = integration_db.get(UsbDrive, drive.id)
    assert updated_drive.current_state == DriveState.IN_USE

    assignment = (
        integration_db.query(DriveAssignment)
        .filter(DriveAssignment.job_id == job_id, DriveAssignment.drive_id == drive.id)
        .first()
    )
    assert assignment is not None


@pytest.mark.integration
def test_create_job_conflict_when_drive_belongs_to_different_project(integration_client, integration_db):
    drive = UsbDrive(
        device_identifier="IT-DRV-JOB-002",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-OTHER",
    )
    integration_db.add(drive)
    integration_db.commit()

    response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-003",
            "evidence_number": "EV-003",
            "source_path": "/tmp/source",
            "drive_id": drive.id,
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


@pytest.mark.integration
def test_get_job_and_get_job_not_found(integration_client, integration_db):
    drive = UsbDrive(device_identifier="IT-DRV-AUTO-004", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    create_response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-004",
            "evidence_number": "EV-004",
            "source_path": "/tmp/source",
        },
    )
    job_id = create_response.json()["id"]

    response = integration_client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["id"] == job_id

    missing = integration_client.get("/jobs/999999")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


@pytest.mark.integration
def test_start_job_updates_thread_count_and_audits(integration_client, integration_db):
    drive = UsbDrive(device_identifier="IT-DRV-AUTO-005", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    create_response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-005",
            "evidence_number": "EV-005",
            "source_path": "/tmp/source",
            "thread_count": 1,
        },
    )
    job_id = create_response.json()["id"]

    with patch("app.services.copy_engine.run_copy_job", return_value=None) as mock_copy:
        response = integration_client.post(f"/jobs/{job_id}/start", json={"thread_count": 3})

    assert response.status_code == 200
    assert response.json()["thread_count"] == 3
    mock_copy.assert_called_once_with(job_id)

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "JOB_STARTED", AuditLog.job_id == job_id)
        .first()
    )
    assert audit is not None


@pytest.mark.integration
def test_start_job_conflict_when_already_running(integration_client, integration_db):
    running_job = ExportJob(
        project_id="PROJ-JOB-006",
        evidence_number="EV-006",
        source_path="/tmp/source",
        status=JobStatus.RUNNING,
    )
    integration_db.add(running_job)
    integration_db.commit()

    response = integration_client.post(f"/jobs/{running_job.id}/start", json={})
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


@pytest.mark.integration
def test_verify_job_sets_verifying_and_audits(integration_client, integration_db):
    drive = UsbDrive(device_identifier="IT-DRV-AUTO-007", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    create_response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-007",
            "evidence_number": "EV-007",
            "source_path": "/tmp/source",
        },
    )
    job_id = create_response.json()["id"]

    with patch("app.services.copy_engine.run_verify_job", return_value=None) as mock_verify:
        response = integration_client.post(f"/jobs/{job_id}/verify")

    assert response.status_code == 200
    assert response.json()["status"] == "VERIFYING"
    mock_verify.assert_called_once_with(job_id)

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "JOB_VERIFY_STARTED", AuditLog.job_id == job_id)
        .first()
    )
    assert audit is not None


@pytest.mark.integration
def test_create_manifest_writes_record_file_and_audit(integration_client, integration_db, tmp_path):
    target_path = tmp_path / "manifest-target"
    drive = UsbDrive(device_identifier="IT-DRV-AUTO-008", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    create_response = integration_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-JOB-008",
            "evidence_number": "EV-008",
            "source_path": "/tmp/source",
            "target_mount_path": str(target_path),
        },
    )
    job_id = create_response.json()["id"]

    response = integration_client.post(f"/jobs/{job_id}/manifest")
    assert response.status_code == 200

    manifest = integration_db.query(Manifest).filter(Manifest.job_id == job_id).first()
    assert manifest is not None
    assert manifest.manifest_path is not None
    assert Path(manifest.manifest_path).exists()

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "MANIFEST_CREATED", AuditLog.job_id == job_id)
        .first()
    )
    assert audit is not None
    assert audit.details["error"] is None

