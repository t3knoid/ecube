import json
import os

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hardware import UsbDrive, DriveState
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest
from app.schemas.jobs import ExportJobSchema, JobCreate, JobStart
from app.services import copy_engine
from app.services.audit_service import create_audit_log

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=ExportJobSchema)
def create_job(body: JobCreate, db: Session = Depends(get_db)):
    job = ExportJob(
        project_id=body.project_id,
        evidence_number=body.evidence_number,
        source_path=body.source_path,
        target_mount_path=body.target_mount_path,
        thread_count=body.thread_count,
        created_by=body.created_by,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if body.drive_id:
        assignment = DriveAssignment(drive_id=body.drive_id, job_id=job.id)
        db.add(assignment)
        drive = db.get(UsbDrive, body.drive_id)
        if drive:
            drive.current_state = DriveState.IN_USE
        db.commit()

    create_audit_log(
        db=db,
        action="JOB_CREATED",
        job_id=job.id,
        details={"project_id": body.project_id},
    )
    return job


@router.get("/{job_id}", response_model=ExportJobSchema)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/{job_id}/start", response_model=ExportJobSchema)
def start_job(
    job_id: int,
    body: JobStart,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.PENDING, JobStatus.FAILED):
        raise HTTPException(
            status_code=409, detail=f"Job is already in status {job.status}"
        )

    if body.thread_count:
        job.thread_count = body.thread_count
        db.commit()

    create_audit_log(db=db, action="JOB_STARTED", job_id=job_id, details={})
    background_tasks.add_task(copy_engine.run_copy_job, job_id, db)
    db.refresh(job)
    return job


@router.post("/{job_id}/verify", response_model=ExportJobSchema)
def verify_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = JobStatus.VERIFYING
    db.commit()
    create_audit_log(db=db, action="JOB_VERIFY_STARTED", job_id=job_id, details={})
    db.refresh(job)
    return job


@router.post("/{job_id}/manifest", response_model=ExportJobSchema)
def create_manifest(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ExportJob, job_id)
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

    manifest = Manifest(job_id=job_id, manifest_path=manifest_path, format="JSON")
    db.add(manifest)
    db.commit()
    create_audit_log(
        db=db,
        action="MANIFEST_CREATED",
        job_id=job_id,
        details={"manifest_path": manifest_path, "error": manifest_error},
    )
    db.refresh(job)
    return job
