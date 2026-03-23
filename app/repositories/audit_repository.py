from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditLog

_logger = logging.getLogger(__name__)


class AuditRepository:
    """Data-access layer for :class:`~app.models.audit.AuditLog`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        action: str,
        user: Optional[str] = None,
        job_id: Optional[int] = None,
        details: Optional[Dict[str, Any]] = None,
        client_ip: Optional[str] = None,
    ) -> AuditLog:
        """Create and persist an immutable audit log entry."""
        entry = AuditLog(
            user=user,
            action=action,
            job_id=job_id,
            details=details or {},
            client_ip=client_ip,
        )
        self.db.add(entry)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(entry)
        return entry

    def add_many(
        self,
        entries: List[Dict[str, Any]],
    ) -> List[AuditLog]:
        """Batch-insert multiple audit log entries in a single commit.

        Each dict in *entries* may contain the keys accepted by
        :meth:`add`: ``action``, ``user``, ``job_id``, ``details``,
        ``client_ip``.
        """
        rows = []
        for kwargs in entries:
            row = AuditLog(
                action=kwargs["action"],
                user=kwargs.get("user"),
                job_id=kwargs.get("job_id"),
                details=kwargs.get("details") or {},
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
) -> None:
    """Write an audit log entry, silently logging on failure.

    Use this instead of duplicating try/except wrappers in every router.
    """
    try:
        AuditRepository(db).add(action=action, user=user, details=details, client_ip=client_ip)
    except Exception:
        _logger.exception("Failed to write audit log for %s", action)
