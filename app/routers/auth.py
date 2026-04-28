"""Authentication router — issues JWTs and exposes public login metadata.

The ``POST /auth/token`` endpoint is **unauthenticated** (it is the login
route). It validates OS credentials via PAM, determines ECUBE roles for the
user (first from the DB ``user_roles`` table, then from OS group mappings via
the configured role resolver), and returns a signed JWT.

The ``GET /auth/public-config`` endpoint is also unauthenticated and returns
only public-safe metadata that the login screen may use for demo deployments.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_providers import get_role_resolver
from app.config import settings
from app.database import get_db
from app.exceptions import AuthorizationError
from app.repositories.audit_repository import best_effort_audit
from app.repositories.user_role_repository import UserRoleRepository
from app.infrastructure.pam_protocol import PamAuthenticator
from app.schemas.errors import R_400, R_401, R_403, R_404, R_422
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


class DemoAccountResponse(BaseModel):
    username: str = Field(..., description="Demo-safe username for public display")
    label: str = Field(default="", description="Short label for the demo account")
    description: str = Field(default="", description="Role or usage description")


class PublicAuthConfigResponse(BaseModel):
    demo_mode_enabled: bool = Field(default=False, description="Whether demo mode is enabled")
    default_nfs_client_version: str = Field(default="4.1", description="Default NFS client version suggested by ECUBE host configuration")
    nfs_client_version_options: list[str] = Field(default_factory=lambda: ["4.2", "4.1", "4.0", "3"], description="Supported NFS client versions operators may select in the UI")
    login_message: str | None = Field(default=None, description="Optional public-safe login instructions")
    demo_accounts: list[DemoAccountResponse] = Field(default_factory=list, description="Demo-safe accounts for display on the login screen")
    shared_password: str | None = Field(default=None, description="Optional shared demo password intentionally shown on the login screen")
    password_change_allowed: bool = Field(default=True, description="Whether password changes are allowed in the current deployment")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/public-config", response_model=PublicAuthConfigResponse)
def public_auth_config() -> PublicAuthConfigResponse:
    """Return public-safe auth metadata for the login screen.

    This route intentionally exposes only display-safe demo information. It must
    not leak internal paths, hardware details, private credentials, or other
    sensitive configuration values.
    """
    if not settings.is_demo_mode_enabled():
        return PublicAuthConfigResponse(
            demo_mode_enabled=False,
            default_nfs_client_version=settings.nfs_client_version,
            nfs_client_version_options=["4.2", "4.1", "4.0", "3"],
            login_message=None,
            demo_accounts=[],
            shared_password=None,
            password_change_allowed=True,
        )

    accounts: list[DemoAccountResponse] = []
    for raw_account in settings.get_demo_accounts():
        try:
            accounts.append(
                DemoAccountResponse(
                    username=str(raw_account.get("username", "")).strip(),
                    label=str(raw_account.get("label", "")).strip(),
                    description=str(raw_account.get("description", "")).strip(),
                )
            )
        except AttributeError:
            logger.warning("Ignoring invalid demo account config", {"type": type(raw_account).__name__})

    accounts = [account for account in accounts if account.username]

    return PublicAuthConfigResponse(
        demo_mode_enabled=True,
        default_nfs_client_version=settings.nfs_client_version,
        nfs_client_version_options=["4.2", "4.1", "4.0", "3"],
        login_message=settings.get_demo_login_message() or None,
        demo_accounts=accounts,
        shared_password=settings.get_demo_shared_password() or None,
        password_change_allowed=not settings.get_demo_disable_password_change(),
    )

@router.post("/token", response_model=TokenResponse, responses={**R_400, **R_401, **R_403, **R_404, **R_422})
def login(
    body: TokenRequest,
    *,
    db: Session = Depends(get_db),
    pam: PamAuthenticator = Depends(_get_pam),
    request: Request,
) -> TokenResponse:
    """Authenticate with OS credentials and receive a signed JWT.

    Authentication requires valid OS credentials and at least one ECUBE role.

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
    #           2) Roles derived from groups via the configured resolver.
    groups = pam.get_user_groups(body.username)
    db_roles = UserRoleRepository(db).get_roles(body.username)
    roles = db_roles if db_roles else get_role_resolver().resolve(groups)

    if not roles:
        best_effort_audit(
            db,
            "AUTH_FAILURE",
            body.username,
            {
                "reason": "No ECUBE roles assigned",
                "path": str(request.url.path),
                "groups": groups,
            },
            client_ip=get_client_ip(request),
        )
        raise AuthorizationError("User is not assigned any ECUBE roles")

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
