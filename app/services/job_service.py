import json
import os
from typing import Optional

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from app.models.hardware import DriveState
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.job_repository import (
    DriveAssignmentRepository,
    JobRepository,
    ManifestRepository,
)
from app.schemas.jobs import JobCreate, JobStart
from app.services import copy_engine


def create_job(body: JobCreate, db: Session, actor: Optional[str] = None) -> ExportJob:
    job_repo = JobRepository(db)
    drive_repo = DriveRepository(db)
    assignment_repo = DriveAssignmentRepository(db)
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
    )
    job_repo.add(job)

    if body.drive_id:
        drive = drive_repo.get_for_update(body.drive_id)
        if not drive:
            raise HTTPException(status_code=404, detail="Drive not found")

        # Enforce project isolation: the drive must belong to the same project, if set
        if getattr(drive, "current_project_id", None) not in (None, body.project_id):
            audit_repo.add(
                action="PROJECT_ISOLATION_VIOLATION",
                user=actor,
                job_id=job.id,
                details={
                    "drive_id": body.drive_id,
                    "existing_project_id": drive.current_project_id,
                    "requested_project_id": body.project_id,
                },
            )
            raise HTTPException(
                status_code=409,
                detail="Drive belongs to a different project",
            )

        # Ensure the drive is in a valid state for assignment
        if drive.current_state == DriveState.IN_USE:
            raise HTTPException(
                status_code=409,
                detail="Drive is already in use",
            )

        assignment_repo.add(DriveAssignment(drive_id=body.drive_id, job_id=job.id))
        drive.current_state = DriveState.IN_USE
        drive_repo.save(drive)

    audit_repo.add(
        action="JOB_CREATED",
        user=actor,
        job_id=job.id,
        details={"project_id": body.project_id},
    )
    return job


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
    if body.thread_count:
        job.thread_count = body.thread_count
    job_repo.save(job)

    audit_repo.add(action="JOB_STARTED", user=actor, job_id=job_id, details={})
    background_tasks.add_task(copy_engine.run_copy_job, job_id)
    db.refresh(job)
    return job


def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session,
    actor: Optional[str] = None,
) -> ExportJob:
    job_repo = JobRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.VERIFYING
    job_repo.save(job)
    audit_repo.add(action="JOB_VERIFY_STARTED", user=actor, job_id=job_id, details={})
    background_tasks.add_task(copy_engine.run_verify_job, job_id)
    db.refresh(job)
    return job


def create_manifest(job_id: int, db: Session, actor: Optional[str] = None) -> ExportJob:
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

    manifest_repo.add(
        Manifest(job_id=job_id, manifest_path=manifest_path, format="JSON")
    )
    audit_repo.add(
        action="MANIFEST_CREATED",
        user=actor,
        job_id=job_id,
        details={"manifest_path": manifest_path, "error": manifest_error},
    )
    db.refresh(job)
    return job
