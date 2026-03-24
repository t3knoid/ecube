import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.config import settings
from app.database import get_db
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditLogSchema
from app.schemas.errors import R_401, R_403, R_422

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

_ALLOWED = require_roles("admin", "manager", "auditor")
_IP_VISIBLE_ROLES = {"admin", "auditor"}


def _redact_ip(entry, user: CurrentUser) -> AuditLogSchema:
    """Serialize an AuditLog, redacting client_ip for non-admin/auditor roles."""
    schema = AuditLogSchema.model_validate(entry)
    if not _IP_VISIBLE_ROLES.intersection(user.roles):
        schema.client_ip = None
    return schema


@router.get("", response_model=List[AuditLogSchema], responses={**R_401, **R_403, **R_422})
def list_audit_logs(
    user: Optional[str] = Query(default=None, description="Filter by user"),
    action: Optional[str] = Query(default=None, description="Filter by action"),
    job_id: Optional[int] = Query(default=None, description="Filter by job ID"),
    since: datetime = Query(default=None, description="Filter entries at or after this timestamp (ISO 8601)"),  # type: ignore[assignment]
    until: datetime = Query(default=None, description="Filter entries at or before this timestamp (ISO 8601)"),  # type: ignore[assignment]
    limit: int = Query(default=settings.audit_log_default_limit, ge=1, le=settings.audit_log_max_limit, description="Maximum number of results"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALLOWED),
):
    """Return audit log entries with optional filters.

    **Roles:** ``admin``, ``manager``, ``auditor``
    """
    entries = AuditRepository(db).query(
        user=user,
        action=action,
        job_id=job_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return [_redact_ip(e, current_user) for e in entries]
