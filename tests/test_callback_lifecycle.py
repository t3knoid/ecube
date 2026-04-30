from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import BackgroundTasks

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus, Manifest
from app.schemas.audit import ChainOfCustodyHandoffRequest
from app.schemas.jobs import JobCreate, JobStart
from app.services import audit_service, job_service
from app.services.reconciliation_service import reconcile_jobs


def _make_drive(
    db,
    *,
    device_identifier: str,
    project_id: str,
    state: DriveState = DriveState.AVAILABLE,
    mount_path: str | None,
):
    drive = UsbDrive(
        device_identifier=device_identifier,
        current_state=state,
        current_project_id=project_id,
        mount_path=mount_path,
    )
    db.add(drive)
    db.commit()
    db.refresh(drive)
    return drive


def _make_job(
    db,
    *,
    project_id: str,
    evidence_number: str,
    status: JobStatus,
    source_path: str,
    target_mount_path: str | None = None,
    drive: UsbDrive | None = None,
    file_count: int = 0,
    copied_bytes: int = 0,
):
    job = ExportJob(
        project_id=project_id,
        evidence_number=evidence_number,
        source_path=source_path,
        target_mount_path=target_mount_path,
        status=status,
        file_count=file_count,
        copied_bytes=copied_bytes,
    )
    db.add(job)
    db.flush()
    if drive is not None:
        db.add(DriveAssignment(drive_id=drive.id, job_id=job.id, file_count=file_count, copied_bytes=copied_bytes))
    db.commit()
    db.refresh(job)
    return job


def test_job_service_emits_create_start_and_pause_callbacks(db):
    drive = _make_drive(
        db,
        device_identifier="USB-CALLBACK-LIFECYCLE-001",
        project_id="PROJ-CALLBACK-LIFECYCLE-001",
        mount_path="/mnt/ecube/callback-lifecycle-001",
    )

    with patch("app.services.job_service.deliver_callback") as mock_callback:
        job = job_service.create_job(
            JobCreate(
                project_id="PROJ-CALLBACK-LIFECYCLE-001",
                evidence_number="EV-CALLBACK-LIFECYCLE-001",
                source_path="/data/callback-lifecycle-001",
                drive_id=drive.id,
                thread_count=2,
            ),
            db,
            actor="processor",
        )
        job_service.start_job(job.id, JobStart(thread_count=3), BackgroundTasks(), db, actor="processor")
        job_service.pause_job(job.id, db, actor="processor")

    events = [call.kwargs["event"] for call in mock_callback.call_args_list]
    assert events == ["JOB_CREATED", "JOB_STARTED", "JOB_PAUSE_REQUESTED"]
    assert mock_callback.call_args_list[1].kwargs["event_details"] == {"thread_count": 3}


def test_job_service_emits_manual_complete_and_archive_callbacks(db):
    drive = _make_drive(
        db,
        device_identifier="USB-CALLBACK-LIFECYCLE-002",
        project_id="PROJ-CALLBACK-LIFECYCLE-002",
        mount_path=None,
    )
    job = _make_job(
        db,
        project_id="PROJ-CALLBACK-LIFECYCLE-002",
        evidence_number="EV-CALLBACK-LIFECYCLE-002",
        status=JobStatus.PAUSED,
        source_path="/data/callback-lifecycle-002",
        drive=drive,
    )

    with patch("app.services.job_service.deliver_callback") as mock_callback:
        job_service.complete_job(job.id, db, actor="processor")
        job_service.archive_job(job.id, confirm=True, db=db, actor="processor")

    events = [call.kwargs["event"] for call in mock_callback.call_args_list]
    assert events == ["JOB_COMPLETED_MANUALLY", "JOB_ARCHIVED"]
    assert mock_callback.call_args_list[0].kwargs["event_details"] == {"previous_status": "PAUSED"}
    assert mock_callback.call_args_list[1].kwargs["event_details"] == {"previous_status": "COMPLETED"}


