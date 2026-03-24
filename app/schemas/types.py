"""Shared Pydantic types for schema definitions."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, StrictInt


def _coerce_whole_float(v: Any) -> Any:
    """Accept whole-number floats as valid integers per JSON Schema semantics.

    JSON Schema ``type: integer`` considers ``1.0`` a valid integer value.
    Pydantic's ``StrictInt`` rejects it because the Python type is ``float``.
    This validator bridges the gap by converting lossless floats before
    ``StrictInt`` validation runs.
    """
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


JsonInt = Annotated[StrictInt, BeforeValidator(_coerce_whole_float)]
"""``StrictInt`` that also accepts whole-number floats (e.g. ``1.0 → 1``).

Matches the JSON Schema ``type: integer`` semantics where ``1.0`` is a valid
integer.  Still rejects strings and non-whole floats.
"""
