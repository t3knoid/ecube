from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Optional, Tuple, cast

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import ConflictError, ECUBEException, EncodingError
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, JobStatus, Manifest
from app.models.network import MountStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.job_repository import (
    DriveAssignmentRepository,
    JobRepository,
    ManifestRepository,
)
from app.repositories.mount_repository import MountRepository
from app.schemas.jobs import JobCreate, JobStart, JobUpdate
from app.services import copy_engine
from app.utils.sanitize import is_encoding_error, resolve_source_path, validate_source_path
from app.utils.path_overlap import classify_source_path_overlap

logger = logging.getLogger(__name__)


_ACTIVE_SOURCE_OVERLAP_STATUSES = (
    JobStatus.PENDING,
    JobStatus.RUNNING,
    JobStatus.PAUSING,
    JobStatus.PAUSED,
    JobStatus.VERIFYING,
)


def _row(instance: object) -> Any:
    """Expose SQLAlchemy model instances using their runtime attribute types."""
    return cast(Any, instance)


def list_jobs(db: Session, limit: int = 200) -> list[ExportJob]:
    """Return the most recent export jobs."""
    repo = JobRepository(db)
    return repo.list_recent(limit=limit)


def _resolve_job_source_path(body: JobCreate, db: Session) -> str:
    if body.mount_id is None:
        try:
            return resolve_source_path(
                body.source_path,
                usb_mount_base_path=settings.usb_mount_base_path,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    mount = MountRepository(db).get(body.mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    mount_row = _row(mount)
    mount_project_id = cast(Optional[str], mount_row.project_id)
    mount_status = cast(MountStatus, mount_row.status)
    mount_root = cast(Optional[str], mount_row.local_mount_point)

    if mount_project_id != body.project_id:
        raise HTTPException(status_code=409, detail="Selected mount is not available for this project")
    if mount_status != MountStatus.MOUNTED or not mount_root:
        raise HTTPException(status_code=409, detail="Selected mount is not mounted")

    try:
        return resolve_source_path(
            body.source_path,
            mount_root=mount_root,
            usb_mount_base_path=settings.usb_mount_base_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _build_source_overlap_message(overlap_type: str, drive_id: int, existing_job_id: int) -> str:
    if overlap_type == "exact":
        return (
            f"A job is already copying from this exact source path to drive {drive_id} "
            f"(job #{existing_job_id})."
        )
    if overlap_type == "ancestor":
        return (
            f"An existing job (#{existing_job_id}) copies from a subdirectory of the requested source. "
            "The parent path would duplicate that content."
        )
    return (
        f"An existing job (#{existing_job_id}) already copies from a parent path that includes "
        "the requested source."
    )


def _reject_source_path_overlap(
    *,
    db: Session,
    audit_repo: AuditRepository,
    actor: Optional[str],
    client_ip: Optional[str],
    project_id: str,
    drive_id: int,
    new_source_path: str,
    exclude_job_id: Optional[int] = None,
) -> None:
    assignment_repo = DriveAssignmentRepository(db)
    active_jobs = assignment_repo.list_active_jobs_for_drive(
        drive_id,
        statuses=_ACTIVE_SOURCE_OVERLAP_STATUSES,
    )

    for existing_job in active_jobs:
        if exclude_job_id is not None and existing_job.id == exclude_job_id:
            continue

        overlap_type = classify_source_path_overlap(existing_job.source_path, new_source_path)
        if overlap_type == "none":
            continue

        db.rollback()
        try:
            audit_repo.add(
                action="JOB_REJECTED_SOURCE_OVERLAP",
                user=actor,
                project_id=project_id,
                drive_id=drive_id,
                details={
                    "actor": actor,
                    "drive_id": drive_id,
                    "project_id": project_id,
                    "new_source_path": new_source_path,
                    "existing_source_path": existing_job.source_path,
                    "overlapping_job_id": existing_job.id,
                    "overlap_type": overlap_type,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for JOB_REJECTED_SOURCE_OVERLAP")

        raise ConflictError(
            _build_source_overlap_message(overlap_type, drive_id, existing_job.id),
            code="SOURCE_OVERLAP",
        )


def create_job(
    body: JobCreate,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
    seeded_job_id: Optional[int] = None,
) -> ExportJob:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)
    resolved_source_path = _resolve_job_source_path(body, db)

    if seeded_job_id is not None:
        existing_job = db.query(ExportJob).filter(ExportJob.id == seeded_job_id).one_or_none()
        if existing_job is not None:
            raise HTTPException(status_code=409, detail=f"Job id {seeded_job_id} already exists")

    job = ExportJob(
        id=seeded_job_id,
        project_id=body.project_id,
        evidence_number=body.evidence_number,
        source_path=resolved_source_path,
        target_mount_path=None,
        thread_count=body.thread_count,
        max_file_retries=body.max_file_retries,
        retry_delay_seconds=body.retry_delay_seconds,
        created_by=actor,
        callback_url=body.callback_url,
        client_ip=client_ip,
    )
    job_row = _row(job)

    # Use a single transaction for the entire create-job-with-drive flow.
    # flush() obtains IDs without committing, so a failure at any step
    # rolls back everything — no orphaned job or assignment records.
    try:
        db.add(job)
        db.flush()  # obtain job.id for the assignment FK

        explicit_bound = False

        if body.drive_id is not None:
            drive = drive_repo.get_for_update(body.drive_id)
            if not drive:
                db.rollback()
                raise HTTPException(status_code=404, detail="Drive not found")

            drive_row = _row(drive)
            current_project_id = cast(Optional[str], drive_row.current_project_id)
            current_state = cast(DriveState, drive_row.current_state)
            mount_path = cast(Optional[str], drive_row.mount_path)

            # Enforce project isolation
            if current_project_id not in (None, body.project_id):
                db.rollback()
                try:
                    audit_repo.add(
                        action="PROJECT_ISOLATION_VIOLATION",
                        user=actor,
                        project_id=body.project_id,
                        drive_id=body.drive_id,
                        # job_id intentionally omitted: the job row was rolled back above
                        # and audit_logs.job_id is an FK — referencing it would fail on
                        # PostgreSQL. The attempted job context is preserved in details.
                        details={
                            "actor": actor,
                            "drive_id": body.drive_id,
                            "existing_project_id": current_project_id,
                            "requested_project_id": body.project_id,
                            "attempted_project_id": body.project_id,
                        },
                        client_ip=client_ip,
                    )
                except Exception:
                    logger.error("Failed to write audit log for PROJECT_ISOLATION_VIOLATION")
                raise HTTPException(
                    status_code=403,
                    detail="Drive belongs to a different project",
                )

            if current_state not in (DriveState.AVAILABLE, DriveState.IN_USE):
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Drive is not available",
                )

            # Bind the drive to this project if currently unbound.
            if current_project_id is None:
                drive_row.current_project_id = body.project_id
                explicit_bound = True

            if not mount_path:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Assigned drive is not mounted",
                )

            job_row.target_mount_path = mount_path
            try:
                job_row.source_path = validate_source_path(
                    cast(str, job_row.source_path),
                    usb_mount_base_path=settings.usb_mount_base_path,
                    target_mount_path=mount_path,
                )
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            _reject_source_path_overlap(
                db=db,
                audit_repo=audit_repo,
                actor=actor,
                client_ip=client_ip,
                project_id=body.project_id,
                drive_id=body.drive_id,
                new_source_path=cast(str, job_row.source_path),
            )
            db.add(DriveAssignment(drive_id=body.drive_id, job_id=cast(int, job_row.id)))
            drive_row.current_state = DriveState.IN_USE
            db.flush()  # validate assignment + drive state change
        else:
            # Auto-assign a drive when drive_id is omitted
            drive, auto_selection = _auto_assign_drive(
                project_id=body.project_id,
                drive_repo=drive_repo,
                db=db,
            )
            drive_row = _row(drive)
            mount_path = cast(Optional[str], drive_row.mount_path)
            if not mount_path:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Assigned drive is not mounted",
                )
            job_row.target_mount_path = mount_path
            try:
                job_row.source_path = validate_source_path(
                    cast(str, job_row.source_path),
                    usb_mount_base_path=settings.usb_mount_base_path,
                    target_mount_path=mount_path,
                )
            except ValueError as exc:
                db.rollback()
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            _reject_source_path_overlap(
                db=db,
                audit_repo=audit_repo,
                actor=actor,
                client_ip=client_ip,
                project_id=body.project_id,
                drive_id=cast(int, drive_row.id),
                new_source_path=cast(str, job_row.source_path),
            )
            db.add(DriveAssignment(drive_id=cast(int, drive_row.id), job_id=cast(int, job_row.id)))
            drive_row.current_state = DriveState.IN_USE
            db.flush()

        bind = db.get_bind()
        if seeded_job_id is not None and getattr(bind.dialect, "name", None) == "postgresql":
            db.execute(
                text(
                    "SELECT setval(pg_get_serial_sequence('export_jobs', 'id'), "
                    "(SELECT COALESCE(MAX(id), 1) FROM export_jobs), true)"
                )
            )

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
    created_job_id = cast(int, job_row.id)
    selected_drive_id = cast(int, drive_row.id)

    # Best-effort audit logging — failures never abort job creation.
    try:
        if body.drive_id is not None and explicit_bound:
            audit_repo.add(
                action="DRIVE_PROJECT_BOUND",
                user=actor,
                job_id=created_job_id,
                details={"drive_id": body.drive_id, "project_id": body.project_id},
                client_ip=client_ip,
            )
    except Exception:
        logger.exception("Failed to write audit log for explicit drive project binding")

    try:
        if body.drive_id is None:
            if auto_selection == "unbound_fallback":
                audit_repo.add(
                    action="DRIVE_PROJECT_BOUND",
                    user=actor,
                    job_id=created_job_id,
                    details={"drive_id": selected_drive_id, "project_id": body.project_id},
                    client_ip=client_ip,
                )
            audit_repo.add(
                action="DRIVE_AUTO_ASSIGNED",
                user=actor,
                job_id=created_job_id,
                details={
                    "drive_id": selected_drive_id,
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
            job_id=created_job_id,
            details={"project_id": body.project_id},
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_CREATED")
    return job


def _auto_assign_drive(
    project_id: str,
    drive_repo: DriveRepository,
    db: Session,
) -> Tuple[UsbDrive, str]:
    """Select a drive automatically when ``drive_id`` is omitted from job creation.

    Returns ``(drive, selection)`` where *selection* is ``"project_bound"``
    or ``"unbound_fallback"``.  Raises 409 if the choice is ambiguous or
    no usable drive exists for the requested project.

    Selection strategy (lock first, then verify uniqueness):

    1. Try to lock a project-bound ``AVAILABLE`` drive (``SKIP LOCKED``).
    2. If a drive was locked, count all project-bound ``AVAILABLE`` drives:

       - Exactly one → unambiguous; use it.
       - More than one → ambiguous; 409 (caller must specify ``drive_id``).

    3. If no drive could be locked, count to diagnose:

       - Zero → no project-bound drives; fall through to unbound path.
       - One or more → drive(s) temporarily unavailable; 409 (retry).

    4. Unbound fallback: pick the first unbound ``AVAILABLE`` drive and bind it.
       If no lockable unbound drive → 409 (no usable drive or retry).
    """
    # --- Project-bound path: lock first, then verify uniqueness ---
    drive = drive_repo.get_one_available_for_project(project_id)

    if drive is not None:
        project_count = drive_repo.count_available_for_project(project_id)
        if project_count > 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Multiple drives assigned to project {project_id}; specify drive_id",
            )
        return drive, "project_bound"

    # No lockable project-bound drive — determine why.
    project_count = drive_repo.count_available_for_project(project_id)
    if project_count >= 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Multiple drives assigned to project {project_id}; specify drive_id"
                if project_count > 1
                else f"Drive for project {project_id} is temporarily unavailable; retry"
            ),
        )

    # --- Unbound fallback path (project_count == 0) ---
    drive = drive_repo.get_next_unbound_available()
    if drive:
        drive_row = _row(drive)
        drive_row.current_project_id = project_id
        return drive, "unbound_fallback"

    # Either no unbound AVAILABLE drives exist, or they are all
    # temporarily unavailable — we cannot distinguish reliably.
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


