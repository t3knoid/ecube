"""User-role management router.

All endpoints require the ``admin`` role.  These manage authorization
(role assignments) only — they do not create or delete OS/LDAP user accounts.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.schemas.users import (
    VALID_ROLES,
    SetRolesRequest,
    UserListResponse,
    UserRolesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


def _audit_log(db: Session, action: str, actor: str, details: dict) -> None:
    """Best-effort audit log.  Never raises."""
    try:
        AuditRepository(db).add(action=action, user=actor, details=details)
    except Exception:
        logger.exception("Failed to write audit log for %s", action)


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
    invalid = set(body.roles) - VALID_ROLES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid roles: {', '.join(sorted(invalid))}. "
            f"Valid roles are: {', '.join(sorted(VALID_ROLES))}",
        )

    repo = UserRoleRepository(db)
    deduplicated = sorted(set(body.roles))
    repo.set_roles(username, deduplicated)

    _audit_log(
        db,
        "ROLE_ASSIGNED",
        current_user.username,
        {
            "target_user": username,
            "roles": deduplicated,
            "path": str(request.url.path),
        },
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
    repo = UserRoleRepository(db)
    repo.delete_roles(username)

    _audit_log(
        db,
        "ROLE_REMOVED",
        current_user.username,
        {
            "target_user": username,
            "path": str(request.url.path),
        },
    )

    return UserRolesResponse(username=username, roles=[])
