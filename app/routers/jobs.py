import logging
import os
import re
from io import BytesIO
from typing import Dict, List, Tuple

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.config import settings
from app.database import get_db
from app.models.audit import AuditLog
from app.models.jobs import JobStatus
from app.repositories.job_repository import DriveAssignmentRepository, FileRepository
from app.schemas.jobs import (
    DriveInfoSchema,
    ExportJobSchema,
    JobAnalyzeRequest,
    JobCreate,
    JobDeleteResponse,
    JobFilesResponse,
    JobStart,
    JobStartupAnalysisClearRequest,
    JobUpdate,
)
from app.schemas.errors import R_400, R_401, R_403, R_404, R_409, R_422, R_500
from app.services import job_service
from app.utils.client_ip import get_client_ip
from app.utils.sanitize import redact_pathlike_substrings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")
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


def _candidate_log_paths() -> list[str]:
    """Return the configured app log and numeric rotations, newest first."""
    if not settings.log_file:
        return []

    base_path = os.path.abspath(settings.log_file)
    log_dir = os.path.dirname(base_path)
    base_name = os.path.basename(base_path)
    candidates = [base_path]

    if not log_dir or not os.path.isdir(log_dir):
        return candidates

    rotation_pattern = re.compile(rf"^{re.escape(base_name)}\.(\d+)$")
    rotations: list[tuple[int, str]] = []
    try:
        for entry in os.listdir(log_dir):
            match = rotation_pattern.fullmatch(entry)
            if match:
                rotations.append((int(match.group(1)), os.path.join(log_dir, entry)))
    except OSError:
        return candidates

    candidates.extend(path for _, path in sorted(rotations))
    return candidates


def _find_recent_log_match(needle: str | list[str]) -> str | None:
    """Return the newest matching line from the app log family."""
    needles = [needle] if isinstance(needle, str) else [term for term in needle if term]
    lowered_needles = [term.lower() for term in needles]
    if not lowered_needles:
        return None

    chunk_size = 64 * 1024

    for path in _candidate_log_paths():
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                position = handle.tell()
                carry = b""

                while position > 0:
                    read_size = min(chunk_size, position)
                    position -= read_size
                    handle.seek(position)
                    data = handle.read(read_size) + carry
                    parts = data.split(b"\n")

                    if position > 0:
                        carry = parts[0]
                        lines = parts[1:]
                    else:
                        carry = b""
                        lines = parts

                    for raw_line in reversed(lines):
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        lowered_line = line.lower()
                        if any(term in lowered_line for term in lowered_needles):
                            return redact_pathlike_substrings(line)
        except OSError:
            continue

    return None


def _build_failure_audit_fallback(schema: ExportJobSchema, db: Session) -> str | None:
    """Return a sanitized synthetic failure event when file logs are unavailable."""
    event = (
        db.query(AuditLog)
        .filter(
            AuditLog.job_id == schema.id,
            AuditLog.action.in_(("JOB_FAILED", "JOB_TIMEOUT", "JOB_RECONCILED")),
        )
        .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .first()
    )
    if event is None:
        return None

    details = event.details if isinstance(event.details, dict) else {}
    reason = details.get("failure_reason") or details.get("reason")
    reason_text = str(reason).strip() if isinstance(reason, str) else ""

    timestamp = event.timestamp.isoformat() if event.timestamp is not None else "unknown-time"
    line = f"{timestamp} [AUDIT] {event.action} job_id={schema.id}"
    if reason_text:
        line += f" reason={reason_text}"
    return redact_pathlike_substrings(line)


def _build_failure_log_entry(schema: ExportJobSchema, db: Session) -> str | None:
    """Return a real correlated application-log line for failed jobs."""
    status_value = getattr(schema.status, "value", schema.status)
    status = str(status_value or "").upper()
    if status != "FAILED":
        return None

    search_terms = [
        f"JOB_FAILED job_id={schema.id}",
        f"FILE_COPY_FAILURE job_id={schema.id}",
        f"JOB_TIMEOUT job_id={schema.id}",
        f"Unexpected copy job failure for job {schema.id}",
        f"path=/jobs/{schema.id}/start",
        f"path=/jobs/{schema.id}/verify",
    ]
    log_match = _find_recent_log_match(search_terms)
    if log_match:
        return log_match
    return _build_failure_audit_fallback(schema, db)


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
    (
        schema.files_succeeded,
        schema.files_failed,
        schema.files_timed_out,
    ) = file_repo.count_done_errors_and_timeouts(job.id)

    # Error summary (fetches at most 5 rows, truncated to stay brief)
    if schema.files_failed and not schema.failure_reason:
        error_rows = file_repo.list_error_messages(job.id, limit=5)
        schema.error_summary = _build_error_summary(schema.files_failed, error_rows)

    schema.failure_log_entry = _build_failure_log_entry(schema, db)

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
    counts_map: Dict[int, Tuple[int, int, int]] = file_repo.bulk_count_done_errors_and_timeouts(job_ids)

    # 2. Bulk error messages — single window-function query for jobs with failures
    failed_job_ids = [jid for jid, (_done, errs, _timeouts) in counts_map.items() if errs > 0]
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

        done, failed, timed_out = counts_map.get(job.id, (0, 0, 0))
        schema.files_succeeded = done
        schema.files_failed = failed
        schema.files_timed_out = timed_out

        if failed and not schema.failure_reason:
            error_rows = errors_map.get(job.id, [])
            schema.error_summary = _build_error_summary(failed, error_rows)

        schema.failure_log_entry = None

        active = assignments_map.get(job.id)
        if active and getattr(active, "drive", None):
            schema.drive = DriveInfoSchema.model_validate(active.drive)

        result.append(schema)
    return result


