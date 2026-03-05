from typing import Any, Dict, Optional

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
        self.db.commit()
        self.db.refresh(entry)
        return entry
