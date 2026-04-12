import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, Manifest
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import (
    ChainOfCustodyDriveReportSchema,
    ChainOfCustodyEventSchema,
    ChainOfCustodyHandoffRequest,
    ChainOfCustodyHandoffResponse,
    ChainOfCustodyReportSchema,
    ManifestSummarySchema,
)

logger = logging.getLogger(__name__)

_COC_DRIVE_ACTIONS = {
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
    "JOB_VERIFY_STARTED",
    "MANIFEST_CREATED",
}

_ACTION_LABELS = {
    "DRIVE_INITIALIZED": "Drive initialized",
    "JOB_CREATED": "Job created",
    "JOB_STARTED": "Copy operation started",
    "JOB_COMPLETED": "Copy operation completed",
    "JOB_FAILED": "Copy operation failed",
    "JOB_VERIFY_STARTED": "Job verification started",
    "MANIFEST_CREATED": "Manifest generated",
    "DRIVE_EJECT_PREPARED": "Drive prepared for eject",
    "DRIVE_EJECT_FAILED": "Drive eject preparation failed",
    "COC_HANDOFF_CONFIRMED": "Custody handoff confirmed",
}


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
    reports = [_build_drive_report(db, drive=d) for d in drives]
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
) -> ChainOfCustodyHandoffResponse:
    drive = db.get(UsbDrive, payload.drive_id)
    if drive is None:
        raise HTTPException(status_code=404, detail="Drive not found")

    if payload.project_id and drive.current_project_id and payload.project_id != drive.current_project_id:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Provided project_id '{payload.project_id}' does not match drive binding '{drive.current_project_id}'"
            ),
        )

    effective_project_id = payload.project_id or drive.current_project_id

    existing = _find_existing_handoff_event(
        db,
        drive_id=drive.id,
        possessor=payload.possessor,
        delivery_time=payload.delivery_time,
        receipt_ref=payload.receipt_ref,
    )
    if existing is not None:
        return _handoff_response_from_audit(existing)

    created = AuditRepository(db).add_uncommitted(
        action="COC_HANDOFF_CONFIRMED",
        user=actor,
        project_id=effective_project_id,
        drive_id=drive.id,
        details={
            "drive_id": drive.id,
            "drive_sn": drive.device_identifier,
            "project_id": effective_project_id,
            "creator": actor,
            "possessor": payload.possessor,
            "delivery_time": payload.delivery_time.isoformat(),
            "received_by": payload.received_by,
            "receipt_ref": payload.receipt_ref,
            "notes": payload.notes,
        },
        client_ip=client_ip,
    )

    # Transition drive to ARCHIVED state after successful handoff to remove from active circulation
    drive.current_state = DriveState.ARCHIVED
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _handoff_response_from_audit(created)


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
        if drive.current_state == DriveState.ARCHIVED:
            raise HTTPException(status_code=410, detail="Drive has been archived after handoff and is no longer available for reporting")
        if project_id and drive.current_project_id and drive.current_project_id != project_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Provided project_id '{project_id}' does not match drive binding '{drive.current_project_id}'"
                ),
            )
        return "DRIVE_ID", [drive]

    if drive_sn is not None:
        matches = db.query(UsbDrive).filter(UsbDrive.device_identifier == drive_sn).all()
        if not matches:
            raise HTTPException(status_code=404, detail="No drive found for provided drive_sn")
        if len(matches) > 1:
            raise HTTPException(status_code=409, detail="drive_sn resolves to multiple drives; provide drive_id")
        drive = matches[0]
        if drive.current_state == DriveState.ARCHIVED:
            raise HTTPException(status_code=410, detail="Drive has been archived after handoff and is no longer available for reporting")
        if project_id and drive.current_project_id and drive.current_project_id != project_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Provided project_id '{project_id}' does not match drive binding '{drive.current_project_id}'"
                ),
            )
        return "DRIVE_SN", [drive]

    project_drives = db.query(UsbDrive).filter(
        UsbDrive.current_project_id == project_id,
        UsbDrive.current_state != DriveState.ARCHIVED
    ).all()
    historical_drive_ids = [
        row[0]
        for row in (
            db.query(AuditLog.drive_id)
            .filter(AuditLog.project_id == project_id, AuditLog.drive_id.isnot(None))
            .distinct()
            .all()
        )
    ]
    historical_drives = (
        db.query(UsbDrive).filter(
            UsbDrive.id.in_(historical_drive_ids),
            UsbDrive.current_state != DriveState.ARCHIVED
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


def _build_drive_report(db: Session, *, drive: UsbDrive) -> ChainOfCustodyDriveReportSchema:
    assignment_rows: Sequence[DriveAssignment] = (
        db.query(DriveAssignment)
        .filter(DriveAssignment.drive_id == drive.id)
        .order_by(DriveAssignment.assigned_at.asc(), DriveAssignment.id.asc())
        .all()
    )
    job_ids = {row.job_id for row in assignment_rows}

    filters = [
        (AuditLog.drive_id == drive.id) & (AuditLog.action.in_(_COC_DRIVE_ACTIONS))
    ]
    if job_ids:
        filters.append((AuditLog.job_id.in_(job_ids)) & (AuditLog.action.in_(_COC_JOB_ACTIONS)))

    events = (
        db.query(AuditLog)
        .filter(or_(*filters))
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )

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
    delivery_time = _parse_iso_datetime((latest_handoff.details or {}).get("delivery_time")) if latest_handoff else None

    manifest_summary = _build_manifest_summary(db, sorted(job_ids))

    return ChainOfCustodyDriveReportSchema(
        drive_id=drive.id,
        drive_sn=drive.device_identifier,
        project_id=drive.current_project_id,
        custody_complete=latest_handoff is not None,
        delivery_time=delivery_time,
        chain_of_custody_events=coc_events,
        manifest_summary=manifest_summary,
    )


def _build_manifest_summary(db: Session, job_ids: List[int]) -> List[ManifestSummarySchema]:
    if not job_ids:
        return []

    jobs = db.query(ExportJob).filter(ExportJob.id.in_(job_ids)).all()
    manifests = db.query(Manifest).filter(Manifest.job_id.in_(job_ids)).all()

    manifests_by_job: Dict[int, List[Manifest]] = {}
    for manifest in manifests:
        manifests_by_job.setdefault(manifest.job_id, []).append(manifest)

    summaries: List[ManifestSummarySchema] = []
    for job in sorted(jobs, key=lambda row: row.id):
        rows = sorted(
            manifests_by_job.get(job.id, []),
            key=lambda row: ((row.created_at or datetime.min.replace(tzinfo=timezone.utc)), row.id),
        )
        latest = rows[-1] if rows else None
        summaries.append(
            ManifestSummarySchema(
                job_id=job.id,
                total_files=job.file_count or 0,
                total_bytes=job.copied_bytes or 0,
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
) -> Optional[AuditLog]:
    candidates = (
        db.query(AuditLog)
        .filter(AuditLog.action == "COC_HANDOFF_CONFIRMED", AuditLog.drive_id == drive_id)
        .order_by(AuditLog.id.desc())
        .all()
    )
    delivery_iso = delivery_time.isoformat()
    for row in candidates:
        details = row.details or {}
        if details.get("possessor") != possessor:
            continue
        if details.get("delivery_time") != delivery_iso:
            continue
        if details.get("receipt_ref") != receipt_ref:
            continue
        return row
    return None


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