@router.get("", response_model=list[ExportJobSchema], responses={**R_401, **R_403, **R_422})
def list_jobs(
    limit: int = Query(default=200, ge=1, le=1000, description="Maximum number of jobs to return"),
    offset: int = Query(default=0, ge=0, description="Number of jobs to skip before returning results"),
    drive_id: int | None = Query(default=None, ge=1, description="Filter jobs by currently assigned drive ID"),
    statuses: list[JobStatus] | None = Query(default=None, description="Filter jobs by status"),
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALL_ROLES),
):
    """List the most recent export jobs, ordered by creation time descending.

    Returns up to *limit* jobs.  Each job includes status, progress, and
    drive assignment metadata.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    jobs = job_service.list_jobs(
        db,
        limit=limit,
        offset=offset,
        drive_id=drive_id,
        statuses=tuple(statuses) if statuses else None,
    )
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


@router.put("/{job_id}", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def update_job(
    job_id: int,
    body: JobUpdate,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Update a non-active job from the Job Detail workflow.

    Editing is limited to safe non-active states so that project isolation and
    drive assignments remain consistent.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.update_job(job_id, body, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.delete("/{job_id}", response_model=JobDeleteResponse, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def delete_job(
    job_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Delete a job that has not yet started.

    Only ``PENDING`` jobs may be removed so that in-flight evidence operations
    are never destroyed from the UI.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    return job_service.delete_job(job_id, db, actor=current_user.username, client_ip=get_client_ip(request))


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
    page: int = Query(default=1, ge=1, description="1-based page number of file rows to return"),
    limit: int | None = Query(default=None, ge=20, le=100, description="Maximum number of file rows to return"),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """Retrieve operator-safe file status rows for an export job.

    Returns per-file copy status and checksum metadata without exposing
    introspection-only path details from system diagnostics endpoints.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    job = job_service.get_job(job_id, db)
    file_repo = FileRepository(db)
    effective_limit = int(limit or settings.job_detail_files_page_size)
    offset = (page - 1) * effective_limit
    files = file_repo.list_by_job(job.id, limit=effective_limit, offset=offset)
    return JobFilesResponse(
        job_id=job.id,
        page=page,
        page_size=effective_limit,
        total_files=file_repo.count_by_job(job.id),
        returned_files=len(files),
        files=files,
    )


@router.post("/{job_id}/start", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def start_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    body: JobStart = Body(default_factory=JobStart),
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


@router.post("/{job_id}/retry-failed", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def retry_failed_files(
    job_id: int,
    background_tasks: BackgroundTasks,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Retry failed and timed-out file copies for a partially successful completed job.

    Available only for ``COMPLETED`` jobs that still contain file rows in
    ``ERROR`` or ``TIMEOUT`` state. The operation re-queues only those failed
    terminal files, leaves successful copies unchanged, and restarts the copy
    engine for that narrowed retry set.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.retry_failed_files(
        job_id,
        background_tasks,
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/analyze", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def analyze_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    body: JobAnalyzeRequest = Body(default_factory=JobAnalyzeRequest),
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Run startup analysis and persist prepared job/file state without starting copy workers.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    _ = body
    job = job_service.analyze_job(job_id, background_tasks, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/complete", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def complete_job(
    job_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Manually mark a safe non-active job as completed.

    This override is limited to non-active states and records an audit entry.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.complete_job(job_id, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/pause", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def pause_job(
    job_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Request a safe pause for an actively running export job.

    The job enters ``PAUSING`` immediately and transitions to ``PAUSED`` once
    in-flight copy threads finish their current work.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.pause_job(job_id, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/startup-analysis/clear", response_model=ExportJobSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_422, **R_500})
def clear_startup_analysis_cache(
    job_id: int,
    body: JobStartupAnalysisClearRequest,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Clear the persisted startup-analysis cache for a job after explicit confirmation.

    This removes only the cached startup-analysis snapshot and preserves the
    per-file copy history used for audit and resume state.

    **Roles:** ``admin``, ``manager``
    """
    job = job_service.clear_job_startup_analysis_cache(
        job_id,
        confirm=body.confirm,
        db=db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/verify", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Verify the integrity of copied data by comparing hashes and file counts.

    Available only for clean ``COMPLETED`` jobs with no failed or timed-out files.
    Launches verification in a background task and transitions the job to ``VERIFYING``.
    Jobs outside that precondition return ``409 Conflict``. Upon completion,
    the job returns to ``COMPLETED`` if verification succeeds or moves to
    ``FAILED`` if verification fails.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.verify_job(job_id, background_tasks, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.post("/{job_id}/manifest", response_model=ExportJobSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def create_manifest(
    job_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Generate a JSON manifest document containing file hashes and copy metadata.

    Available only for clean ``COMPLETED`` jobs with no failed or timed-out
    files. Jobs outside that precondition return ``409 Conflict``.
    Creates a manifest file on the USB drive listing all copied files with their
    checksums and sizes. The manifest is written as plain JSON for audit and
    compliance purposes.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    job = job_service.create_manifest(job_id, db, actor=current_user.username, client_ip=get_client_ip(request))
    return _redact_ip(job, current_user, db)


@router.get("/{job_id}/manifest/download", responses={**R_401, **R_403, **R_404, **R_500})
def download_manifest(
    job_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
    request: Request,
):
    """Download the most recently generated manifest for a job as JSON.

    Available only to the same roles that can generate manifests and returns
    the latest manifest content without exposing the host filesystem path.

    **Roles:** ``admin``, ``manager``, ``processor``
    """
    manifest_bytes, manifest_name = job_service.download_manifest(
        job_id,
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )
    return StreamingResponse(
        BytesIO(manifest_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{manifest_name}"'},
    )
