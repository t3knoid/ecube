"""Shared Pydantic type utilities for request schemas."""

from __future__ import annotations

from typing import Any

from pydantic import model_validator


class StrictIntMixin:
    """Mixin that coerces whole-number floats (e.g. 4.0) to int before
    Pydantic's strict validation, so ``StrictInt`` fields accept JSON
    numbers while still rejecting strings, booleans, and fractional floats.

    Use as the **first** base class::

        class MyModel(StrictIntMixin, BaseModel):
            count: StrictInt = Field(...)
    """

    @model_validator(mode="before")
    @classmethod
    def _coerce_whole_floats(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, float) and val.is_integer():
                    data[key] = int(val)
        return data
