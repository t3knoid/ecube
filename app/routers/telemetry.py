"""Frontend telemetry ingestion endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, status

from app.auth import CurrentUser, require_roles
from app.schemas.errors import R_401, R_403, R_422
from app.schemas.telemetry import UiNavigationTelemetryEvent
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["telemetry"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")


@router.post("/ui-navigation", status_code=status.HTTP_202_ACCEPTED, responses={**R_401, **R_403, **R_422})
def ingest_ui_navigation_telemetry(
    payload: UiNavigationTelemetryEvent,
    request: Request,
    current_user: CurrentUser = Depends(_ALL_ROLES),
) -> dict[str, str]:
    """Ingest frontend UI navigation telemetry for troubleshooting.

    This endpoint records selected UI navigation events in application logs at
    DEBUG level for traceability. It is intentionally lightweight and does not
    replace audit logging.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    logger.debug(
        "UI_NAVIGATION_TELEMETRY actor=%s event_type=%s action=%s label=%s source=%s destination=%s route_name=%s reason=%s client_ip=%s",
        current_user.username,
        payload.event_type,
        payload.action,
        payload.label,
        payload.source,
        payload.destination,
        payload.route_name,
        payload.reason,
        get_client_ip(request),
    )
    return {"status": "accepted"}
