"""Pydantic schemas for admin configuration management endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StrictBool, StrictInt, model_validator

from app.schemas.types import StrictIntMixin
from app.utils.sanitize import StrictSafeStr


class ConfigurationField(BaseModel):
    """Single editable configuration field with restart metadata."""

    key: str = Field(..., description="Configuration key")
    value: Any = Field(..., description="Current effective value")
    requires_restart: bool = Field(..., description="Whether changing this field requires service restart")


class ConfigurationGetResponse(BaseModel):
    """Response for ``GET /admin/configuration``."""

    settings: List[ConfigurationField] = Field(default_factory=list)


class ConfigurationUpdateRequest(StrictIntMixin, BaseModel):
    """Request body for ``PUT /admin/configuration``.

    All fields are optional; only supplied fields are updated.
    """

    model_config = {"extra": "forbid", "json_schema_extra": {"minProperties": 1}}

    log_level: Optional[Literal["DEBUG", "INFO", "WARNING", "ERROR"]] = Field(default=None)
    log_format: Optional[Literal["text", "json"]] = Field(default=None)
    log_file: Optional[StrictSafeStr] = Field(default=None)
    log_file_max_bytes: Optional[StrictInt] = Field(default=None, ge=1)
    log_file_backup_count: Optional[StrictInt] = Field(default=None, ge=0)

    db_pool_size: Optional[StrictInt] = Field(default=None, ge=1, le=100)
    db_pool_max_overflow: Optional[StrictInt] = Field(default=None, ge=0, le=200)
    db_pool_recycle_seconds: Optional[StrictInt] = Field(default=None, ge=-1)

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "ConfigurationUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one setting must be provided")
        return self


class ConfigurationUpdateResponse(BaseModel):
    """Response for ``PUT /admin/configuration``."""

    status: str = Field(..., description="Update status")
    changed_settings: List[str] = Field(default_factory=list)
    changed_setting_values: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    applied_immediately: List[str] = Field(default_factory=list)
    restart_required_settings: List[str] = Field(default_factory=list)
    restart_required: bool = Field(...)


class ConfigurationRestartRequest(BaseModel):
    """Request body for ``POST /admin/configuration/restart``."""

    model_config = {"extra": "forbid"}

    confirm: StrictBool = Field(..., description="Must be true to confirm service restart")


class ConfigurationRestartResponse(BaseModel):
    """Response for ``POST /admin/configuration/restart``."""

    status: str = Field(..., description="Restart request status")
    service: str = Field(..., description="Service unit name")
