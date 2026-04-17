from datetime import datetime
import logging
from typing import Any, Dict, List, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.utils.sanitize import normalize_project_id, sanitize_audit_details

_logger = logging.getLogger(__name__)

_MAX_INT32 = 2_147_483_647


class AuditRepository:
    """Data-access layer for :class:`~app.models.audit.AuditLog`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        action: str,
        user: Optional[str] = None,
        project_id: Optional[str] = None,
        drive_id: Optional[int] = None,
        job_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        client_ip: Optional[str] = None,
    ) -> AuditLog:
        """Create and persist an immutable audit log entry."""
        entry = self.add_uncommitted(
            action=action,
            user=user,
            project_id=project_id,
            drive_id=drive_id,
            job_id=job_id,
            details=details,
            client_ip=client_ip,
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return entry

    def add_uncommitted(
        self,
        action: str,
        user: Optional[str] = None,
        project_id: Optional[str] = None,
        drive_id: Optional[int] = None,
        job_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        client_ip: Optional[str] = None,
    ) -> AuditLog:
        """Create and stage an immutable audit log entry without committing.

        This is intended for callers that need to include audit writes in a
        wider atomic transaction before issuing a single commit.
        """
        sanitized_details = sanitize_audit_details(details or {})
        normalized_project_id = _normalize_project_id(project_id)
        normalized_drive_id = _normalize_drive_id(drive_id)
        resolved_project_id = normalized_project_id if normalized_project_id is not None else _extract_project_id(sanitized_details)
        resolved_drive_id = normalized_drive_id if normalized_drive_id is not None else _extract_drive_id(sanitized_details)
        entry = AuditLog(
            user=user,
            action=action,
            project_id=resolved_project_id,
            drive_id=resolved_drive_id,
            job_id=job_id,
            details=sanitized_details,
            client_ip=client_ip,
        )
        self.db.add(entry)
        self.db.flush()
        self.db.refresh(entry)
        return entry

    def add_many(
        self,
        entries: List[Dict[str, Any]],
    ) -> List[AuditLog]:
        """Batch-insert multiple audit log entries in a single commit.

        Each dict in *entries* may contain the keys accepted by
        :meth:`add`: ``action``, ``user``, ``project_id``, ``drive_id``, ``job_id``, ``details``,
        ``client_ip``.
        """
        rows = []
        for kwargs in entries:
            details = sanitize_audit_details(kwargs.get("details") or {})
            project_id = _normalize_project_id(kwargs.get("project_id"))
            drive_id = _normalize_drive_id(kwargs.get("drive_id"))
            row = AuditLog(
                action=kwargs["action"],
                user=kwargs.get("user"),
                project_id=project_id if project_id is not None else _extract_project_id(details),
                drive_id=drive_id if drive_id is not None else _extract_drive_id(details),
                job_id=kwargs.get("job_id"),
                details=details,
                client_ip=kwargs.get("client_ip"),
            )
            self.db.add(row)
            rows.append(row)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for row in rows:
            self.db.refresh(row)
        return rows

    def delete_older_than(self, cutoff: datetime) -> int:
        """Delete audit log entries older than *cutoff*. Returns count deleted."""
        count = (
            self.db.query(AuditLog)
            .filter(AuditLog.timestamp < cutoff)
            .delete(synchronize_session=False)
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return count

    def query(
        self,
        user: Optional[str] = None,
        action: Optional[str] = None,
        project_id: Optional[str] = None,
        drive_id: Optional[int] = None,
        job_id: Optional[int] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditLog]:
        """Return audit log entries matching the given filters."""
        q = self.db.query(AuditLog)
        if user is not None:
            q = q.filter(AuditLog.user == user)
        if action is not None:
            q = q.filter(AuditLog.action == action)
        if project_id is not None:
            q = q.filter(AuditLog.project_id == project_id)
        if drive_id is not None:
            q = q.filter(AuditLog.drive_id == drive_id)
        if job_id is not None:
            q = q.filter(AuditLog.job_id == job_id)
        if since is not None:
            q = q.filter(AuditLog.timestamp >= since)
        if until is not None:
            q = q.filter(AuditLog.timestamp <= until)
        return q.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()


def best_effort_audit(
    db: Session,
    action: str,
    user: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    client_ip: Optional[str] = None,
    *,
    project_id: Optional[str] = None,
    drive_id: Optional[int] = None,
) -> None:
    """Write an audit log entry, silently logging on failure.

    Use this instead of duplicating try/except wrappers in every router.
    """
    try:
        AuditRepository(db).add(
            action=action,
            user=user,
            project_id=project_id,
            drive_id=drive_id,
            details=details,
            client_ip=client_ip,
        )
    except Exception:
        _logger.exception("Failed to write audit log for %s", action)


def _extract_project_id(details: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not isinstance(details, Mapping):
        return None
    value = details.get("project_id")
    return value if isinstance(value, str) and value else None


def _normalize_project_id(project_id: Optional[str]) -> Optional[str]:
    normalized = normalize_project_id(project_id)
    if not isinstance(normalized, str) or normalized == "":
        return None
    return normalized


def _normalize_drive_id(drive_id: Optional[int]) -> Optional[int]:
    if drive_id is None:
        return None
    if isinstance(drive_id, bool):
        return None
    if isinstance(drive_id, int):
        return drive_id if 0 < drive_id <= _MAX_INT32 else None
    if isinstance(drive_id, float) and drive_id.is_integer() and drive_id > 0:
        normalized = int(drive_id)
        return normalized if normalized <= _MAX_INT32 else None
    return None


def _extract_drive_id(details: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not isinstance(details, Mapping):
        return None
    value = details.get("drive_id")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= _MAX_INT32 else None
    if isinstance(value, float) and value.is_integer() and value > 0:
        normalized = int(value)
        return normalized if normalized <= _MAX_INT32 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if 0 < parsed <= _MAX_INT32 else None
    return None
