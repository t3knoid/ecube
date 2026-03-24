"""Authentication router — issues JWTs for locally authenticated users.

The ``POST /auth/token`` endpoint is **unauthenticated** (it is the login
route).  It validates OS credentials via PAM, determines ECUBE roles for the
user (first from the DB ``user_roles`` table, then from OS group mappings via
the configured role resolver), and returns a signed JWT.
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
from app.repositories.audit_repository import best_effort_audit
from app.repositories.user_role_repository import UserRoleRepository
from app.infrastructure.pam_protocol import PamAuthenticator
from app.schemas.errors import R_400, R_401, R_404, R_422
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Dependency — platform-selected authenticator
# ---------------------------------------------------------------------------

def _get_pam() -> PamAuthenticator:
    """Provide a :class:`PamAuthenticator` via the infrastructure factory.

    Raises 404 early when OIDC is the active resolver so that PAM modules
    are never imported on platforms/configurations that don't need them.
    """
    if settings.role_resolver == "oidc":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Local login is not available when OIDC authentication is enabled",
        )
    from app.infrastructure import get_authenticator
    return get_authenticator()


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
        description="OS username (POSIX format)",
    )
    password: str = Field(..., min_length=1, description="OS password")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Signed JWT")
    token_type: str = Field(default="bearer")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/token", response_model=TokenResponse, responses={**R_400, **R_401, **R_404, **R_422})
def login(
    body: TokenRequest,
    *,
    db: Session = Depends(get_db),
    pam: PamAuthenticator = Depends(_get_pam),
    request: Request,
) -> TokenResponse:
    """Authenticate with OS credentials and receive a signed JWT.

    No role is required — this is the login route.

    This endpoint is available when ``role_resolver`` is ``local`` or ``ldap``.
    When OIDC mode is active, users authenticate externally via the identity
    provider and this endpoint returns 404 (enforced in ``_get_pam``).
    """
    if not pam.authenticate(body.username, body.password):
        best_effort_audit(
            db,
            "AUTH_FAILURE",
            body.username,
            {"reason": "Invalid credentials", "path": str(request.url.path)},
            client_ip=get_client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Resolve ECUBE roles for the user.
    # Priority: 1) Explicit roles from DB ``user_roles`` table,
    #            2) Roles derived from OS groups via the configured resolver.
    groups = pam.get_user_groups(body.username)
    db_roles = UserRoleRepository(db).get_roles(body.username)
    roles = db_roles if db_roles else get_role_resolver().resolve(groups)

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

    best_effort_audit(
        db,
        "AUTH_SUCCESS",
        body.username,
        {"groups": groups, "roles": roles, "path": str(request.url.path)},
        client_ip=get_client_ip(request),
    )

    return TokenResponse(access_token=token)
