from datetime import datetime, timezone
import json
import logging
import os
from typing import Optional, Tuple

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.exceptions import ECUBEException, EncodingError
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.job_repository import (
    JobRepository,
    ManifestRepository,
)
from app.schemas.jobs import JobCreate, JobStart
from app.services import copy_engine
from app.utils.sanitize import is_encoding_error

logger = logging.getLogger(__name__)


def create_job(body: JobCreate, db: Session, actor: Optional[str] = None, client_ip: Optional[str] = None) -> ExportJob:
    job_repo = JobRepository(db)
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    job = ExportJob(
        project_id=body.project_id,
        evidence_number=body.evidence_number,
        source_path=body.source_path,
        target_mount_path=body.target_mount_path,
        thread_count=body.thread_count,
        max_file_retries=body.max_file_retries,
        retry_delay_seconds=body.retry_delay_seconds,
        created_by=body.created_by,
        client_ip=client_ip,
    )

    # Use a single transaction for the entire create-job-with-drive flow.
    # flush() obtains IDs without committing, so a failure at any step
    # rolls back everything — no orphaned job or assignment records.
    try:
        db.add(job)
        db.flush()  # obtain job.id for the assignment FK

        if body.drive_id is not None:
            drive = drive_repo.get_for_update(body.drive_id)
            if not drive:
                db.rollback()
                raise HTTPException(status_code=404, detail="Drive not found")

            # Enforce project isolation
            if getattr(drive, "current_project_id", None) not in (None, body.project_id):
                db.rollback()
                try:
                    audit_repo.add(
                        action="PROJECT_ISOLATION_VIOLATION",
                        user=actor,
                        job_id=job.id,
                        details={
                            "actor": actor,
                            "drive_id": body.drive_id,
                            "existing_project_id": drive.current_project_id,
                            "requested_project_id": body.project_id,
                        },
                        client_ip=client_ip,
                    )
                except Exception:
                    logger.exception("Failed to write audit log for PROJECT_ISOLATION_VIOLATION")
                raise HTTPException(
                    status_code=403,
                    detail="Drive belongs to a different project",
                )

            if drive.current_state == DriveState.IN_USE:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Drive is already in use",
                )

            db.add(DriveAssignment(drive_id=body.drive_id, job_id=job.id))
            drive.current_state = DriveState.IN_USE
            db.flush()  # validate assignment + drive state change
        else:
            # Auto-assign a drive when drive_id is omitted
            drive, auto_selection = _auto_assign_drive(
                project_id=body.project_id,
                job_id=job.id,
                drive_repo=drive_repo,
                db=db,
            )
            db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
            drive.current_state = DriveState.IN_USE
            db.flush()

        db.commit()
    except (HTTPException, ECUBEException):
        raise
    except Exception as exc:
        db.rollback()
        if is_encoding_error(exc):
            raise EncodingError("Job data contains invalid characters") from exc
        logger.exception("DB commit failed while creating job")
        raise HTTPException(
            status_code=500,
            detail="Database error while creating job",
        )

    db.refresh(job)

    # Best-effort audit logging — failures never abort job creation.
    try:
        if body.drive_id is None:
            if auto_selection == "unbound_fallback":
                audit_repo.add(
                    action="DRIVE_PROJECT_BOUND",
                    user=actor,
                    job_id=job.id,
                    details={"drive_id": drive.id, "project_id": body.project_id},
                    client_ip=client_ip,
                )
            audit_repo.add(
                action="DRIVE_AUTO_ASSIGNED",
                user=actor,
                job_id=job.id,
                details={
                    "drive_id": drive.id,
                    "project_id": body.project_id,
                    "selection": auto_selection,
                },
                client_ip=client_ip,
            )
    except Exception:
        logger.exception("Failed to write audit log for auto-assignment")

    try:
        audit_repo.add(
            action="JOB_CREATED",
            user=actor,
            job_id=job.id,
            details={"project_id": body.project_id},
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_CREATED")
    return job


def _auto_assign_drive(
    project_id: str,
    job_id: int,
    drive_repo: DriveRepository,
    db: Session,
) -> Tuple[UsbDrive, str]:
    """Select a drive automatically when ``drive_id`` is omitted from job creation.

    Returns ``(drive, selection)`` where *selection* is ``"project_bound"``
    or ``"unbound_fallback"``.  Raises 409 if the choice is ambiguous or
    no usable drive exists for the requested project.

    Disambiguation rules:
    1. Exactly one AVAILABLE drive bound to *project_id* → select it.
    2. Zero project-bound matches → pick the first unbound AVAILABLE drive and bind it.
    3. Multiple project-bound matches → fail 409 (caller must specify).
    4. No usable drive (none bound to the project and none unbound) → fail 409.
    """
    project_count = drive_repo.count_available_for_project(project_id)

    if project_count == 1:
        drive = drive_repo.get_one_available_for_project(project_id)
        if drive is None:
            # The single candidate is locked by another transaction.
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Drive for project {project_id} is locked by another operation",
            )
        return drive, "project_bound"

    if project_count > 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Multiple drives assigned to project {project_id}; specify drive_id",
        )

    # No project-bound drives — try an unbound AVAILABLE drive
    drive = drive_repo.get_next_unbound_available()
    if drive:
        drive.current_project_id = project_id
        return drive, "unbound_fallback"

    # No usable drive — none bound to the project and none unbound
    db.rollback()
    raise HTTPException(
        status_code=409,
        detail=f"No available drive for project {project_id}",
    )


