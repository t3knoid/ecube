import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, JobStatus, Manifest
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.job_repository import JobChainOfCustodySnapshotRepository, JobRepository
from app.schemas.audit import (
    ChainOfCustodyDriveReportSchema,
    ChainOfCustodyEventSchema,
    ChainOfCustodyHandoffRequest,
    ChainOfCustodyHandoffResponse,
    ChainOfCustodyReportSchema,
    ManifestSummarySchema,
)
from app.services.callback_service import deliver_callback

logger = logging.getLogger(__name__)


def _emit_job_lifecycle_callback(
    job: ExportJob,
    *,
    event: str,
    actor: Optional[str] = None,
    event_at: Optional[datetime] = None,
    event_details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        deliver_callback(
            job,
            event=event,
            event_actor=actor,
            event_at=event_at,
            event_details=event_details,
        )
    except Exception:
        logger.exception(
            "Failed to dispatch lifecycle callback",
            extra={"job_id": job.id, "event": event},
        )

_COC_DRIVE_ACTIONS = {
    "DRIVE_DISCOVERED",
    "DRIVE_INITIALIZED",
    "DRIVE_EJECT_PREPARED",
    "DRIVE_EJECT_FAILED",
    "COC_HANDOFF_CONFIRMED",
}

_COC_JOB_ACTIONS = {
    "JOB_CREATED",
    "JOB_STARTED",
    "JOB_COMPLETED",
    "JOB_FAILED",
    "JOB_ARCHIVED",
    "JOB_VERIFY_STARTED",
    "MANIFEST_CREATED",
    "MANIFEST_DOWNLOADED",
}

_ACTION_LABELS = {
    "MOUNT_SHARE_DISCOVERY_ATTEMPTED": "Mount share discovery attempted",
    "MOUNT_SHARE_DISCOVERY_FAILED": "Mount share discovery failed",
    "MOUNT_UPDATED": "Mount updated",
    "DRIVE_DISCOVERED": "Drive discovered",
    "DRIVE_INITIALIZED": "Drive initialized",
    "JOB_CREATED": "Job created",
    "JOB_STARTED": "Copy operation started",
    "JOB_COMPLETED": "Copy operation completed",
    "JOB_FAILED": "Copy operation failed",
    "JOB_ARCHIVED": "Job archived",
    "JOB_VERIFY_STARTED": "Job verification started",
    "MANIFEST_CREATED": "Manifest generated",
    "MANIFEST_DOWNLOADED": "Manifest downloaded",
    "MANIFEST_CREATE_FAILED": "Manifest generation failed",
    "DRIVE_EJECT_PREPARED": "Drive prepared for eject",
    "DRIVE_EJECT_FAILED": "Drive eject preparation failed",
    "COC_HANDOFF_CONFIRMED": "Custody handoff confirmed",
    "COC_SNAPSHOT_STORED": "Chain of custody snapshot stored",
    "COC_SNAPSHOT_RECALLED": "Stored chain of custody snapshot recalled",
}


def _format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return f"{dt.isoformat()}Z"
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def create_audit_log(
    db: Session,
    action: str,
    user: Optional[str] = None,
    project_id: Optional[str] = None,
    drive_id: Optional[int] = None,
    job_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    client_ip: Optional[str] = None,
) -> AuditLog:
    return AuditRepository(db).add(
        action=action,
        user=user,
        project_id=project_id,
        drive_id=drive_id,
        job_id=job_id,
        details=details,
        client_ip=client_ip,
    )


def log_and_audit(
    db: Session,
    action: str,
    actor_id: Optional[str] = None,
    *,
    level: int = logging.INFO,
    drive_id: Optional[int] = None,
    project_id: Optional[str] = None,
    job_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    client_ip: Optional[str] = None,
) -> AuditLog:
    """Write an event both to the Python logger **and** to the ``audit_logs`` table.

    This helper bridges application-level logging with the database-backed
    audit trail so that security-relevant events are recorded consistently in
    both systems.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    action:
        Machine-readable action code (e.g. ``"DRIVE_INITIALIZED"``).
    actor_id:
        Username or identifier of the acting user (may be ``None`` for system
        events).
    level:
        Python log level (e.g. ``logging.WARNING``).  The message is emitted
        through the ``app.services.audit_service`` logger at this level.
    drive_id, project_id, job_id:
        Optional context IDs included in the structured log record and stored
        in the audit ``details`` column.
    metadata:
        Arbitrary extra context merged into ``details``.
    """
    details: Dict[str, Any] = {}
    if drive_id is not None:
        details["drive_id"] = drive_id
    if project_id is not None:
        details["project_id"] = project_id
    if metadata:
        details.update(metadata)

    log_extra = dict(details)
    log_extra["user_id"] = actor_id

    logger.log(level, action, extra=log_extra)

    return AuditRepository(db).add(
        action=action,
        user=actor_id,
        project_id=project_id,
        drive_id=drive_id,
        job_id=job_id,
        details=details or None,
        client_ip=client_ip,
    )


def purge_expired_audit_logs(db: Session, retention_days: int) -> int:
    """Delete audit log records older than *retention_days*.

    Returns the number of records deleted.  When *retention_days* is ``0``,
    cleanup is skipped and ``0`` is returned.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    count = AuditRepository(db).delete_older_than(cutoff)
    if count:
        logger.info("Purged %d audit log records older than %s", count, cutoff.isoformat())
    return count


def get_chain_of_custody_report(
    db: Session,
    *,
    drive_id: Optional[int],
    drive_sn: Optional[str],
    project_id: Optional[str],
) -> ChainOfCustodyReportSchema:
    selector_mode, drives = _resolve_coc_targets(
        db,
        drive_id=drive_id,
        drive_sn=drive_sn,
        project_id=project_id,
    )
    # project_id takes precedence so that:
    # - PROJECT selector: always uses the queried project (even for
    #   historically-participated drives whose current binding differs).
    # - DRIVE_ID/DRIVE_SN: uses caller's project_id (already validated to match
    #   the binding) or falls back to the drive's own binding.  _resolve_coc_targets
    #   guarantees that at least one is non-None for drive selectors, so
    #   effective_project_id is never None here — preventing cross-lifecycle bleed.
    effective_project_ids: Dict[int, Optional[str]] = {
        d.id: (project_id or d.current_project_id) for d in drives
    }
    reports = _build_all_drive_reports(db, drives, effective_project_ids)
    return ChainOfCustodyReportSchema(
        selector_mode=selector_mode,
        project_id=project_id,
        reports=reports,
    )


def confirm_chain_of_custody_handoff(
    db: Session,
    *,
    payload: ChainOfCustodyHandoffRequest,
    actor: Optional[str],
    client_ip: Optional[str],
    job_id: Optional[int] = None,
    lifecycle_start_at: Optional[datetime] = None,
) -> ChainOfCustodyHandoffResponse:
    # Acquire a per-drive row lock (SELECT … FOR UPDATE NOWAIT on PostgreSQL;
    # silently ignored on SQLite used in tests) before the idempotency check
    # so that two concurrent identical submissions cannot both pass
    # _find_existing_handoff_event() and insert duplicate COC_HANDOFF_CONFIRMED
    # rows.  If the row is already locked, ConflictError (HTTP 409) is raised.
    drive = DriveRepository(db).get_for_update(payload.drive_id)
    if drive is None:
        raise HTTPException(status_code=404, detail="Drive not found")

    if payload.project_id and drive.current_project_id and payload.project_id != drive.current_project_id:
        try:
            AuditRepository(db).add(
                action="PROJECT_ISOLATION_VIOLATION",
                user=actor,
                project_id=payload.project_id,
                drive_id=drive.id,
                details={
                    "actor": actor,
                    "drive_id": drive.id,
                    "existing_project_id": drive.current_project_id,
                    "requested_project_id": payload.project_id,
                    "context": "coc_handoff",
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.error("Failed to write audit log for PROJECT_ISOLATION_VIOLATION")
        raise HTTPException(
            status_code=409,
            detail=(
                f"Provided project_id '{payload.project_id}' does not match drive binding '{drive.current_project_id}'"
            ),
        )

    effective_project_id = payload.project_id or drive.current_project_id

    if effective_project_id is None:
        raise HTTPException(
            status_code=422,
            detail="Drive has no project binding and no project_id was provided; cannot record handoff",
        )

    existing = _find_existing_handoff_event(
        db,
        drive_id=drive.id,
        possessor=payload.possessor,
        delivery_time=payload.delivery_time,
        receipt_ref=payload.receipt_ref,
        project_id=effective_project_id,
        job_id=job_id,
        lifecycle_start_at=lifecycle_start_at,
    )
    if existing is not None:
        return _handoff_response_from_audit(existing)

    created = AuditRepository(db).add_uncommitted(
        action="COC_HANDOFF_CONFIRMED",
        user=actor,
        project_id=effective_project_id,
        drive_id=drive.id,
        job_id=job_id,
        details={
            "drive_id": drive.id,
            "drive_sn": drive.device_identifier,
            "job_id": job_id,
            "project_id": effective_project_id,
            "creator": actor,
            "possessor": payload.possessor,
            "delivery_time": payload.delivery_time.isoformat().replace("+00:00", "Z"),
            "received_by": payload.received_by,
            "receipt_ref": payload.receipt_ref,
            "notes": payload.notes,
        },
        client_ip=client_ip,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _handoff_response_from_audit(created)


def get_job_chain_of_custody_report(
    db: Session,
    *,
    job_id: int,
    actor: Optional[str],
    client_ip: Optional[str],
    allow_persistence: bool = True,
) -> ChainOfCustodyReportSchema:
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    snapshot_repo = JobChainOfCustodySnapshotRepository(db)
    snapshot = snapshot_repo.get_by_job_id(job.id)
    if snapshot is None:
        if job.status == JobStatus.ARCHIVED:
            raise HTTPException(
                status_code=404,
                detail="No stored chain-of-custody snapshot is available for this archived job",
            )
        if not allow_persistence:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No stored chain-of-custody snapshot is available for this job; "
                    "ask an admin or manager to refresh the report to create one"
                ),
            )
        raise HTTPException(
            status_code=404,
            detail="No stored chain-of-custody snapshot is available for this job; refresh the report to create one",
        )

    if allow_persistence:
        AuditRepository(db).add(
            action="COC_SNAPSHOT_RECALLED",
            user=actor,
            project_id=job.project_id,
            job_id=job.id,
            details={
                "job_id": job.id,
                "project_id": job.project_id,
                "stored_at": _format_utc_iso(snapshot.stored_at),
                "updated_at": _format_utc_iso(snapshot.updated_at),
            },
            client_ip=client_ip,
        )
    return _report_with_snapshot_metadata(
        ChainOfCustodyReportSchema.model_validate(snapshot.payload),
        snapshot,
    )


def refresh_job_chain_of_custody_report(
    db: Session,
    *,
    job_id: int,
    actor: Optional[str],
    client_ip: Optional[str],
) -> ChainOfCustodyReportSchema:
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == JobStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Archived jobs can only return the last stored chain-of-custody snapshot")

    report = _build_job_chain_of_custody_report(db, job)
    snapshot = _store_job_chain_of_custody_snapshot(
        db,
        job=job,
        report=report,
        actor=actor,
        client_ip=client_ip,
    )
    return _report_with_snapshot_metadata(report, snapshot)


def confirm_job_chain_of_custody_handoff(
    db: Session,
    *,
    job_id: int,
    payload: ChainOfCustodyHandoffRequest,
    actor: Optional[str],
    client_ip: Optional[str],
) -> ChainOfCustodyHandoffResponse:
    job = JobRepository(db).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if payload.project_id is not None and payload.project_id != job.project_id:
        raise HTTPException(status_code=409, detail="Provided project_id does not match the job project")

    assignment = (
        db.query(DriveAssignment)
        .filter(DriveAssignment.job_id == job.id, DriveAssignment.drive_id == payload.drive_id)
        .one_or_none()
    )
    if assignment is None:
        raise HTTPException(status_code=409, detail="Drive is not assigned to this job")

    response = confirm_chain_of_custody_handoff(
        db,
        payload=payload,
        actor=actor,
        client_ip=client_ip,
        job_id=job.id,
        lifecycle_start_at=_job_drive_lifecycle_start_at(job=job, assignment=assignment),
    )

    refreshed_job = JobRepository(db).get(job.id)
    if refreshed_job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    report = _build_job_chain_of_custody_report(db, refreshed_job)
    _store_job_chain_of_custody_snapshot(
        db,
        job=refreshed_job,
        report=report,
        actor=actor,
        client_ip=client_ip,
    )
    _emit_job_lifecycle_callback(
        refreshed_job,
        event="COC_HANDOFF_CONFIRMED",
        actor=actor,
        event_at=response.recorded_at,
        event_details={
            "drive_id": response.drive_id,
            "project_id": response.project_id,
            "possessor": response.possessor,
            "delivery_time": _format_utc_iso(response.delivery_time),
            "received_by": response.received_by,
            "receipt_ref": response.receipt_ref,
            "recorded_at": _format_utc_iso(response.recorded_at),
        },
    )
    return response


def _resolve_coc_targets(
    db: Session,
    *,
    drive_id: Optional[int],
    drive_sn: Optional[str],
    project_id: Optional[str],
) -> Tuple[str, List[UsbDrive]]:
    if drive_id is None and drive_sn is None and project_id is None:
        raise HTTPException(status_code=422, detail="At least one selector is required")

    if drive_id is not None:
        drive = db.get(UsbDrive, drive_id)
        if drive is None:
            raise HTTPException(status_code=404, detail="Drive not found")
        if project_id and drive.current_project_id and drive.current_project_id != project_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Provided project_id '{project_id}' does not match drive binding '{drive.current_project_id}'"
                ),
            )
        if project_id is None and drive.current_project_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Drive has no project binding; provide project_id to scope "
                    "the report to a specific project lifecycle"
                ),
            )
        return "DRIVE_ID", [drive]

    if drive_sn is not None:
        try:
            drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == drive_sn).one_or_none()
        except MultipleResultsFound:
            raise HTTPException(
                status_code=409,
                detail="drive_sn resolves to multiple drives; provide drive_id to select unambiguously",
            )
        if drive is None:
            raise HTTPException(status_code=404, detail="No drive found for provided drive_sn")
        if project_id and drive.current_project_id and drive.current_project_id != project_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Provided project_id '{project_id}' does not match drive binding '{drive.current_project_id}'"
                ),
            )
        if project_id is None and drive.current_project_id is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Drive has no project binding; provide project_id to scope "
                    "the report to a specific project lifecycle"
                ),
            )
        return "DRIVE_SN", [drive]

    project_drives = db.query(UsbDrive).filter(
        UsbDrive.current_project_id == project_id,
    ).all()

    # Derive historical drive IDs from two authoritative sources:
    # 1. CoC-relevant audit events (lifecycle actions only — not denials like
    #    INIT_REJECTED_* or PROJECT_ISOLATION_VIOLATION which record a drive_id
    #    that was *denied* participation, not one that actually participated).
    # 2. DriveAssignment → ExportJob for the project (captures drives that
    #    had copy jobs even if the audit trail has been purged).
    _COC_HISTORY_ACTIONS = _COC_DRIVE_ACTIONS | _COC_JOB_ACTIONS
    audit_drive_ids = {
        row[0]
        for row in (
            db.query(AuditLog.drive_id)
            .filter(
                AuditLog.project_id == project_id,
                AuditLog.drive_id.isnot(None),
                AuditLog.action.in_(_COC_HISTORY_ACTIONS),
            )
            .distinct()
            .all()
        )
    }
    assignment_drive_ids = {
        row[0]
        for row in (
            db.query(DriveAssignment.drive_id)
            .join(ExportJob, ExportJob.id == DriveAssignment.job_id)
            .filter(ExportJob.project_id == project_id)
            .distinct()
            .all()
        )
    }
    historical_drive_ids = audit_drive_ids | assignment_drive_ids

    # Include drives that historically participated in this project even if they
    # have since been reformatted and reassigned (current_project_id differs).
    historical_drives = (
        db.query(UsbDrive).filter(
            UsbDrive.id.in_(historical_drive_ids),
        ).all()
        if historical_drive_ids
        else []
    )

    seen: set[int] = set()
    merged: List[UsbDrive] = []
    for drive in [*project_drives, *historical_drives]:
        if drive.id in seen:
            continue
        seen.add(drive.id)
        merged.append(drive)
    return "PROJECT", sorted(merged, key=lambda d: d.id)


def _build_all_drive_reports(
    db: Session,
    drives: List[UsbDrive],
    effective_project_ids: Dict[int, Optional[str]],
) -> List[ChainOfCustodyDriveReportSchema]:
    """Assemble CoC reports for all target drives in 4 queries.

    Instead of issuing 4 queries per drive (assignments, events, jobs,
    manifests), this function prefetches all relevant rows for every drive in
    a single round-trip each and partitions results in memory.  This prevents
    O(N) query growth when a project has many drives.
    """
    if not drives:
        return []

    drive_ids = [d.id for d in drives]

    # 1. Batch-fetch all drive assignments together with their job's project_id
    #    so we can apply per-drive project scoping in Python.
    raw_assignments = (
        db.query(DriveAssignment, ExportJob.project_id)
        .join(ExportJob, ExportJob.id == DriveAssignment.job_id)
        .filter(DriveAssignment.drive_id.in_(drive_ids))
        .order_by(DriveAssignment.assigned_at.asc(), DriveAssignment.id.asc())
        .all()
    )
    job_ids_per_drive: Dict[int, set] = {d.id: set() for d in drives}
    for assignment, job_project_id in raw_assignments:
        eff_pid = effective_project_ids.get(assignment.drive_id)
        if eff_pid is None or job_project_id == eff_pid:
            job_ids_per_drive[assignment.drive_id].add(assignment.job_id)

    all_job_ids: List[int] = sorted({jid for jids in job_ids_per_drive.values() for jid in jids})

    # Reverse map: job_id → owning drive_id (used to route job-level events).
    job_id_to_drive_id: Dict[int, int] = {
        jid: did
        for did, jids in job_ids_per_drive.items()
        for jid in jids
    }
    assignment_by_drive_and_job: Dict[tuple[int, int], DriveAssignment] = {}
    for assignment, job_project_id in raw_assignments:
        eff_pid = effective_project_ids.get(assignment.drive_id)
        if eff_pid is None or job_project_id == eff_pid:
            assignment_by_drive_and_job[(assignment.drive_id, assignment.job_id)] = assignment

    # 2. Batch-fetch all relevant audit events in one query, then partition by
    #    drive in Python.  Drive-level events are project-scoped after fetch;
    #    job-level events are already implicitly scoped via job_ids_per_drive.
    event_filters = [
        (AuditLog.drive_id.in_(drive_ids)) & (AuditLog.action.in_(_COC_DRIVE_ACTIONS)),
    ]
    if all_job_ids:
        event_filters.append(
            (AuditLog.job_id.in_(all_job_ids)) & (AuditLog.action.in_(_COC_JOB_ACTIONS))
        )
    all_events: List[AuditLog] = (
        db.query(AuditLog)
        .filter(or_(*event_filters))
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )

    events_per_drive: Dict[int, List[AuditLog]] = {d.id: [] for d in drives}
    for event in all_events:
        if event.action in _COC_DRIVE_ACTIONS:
            if event.drive_id not in events_per_drive:
                continue
            eff_pid = effective_project_ids.get(event.drive_id)
            if eff_pid is None or event.project_id == eff_pid:
                events_per_drive[event.drive_id].append(event)
        elif event.action in _COC_JOB_ACTIONS and event.job_id is not None:
            owner = job_id_to_drive_id.get(event.job_id)
            if owner is not None:
                events_per_drive[owner].append(event)

    job_creation_details_by_job = _extract_job_creation_details(all_events)

    # 3–4. Batch-fetch jobs and manifests for manifest summary assembly.
    jobs_by_id: Dict[int, ExportJob] = {}
    manifests_by_job: Dict[int, List[Manifest]] = {}
    if all_job_ids:
        for job in db.query(ExportJob).filter(ExportJob.id.in_(all_job_ids)).all():
            jobs_by_id[job.id] = job
        for manifest in db.query(Manifest).filter(Manifest.job_id.in_(all_job_ids)).all():
            manifests_by_job.setdefault(manifest.job_id, []).append(manifest)

    # Assemble one report per drive from the pre-fetched data.
    drive_map = {d.id: d for d in drives}
    reports: List[ChainOfCustodyDriveReportSchema] = []
    for drive_id_key in sorted(drive_map):
        drive = drive_map[drive_id_key]
        events = events_per_drive[drive_id_key]

        coc_events: List[ChainOfCustodyEventSchema] = [
            ChainOfCustodyEventSchema(
                event_id=e.id,
                event_type=e.action,
                timestamp=e.timestamp,
                actor=e.user,
                action=_ACTION_LABELS.get(e.action, e.action.replace("_", " ").title()),
                details=e.details or {},
            )
            for e in events
        ]

        handoff_events = [e for e in events if e.action == "COC_HANDOFF_CONFIRMED"]
        latest_handoff = handoff_events[-1] if handoff_events else None
        delivery_time = (
            _parse_iso_datetime((latest_handoff.details or {}).get("delivery_time"))
            if latest_handoff else None
        )

        # Report the project scope that was actually used to filter events, not
        # necessarily the drive's current binding (they diverge for reassigned
        # drives or when the PROJECT selector requested a specific project).
        reports.append(
            ChainOfCustodyDriveReportSchema(
                drive_id=drive.id,
                drive_sn=drive.device_identifier,
                drive_manufacturer=drive.manufacturer,
                drive_model=drive.product_name,
                project_id=effective_project_ids[drive_id_key],
                evidence_number=next(
                    (
                        jobs_by_id[job_id].evidence_number
                        for job_id in sorted(job_ids_per_drive[drive_id_key])
                        if jobs_by_id.get(job_id) is not None and jobs_by_id[job_id].evidence_number
                    ),
                    None,
                ),
                custody_complete=latest_handoff is not None,
                delivery_time=delivery_time,
                chain_of_custody_events=coc_events,
                manifest_summary=_assemble_manifest_summary(
                    drive_id_key,
                    sorted(job_ids_per_drive[drive_id_key]),
                    jobs_by_id,
                    manifests_by_job,
                    assignment_by_drive_and_job,
                    job_creation_details_by_job,
                ),
            )
        )

    return reports


def _build_job_chain_of_custody_report(
    db: Session,
    job: ExportJob,
) -> ChainOfCustodyReportSchema:
    assignments = (
        db.query(DriveAssignment)
        .join(UsbDrive, UsbDrive.id == DriveAssignment.drive_id)
        .filter(DriveAssignment.job_id == job.id)
        .order_by(DriveAssignment.assigned_at.asc(), DriveAssignment.id.asc())
        .all()
    )
    if not assignments:
        raise HTTPException(status_code=409, detail="Job has no drive assignments for chain-of-custody reporting")

    drives_by_id: Dict[int, UsbDrive] = {}
    assignment_by_drive_and_job: Dict[tuple[int, int], DriveAssignment] = {}
    for assignment in assignments:
        if assignment.drive is None:
            continue
        drives_by_id[assignment.drive_id] = assignment.drive
        assignment_by_drive_and_job[(assignment.drive_id, job.id)] = assignment

    drives = [drives_by_id[drive_id] for drive_id in sorted(drives_by_id)]
    if not drives:
        raise HTTPException(status_code=409, detail="Job has no drive assignments for chain-of-custody reporting")

    drive_ids = [drive.id for drive in drives]
    drive_events = (
        db.query(AuditLog)
        .filter(
            AuditLog.drive_id.in_(drive_ids),
            AuditLog.action.in_(_COC_DRIVE_ACTIONS),
            AuditLog.project_id == job.project_id,
        )
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    job_events = (
        db.query(AuditLog)
        .filter(
            AuditLog.job_id == job.id,
            AuditLog.action.in_(_COC_JOB_ACTIONS),
        )
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    manifests = db.query(Manifest).filter(Manifest.job_id == job.id).all()

    manifests_by_job = {job.id: manifests}
    jobs_by_id = {job.id: job}
    job_creation_details_by_job = _extract_job_creation_details(job_events)
    reports: List[ChainOfCustodyDriveReportSchema] = []
    for drive in drives:
        lifecycle_start_at = _job_drive_lifecycle_start_at(
            job=job,
            assignment=assignment_by_drive_and_job.get((drive.id, job.id)),
        )
        events = [
            event
            for event in drive_events
            if event.drive_id == drive.id
            and (
                event.action != "COC_HANDOFF_CONFIRMED"
                or _handoff_event_matches_job_lifecycle(
                    event,
                    job_id=job.id,
                    lifecycle_start_at=lifecycle_start_at,
                )
            )
        ]
        events.extend(job_events)
        events.sort(key=lambda row: (row.timestamp, row.id))

        coc_events = [
            ChainOfCustodyEventSchema(
                event_id=event.id,
                event_type=event.action,
                timestamp=event.timestamp,
                actor=event.user,
                action=_ACTION_LABELS.get(event.action, event.action.replace("_", " ").title()),
                details=event.details or {},
            )
            for event in events
        ]

        handoff_events = [event for event in events if event.action == "COC_HANDOFF_CONFIRMED"]
        latest_handoff = handoff_events[-1] if handoff_events else None
        delivery_time = (
            _parse_iso_datetime((latest_handoff.details or {}).get("delivery_time"))
            if latest_handoff is not None else None
        )

        reports.append(
            ChainOfCustodyDriveReportSchema(
                drive_id=drive.id,
                drive_sn=drive.device_identifier,
                drive_manufacturer=drive.manufacturer,
                drive_model=drive.product_name,
                project_id=job.project_id,
                evidence_number=job.evidence_number,
                custody_complete=latest_handoff is not None,
                delivery_time=delivery_time,
                chain_of_custody_events=coc_events,
                manifest_summary=_assemble_manifest_summary(
                    drive.id,
                    [job.id],
                    jobs_by_id,
                    manifests_by_job,
                    assignment_by_drive_and_job,
                    job_creation_details_by_job,
                ),
            )
        )

    return ChainOfCustodyReportSchema(
        selector_mode="JOB",
        project_id=job.project_id,
        reports=reports,
    )


def _store_job_chain_of_custody_snapshot(
    db: Session,
    *,
    job: ExportJob,
    report: ChainOfCustodyReportSchema,
    actor: Optional[str],
    client_ip: Optional[str],
) -> JobChainOfCustodySnapshotRepository:
    payload = report.model_dump(mode="json")
    snapshot = JobChainOfCustodySnapshotRepository(db).upsert_for_job(
        job_id=job.id,
        payload=payload,
        stored_by=actor,
    )
    AuditRepository(db).add(
        action="COC_SNAPSHOT_STORED",
        user=actor,
        project_id=job.project_id,
        job_id=job.id,
        details={
            "job_id": job.id,
            "project_id": job.project_id,
            "report_count": len(report.reports),
        },
        client_ip=client_ip,
    )
    logger.info(
        "Stored chain-of-custody snapshot",
        {
            "job_id": job.id,
            "project_id": job.project_id,
            "report_count": len(report.reports),
            "stored_by": actor,
            "snapshot_updated_at": _format_utc_iso(snapshot.updated_at),
        },
    )
    logger.debug(
        "Stored chain-of-custody snapshot details",
        {
            "job_id": job.id,
            "snapshot_id": snapshot.id,
            "snapshot_stored_at": _format_utc_iso(snapshot.stored_at),
            "snapshot_updated_at": _format_utc_iso(snapshot.updated_at),
        },
    )
    _emit_job_lifecycle_callback(
        job,
        event="COC_SNAPSHOT_STORED",
        actor=actor,
        event_at=snapshot.updated_at,
        event_details={
            "report_count": len(report.reports),
            "snapshot_stored_at": _format_utc_iso(snapshot.stored_at),
            "snapshot_updated_at": _format_utc_iso(snapshot.updated_at),
        },
    )
    return snapshot


def _report_with_snapshot_metadata(
    report: ChainOfCustodyReportSchema,
    snapshot,
) -> ChainOfCustodyReportSchema:
    return report.model_copy(
        update={
            "snapshot_stored_at": snapshot.stored_at,
            "snapshot_updated_at": snapshot.updated_at,
            "snapshot_stored_by": snapshot.stored_by,
        }
    )


def _assemble_manifest_summary(
    drive_id: int,
    job_ids: List[int],
    jobs_by_id: Dict[int, ExportJob],
    manifests_by_job: Dict[int, List[Manifest]],
    assignment_by_drive_and_job: Dict[tuple[int, int], DriveAssignment],
    job_creation_details_by_job: Dict[int, Dict[str, Any]],
) -> List[ManifestSummarySchema]:
    summaries: List[ManifestSummarySchema] = []
    for jid in job_ids:
        job = jobs_by_id.get(jid)
        assignment = assignment_by_drive_and_job.get((drive_id, jid))
        if job is None:
            continue
        rows = sorted(
            manifests_by_job.get(jid, []),
            key=lambda row: ((row.created_at or datetime.min.replace(tzinfo=timezone.utc)), row.id),
        )
        latest = rows[-1] if rows else None
        summaries.append(
            ManifestSummarySchema(
                job_id=job.id,
                evidence_number=job.evidence_number,
                processor_notes=(job_creation_details_by_job.get(jid, {}).get("processor_notes")
                    or job_creation_details_by_job.get(jid, {}).get("notes")),
                total_files=(assignment.file_count if assignment is not None else 0) or 0,
                total_bytes=(assignment.copied_bytes if assignment is not None else 0) or 0,
                manifest_count=len(rows),
                latest_manifest_path=latest.manifest_path if latest else None,
                latest_manifest_format=latest.format if latest else None,
                latest_manifest_created_at=latest.created_at if latest else None,
            )
        )
    return summaries


def _find_existing_handoff_event(
    db: Session,
    *,
    drive_id: int,
    possessor: str,
    delivery_time: datetime,
    receipt_ref: Optional[str],
    project_id: str,
    job_id: Optional[int] = None,
    lifecycle_start_at: Optional[datetime] = None,
) -> Optional[AuditLog]:
    # Scope idempotency to the resolved project lifecycle and, when available,
    # the specific job lifecycle so a reused drive cannot satisfy a later job.
    query = db.query(AuditLog).filter(
        AuditLog.action == "COC_HANDOFF_CONFIRMED",
        AuditLog.drive_id == drive_id,
        AuditLog.project_id == project_id,
    )
    candidates = query.order_by(AuditLog.id.desc()).all()
    delivery_iso = delivery_time.isoformat().replace("+00:00", "Z")
    for row in candidates:
        if not _handoff_event_matches_job_lifecycle(
            row,
            job_id=job_id,
            lifecycle_start_at=lifecycle_start_at,
        ):
            continue
        details = row.details or {}
        if details.get("possessor") != possessor:
            continue
        if (details.get("delivery_time") or "").replace("+00:00", "Z") != delivery_iso:
            continue
        if details.get("receipt_ref") != receipt_ref:
            continue
        return row
    return None


def _handoff_event_matches_job_lifecycle(
    event: AuditLog,
    *,
    job_id: Optional[int],
    lifecycle_start_at: Optional[datetime],
) -> bool:
    if job_id is None:
        return True
    if event.job_id == job_id:
        return True
    if event.job_id is not None:
        return False
    if lifecycle_start_at is None:
        return False
    return event.timestamp is not None and event.timestamp >= lifecycle_start_at


def _job_drive_lifecycle_start_at(
    *,
    job: ExportJob,
    assignment: Optional[DriveAssignment],
) -> Optional[datetime]:
    return (
        (assignment.assigned_at if assignment is not None else None)
        or job.created_at
        or job.started_at
        or job.completed_at
    )


def _handoff_response_from_audit(entry: AuditLog) -> ChainOfCustodyHandoffResponse:
    details = entry.details or {}
    return ChainOfCustodyHandoffResponse(
        event_id=entry.id,
        event_type=entry.action,
        drive_id=entry.drive_id or int(details.get("drive_id") or 0),
        project_id=entry.project_id,
        creator=details.get("creator") or entry.user,
        possessor=details.get("possessor") or "",
        delivery_time=_parse_iso_datetime(details.get("delivery_time")) or entry.timestamp,
        received_by=details.get("received_by"),
        receipt_ref=details.get("receipt_ref"),
        notes=details.get("notes"),
        recorded_at=entry.timestamp,
    )


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _extract_job_creation_details(events: List[AuditLog]) -> Dict[int, Dict[str, Any]]:
    details_by_job: Dict[int, Dict[str, Any]] = {}
    for event in events:
        if event.action != "JOB_CREATED" or event.job_id is None:
            continue
        details_by_job[event.job_id] = event.details or {}
    return details_by_job
