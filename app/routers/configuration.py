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


@router.get(
    "",
    response_model=ConfigurationGetResponse,
    responses={**R_401, **R_403, **R_503},
)
def get_configuration(
    _: CurrentUser = Depends(_ADMIN_ONLY),
) -> ConfigurationGetResponse:
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
    values = {key: getattr(body, key) for key in body.model_fields_set}
    try:
        result = configuration_service.update_configuration(values)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    try:
        log_and_audit(
            db,
            action="CONFIGURATION_UPDATED",
            actor_id=current_user.username,
            metadata={
                "changed_settings": result["changed_settings"],
                "restart_required_settings": result["restart_required_settings"],
            },
        )
    except Exception:
        logger.info(
            "CONFIGURATION_UPDATED actor=%s changed=%s",
            current_user.username,
            result["changed_settings"],
        )

    return ConfigurationUpdateResponse(**result)


@router.post(
    "/restart",
    response_model=ConfigurationRestartResponse,
    responses={**R_400, **R_401, **R_403, **R_500, **R_503},
)
def restart_application_service(
    body: ConfigurationRestartRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_ONLY),
) -> ConfigurationRestartResponse:
    try:
        result = configuration_service.request_service_restart(confirm=body.confirm)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    try:
        log_and_audit(
            db,
            action="CONFIGURATION_RESTART_REQUESTED",
            actor_id=current_user.username,
            metadata={"service": result["service"], "confirmed": True},
        )
    except Exception:
        logger.info("CONFIGURATION_RESTART_REQUESTED actor=%s", current_user.username)

    return ConfigurationRestartResponse(**result)