def _require_editable_job(job: ExportJob) -> None:
    job_row = _row(job)
    if cast(JobStatus, job_row.status) not in (JobStatus.PENDING, JobStatus.PAUSED, JobStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail="Only pending, paused, or failed jobs can be edited from Job Detail",
        )


def _other_active_assignments_for_drive(db: Session, drive_id: int, *, exclude_job_id: Optional[int] = None) -> int:
    query = db.query(DriveAssignment).filter(
        DriveAssignment.drive_id == drive_id,
        DriveAssignment.released_at.is_(None),
    )
    if exclude_job_id is not None:
        query = query.filter(DriveAssignment.job_id != exclude_job_id)
    return query.count()


def update_job(
    job_id: int,
    body: JobUpdate,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> ExportJob:
    job_repo = JobRepository(db)
    drive_repo = DriveRepository(db)
    assignment_repo = DriveAssignmentRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_row = _row(job)
    _require_editable_job(job)

    if body.project_id != cast(Optional[str], job_row.project_id):
        raise HTTPException(
            status_code=409,
            detail="Project cannot be changed for an existing job",
        )

    resolved_source_path = _resolve_job_source_path(body, db)
    active_assignment = assignment_repo.get_active_for_job(job_id)
    assignment_row = _row(active_assignment) if active_assignment is not None else None
    current_drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None
    requested_drive_id = body.drive_id if body.drive_id is not None else current_drive_id
    if requested_drive_id is None:
        raise HTTPException(status_code=409, detail="Job has no assigned drive")

    drive = drive_repo.get_for_update(int(requested_drive_id))
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    drive_row = _row(drive)
    drive_project_id = cast(Optional[str], drive_row.current_project_id)
    drive_state = cast(DriveState, drive_row.current_state)
    drive_mount_path = cast(Optional[str], drive_row.mount_path)

    if drive_project_id not in (None, cast(Optional[str], job_row.project_id)):
        raise HTTPException(status_code=403, detail="Drive belongs to a different project")
    if drive_state not in (DriveState.AVAILABLE, DriveState.IN_USE):
        raise HTTPException(status_code=409, detail="Drive is not available")
    if not drive_mount_path:
        raise HTTPException(status_code=409, detail="Assigned drive is not mounted")

    if drive_project_id is None:
        drive_row.current_project_id = cast(Optional[str], job_row.project_id)

    try:
        validated_source_path = validate_source_path(
            resolved_source_path,
            usb_mount_base_path=settings.usb_mount_base_path,
            target_mount_path=drive_mount_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _reject_source_path_overlap(
        db=db,
        audit_repo=audit_repo,
        actor=actor,
        client_ip=client_ip,
        project_id=cast(str, job_row.project_id),
        drive_id=int(requested_drive_id),
        new_source_path=validated_source_path,
        exclude_job_id=job_id,
    )

    changed_fields: list[str] = []
    if cast(Optional[str], job_row.evidence_number) != body.evidence_number:
        changed_fields.append("evidence_number")
    if cast(Optional[str], job_row.source_path) != validated_source_path:
        changed_fields.append("source_path")
    if int(cast(Optional[int], job_row.thread_count) or 0) != int(body.thread_count):
        changed_fields.append("thread_count")
    if int(cast(Optional[int], job_row.max_file_retries) or 0) != int(body.max_file_retries):
        changed_fields.append("max_file_retries")
    if int(cast(Optional[int], job_row.retry_delay_seconds) or 0) != int(body.retry_delay_seconds):
        changed_fields.append("retry_delay_seconds")
    if current_drive_id != requested_drive_id:
        changed_fields.append("drive_id")

    if assignment_row is not None and current_drive_id != requested_drive_id:
        assignment_row.released_at = datetime.now(timezone.utc)
        if current_drive_id is not None:
            previous_drive = drive_repo.get_for_update(int(current_drive_id))
            if previous_drive:
                previous_drive_row = _row(previous_drive)
                previous_drive_id = cast(int, previous_drive_row.id)
                if _other_active_assignments_for_drive(db, previous_drive_id, exclude_job_id=job_id) == 0:
                    previous_drive_row.current_state = DriveState.AVAILABLE
        db.add(DriveAssignment(drive_id=int(requested_drive_id), job_id=job_id))
    elif assignment_row is None:
        db.add(DriveAssignment(drive_id=int(requested_drive_id), job_id=job_id))

    drive_row.current_state = DriveState.IN_USE
    job_row.evidence_number = body.evidence_number
    job_row.source_path = validated_source_path
    job_row.target_mount_path = drive_mount_path
    job_row.thread_count = int(body.thread_count)
    job_row.max_file_retries = int(body.max_file_retries)
    job_row.retry_delay_seconds = int(body.retry_delay_seconds)
    job_row.callback_url = body.callback_url

    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while updating job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while updating job",
        )

    try:
        audit_repo.add(
            action="JOB_UPDATED",
            user=actor,
            project_id=cast(Optional[str], job_row.project_id),
            drive_id=int(requested_drive_id),
            job_id=job_id,
            details={
                "project_id": cast(Optional[str], job_row.project_id),
                "drive_id": int(requested_drive_id),
                "updated_fields": changed_fields,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_UPDATED")

    db.refresh(job)
    return job


def complete_job(
    job_id: int,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> ExportJob:
    job_repo = JobRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_row = _row(job)
    current_status = cast(JobStatus, job_row.status)
    if current_status not in (JobStatus.PENDING, JobStatus.PAUSED, JobStatus.FAILED):
        raise HTTPException(
            status_code=409,
            detail="Only pending, paused, or failed jobs can be manually completed",
        )

    previous_status = current_status.value
    job_row.status = JobStatus.COMPLETED
    if cast(Optional[datetime], job_row.completed_at) is None:
        job_row.completed_at = datetime.now(timezone.utc)

    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while completing job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while completing job",
        )

    try:
        assignment = DriveAssignmentRepository(db).get_active_for_job(job_id)
        assignment_row = _row(assignment) if assignment is not None else None
        active_drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None
        audit_repo.add(
            action="JOB_COMPLETED_MANUALLY",
            user=actor,
            project_id=cast(Optional[str], job_row.project_id),
            drive_id=active_drive_id,
            job_id=job_id,
            details={
                "project_id": cast(Optional[str], job_row.project_id),
                "previous_status": previous_status,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_COMPLETED_MANUALLY")

    db.refresh(job)
    return job


def delete_job(
    job_id: int,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> dict[str, object]:
    job_repo = JobRepository(db)
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_row = _row(job)
    if cast(JobStatus, job_row.status) != JobStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail="Only pending jobs can be deleted",
        )

    project_id = cast(Optional[str], job_row.project_id)
    assignment = DriveAssignmentRepository(db).get_active_for_job(job_id)
    assignment_row = _row(assignment) if assignment is not None else None
    drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None

    if drive_id is not None:
        drive = drive_repo.get_for_update(int(drive_id))
        if drive and _other_active_assignments_for_drive(db, int(drive_id), exclude_job_id=job_id) == 0:
            drive_row = _row(drive)
            drive_row.current_state = DriveState.AVAILABLE

    db.query(Manifest).filter(Manifest.job_id == job_id).delete(synchronize_session=False)
    db.query(ExportFile).filter(ExportFile.job_id == job_id).delete(synchronize_session=False)
    db.query(DriveAssignment).filter(DriveAssignment.job_id == job_id).delete(synchronize_session=False)
    db.delete(job)

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("DB commit failed while deleting job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while deleting job",
        )

    try:
        audit_repo.add(
            action="JOB_DELETED",
            user=actor,
            project_id=project_id,
            drive_id=drive_id,
            job_id=job_id,
            details={
                "job_id": job_id,
                "project_id": project_id,
                "drive_id": drive_id,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_DELETED")

    return {"job_id": job_id, "status": "deleted"}


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

    job_row = _row(job)
    current_status = cast(JobStatus, job_row.status)
    if current_status not in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.PAUSED):
        raise HTTPException(
            status_code=409, detail=f"Job is already in status {current_status}"
        )

    try:
        job_row.source_path = validate_source_path(
            cast(str, job_row.source_path),
            usb_mount_base_path=settings.usb_mount_base_path,
            target_mount_path=cast(Optional[str], job_row.target_mount_path),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Transition to RUNNING inside the locked transaction so that any concurrent
    # request arriving after this commit will observe the updated state and be
    # rejected with 409 before the background copy task begins.
    job_row.status = JobStatus.RUNNING
    job_row.started_by = actor
    job_row.started_at = datetime.now(timezone.utc)
    job_row.active_duration_seconds = int(cast(Optional[int], job_row.active_duration_seconds) or 0)
    job_row.completed_at = None
    if body.thread_count:
        job_row.thread_count = int(body.thread_count)
    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while starting job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while starting job",
        )

    assignment = DriveAssignmentRepository(db).get_active_for_job(job_id)
    assignment_row = _row(assignment) if assignment is not None else None
    active_drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None
    job_project_id = cast(Optional[str], job_row.project_id)
    job_status = cast(JobStatus, job_row.status)

    logger.debug(
        "Job start context",
        {
            "job_id": job_id,
            "project_id": job_project_id,
            "drive_id": active_drive_id,
            "source_path": cast(Optional[str], job_row.source_path),
            "target_mount_path": cast(Optional[str], job_row.target_mount_path),
            "actor": actor or "system",
        },
    )
    logger.info(
        f"JOB_STARTED job_id={job_id} project_id={job_project_id} "
        f"status={job_status.value} thread_count={job_row.thread_count} actor={actor or 'system'}",
        extra={
            "job_id": job_id,
            "project_id": job_project_id,
            "status": job_status.value,
            "thread_count": cast(Optional[int], job_row.thread_count),
            "actor": actor or "system",
        },
    )

    try:
        audit_repo.add(
            action="JOB_STARTED",
            user=actor,
            project_id=job_project_id,
            drive_id=active_drive_id,
            job_id=job_id,
            details={
                "project_id": job_project_id,
                "drive_id": active_drive_id,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_STARTED")
    background_tasks.add_task(copy_engine.run_copy_job, job_id)
    db.refresh(job)
    return job


def pause_job(
    job_id: int,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> ExportJob:
    job_repo = JobRepository(db)
    audit_repo = AuditRepository(db)

    job = job_repo.get_for_update(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_row = _row(job)
    current_status = cast(JobStatus, job_row.status)
    if current_status != JobStatus.RUNNING:
        raise HTTPException(status_code=409, detail=f"Job is already in status {current_status}")

    job_row.status = JobStatus.PAUSING
    job_row.completed_at = None
    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while pausing job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while pausing job",
        )

    assignment = DriveAssignmentRepository(db).get_active_for_job(job_id)
    assignment_row = _row(assignment) if assignment is not None else None
    active_drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None
    job_project_id = cast(Optional[str], job_row.project_id)
    job_status = cast(JobStatus, job_row.status)

    logger.info(
        f"JOB_PAUSE_REQUESTED job_id={job_id} project_id={job_project_id} status={job_status.value} actor={actor or 'system'}",
        extra={
            "job_id": job_id,
            "project_id": job_project_id,
            "status": job_status.value,
            "actor": actor or "system",
        },
    )

    try:
        audit_repo.add(
            action="JOB_PAUSE_REQUESTED",
            user=actor,
            project_id=job_project_id,
            drive_id=active_drive_id,
            job_id=job_id,
            details={
                "project_id": job_project_id,
                "drive_id": active_drive_id,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for JOB_PAUSE_REQUESTED")

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

    job_row = _row(job)
    job_row.status = JobStatus.VERIFYING
    try:
        job_repo.save(job)
    except Exception:
        logger.exception("DB commit failed while starting verification for job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while starting job verification",
        )
    try:
        assignment = DriveAssignmentRepository(db).get_active_for_job(job_id)
        assignment_row = _row(assignment) if assignment is not None else None
        active_drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None
        job_project_id = cast(Optional[str], job_row.project_id)
        audit_repo.add(
            action="JOB_VERIFY_STARTED",
            user=actor,
            project_id=job_project_id,
            drive_id=active_drive_id,
            job_id=job_id,
            details={
                "project_id": job_project_id,
                "drive_id": active_drive_id,
            },
            client_ip=client_ip,
        )
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

    job_row = _row(job)
    job_project_id = cast(Optional[str], job_row.project_id)
    target_mount_path = cast(Optional[str], job_row.target_mount_path)
    assignment = DriveAssignmentRepository(db).get_active_for_job(job_id)
    assignment_row = _row(assignment) if assignment is not None else None
    active_drive_id = cast(Optional[int], assignment_row.drive_id) if assignment_row is not None else None
    generated_at = datetime.now(timezone.utc).isoformat()
    generated_by = actor or "system"
    manifest_data = {
        "job_id": cast(int, job_row.id),
        "project_id": job_project_id,
        "evidence_number": cast(Optional[str], job_row.evidence_number),
        "generated_at": generated_at,
        "generated_by": generated_by,
        "files": [
            {
                "path": f.relative_path,
                "checksum": f.checksum,
                "size_bytes": f.size_bytes,
            }
            for f in job.files
        ],
    }

    def audit_manifest_failure(error_message: str, manifest_file: Optional[str] = None) -> None:
        try:
            audit_repo.add(
                action="MANIFEST_CREATE_FAILED",
                user=actor,
                project_id=job_project_id,
                drive_id=active_drive_id,
                job_id=job_id,
                details={
                    "project_id": job_project_id,
                    "drive_id": active_drive_id,
                    "manifest_file": manifest_file,
                    "generated_at": generated_at,
                    "generated_by": generated_by,
                    "error": error_message,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.error("Failed to write audit log for MANIFEST_CREATE_FAILED")

    if not target_mount_path:
        manifest_error = "Assigned drive is not mounted"
        logger.warning(
            "Manifest generation rejected",
            extra={"job_id": job_id, "project_id": job_project_id, "reason": "drive_not_mounted"},
        )
        audit_manifest_failure(manifest_error)
        raise HTTPException(status_code=409, detail=manifest_error)

    candidate_path = os.path.join(target_mount_path, "manifest.json")
    manifest_name = os.path.basename(candidate_path)
    try:
        os.makedirs(target_mount_path, exist_ok=True)
        with open(candidate_path, "w", encoding="utf-8") as fp:
            json.dump(manifest_data, fp, indent=2)
    except Exception as exc:
        manifest_error = "Manifest file could not be written"
        logger.warning(
            "Manifest file write failed",
            extra={"job_id": job_id, "project_id": job_project_id},
        )
        logger.debug(
            "Manifest file write failure details",
            {"path": candidate_path, "raw_error": str(exc)},
        )
        audit_manifest_failure(manifest_error, manifest_name)
        raise HTTPException(status_code=500, detail=manifest_error) from exc

    try:
        manifest_repo.add(
            Manifest(job_id=job_id, manifest_path=candidate_path, format="JSON")
        )
    except Exception:
        logger.error("DB commit failed while creating manifest for job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while creating manifest",
        )

    logger.info(
        f"MANIFEST_CREATED job_id={job_id} project_id={job_project_id} format=JSON actor={actor or 'system'} result=written",
        extra={
            "job_id": job_id,
            "project_id": job_project_id,
            "drive_id": active_drive_id,
            "actor": actor or "system",
            "result": "written",
        },
    )
    try:
        audit_repo.add(
            action="MANIFEST_CREATED",
            user=actor,
            project_id=job_project_id,
            drive_id=active_drive_id,
            job_id=job_id,
            details={
                "project_id": job_project_id,
                "drive_id": active_drive_id,
                "manifest_file": manifest_name,
                "generated_at": generated_at,
                "generated_by": generated_by,
                "error": None,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.error("Failed to write audit log for MANIFEST_CREATED")
    db.refresh(job)
    return job
