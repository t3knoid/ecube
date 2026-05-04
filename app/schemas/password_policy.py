"""Schemas for password policy APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field, StrictInt, model_validator

from app.schemas.types import StrictIntMixin


class PasswordPolicySettings(BaseModel):
    """Current effective PAM password policy settings."""

    minlen: StrictInt = Field(..., ge=12, le=128)
    minclass: StrictInt = Field(..., ge=0, le=4)
    maxrepeat: StrictInt = Field(..., ge=0)
    maxsequence: StrictInt = Field(..., ge=0)
    maxclassrepeat: StrictInt = Field(..., ge=0)
    dictcheck: StrictInt = Field(..., ge=0, le=1)
    usercheck: StrictInt = Field(..., ge=0, le=1)
    difok: StrictInt = Field(..., ge=0, le=255)
    retry: StrictInt = Field(..., ge=1, le=10)


class PasswordPolicyUpdateRequest(StrictIntMixin, BaseModel):
    """Request body for ``PUT /admin/password-policy``."""

    model_config = {"extra": "forbid", "json_schema_extra": {"minProperties": 1}}

    minlen: StrictInt | None = Field(default=None, ge=12, le=128)
    minclass: StrictInt | None = Field(default=None, ge=0, le=4)
    maxrepeat: StrictInt | None = Field(default=None, ge=0)
    maxsequence: StrictInt | None = Field(default=None, ge=0)
    maxclassrepeat: StrictInt | None = Field(default=None, ge=0)
    dictcheck: StrictInt | None = Field(default=None, ge=0, le=1)
    usercheck: StrictInt | None = Field(default=None, ge=0, le=1)
    difok: StrictInt | None = Field(default=None, ge=0, le=255)
    retry: StrictInt | None = Field(default=None, ge=1, le=10)
    enforce_for_root: StrictInt | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_enforce_for_root(self) -> "PasswordPolicyUpdateRequest":
        if self.enforce_for_root is not None and self.enforce_for_root != 1:
            raise ValueError("enforce_for_root must remain set to 1")
        return self