"""Pydantic schemas for admin configuration management endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, StrictBool, StrictInt, model_validator

from app.schemas.types import StrictIntMixin
from app.utils.callback_payload_contract import validate_callback_payload_contract
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
    nfs_client_version: Optional[Literal["4.2", "4.1", "4.0", "3"]] = Field(default=None)

    db_pool_size: Optional[StrictInt] = Field(default=None, ge=1, le=100)
    db_pool_max_overflow: Optional[StrictInt] = Field(default=None, ge=0, le=200)
    db_pool_recycle_seconds: Optional[StrictInt] = Field(default=None, ge=-1)
    startup_analysis_batch_size: Optional[StrictInt] = Field(default=None, ge=1, le=5000)
    mkfs_exfat_cluster_size: Optional[Literal["4K", "64K", "128K", "256K"]] = Field(default=None)
    drive_format_timeout_seconds: Optional[StrictInt] = Field(default=None, ge=1)
    drive_mount_timeout_seconds: Optional[StrictInt] = Field(default=None, ge=1)
    copy_job_timeout: Optional[StrictInt] = Field(default=None, ge=0)
    job_detail_files_page_size: Optional[StrictInt] = Field(default=None, ge=20, le=100)
    callback_default_url: Optional[StrictSafeStr] = Field(
        default=None,
        json_schema_extra={"pattern": "^https://[a-zA-Z0-9]"},
    )
    callback_proxy_url: Optional[StrictSafeStr] = Field(
        default=None,
        json_schema_extra={"pattern": "^https?://[a-zA-Z0-9]"},
    )
    callback_hmac_secret: Optional[StrictSafeStr] = Field(default=None)
    clear_callback_hmac_secret: Optional[StrictBool] = Field(default=None)
    callback_payload_fields: Optional[List[StrictSafeStr]] = Field(default=None)
    callback_payload_field_map: Optional[Dict[StrictSafeStr, StrictSafeStr]] = Field(default=None)

    @staticmethod
    def _normalize_optional_string(values: dict[str, Any], key: str) -> dict[str, Any]:
        if key not in values:
            return values
        value = values.get(key)
        if value is None:
            return values
        if isinstance(value, str) and not value.strip():
            values = dict(values)
            values[key] = None
        return values

    @staticmethod
    def _validate_url_value(
        *,
        field_name: str,
        value: Optional[str],
        allowed_schemes: tuple[str, ...],
    ) -> Optional[str]:
        if value is None:
            return value

        normalized = value.strip()
        try:
            parsed = urlparse(normalized)
        except Exception as exc:
            raise ValueError(f"{field_name} is not a valid URL") from exc
        if parsed.scheme.lower() not in allowed_schemes:
            allowed = " or ".join(s.upper() for s in allowed_schemes)
            raise ValueError(f"{field_name} must use {allowed}")
        if not parsed.hostname:
            raise ValueError(f"{field_name} must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError(f"{field_name} must not contain embedded credentials")
        return normalized

    @model_validator(mode="before")
    @classmethod
    def normalize_optional_blank_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        if not values:
            raise ValueError("At least one setting must be provided")
        values = cls._normalize_optional_string(values, "callback_default_url")
        values = cls._normalize_optional_string(values, "callback_proxy_url")
        return values

    @model_validator(mode="after")
    def validate_callback_fields(self) -> "ConfigurationUpdateRequest":
        self.callback_default_url = self._validate_url_value(
            field_name="callback_default_url",
            value=self.callback_default_url,
            allowed_schemes=("https",),
        )
        self.callback_proxy_url = self._validate_url_value(
            field_name="callback_proxy_url",
            value=self.callback_proxy_url,
            allowed_schemes=("http", "https"),
        )
        if self.clear_callback_hmac_secret and self.callback_hmac_secret is not None:
            raise ValueError(
                "callback_hmac_secret cannot be updated and cleared in the same request"
            )
        if self.callback_hmac_secret is not None:
            normalized_secret = self.callback_hmac_secret.strip()
            if not normalized_secret:
                raise ValueError("callback_hmac_secret must not be empty")
            self.callback_hmac_secret = normalized_secret
        self.callback_payload_fields, self.callback_payload_field_map = validate_callback_payload_contract(
            self.callback_payload_fields,
            self.callback_payload_field_map,
        )
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
