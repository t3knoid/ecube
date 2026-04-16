import logging
from typing import Dict, List, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.repositories.job_repository import DriveAssignmentRepository, FileRepository
from app.schemas.jobs import DriveInfoSchema, ExportJobSchema, JobCreate, JobFilesResponse, JobStart
from app.schemas.errors import R_400, R_401, R_403, R_404, R_409, R_422, R_500
from app.services import job_service
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER_PROCESSOR = require_roles("admin", "manager", "processor")

_IP_VISIBLE_ROLES = {"admin", "auditor"}


def _build_error_summary(files_failed: int, error_rows: List[Tuple[str, str]]) -> str:
    """Format an error summary string from failure count and error rows."""
    prefix = f"{files_failed} file{'s' if files_failed != 1 else ''} failed"
    if error_rows:
        parts = [
            f"{msg[:120]}{'…' if len(msg) > 120 else ''} ({path[:80]}{'…' if len(path) > 80 else ''})"
            for msg, path in error_rows
        ]
        summary = prefix + ": " + ", ".join(parts)
        unreported = files_failed - len(error_rows)
        if unreported > 0:
            summary += f", ... and {unreported} more"
    else:
        summary = prefix
    if len(summary) > 1024:
        summary = summary[:1021] + "..."
    return summary


def _redact_ip(job, user: CurrentUser, db: Session) -> ExportJobSchema:
    """Serialize an ExportJob, enriching with derived fields and redacting client_ip.

    Used by single-job endpoints (get, create, start).  The list endpoint
    uses :func:`_enrich_jobs_bulk` instead to avoid N+1 queries.
    """
    schema = ExportJobSchema.model_validate(job)
    if not _IP_VISIBLE_ROLES.intersection(user.roles):
        schema.client_ip = None

    # Derived file counts via a single aggregate query
    file_repo = FileRepository(db)
    schema.files_succeeded, schema.files_failed = file_repo.count_done_and_errors(job.id)

    # Error summary (fetches at most 5 rows, truncated to stay brief)
    if schema.files_failed:
        error_rows = file_repo.list_error_messages(job.id, limit=5)
        schema.error_summary = _build_error_summary(schema.files_failed, error_rows)

    # Nested drive info — select the most recent unreleased assignment
    assignment_repo = DriveAssignmentRepository(db)
    active = assignment_repo.get_active_for_job(job.id)
    if active and getattr(active, "drive", None):
        schema.drive = DriveInfoSchema.model_validate(active.drive)

    return schema


def _enrich_jobs_bulk(
    jobs: list, user: CurrentUser, db: Session
) -> List[ExportJobSchema]:
    """Serialize a list of ExportJob models with bulk-fetched aggregates.

    Replaces per-job queries with three bulk queries (file counts, error
    messages, active assignments) regardless of list size.
    """
    if not jobs:
        return []

    redact_ip = not _IP_VISIBLE_ROLES.intersection(user.roles)
    job_ids = [j.id for j in jobs]

    # 1. Bulk file counts — single GROUP BY query
    file_repo = FileRepository(db)
    counts_map: Dict[int, Tuple[int, int]] = file_repo.bulk_count_done_and_errors(job_ids)

    # 2. Bulk error messages — single window-function query for jobs with failures
    failed_job_ids = [jid for jid, (_, errs) in counts_map.items() if errs > 0]
    errors_map: Dict[int, List[Tuple[str, str]]] = (
        file_repo.bulk_list_error_messages(failed_job_ids) if failed_job_ids else {}
    )

    # 3. Bulk active assignments — single query with eager-loaded drives
    assignment_repo = DriveAssignmentRepository(db)
    assignments_map = assignment_repo.bulk_get_active_for_jobs(job_ids)

    # Assemble schemas
    result: List[ExportJobSchema] = []
    for job in jobs:
        schema = ExportJobSchema.model_validate(job)
        if redact_ip:
            schema.client_ip = None

        done, failed = counts_map.get(job.id, (0, 0))
        schema.files_succeeded = done
        schema.files_failed = failed

        if failed:
            error_rows = errors_map.get(job.id, [])
            schema.error_summary = _build_error_summary(failed, error_rows)

        active = assignments_map.get(job.id)
        if active and getattr(active, "drive", None):
            schema.drive = DriveInfoSchema.model_validate(active.drive)

        result.append(schema)
    return result


@router.get("", response_model=list[ExportJobSchema], responses={**R_401, **R_403, **R_422})
def list_jobs(
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum number of jobs to return"),
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALL_ROLES),
):
    """List the most recent export jobs, ordered by creation time descending.

    Returns up to *limit* jobs.  Each job includes status, progress, and
    drive assignment metadata.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    jobs = job_service.list_jobs(db, limit=limit)
    return _enrich_jobs_bulk(jobs, current_user, db)


@router.post("", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def create_job(
    body: JobCreate,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Create a new export job to copy eDiscovery data to an assigned drive.

    Initializes the job with source path, target drive, and any additional manifest files.
    The job starts in ``PENDING`` state and awaits ``start_job`` to begin copying.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.create_job(body, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


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
    return _redact_ip(job, current_user, db)


@router.get("/{job_id}/files", response_model=JobFilesResponse, responses={**R_401, **R_403, **R_404, **R_422})
def get_job_files(
    job_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """Retrieve operator-safe file status rows for an export job.

    Returns per-file copy status and checksum metadata without exposing
    introspection-only path details from system diagnostics endpoints.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    job = job_service.get_job(job_id, db)
    files = FileRepository(db).list_by_job(job.id)
    return JobFilesResponse(job_id=job.id, files=files)


@router.post("/{job_id}/start", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def start_job(
    job_id: int,
    body: JobStart,
    background_tasks: BackgroundTasks,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Start copying data from the source to the assigned USB drive.

    Launches the copy process in a background task and transitions the job to ``RUNNING``.
    Progress updates and errors are recorded in the job's status.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.start_job(job_id, body, background_tasks, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/verify", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Verify the integrity of copied data by comparing hashes and file counts.

    Launches verification in a background task and transitions the job to ``VERIFYING``.
    Upon completion, sets the job to ``COMPLETED`` if verification succeeds or ``FAILED`` if it fails.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.verify_job(job_id, background_tasks, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/manifest", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def create_manifest(
    job_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Generate a JSON manifest document containing file hashes and copy metadata.

    Creates a manifest file on the USB drive listing all copied files with their
    checksums and sizes. The manifest is written as plain JSON for audit and compliance purposes.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.create_manifest(job_id, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)
