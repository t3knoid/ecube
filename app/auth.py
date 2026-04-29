import logging
from dataclasses import dataclass, field
from typing import Callable, List, NoReturn, Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.exceptions import AuthorizationError

_bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    id: str
    username: str
    groups: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)


def _raise_authentication_http_exception(
    request: Request,
    *,
    detail: str,
    reason: str,
    extra: Optional[dict[str, object]] = None,
) -> NoReturn:
    log_extra = {
        "event_code": "AUTHENTICATION_DENIED",
        "status_code": status.HTTP_401_UNAUTHORIZED,
        "request_path": str(request.url.path),
        "request_method": request.method,
        "auth_reason": reason,
        "role_resolver": settings.role_resolver,
    }
    if extra:
        log_extra.update(extra)

    logger.warning("Authentication denied", extra=log_extra)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """FastAPI dependency that validates a bearer token and returns the authenticated user.

    Raises HTTP 401 for missing, invalid, or expired tokens.

    Token validation strategy
    -------------------------
    When ``role_resolver = "oidc"`` the token is treated as an OIDC ID token
    and validated against the provider's public keys (via JWKS).  The
    ``oidc_group_claim_name`` claim is extracted and resolved to roles by
    :class:`~app.auth_providers.OidcGroupRoleResolver`.

    For all other ``role_resolver`` values (``"local"``, ``"ldap"``) the token
    is validated as a locally-issued HS256 JWT signed with ``secret_key``.

    Role resolution strategy
    ------------------------
    If the token carries a non-empty ``roles`` claim, those roles are used
    directly (backward-compatible behaviour for local/LDAP modes).

    If ``roles`` is absent or empty, the configured role resolver (see
    :func:`app.auth_providers.get_role_resolver`) is applied to the ``groups``
    claim.  This allows bearer tokens that carry only group memberships to
    obtain ECUBE roles without route code changes.
    """
    request.state.db = db

    if credentials is None:
        _raise_authentication_http_exception(
            request,
            detail="Missing authentication token",
            reason="missing_token",
        )

    if credentials.scheme.lower() != "bearer":
        _raise_authentication_http_exception(
            request,
            detail="Invalid authentication token",
            reason="invalid_auth_scheme",
            extra={"auth_scheme": credentials.scheme},
        )

    token = credentials.credentials

    # ------------------------------------------------------------------
    # OIDC validation path
    # ------------------------------------------------------------------
    if settings.role_resolver == "oidc":
        return _get_current_user_oidc(token, request)

    # ------------------------------------------------------------------
    # Local / LDAP validation path (HS256 symmetric key)
    # ------------------------------------------------------------------
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
    except jwt.ExpiredSignatureError:
        _raise_authentication_http_exception(
            request,
            detail="Token has expired",
            reason="token_expired",
        )
    except jwt.InvalidTokenError:
        _raise_authentication_http_exception(
            request,
            detail="Invalid authentication token",
            reason="token_validation_failed",
        )

    user_id = payload.get("sub")
    username = payload.get("username")
    if user_id is None or username is None:
        _raise_authentication_http_exception(
            request,
            detail="Invalid token payload",
            reason="invalid_token_payload",
        )

    groups = payload.get("groups", [])
    roles = payload.get("roles", [])
    if groups is None:
        groups = []
    if roles is None:
        roles = []

    if not isinstance(groups, list) or not all(isinstance(group, str) for group in groups):
        _raise_authentication_http_exception(
            request,
            detail="Invalid token payload",
            reason="invalid_token_groups",
        )

    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        _raise_authentication_http_exception(
            request,
            detail="Invalid token payload",
            reason="invalid_token_roles",
        )

    # When the token carries no explicit roles, resolve them from group
    # memberships using the configured role resolver provider.
    if not roles and groups:
        from app.auth_providers import get_role_resolver

        roles = get_role_resolver().resolve(groups)

    current_user = CurrentUser(
        id=user_id,
        username=username,
        groups=groups,
        roles=roles,
    )

    request.state.current_user = current_user
    return current_user


