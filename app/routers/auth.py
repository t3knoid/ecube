"""Authentication router — issues JWTs for locally authenticated users.

The ``POST /auth/token`` endpoint is **unauthenticated** (it is the login
route).  It validates OS credentials via PAM, resolves group memberships to
ECUBE roles, and returns a signed JWT.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_providers import get_role_resolver
from app.config import settings
from app.database import get_db
from app.repositories.audit_repository import AuditRepository
from app.services.pam_service import LinuxPamAuthenticator, get_user_groups

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    username: str = Field(..., min_length=1, description="OS username")
    password: str = Field(..., min_length=1, description="OS password")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Signed JWT")
    token_type: str = Field(default="bearer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit_log(db: Session, action: str, username: Optional[str], details: dict) -> None:
    """Best-effort audit log.  Never raises."""
    try:
        AuditRepository(db).add(action=action, user=username, details=details)
    except Exception:
        logger.exception("Failed to write audit log for %s", action)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/token", response_model=TokenResponse)
def login(
    body: TokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate with OS credentials and receive a signed JWT.

    No role is required — this is the login route.

    This endpoint is available when ``role_resolver`` is ``local`` or ``ldap``.
    When OIDC mode is active, users authenticate externally via the identity
    provider and this endpoint returns 404.
    """
    if settings.role_resolver == "oidc":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local login is not available when OIDC authentication is enabled",
        )

    pam = LinuxPamAuthenticator()
    if not pam.authenticate(body.username, body.password):
        _audit_log(
            db,
            "AUTH_FAILURE",
            body.username,
            {"reason": "Invalid credentials", "path": str(request.url.path)},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Only expose the DB session in request.state after successful authentication
    request.state.db = db

    # Resolve OS groups → ECUBE roles
    groups = get_user_groups(body.username)
    roles = get_role_resolver().resolve(groups)

    # Build JWT payload
    now = datetime.now(timezone.utc)
    payload = {
        "sub": body.username,
        "username": body.username,
        "groups": groups,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_expire_minutes),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    _audit_log(
        db,
        "AUTH_SUCCESS",
        body.username,
        {"groups": groups, "roles": roles, "path": str(request.url.path)},
    )

    return TokenResponse(access_token=token)
