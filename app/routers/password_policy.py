"""Admin password policy endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.infrastructure import get_password_policy_provider
from app.infrastructure.password_policy_protocol import PasswordPolicyError, PasswordPolicyProvider
from app.schemas.errors import R_401, R_403, R_422, R_500, R_503
from app.schemas.password_policy import PasswordPolicySettings, PasswordPolicyUpdateRequest
from app.services.audit_service import log_and_audit
from app.utils.sanitize import sanitize_error_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/password-policy", tags=["admin"])
_ADMIN_ONLY = require_roles("admin")


def _get_provider() -> PasswordPolicyProvider:
    return get_password_policy_provider()


def _safe_password_policy_service_message(message: str) -> str:
    sanitized = sanitize_error_message(message, "Password policy service is unavailable.")
    if sanitized in {
        "Target device or path was not found",
        "Filesystem type is not supported by the host",
        "Invalid device path",
        "Target is busy",
    }:
        return "Password policy service is unavailable."
    return sanitized


def _log_password_policy_service_failure(*, operation: str, detail: str) -> None:
    summary = _safe_password_policy_service_message(detail)
    logger.info(
        "Password policy service unavailable",
        extra={
            "operation_surface": operation,
            "failure_category": "password_policy_service_unavailable",
            "failure_summary": summary,
        },
    )
    logger.debug(
        "Password policy service diagnostic",
        extra={
            "operation_surface": operation,
            "detail": detail,
        },
    )


@router.get(
    "",
    response_model=PasswordPolicySettings,
    responses={**R_401, **R_403, **R_503},
)
def get_password_policy(
    _: CurrentUser = Depends(_ADMIN_ONLY),
    provider: PasswordPolicyProvider = Depends(_get_provider),
) -> PasswordPolicySettings:
    try:
        return PasswordPolicySettings(**provider.get_policy_settings())
    except PasswordPolicyError as exc:
        _log_password_policy_service_failure(
            operation="admin.password_policy.get",
            detail=exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_safe_password_policy_service_message(exc.message),
        )


@router.put(
    "",
    response_model=PasswordPolicySettings,
    responses={**R_401, **R_403, **R_422, **R_500, **R_503},
)
def update_password_policy(
    body: PasswordPolicyUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_ONLY),
    provider: PasswordPolicyProvider = Depends(_get_provider),
) -> PasswordPolicySettings:
    updates = {
        key: getattr(body, key)
        for key in body.model_fields_set
        if key != "enforce_for_root" and getattr(body, key) is not None
    }

    try:
        previous_values, next_values = provider.update_policy_settings(updates)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    except PasswordPolicyError as exc:
        _log_password_policy_service_failure(
            operation="admin.password_policy.update",
            detail=exc.message,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_safe_password_policy_service_message(exc.message),
        )
    except Exception:
        logger.exception(
            "Password policy update failed",
            extra={"actor": current_user.username},
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Password policy update failed")

    log_and_audit(
        db,
        action="PASSWORD_POLICY_UPDATED",
        actor_id=current_user.username,
        metadata={
            "path": str(request.url.path),
            "previous_values": previous_values,
            "new_values": next_values,
        },
    )
    return PasswordPolicySettings(**next_values)