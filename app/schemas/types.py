"""Shared Pydantic type utilities for request schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import Query
from pydantic import model_validator


# ---------------------------------------------------------------------------
# Optional Query helpers – correct Python type while hiding null from OpenAPI
# ---------------------------------------------------------------------------

# Schema overrides that force OpenAPI to emit a clean, non-nullable type
# even though the Python annotation is Optional.
_INT_SCHEMA = {"type": "integer", "anyOf": None}
_DATETIME_SCHEMA = {"type": "string", "format": "date-time", "anyOf": None}


def OptionalIntQuery(*, description: str, **kwargs: Any) -> Optional[int]:
    """``Query(default=None)`` typed as ``Optional[int]`` with a clean
    ``{type: integer}`` OpenAPI schema (no ``anyOf`` / ``null``)."""
    return Query(  # type: ignore[return-value]
        default=None,
        json_schema_extra=_INT_SCHEMA,
        description=description,
        **kwargs,
    )


def OptionalDatetimeQuery(*, description: str, **kwargs: Any) -> Optional[datetime]:
    """``Query(default=None)`` typed as ``Optional[datetime]`` with a clean
    ``{type: string, format: date-time}`` OpenAPI schema."""
    return Query(  # type: ignore[return-value]
        default=None,
        json_schema_extra=_DATETIME_SCHEMA,
        description=description,
        **kwargs,
    )


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
