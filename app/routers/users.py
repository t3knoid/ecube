"""User-role management router.

All endpoints require the ``admin`` role.  These manage authorization
(role assignments) only — they do not create or delete OS/LDAP user accounts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.constants import USERNAME_RE
from app.database import get_db
from app.repositories.audit_repository import best_effort_audit
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.users import (
    SetRolesRequest,
    UserListResponse,
    UserRolesResponse,
)
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _validate_username(username: str) -> str:
    """Reject usernames with shell metacharacters or invalid format."""
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid username. Must start with a lowercase letter or "
            "underscore, contain only lowercase letters, digits, hyphens, "
            "or underscores, and be 1–32 characters.",
        )
    return username


@router.get("", response_model=UserListResponse)
def list_users(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles("admin")),
) -> UserListResponse:
    """List all users with their ECUBE role assignments."""
    users = UserRoleRepository(db).list_users()
    return UserListResponse(
        users=[UserRolesResponse(**u) for u in users],
    )


@router.get("/{username}/roles", response_model=UserRolesResponse)
def get_user_roles(
    username: str,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_roles("admin")),
) -> UserRolesResponse:
    """Get role assignments for a specific user."""
    _validate_username(username)
    roles = UserRoleRepository(db).get_roles(username)
    return UserRolesResponse(username=username, roles=roles)


@router.put("/{username}/roles", response_model=UserRolesResponse)
def set_user_roles(
    username: str,
    body: SetRolesRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> UserRolesResponse:
    """Set roles for a user (replaces all existing role assignments)."""
    _validate_username(username)

    repo = UserRoleRepository(db)
    deduplicated = sorted(set(body.roles))
    try:
        repo.set_roles(username, deduplicated)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to set roles for user '%s'", username)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update role assignments. Please retry.",
        )

    best_effort_audit(
        db,
        "ROLE_ASSIGNED",
        current_user.username,
        {
            "target_user": username,
            "roles": deduplicated,
            "path": str(request.url.path),
        },
        client_ip=get_client_ip(request),
    )

    return UserRolesResponse(username=username, roles=deduplicated)


@router.delete(
    "/{username}/roles",
    response_model=UserRolesResponse,
    status_code=status.HTTP_200_OK,
)
def delete_user_roles(
    username: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_roles("admin")),
) -> UserRolesResponse:
    """Remove all role assignments for a user."""
    _validate_username(username)
    repo = UserRoleRepository(db)
    try:
        repo.delete_roles(username)
    except Exception:
        db.rollback()
        logger.exception("Failed to delete roles for user '%s'", username)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove role assignments. Please retry.",
        )

    best_effort_audit(
        db,
        "ROLE_REMOVED",
        current_user.username,
        {
            "target_user": username,
            "path": str(request.url.path),
        },
        client_ip=get_client_ip(request),
    )

    return UserRolesResponse(username=username, roles=[])
