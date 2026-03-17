"""Pydantic schemas for database provisioning and settings endpoints."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Only allow valid hostnames or IPv4 addresses — no URLs, no schemes, no paths.
_HOSTNAME_RE = re.compile(
    r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.[A-Za-z0-9-]{1,63})*$"
)
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,62}$")


def _validate_host(v: str) -> str:
    """Validate hostname to prevent SSRF — reject URLs, schemes, and paths."""
    v = v.strip()
    if not v:
        raise ValueError("Host must not be empty")
    if "://" in v or "/" in v or "@" in v:
        raise ValueError("Host must be a hostname or IP address, not a URL")
    if not (_HOSTNAME_RE.match(v) or _IPV4_RE.match(v)):
        raise ValueError(
            "Host must be a valid hostname or IPv4 address"
        )
    return v


def _validate_pg_identifier(v: str) -> str:
    """Validate PostgreSQL identifier (database name, username)."""
    if not _IDENTIFIER_RE.match(v):
        raise ValueError(
            "Must be a valid identifier: start with a letter or underscore, "
            "contain only letters, digits, and underscores, max 63 characters"
        )
    return v


# ---------------------------------------------------------------------------
# Test connection
# ---------------------------------------------------------------------------


class DatabaseTestConnectionRequest(BaseModel):
    """Request body for ``POST /setup/database/test-connection``."""

    host: str = Field(..., min_length=1, max_length=255, description="PostgreSQL server hostname or IP")
    port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL server port")
    admin_username: str = Field(..., min_length=1, max_length=63, description="PostgreSQL admin username")
    admin_password: str = Field(..., min_length=1, description="PostgreSQL admin password")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        return _validate_host(v)


class DatabaseTestConnectionResponse(BaseModel):
    """Response for ``POST /setup/database/test-connection``."""

    status: str = Field(..., description="Connection test result")
    server_version: str = Field(..., description="PostgreSQL server version string")


# ---------------------------------------------------------------------------
# Provision
# ---------------------------------------------------------------------------


class DatabaseProvisionRequest(BaseModel):
    """Request body for ``POST /setup/database/provision``."""

    host: str = Field(..., min_length=1, max_length=255, description="PostgreSQL server hostname or IP")
    port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL server port")
    admin_username: str = Field(..., min_length=1, max_length=63, description="PostgreSQL admin username")
    admin_password: str = Field(..., min_length=1, description="PostgreSQL admin password")
    app_database: str = Field(default="ecube", min_length=1, max_length=63, description="Application database name")
    app_username: str = Field(default="ecube", min_length=1, max_length=63, description="Application database user")
    app_password: str = Field(..., min_length=1, description="Application database user password")
    force: bool = Field(default=False, description="Allow re-provisioning an already-provisioned database")

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        return _validate_host(v)

    @field_validator("app_database")
    @classmethod
    def validate_app_database(cls, v: str) -> str:
        return _validate_pg_identifier(v)

    @field_validator("app_username")
    @classmethod
    def validate_app_username(cls, v: str) -> str:
        return _validate_pg_identifier(v)


class DatabaseProvisionResponse(BaseModel):
    """Response for ``POST /setup/database/provision``."""

    status: str = Field(..., description="Provisioning result")
    database: str = Field(..., description="Created database name")
    user: str = Field(..., description="Created database user")
    migrations_applied: int = Field(..., description="Number of migrations applied")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class DatabaseStatusResponse(BaseModel):
    """Response for ``GET /setup/database/status``."""

    connected: bool = Field(..., description="Whether the database is reachable")
    database: Optional[str] = Field(default=None, description="Database name")
    host: Optional[str] = Field(default=None, description="Database host")
    port: Optional[int] = Field(default=None, description="Database port")
    current_migration: Optional[str] = Field(default=None, description="Current migration revision")
    pending_migrations: Optional[int] = Field(default=None, description="Number of pending migrations")


# ---------------------------------------------------------------------------
# Settings update
# ---------------------------------------------------------------------------


class DatabaseSettingsUpdateRequest(BaseModel):
    """Request body for ``PUT /setup/database/settings``.

    All fields are optional — only supplied fields are updated.
    """

    host: Optional[str] = Field(default=None, min_length=1, max_length=255, description="PostgreSQL host")
    port: Optional[int] = Field(default=None, ge=1, le=65535, description="PostgreSQL port")
    app_database: Optional[str] = Field(default=None, min_length=1, max_length=63, description="Database name")
    app_username: Optional[str] = Field(default=None, min_length=1, max_length=63, description="Database user")
    app_password: Optional[str] = Field(default=None, min_length=1, description="Database user password")
    pool_size: Optional[int] = Field(default=None, ge=1, le=100, description="Connection pool size")
    pool_max_overflow: Optional[int] = Field(default=None, ge=0, le=200, description="Max overflow connections")

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "DatabaseSettingsUpdateRequest":
        if all(
            getattr(self, f) is None
            for f in (
                "host", "port", "app_database", "app_username",
                "app_password", "pool_size", "pool_max_overflow",
            )
        ):
            raise ValueError("At least one setting must be provided")
        return self

    @field_validator("host")
    @classmethod
    def validate_host(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_host(v)
        return v

    @field_validator("app_database")
    @classmethod
    def validate_app_database(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_pg_identifier(v)
        return v

    @field_validator("app_username")
    @classmethod
    def validate_app_username(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return _validate_pg_identifier(v)
        return v


class DatabaseSettingsUpdateResponse(BaseModel):
    """Response for ``PUT /setup/database/settings``."""

    status: str = Field(..., description="Update result")
    host: str = Field(..., description="Current database host")
    port: int = Field(..., description="Current database port")
    database: str = Field(..., description="Current database name")
    connected: bool = Field(..., description="Whether the new settings connect successfully")
