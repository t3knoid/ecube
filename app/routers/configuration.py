"""Admin configuration endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.configuration import (
    ConfigurationGetResponse,
    ConfigurationRestartRequest,
    ConfigurationRestartResponse,
    ConfigurationUpdateRequest,
    ConfigurationUpdateResponse,
)
from app.schemas.errors import R_400, R_401, R_403, R_422, R_500, R_503
from app.services import configuration_service
from app.services.audit_service import log_and_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/configuration", tags=["admin"])
_ADMIN_ONLY = require_roles("admin")


def _log_configuration_event(
    db: Session,
    *,
    action: str,
    actor: str,
    level: int,
    metadata: dict,
    fallback_message: str,
    fallback_args: tuple,
) -> None:
    try:
        log_and_audit(
            db,
            action=action,
            actor_id=actor,
            level=level,
            metadata=metadata,
        )
    except Exception:
        logger.error(fallback_message, *fallback_args)


@router.get(
    "",
    response_model=ConfigurationGetResponse,
    responses={**R_401, **R_403, **R_503},
)
def get_configuration(
    _: CurrentUser = Depends(_ADMIN_ONLY),
) -> ConfigurationGetResponse:
    """Return the current runtime configuration values for admin users."""
    return ConfigurationGetResponse(settings=configuration_service.get_configuration_fields())


@router.put(
    "",
    response_model=ConfigurationUpdateResponse,
    responses={**R_401, **R_403, **R_422, **R_500, **R_503},
)
def update_configuration(
    body: ConfigurationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_ONLY),
) -> ConfigurationUpdateResponse:
    """Apply supported runtime/admin configuration updates.

    Returns changed settings and whether a service restart is required for any
    of the requested updates.
    """
    values = {key: getattr(body, key) for key in body.model_fields_set}
    requested_settings = sorted(values.keys())
    requested_values = {key: values[key] for key in requested_settings}

    _log_configuration_event(
        db,
        action="CONFIGURATION_UPDATE_ATTEMPTED",
        actor=current_user.username,
        level=logging.WARNING,
        metadata={
            "requested_settings": requested_settings,
            "requested_values": requested_values,
        },
        fallback_message="CONFIGURATION_UPDATE_ATTEMPTED actor=%s requested=%s",
        fallback_args=(current_user.username, requested_settings),
    )

    try:
        result = configuration_service.update_configuration(values)
    except ValueError as exc:
        _log_configuration_event(
            db,
            action="CONFIGURATION_UPDATE_REJECTED",
            actor=current_user.username,
            level=logging.WARNING,
            metadata={
                "requested_settings": requested_settings,
                "requested_values": requested_values,
                "reason": str(exc),
            },
            fallback_message="CONFIGURATION_UPDATE_REJECTED actor=%s requested=%s reason=%s",
            fallback_args=(current_user.username, requested_settings, str(exc)),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    except Exception as exc:
        _log_configuration_event(
            db,
            action="CONFIGURATION_UPDATE_FAILED",
            actor=current_user.username,
            level=logging.ERROR,
            metadata={
                "requested_settings": requested_settings,
                "requested_values": requested_values,
                "reason": str(exc),
            },
            fallback_message="CONFIGURATION_UPDATE_FAILED actor=%s requested=%s reason=%s",
            fallback_args=(current_user.username, requested_settings, str(exc)),
        )
        logger.exception(
            "CONFIGURATION_UPDATE_UNHANDLED actor=%s requested=%s",
            current_user.username,
            requested_settings,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration update failed",
        )

    _log_configuration_event(
        db,
        action="CONFIGURATION_UPDATED",
        actor=current_user.username,
        level=logging.WARNING,
        metadata={
            "changed_settings": result["changed_settings"],
            "changed_setting_values": result["changed_setting_values"],
            "restart_required_settings": result["restart_required_settings"],
        },
        fallback_message="CONFIGURATION_UPDATED actor=%s changed=%s",
        fallback_args=(current_user.username, result["changed_settings"]),
    )

    return ConfigurationUpdateResponse(**result)


@router.post(
    "/restart",
    response_model=ConfigurationRestartResponse,
    responses={**R_400, **R_401, **R_403, **R_422, **R_500, **R_503},
)
def restart_application_service(
    body: ConfigurationRestartRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_ONLY),
) -> ConfigurationRestartResponse:
    """Request an application service restart after explicit confirmation."""
    try:
        result = configuration_service.request_service_restart(confirm=body.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception:
        logger.exception(
            "CONFIGURATION_RESTART_UNHANDLED actor=%s",
            current_user.username,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration restart request failed",
        )

    _log_configuration_event(
        db,
        action="CONFIGURATION_RESTART_REQUESTED",
        actor=current_user.username,
        level=logging.WARNING,
        metadata={"service": result["service"], "confirmed": True},
        fallback_message="CONFIGURATION_RESTART_REQUESTED actor=%s",
        fallback_args=(current_user.username,),
    )

    return ConfigurationRestartResponse(**result)
