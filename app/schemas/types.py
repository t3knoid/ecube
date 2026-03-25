"""Shared Pydantic type utilities for request schemas."""

from __future__ import annotations

from typing import Any

from fastapi import Query
from pydantic import model_validator


# ---------------------------------------------------------------------------
# Optional Query helpers – correct Python type while hiding null from OpenAPI
# ---------------------------------------------------------------------------

# Schema overrides that force OpenAPI to emit a clean, non-nullable type
# even though the Python annotation is Optional.  We use a callable so we
# can *remove* the ``anyOf`` key rather than setting it to ``None`` (which
# would produce ``anyOf: null`` — invalid in OpenAPI 3.1 / JSON Schema).


def _int_schema(schema: dict[str, Any]) -> None:
    schema.pop("anyOf", None)
    schema["type"] = "integer"


def _datetime_schema(schema: dict[str, Any]) -> None:
    schema.pop("anyOf", None)
    schema["type"] = "string"
    schema["format"] = "date-time"


def OptionalIntQuery(*, description: str, **kwargs: Any) -> Any:
    """``Query(default=None)`` typed as ``Optional[int]`` with a clean
    ``{type: integer}`` OpenAPI schema (no ``anyOf`` / ``null``)."""
    return Query(
        default=None,
        json_schema_extra=_int_schema,
        description=description,
        **kwargs,
    )


def OptionalDatetimeQuery(*, description: str, **kwargs: Any) -> Any:
    """``Query(default=None)`` typed as ``Optional[datetime]`` with a clean
    ``{type: string, format: date-time}`` OpenAPI schema."""
    return Query(
        default=None,
        json_schema_extra=_datetime_schema,
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
