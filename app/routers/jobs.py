from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.jobs import ExportJobSchema, JobCreate, JobStart
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER_PROCESSOR = require_roles("admin", "manager", "processor")


@router.post("", response_model=ExportJobSchema)
def create_job(
    body: JobCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Create a new export job to copy eDiscovery data to an assigned drive.

    Initializes the job with source path, target drive, and any additional manifest files.
    The job starts in ``PENDING`` state and awaits ``start_job`` to begin copying.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    return job_service.create_job(body, db, actor=current_user.username)


@router.get("/{job_id}", response_model=ExportJobSchema)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """Retrieve the current state and progress of an export job.

    Returns job metadata, status, copied file count, and any verification results.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return job_service.get_job(job_id, db)


@router.post("/{job_id}/start", response_model=ExportJobSchema)
def start_job(
    job_id: int,
    body: JobStart,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Start copying data from the source to the assigned USB drive.

    Launches the copy process in a background task and transitions the job to ``IN_PROGRESS``.
    Progress updates and errors are recorded in the job's status.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    return job_service.start_job(job_id, body, background_tasks, db, actor=current_user.username)


@router.post("/{job_id}/verify", response_model=ExportJobSchema)
def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Verify the integrity of copied data by comparing hashes and file counts.

    Launches verification in a background task and transitions the job to ``VERIFYING``.
    Upon completion, sets the job to ``COMPLETED`` if verification succeeds or ``FAILED`` if it fails.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    return job_service.verify_job(job_id, background_tasks, db, actor=current_user.username)


@router.post("/{job_id}/manifest", response_model=ExportJobSchema)
def create_manifest(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Generate a JSON manifest document containing file hashes and copy metadata.

    Creates a manifest file on the USB drive listing all copied files with their
    checksums and sizes. The manifest is written as plain JSON for audit and compliance purposes.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    return job_service.create_manifest(job_id, db, actor=current_user.username)