def get_job(job_id: int, db: Session) -> ExportJob:
    job = JobRepository(db).get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def start_job(
    job_id: int,
    body: JobStart,
    background_tasks: BackgroundTasks,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> ExportJob:
    job_repo = JobRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.PENDING, JobStatus.FAILED):
        raise HTTPException(
            status_code=409, detail=f"Job is already in status {job.status}"
        )

    # Transition to RUNNING inside the locked transaction so that any concurrent
    # request arriving after this commit will observe the updated state and be
    # rejected with 409 before the background copy task begins.
    job.status = JobStatus.RUNNING
    job.started_by = actor
    job.started_at = datetime.now(timezone.utc)
    job.completed_at = None
    if body.thread_count:
        job.thread_count = body.thread_count
    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while starting job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while starting job",
        )

    try:
        audit_repo.add(action="JOB_STARTED", user=actor, job_id=job_id, details={}, client_ip=client_ip)
    except Exception:
        logger.exception("Failed to write audit log for JOB_STARTED")
    background_tasks.add_task(copy_engine.run_copy_job, job_id)
    db.refresh(job)
    return job


def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> ExportJob:
    job_repo = JobRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.VERIFYING
    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while starting verification for job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while starting job verification",
        )
    try:
        audit_repo.add(action="JOB_VERIFY_STARTED", user=actor, job_id=job_id, details={}, client_ip=client_ip)
    except Exception:
        logger.exception("Failed to write audit log for JOB_VERIFY_STARTED")
    background_tasks.add_task(copy_engine.run_verify_job, job_id)
    db.refresh(job)
    return job


def create_manifest(job_id: int, db: Session, actor: Optional[str] = None, client_ip: Optional[str] = None) -> ExportJob:
    job_repo = JobRepository(db)
    manifest_repo = ManifestRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    manifest_data = {
        "job_id": job.id,
        "project_id": job.project_id,
        "evidence_number": job.evidence_number,
        "files": [
            {
                "path": f.relative_path,
                "checksum": f.checksum,
                "size_bytes": f.size_bytes,
            }
            for f in job.files
        ],
    }

    manifest_path = None
    manifest_error = None
    if job.target_mount_path:
        manifest_path = os.path.join(
            job.target_mount_path, f"manifest_{job.id}.json"
        )
        try:
            os.makedirs(job.target_mount_path, exist_ok=True)
            with open(manifest_path, "w") as fp:
                json.dump(manifest_data, fp, indent=2)
        except Exception as exc:
            manifest_error = str(exc)
            manifest_path = None

    try:
        manifest_repo.add(
            Manifest(job_id=job_id, manifest_path=manifest_path, format="JSON")
        )
    except Exception:
        logger.exception("DB commit failed while creating manifest for job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while creating manifest",
        )
    try:
        audit_repo.add(
            action="MANIFEST_CREATED",
            user=actor,
            job_id=job_id,
            details={"manifest_path": manifest_path, "error": manifest_error},
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for MANIFEST_CREATED")
    db.refresh(job)
    return job
