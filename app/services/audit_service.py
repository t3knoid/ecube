from sqlalchemy.orm import Session
from app.models.audit import AuditLog
from typing import Optional, Dict, Any


def create_audit_log(
    db: Session,
    action: str,
    user: Optional[str] = None,
    job_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(
        user=user,
        action=action,
        job_id=job_id,
        details=details or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