def _get_current_user_oidc(token: str, request: Request) -> CurrentUser:
    """Validate an OIDC ID token and return the authenticated user.

    Delegates token validation to :mod:`app.services.oidc_service`.  Extracts
    the ``sub`` claim as the user ID, ``preferred_username`` / ``email`` / ``sub``
    as the display username, and the configured group claim for role resolution.

    Raises:
        HTTPException: HTTP 401 on any token validation failure.
    """
    from app.auth_providers import get_role_resolver
    from app.services.oidc_service import OidcTokenError, validate_token

    try:
        payload = validate_token(token)
    except OidcTokenError as exc:
        _raise_authentication_http_exception(
            request,
            detail=str(exc),
            reason="oidc_validation_failed",
            extra={"error_type": type(exc).__name__},
        )

    user_id = payload.get("sub")
    if not user_id:
        _raise_authentication_http_exception(
            request,
            detail="Invalid token payload",
            reason="invalid_token_payload",
        )

    # Prefer a human-readable username; fall back to the subject identifier.
    username: str = (
        payload.get("preferred_username")
        or payload.get("email")
        or user_id
    )

    raw_groups = payload.get(settings.oidc_group_claim_name, [])
    if not isinstance(raw_groups, list) or not all(isinstance(g, str) for g in raw_groups):
        _raise_authentication_http_exception(
            request,
            detail="Invalid token payload",
            reason="invalid_token_groups",
        )

    groups = raw_groups
    roles = get_role_resolver().resolve(groups)

    current_user = CurrentUser(
        id=user_id,
        username=username,
        groups=groups,
        roles=roles,
    )
    request.state.current_user = current_user
    return current_user


def require_roles(*allowed_roles: str) -> Callable[..., CurrentUser]:
    """FastAPI dependency factory that enforces role-based access control.

    Returns a dependency callable that validates the current user holds at least
    one of *allowed_roles*.  Raises HTTP 403 (via :class:`AuthorizationError`)
    when the user is authenticated but lacks the required role.  Every denial is
    recorded in application logs and, when available, the audit log with the actor
    identity and request context.

    Usage::

        @router.post("/drives/{drive_id}/initialize")
        def initialize_drive(
            drive_id: int,
            db: Session = Depends(get_db),
            _: CurrentUser = Depends(require_roles("admin", "manager")),
        ):
            ...
    """

    def _check(
        request: Request,
        current_user: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> CurrentUser:
        if not any(r in current_user.roles for r in allowed_roles):
            _try_log_authorization_denied(
                db=db,
                actor_id=current_user.id,
                actor=current_user.username,
                path=str(request.url.path),
                method=request.method,
                required_roles=list(allowed_roles),
                user_roles=current_user.roles,
            )
            raise AuthorizationError(
                f"This action requires one of the following roles: {', '.join(sorted(allowed_roles))}"
            )
        return current_user

    return _check


def _try_log_authorization_denied(
    db: Optional[Session],
    actor_id: Optional[str],
    actor: str,
    path: str,
    method: str,
    required_roles: List[str],
    user_roles: List[str],
) -> None:
    """Best-effort audit log for role-denial events.  Never raises."""
    logger.warning(
        "Authorization denied",
        extra={
            "event_code": "AUTHORIZATION_DENIED",
            "status_code": status.HTTP_403_FORBIDDEN,
            "actor_id": actor_id,
            "actor_username": actor,
            "request_path": path,
            "request_method": method,
            "required_roles": sorted(required_roles),
            "user_roles": sorted(user_roles),
        },
    )
    if db is None:
        return
    try:
        from app.repositories.audit_repository import AuditRepository

        AuditRepository(db).add(
            action="AUTHORIZATION_DENIED",
            user=actor,
            details={
                "path": path,
                "method": method,
                "required_roles": required_roles,
                "user_roles": user_roles,
            },
        )
    except Exception:
        pass
