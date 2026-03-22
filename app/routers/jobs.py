import logging
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.jobs import DriveInfoSchema, ExportJobSchema, JobCreate, JobStart
from app.schemas.errors import R_401, R_403, R_404, R_409, R_422, R_500
from app.services import job_service
from app.utils.client_ip import get_client_ip
from app.models.jobs import FileStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER_PROCESSOR = require_roles("admin", "manager", "processor")

_IP_VISIBLE_ROLES = {"admin", "auditor"}


def _redact_ip(job, user: CurrentUser) -> ExportJobSchema:
    """Serialize an ExportJob, enriching with derived fields and redacting client_ip."""
    schema = ExportJobSchema.model_validate(job)
    if not _IP_VISIBLE_ROLES.intersection(user.roles):
        schema.client_ip = None

    # Derived file counts
    files = getattr(job, "files", None) or []
    schema.files_succeeded = sum(1 for f in files if f.status == FileStatus.DONE)
    schema.files_failed = sum(1 for f in files if f.status == FileStatus.ERROR)

    # Error summary
    errors = [f for f in files if f.status == FileStatus.ERROR and f.error_message]
    if errors:
        parts = [f"{f.error_message} ({f.relative_path})" for f in errors[:5]]
        prefix = f"{len(errors)} file{'s' if len(errors) != 1 else ''} failed: "
        summary = prefix + ", ".join(parts)
        if len(errors) > 5:
            summary += f", ... and {len(errors) - 5} more"
        schema.error_summary = summary

    # Nested drive info
    assignments = getattr(job, "assignments", None) or []
    if assignments and getattr(assignments[0], "drive", None):
        schema.drive = DriveInfoSchema.model_validate(assignments[0].drive)

    return schema


@router.post("", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def create_job(
    body: JobCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Create a new export job to copy eDiscovery data to an assigned drive.

    Initializes the job with source path, target drive, and any additional manifest files.
    The job starts in ``PENDING`` state and awaits ``start_job`` to begin copying.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.create_job(body, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user)


@router.get("/{job_id}", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_422})
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALL_ROLES),
):
    """Retrieve the current state and progress of an export job.

    Returns job metadata, status, copied file count, and any verification results.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    job = job_service.get_job(job_id, db)
    return _redact_ip(job, current_user)


@router.post("/{job_id}/start", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def start_job(
    job_id: int,
    body: JobStart,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Start copying data from the source to the assigned USB drive.

    Launches the copy process in a background task and transitions the job to ``IN_PROGRESS``.
    Progress updates and errors are recorded in the job's status.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.start_job(job_id, body, background_tasks, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user)


@router.post("/{job_id}/verify", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Verify the integrity of copied data by comparing hashes and file counts.

    Launches verification in a background task and transitions the job to ``VERIFYING``.
    Upon completion, sets the job to ``COMPLETED`` if verification succeeds or ``FAILED`` if it fails.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.verify_job(job_id, background_tasks, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user)


@router.post("/{job_id}/manifest", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def create_manifest(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    """Generate a JSON manifest document containing file hashes and copy metadata.

    Creates a manifest file on the USB drive listing all copied files with their
    checksums and sizes. The manifest is written as plain JSON for audit and compliance purposes.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.create_manifest(job_id, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user)
