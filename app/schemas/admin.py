"""Pydantic schemas for administrative endpoints."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.constants import ECUBE_GROUPNAME_PATTERN
from app.schemas.users import RoleName

_UNSAFE_PASSWORD_CHARS = frozenset("\n\r:")


def _check_password_safety(v: str) -> str:
    """Reject passwords containing characters that are unsafe for chpasswd."""
    found = _UNSAFE_PASSWORD_CHARS.intersection(v)
    if found:
        labels = sorted(
            "newline" if c == "\n" else "carriage-return" if c == "\r" else "colon"
            for c in found
        )
        raise ValueError(
            f"Password contains unsafe characters: {', '.join(labels)}. "
            "Newlines and colons are not permitted."
        )
    return v


# ---------------------------------------------------------------------------
# Log file schemas
# ---------------------------------------------------------------------------


class MessageResponse(BaseModel):
    """Simple success message returned by mutating endpoints."""

    message: str = Field(..., description="Human-readable success message")


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


class _GroupItem(str):
    """Constrained string for group names used in list fields."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema
        return core_schema.str_schema(
            min_length=1,
            max_length=32,
            pattern=r"^[a-z_][a-z0-9_-]{0,31}$",
        )


class _EcubeGroupItem(str):
    """Constrained string for ecube-prefixed group names."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type, handler):
        from pydantic_core import core_schema
        return core_schema.str_schema(
            min_length=1,
            max_length=32,
            pattern=ECUBE_GROUPNAME_PATTERN,
        )


# ---------------------------------------------------------------------------
# OS user management schemas
# ---------------------------------------------------------------------------


class CreateOSUserRequest(BaseModel):
    """Request body for ``POST /admin/os-users``."""

    model_config = {"extra": "forbid"}

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
        pattern=r"^[^\n\r:]+$",
        description="Initial password for the user (newlines and colons are not permitted)",
    )

    @field_validator("password")
    @classmethod
    def password_safe_chars(cls, v: str) -> str:
        return _check_password_safety(v)

    roles: List[RoleName] = Field(
        ...,
        min_length=1,
        description="ECUBE roles to assign to the user in the database (required)",
    )

    groups: Optional[List[_GroupItem]] = Field(
        default=None,
        description=(
            "Optional additional OS groups for backward compatibility. "
            "ECUBE groups are derived from selected roles."
        ),
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
        pattern=r"^[^\n\r:]+$",
        description="New password for the user (newlines and colons are not permitted)",
    )

    @field_validator("password")
    @classmethod
    def password_safe_chars(cls, v: str) -> str:
        return _check_password_safety(v)


class SetOSGroupsRequest(BaseModel):
    """Request body for ``PUT /admin/os-users/{username}/groups``."""

    groups: List[_EcubeGroupItem] = Field(
        ...,
        min_length=1,
        description=(
            "ECUBE groups to set for the user (replaces only ecube-* groups; "
            "non-ECUBE supplementary groups are preserved automatically)"
        ),
    )


class AddOSGroupsRequest(BaseModel):
    """Request body for ``POST /admin/os-users/{username}/groups``."""

    groups: List[_GroupItem] = Field(
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
        pattern=ECUBE_GROUPNAME_PATTERN,
        description="ECUBE-managed POSIX group name (must start with 'ecube-')",
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

    model_config = {"extra": "forbid"}

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
        pattern=r"^[^\n\r:]+$",
        description="Admin password (newlines and colons are not permitted)",
    )

    @field_validator("password")
    @classmethod
    def password_safe_chars(cls, v: str) -> str:
        return _check_password_safety(v)


class SetupInitializeResponse(BaseModel):
    """Response for ``POST /setup/initialize``."""

    message: str
    username: str
    groups_created: List[str] = Field(default_factory=list)
