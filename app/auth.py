from dataclasses import dataclass, field
from typing import Callable, List

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.exceptions import AuthorizationError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    id: str
    username: str
    groups: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency that validates a bearer token and returns the authenticated user.

    Raises HTTP 401 for missing, invalid, or expired tokens.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    username = payload.get("username")
    if user_id is None or username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user = CurrentUser(
        id=user_id,
        username=username,
        groups=payload.get("groups", []),
        roles=payload.get("roles", []),
    )

    request.state.current_user = current_user
    return current_user


def require_roles(*allowed_roles: str) -> Callable[..., CurrentUser]:
    """FastAPI dependency factory that enforces role-based access control.

    Returns a dependency callable that validates the current user holds at least
    one of *allowed_roles*.  Raises HTTP 403 (via :class:`AuthorizationError`)
    when the user is authenticated but lacks the required role.

    Usage::

        @router.post("/drives/{drive_id}/initialize")
        def initialize_drive(
            drive_id: int,
            db: Session = Depends(get_db),
            _: CurrentUser = Depends(require_roles("admin", "manager")),
        ):
            ...
    """

    def _check(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(r in current_user.roles for r in allowed_roles):
            raise AuthorizationError(
                f"This action requires one of the following roles: {', '.join(sorted(allowed_roles))}"
            )
        return current_user

    return _check
