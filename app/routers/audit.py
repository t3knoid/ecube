import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.config import settings
from app.database import get_db
from app.exceptions import EncodingError
from app.repositories.audit_repository import AuditRepository
from app.schemas.audit import (
    AuditLogFilterOptionsResponse,
    AuditLogListResponse,
    AuditLogSchema,
    ChainOfCustodyHandoffRequest,
    ChainOfCustodyHandoffResponse,
    ChainOfCustodyReportSchema,
)
from app.schemas.errors import R_401, R_403, R_404, R_409, R_422
from app.schemas.types import OptionalDatetimeQuery, OptionalIntQuery
from app.services import audit_service
from app.utils.client_ip import get_client_ip
from app.utils.sanitize import normalize_project_id, strict_sanitize_string

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

_ALLOWED = require_roles("admin", "manager", "auditor")
_WRITE_ALLOWED = require_roles("admin", "manager")
@router.get("", response_model=AuditLogListResponse, responses={**R_401, **R_403, **R_422})
def list_audit_logs(
    user: Optional[str] = Query(default=None, description="Filter by user"),
    action: Optional[str] = Query(default=None, description="Filter by action"),
    project_id: Optional[str] = Query(default=None, min_length=1, description="Filter by project ID"),
    drive_id: Optional[int] = OptionalIntQuery(description="Filter by drive ID"),
    job_id: Optional[int] = OptionalIntQuery(description="Filter by job ID"),
    since: Optional[datetime] = OptionalDatetimeQuery(description="Filter entries at or after this timestamp (ISO 8601)"),
    until: Optional[datetime] = OptionalDatetimeQuery(description="Filter entries at or before this timestamp (ISO 8601)"),
    search: Optional[str] = Query(default=None, description="Case-insensitive substring search across operator-visible audit fields"),
    include_total: bool = Query(default=True, description="Whether to compute the exact total count for the current filter set"),
    limit: int = Query(default=settings.audit_log_default_limit, ge=1, le=settings.audit_log_max_limit, description="Maximum number of results"),
    offset: int = Query(default=0, ge=0, description="Number of results to skip"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALLOWED),
):
    """Return audit log entries with optional filters.

    **Roles:** ``admin``, ``manager``, ``auditor``
    """
    if project_id is not None:
        normalized_project_id = normalize_project_id(project_id)
        if not isinstance(normalized_project_id, str) or not normalized_project_id:
            raise EncodingError("project_id is empty after removing invalid characters")
        project_id = normalized_project_id

    return audit_service.list_audit_logs(
        db,
        roles=current_user.roles,
        user=user,
        action=action,
        project_id=project_id,
        drive_id=drive_id,
        job_id=job_id,
        since=since,
        until=until,
        search=search,
        include_total=include_total,
        limit=limit,
        offset=offset,
    )


@router.get("/options", response_model=AuditLogFilterOptionsResponse, responses={**R_401, **R_403})
def get_audit_filter_options(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALLOWED),
):
    """Return distinct filter values for the audit log search controls.

    **Roles:** ``admin``, ``manager``, ``auditor``
    """
    return audit_service.get_audit_filter_options(db)


@router.get("/chain-of-custody", response_model=ChainOfCustodyReportSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422})
def get_chain_of_custody(
    drive_id: Optional[int] = OptionalIntQuery(description="Authoritative drive selector when provided"),
    drive_sn: Optional[str] = Query(default=None, min_length=1, description="Drive device identifier/serial"),
    project_id: Optional[str] = Query(default=None, min_length=1, description="Project selector"),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALLOWED),
):
    """Return chain-of-custody report sections by drive or project selectors.

    Selector precedence: ``drive_id`` > ``drive_sn`` > ``project_id``.

    **Roles:** ``admin``, ``manager``, ``auditor``
    """
    if drive_sn is not None:
        try:
            strict_sanitize_string(drive_sn)
        except ValueError:
            raise EncodingError("drive_sn contains invalid characters")

    if project_id is not None:
        normalized_project_id = normalize_project_id(project_id)
        if not isinstance(normalized_project_id, str) or not normalized_project_id:
            raise EncodingError("project_id is empty after removing invalid characters")
        project_id = normalized_project_id

    return audit_service.get_chain_of_custody_report(
        db,
        drive_id=drive_id,
        drive_sn=drive_sn,
        project_id=project_id,
    )


@router.post("/chain-of-custody/handoff", response_model=ChainOfCustodyHandoffResponse, responses={**R_401, **R_403, **R_404, **R_409, **R_422})
def confirm_chain_of_custody_handoff(
    body: ChainOfCustodyHandoffRequest,
    request: Request,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_WRITE_ALLOWED),
):
    """Record legal custody transfer as a dedicated append-only audit event.

    **Roles:** ``admin``, ``manager``
    """
    return audit_service.confirm_chain_of_custody_handoff(
        db,
        payload=body,
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )
