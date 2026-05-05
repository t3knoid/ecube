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
from app.exceptions import AuthenticationError, AuthorizationError
from app.infrastructure import get_os_user_provider, get_password_policy_provider
from app.infrastructure.os_user_protocol import OSUserError, OsUserProvider
from app.repositories.audit_repository import best_effort_audit
from app.repositories.user_role_repository import UserRoleRepository
from app.infrastructure.pam_protocol import PamAuthenticator
from app.infrastructure.password_policy_protocol import PasswordPolicyProvider
from app.schemas.errors import R_400, R_401, R_403, R_404, R_422
from app.utils.client_ip import get_client_ip
from app.utils.sanitize import sanitize_error_message, summarize_password_policy_violation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_PAM_NEW_AUTHTOK_REQD = 12
_PAM_ACCT_EXPIRED = 13
_PAM_AUTHTOK_EXPIRED = 27


def _classify_pam_auth_failure(pam: PamAuthenticator) -> tuple[str | None, str]:
    code = getattr(pam, "code", None)
    if code in {_PAM_NEW_AUTHTOK_REQD, _PAM_AUTHTOK_EXPIRED}:
        return "password_expired", "Password has expired."
    if code == _PAM_ACCT_EXPIRED:
        return "account_expired", "Account has expired."
    return None, "Invalid credentials"


def _is_pam_policy_violation(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        marker in lowered
        for marker in (
            "pam:",
            "bad password",
            "password fails",
            "password has been already used",
            "password unchanged",
            "have exhausted maximum number of retries",
        )
    )


def _safe_password_policy_rejection_message(message: str) -> str:
    sanitized = summarize_password_policy_violation(message, "New password does not satisfy the active password policy.")
    if sanitized in {
        "Permission or authentication failure",
        "Operation timed out",
        "Target device or path was not found",
    }:
        return "New password does not satisfy the active password policy."
    return sanitized


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


def _get_os_user() -> OsUserProvider:
    return get_os_user_provider()


def _get_password_policy() -> PasswordPolicyProvider:
    return get_password_policy_provider()


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
    password_expiration_warning_days: int | None = Field(
        default=None,
        description="Days remaining before the password expires when the account is inside the warning window",
    )


class ChangePasswordRequest(BaseModel):
    username: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
        description="OS username (POSIX format)",
    )
    current_password: str = Field(..., min_length=1, description="Current OS password")
    new_password: str = Field(
        ...,
        min_length=1,
        pattern=r"^[^\n\r:]+$",
        description="Replacement OS password",
    )


class DemoAccountResponse(BaseModel):
    username: str = Field(..., description="Demo-safe username for public display")
    label: str = Field(default="", description="Short label for the demo account")
    description: str = Field(default="", description="Role or usage description")


class PublicAuthConfigResponse(BaseModel):
    demo_mode_enabled: bool = Field(default=False, description="Whether demo mode is enabled")
    default_nfs_client_version: str = Field(default="4.1", description="Default NFS client version suggested by ECUBE host configuration")
    drive_mount_timeout_seconds: int = Field(default=120, description="Default drive mount timeout in seconds for public-safe UI workflows")
    nfs_client_version_options: list[str] = Field(default_factory=lambda: ["4.2", "4.1", "4.0", "3"], description="Supported NFS client versions operators may select in the UI")
    login_message: str | None = Field(default=None, description="Optional public-safe login instructions")
    shared_password: str | None = Field(default=None, description="Public shared demo password displayed on the login screen when demo mode is enabled")
    setup_account_username: str | None = Field(default=None, description="Demo setup account username the setup wizard should reconcile when demo mode is enabled")
    demo_accounts: list[DemoAccountResponse] = Field(default_factory=list, description="Demo-safe accounts for display on the login screen")
    password_change_allowed: bool = Field(default=True, description="Whether password changes are allowed in the current deployment")


def _get_demo_setup_account_username() -> str | None:
    configured_accounts = settings.get_demo_accounts()
    for raw_account in configured_accounts:
        if not isinstance(raw_account, dict):
            continue
        username = str(raw_account.get("username", "")).strip()
        roles = raw_account.get("roles")
        if not username or not isinstance(roles, list):
            continue
        if any(str(role).strip() == "admin" for role in roles):
            return username

    for raw_account in configured_accounts:
        if not isinstance(raw_account, dict):
            continue
        username = str(raw_account.get("username", "")).strip()
        if username:
            return username

    return None


def _resolve_roles(db: Session, pam: PamAuthenticator, username: str) -> tuple[list[str], list[str]]:
    groups = pam.get_user_groups(username)
    db_roles = UserRoleRepository(db).get_roles(username)
    roles = db_roles if db_roles else get_role_resolver().resolve(groups)
    return groups, roles


def _password_warning_days(policy_provider: PasswordPolicyProvider, username: str) -> int | None:
    info = policy_provider.get_password_expiration_info(username)
    if info is None or not info.warning_active:
        return None
    return info.days_until_expiration


def _build_token_response(
    *,
    username: str,
    groups: list[str],
    roles: list[str],
    policy_provider: PasswordPolicyProvider,
) -> TokenResponse:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "username": username,
        "groups": groups,
        "roles": roles,
        "iat": now,
        "exp": now + timedelta(minutes=settings.token_expire_minutes),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return TokenResponse(
        access_token=token,
        password_expiration_warning_days=_password_warning_days(policy_provider, username),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/public-config", response_model=PublicAuthConfigResponse)
def public_auth_config() -> PublicAuthConfigResponse:
    """Return public-safe frontend runtime metadata.

    This route must avoid leaking internal paths, hardware details, per-account
    credentials, or other sensitive configuration values. It may expose
    public-safe UI defaults such as NFS client version hints and drive mount
    timeout values. In demo mode it may intentionally expose the shared demo
    password so unattended users can sign in.
    """
    if not settings.is_demo_mode_enabled():
        return PublicAuthConfigResponse(
            demo_mode_enabled=False,
            default_nfs_client_version=settings.nfs_client_version,
            drive_mount_timeout_seconds=settings.drive_mount_timeout_seconds,
            nfs_client_version_options=["4.2", "4.1", "4.0", "3"],
            login_message=None,
            shared_password=None,
            setup_account_username=None,
            demo_accounts=[],
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
        drive_mount_timeout_seconds=settings.drive_mount_timeout_seconds,
        nfs_client_version_options=["4.2", "4.1", "4.0", "3"],
        login_message=settings.get_demo_login_message() or None,
        shared_password=settings.get_demo_shared_password() or None,
        setup_account_username=_get_demo_setup_account_username(),
        demo_accounts=accounts,
        password_change_allowed=not settings.get_demo_disable_password_change(),
    )

@router.post("/token", response_model=TokenResponse, responses={**R_400, **R_401, **R_403, **R_404, **R_422})
def login(
    body: TokenRequest,
    *,
    db: Session = Depends(get_db),
    pam: PamAuthenticator = Depends(_get_pam),
    policy_provider: PasswordPolicyProvider = Depends(_get_password_policy),
    request: Request,
) -> TokenResponse:
    """Authenticate with OS credentials and receive a signed JWT.

    Authentication requires valid OS credentials and at least one ECUBE role.

    This endpoint is available when ``role_resolver`` is ``local`` or ``ldap``.
    When OIDC mode is active, users authenticate externally via the identity
    provider and this endpoint returns 404 (enforced in ``_get_pam``).
    """
    if not pam.authenticate(body.username, body.password):
        auth_reason, auth_message = _classify_pam_auth_failure(pam)
        best_effort_audit(
            db,
            "AUTH_FAILURE",
            body.username,
            {"reason": auth_reason or "invalid_credentials", "path": str(request.url.path)},
            client_ip=get_client_ip(request),
        )
        raise AuthenticationError(
            auth_message,
            reason=auth_reason,
        )

    # Resolve ECUBE roles for the user.
    # Priority: 1) Explicit roles from DB ``user_roles`` table,
    #           2) Roles derived from groups via the configured resolver.
    groups, roles = _resolve_roles(db, pam, body.username)

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

    best_effort_audit(
        db,
        "AUTH_SUCCESS",
        body.username,
        {"groups": groups, "roles": roles, "path": str(request.url.path)},
        client_ip=get_client_ip(request),
    )

    return _build_token_response(
        username=body.username,
        groups=groups,
        roles=roles,
        policy_provider=policy_provider,
    )


@router.post("/change-password", response_model=TokenResponse, responses={**R_400, **R_401, **R_403, **R_404, **R_422})
def change_password(
    body: ChangePasswordRequest,
    *,
    db: Session = Depends(get_db),
    pam: PamAuthenticator = Depends(_get_pam),
    os_user_provider: OsUserProvider = Depends(_get_os_user),
    policy_provider: PasswordPolicyProvider = Depends(_get_password_policy),
    request: Request,
) -> TokenResponse:
    authenticated = pam.authenticate(body.username, body.current_password)
    auth_reason, auth_message = _classify_pam_auth_failure(pam)
    if not authenticated and auth_reason != "password_expired":
        best_effort_audit(
            db,
            "PASSWORD_CHANGE_FAILED",
            body.username,
            {"reason": auth_reason or "invalid_current_password", "path": str(request.url.path)},
            client_ip=get_client_ip(request),
        )
        raise AuthenticationError(auth_message, reason=auth_reason)

    try:
        os_user_provider.reset_password(body.username, body.new_password)
    except ValueError as exc:
        best_effort_audit(
            db,
            "PASSWORD_CHANGE_FAILED",
            body.username,
            {"reason": "invalid_password_input", "path": str(request.url.path)},
            client_ip=get_client_ip(request),
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    except OSUserError as exc:
        failure_reason = "pam_policy_violation" if _is_pam_policy_violation(exc.message) else "password_change_failed"
        best_effort_audit(
            db,
            "PASSWORD_CHANGE_FAILED",
            body.username,
            {"reason": failure_reason, "path": str(request.url.path)},
            client_ip=get_client_ip(request),
        )
        if failure_reason == "pam_policy_violation":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_safe_password_policy_rejection_message(exc.message),
            )
        logger.info(
            "Password change failed",
            extra={"operation_surface": "auth.change_password", "failure_category": "password_change_failed"},
        )
        logger.debug(
            "Password change diagnostic",
            extra={"username": body.username, "detail": exc.message},
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Password change failed")

    groups, roles = _resolve_roles(db, pam, body.username)
    if not roles:
        raise AuthorizationError("User is not assigned any ECUBE roles")

    best_effort_audit(
        db,
        "PASSWORD_CHANGED",
        body.username,
        {"path": str(request.url.path)},
        client_ip=get_client_ip(request),
    )

    return _build_token_response(
        username=body.username,
        groups=groups,
        roles=roles,
        policy_provider=policy_provider,
    )
