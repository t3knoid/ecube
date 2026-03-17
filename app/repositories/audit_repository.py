from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditLog


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
    ) -> AuditLog:
        """Create and persist an immutable audit log entry."""
        entry = AuditLog(
            user=user,
            action=action,
            job_id=job_id,
            details=details or {},
        )
        self.db.add(entry)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(entry)
        return entry

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
