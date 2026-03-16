"""Pydantic schemas for user-role management endpoints."""

from typing import List

from pydantic import BaseModel, Field

from app.repositories.user_role_repository import VALID_ROLES  # noqa: F401


class UserRolesResponse(BaseModel):
    """Role assignments for a single user."""

    username: str
    roles: List[str]


class UserListResponse(BaseModel):
    """List of all users with role assignments."""

    users: List[UserRolesResponse]


class SetRolesRequest(BaseModel):
    """Request body for ``PUT /users/{username}/roles``."""

    roles: List[str] = Field(
        ...,
        min_length=1,
        description="List of ECUBE roles to assign (admin, manager, processor, auditor)",
    )
