from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.repositories.audit_repository import AuditRepository


def create_audit_log(
    db: Session,
    action: str,
    user: Optional[str] = None,
    job_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    return AuditRepository(db).add(
        action=action,
        user=user,
        job_id=job_id,
        details=details,
    )