def test_job_service_emits_retry_and_manifest_callbacks(db, tmp_path):
    retry_drive = _make_drive(
        db,
        device_identifier="USB-CALLBACK-LIFECYCLE-003",
        project_id="PROJ-CALLBACK-LIFECYCLE-003",
        mount_path="/mnt/ecube/callback-lifecycle-003",
    )
    retry_job = _make_job(
        db,
        project_id="PROJ-CALLBACK-LIFECYCLE-003",
        evidence_number="EV-CALLBACK-LIFECYCLE-003",
        status=JobStatus.COMPLETED,
        source_path="/data/callback-lifecycle-003",
        target_mount_path=retry_drive.mount_path,
        drive=retry_drive,
    )
    db.add_all([
        ExportFile(job_id=retry_job.id, relative_path="failed.bin", status=FileStatus.ERROR),
        ExportFile(job_id=retry_job.id, relative_path="timed.bin", status=FileStatus.TIMEOUT),
    ])
    db.commit()

    manifest_drive = _make_drive(
        db,
        device_identifier="USB-CALLBACK-LIFECYCLE-004",
        project_id="PROJ-CALLBACK-LIFECYCLE-004",
        mount_path=str(tmp_path),
    )
    manifest_job = _make_job(
        db,
        project_id="PROJ-CALLBACK-LIFECYCLE-004",
        evidence_number="EV-CALLBACK-LIFECYCLE-004",
        status=JobStatus.COMPLETED,
        source_path="/data/callback-lifecycle-004",
        target_mount_path=str(tmp_path),
        drive=manifest_drive,
        file_count=1,
        copied_bytes=128,
    )
    db.add(
        ExportFile(
            job_id=manifest_job.id,
            relative_path="done.bin",
            status=FileStatus.DONE,
            checksum="abc123",
            size_bytes=128,
        )
    )
    db.commit()

    with patch("app.services.job_service.deliver_callback") as mock_callback:
        job_service.retry_failed_files(retry_job.id, BackgroundTasks(), db, actor="processor")
        job_service.create_manifest(manifest_job.id, db, actor="processor")

    events = [call.kwargs["event"] for call in mock_callback.call_args_list]
    assert events == ["JOB_RETRY_FAILED_FILES_STARTED", "MANIFEST_CREATED"]
    assert mock_callback.call_args_list[0].kwargs["event_details"] == {
        "retry_file_count": 2,
        "error_count": 1,
        "timeout_count": 1,
    }
    assert mock_callback.call_args_list[1].kwargs["event_details"]["manifest_file"] == "manifest.json"


def test_audit_service_emits_snapshot_and_handoff_callbacks(db):
    drive = _make_drive(
        db,
        device_identifier="USB-CALLBACK-LIFECYCLE-005",
        project_id="PROJ-CALLBACK-LIFECYCLE-005",
        mount_path="/mnt/ecube/callback-lifecycle-005",
    )
    job = _make_job(
        db,
        project_id="PROJ-CALLBACK-LIFECYCLE-005",
        evidence_number="EV-CALLBACK-LIFECYCLE-005",
        status=JobStatus.COMPLETED,
        source_path="/data/callback-lifecycle-005",
        drive=drive,
        file_count=2,
        copied_bytes=512,
    )
    db.add(Manifest(job_id=job.id, manifest_path="/tmp/manifest-callback-lifecycle-005.json", format="JSON"))
    db.add_all([
        AuditLog(action="DRIVE_INITIALIZED", drive_id=drive.id, project_id=job.project_id, details={"drive_id": drive.id}),
        AuditLog(action="JOB_CREATED", drive_id=drive.id, job_id=job.id, project_id=job.project_id, details={"project_id": job.project_id}),
    ])
    db.commit()

    with patch("app.services.audit_service.deliver_callback") as mock_callback:
        audit_service.refresh_job_chain_of_custody_report(db, job_id=job.id, actor="manager", client_ip=None)
        audit_service.confirm_job_chain_of_custody_handoff(
            db,
            job_id=job.id,
            payload=ChainOfCustodyHandoffRequest(
                drive_id=drive.id,
                project_id=job.project_id,
                possessor="Evidence Locker",
                delivery_time=datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc),
                received_by="Custodian A",
                receipt_ref="RCPT-100",
            ),
            actor="manager",
            client_ip=None,
        )

    events = [call.kwargs["event"] for call in mock_callback.call_args_list]
    assert events == ["COC_SNAPSHOT_STORED", "COC_SNAPSHOT_STORED", "COC_HANDOFF_CONFIRMED"]
    assert mock_callback.call_args_list[0].kwargs["event_details"]["report_count"] >= 1
    assert mock_callback.call_args_list[2].kwargs["event_details"]["possessor"] == "Evidence Locker"


def test_reconcile_jobs_emits_reconciled_callback(db):
    job = _make_job(
        db,
        project_id="PROJ-CALLBACK-LIFECYCLE-006",
        evidence_number="EV-CALLBACK-LIFECYCLE-006",
        status=JobStatus.RUNNING,
        source_path="/data/callback-lifecycle-006",
    )

    with patch("app.services.reconciliation_service.deliver_callback") as mock_callback:
        result = reconcile_jobs(db)

    assert result["jobs_corrected"] == 1
    assert mock_callback.call_count == 1
    assert mock_callback.call_args.kwargs["event"] == "JOB_RECONCILED"
    assert mock_callback.call_args.kwargs["event_details"] == {
        "old_status": "RUNNING",
        "new_status": "FAILED",
        "reason": "interrupted by restart",
    }