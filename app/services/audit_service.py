import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


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

    logger.log(
        level,
        action,
        extra={
            "user_id": actor_id,
            "drive_id": drive_id,
            "project_id": project_id,
            **(metadata or {}),
        },
    )

    return AuditRepository(db).add(
        action=action,
        user=actor_id,
        job_id=job_id,
        details=details or None,
    )
