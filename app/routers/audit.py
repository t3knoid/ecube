from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import AuditLogSchema

router = APIRouter(prefix="/audit", tags=["audit"])

_ALLOWED = require_roles("admin", "manager", "auditor")


@router.get("", response_model=List[AuditLogSchema])
def list_audit_logs(
    user: Optional[str] = Query(default=None, description="Filter by user"),
    action: Optional[str] = Query(default=None, description="Filter by action"),
    job_id: Optional[int] = Query(default=None, description="Filter by job ID"),
    since: Optional[datetime] = Query(default=None, description="Filter entries at or after this timestamp (ISO 8601)"),
    until: Optional[datetime] = Query(default=None, description="Filter entries at or before this timestamp (ISO 8601)"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of results"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALLOWED),
):
    """Return audit log entries with optional filters.

    **Roles:** ``admin``, ``manager``, ``auditor``
    """
    return AuditRepository(db).query(
        user=user,
        action=action,
        job_id=job_id,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
