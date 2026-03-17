"""Pydantic schemas for administrative endpoints."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.users import RoleName


# ---------------------------------------------------------------------------
# Log file schemas
# ---------------------------------------------------------------------------


class LogFileInfo(BaseModel):
    """Metadata about a single log file."""

    name: str = Field(..., description="Log file name (e.g. app.log, app.log.1)")
    size: int = Field(..., description="File size in bytes")
    created: datetime = Field(..., description="File creation timestamp (ISO 8601)")
    modified: datetime = Field(..., description="File last-modified timestamp (ISO 8601)")


class LogFilesResponse(BaseModel):
    """Response for ``GET /admin/logs``."""

    log_files: List[LogFileInfo] = Field(default_factory=list, description="Available log files")
    total_size: int = Field(..., description="Total size of all log files in bytes")
    log_directory: str = Field(..., description="Absolute path to the log directory")


# ---------------------------------------------------------------------------
# OS user management schemas
# ---------------------------------------------------------------------------


class CreateOSUserRequest(BaseModel):
    """Request body for ``POST /admin/os-users``."""

    username: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
        description="POSIX username (lowercase letters, digits, hyphens, underscores)",
    )
    password: str = Field(
        ...,
        min_length=1,
        description="Initial password for the user",
    )
    groups: Optional[List[str]] = Field(
        default=None,
        description="OS groups to add the user to",
    )
    roles: Optional[List[RoleName]] = Field(
        default=None,
        description="ECUBE roles to assign to the user in the database",
    )


class OSUserResponse(BaseModel):
    """Representation of an OS user."""

    username: str
    uid: int
    gid: int
    home: str
    shell: str
    groups: List[str] = Field(default_factory=list)


class OSUserListResponse(BaseModel):
    """Response for ``GET /admin/os-users``."""

    users: List[OSUserResponse]


class ResetPasswordRequest(BaseModel):
    """Request body for ``PUT /admin/os-users/{username}/password``."""

    password: str = Field(
        ...,
        min_length=1,
        description="New password for the user",
    )


class SetOSGroupsRequest(BaseModel):
    """Request body for ``PUT /admin/os-users/{username}/groups``."""

    groups: List[str] = Field(
        ...,
        description="OS groups to set for the user (replaces existing supplementary groups)",
    )


class AddOSGroupsRequest(BaseModel):
    """Request body for ``POST /admin/os-users/{username}/groups``."""

    groups: List[str] = Field(
        ...,
        min_length=1,
        description="OS groups to add to the user (appends without removing existing groups)",
    )


# ---------------------------------------------------------------------------
# OS group management schemas
# ---------------------------------------------------------------------------


class CreateOSGroupRequest(BaseModel):
    """Request body for ``POST /admin/os-groups``."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
        description="POSIX group name",
    )


class OSGroupResponse(BaseModel):
    """Representation of an OS group."""

    name: str
    gid: int
    members: List[str] = Field(default_factory=list)


class OSGroupListResponse(BaseModel):
    """Response for ``GET /admin/os-groups``."""

    groups: List[OSGroupResponse]


# ---------------------------------------------------------------------------
# Setup wizard schemas
# ---------------------------------------------------------------------------


class SetupStatusResponse(BaseModel):
    """Response for ``GET /setup/status``."""

    initialized: bool = Field(
        ...,
        description="True if at least one admin user exists in the database",
    )


class SetupInitializeRequest(BaseModel):
    """Request body for ``POST /setup/initialize``."""

    username: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
        description="Admin username to create",
    )
    password: str = Field(
        ...,
        min_length=1,
        description="Admin password",
    )


class SetupInitializeResponse(BaseModel):
    """Response for ``POST /setup/initialize``."""

    message: str
    username: str
    groups_created: List[str] = Field(default_factory=list)
