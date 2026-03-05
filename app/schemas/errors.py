"""Pydantic schemas for standardized error responses."""

from typing import Optional

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Uniform error payload returned by all exception handlers.

    Attributes:
        code: A machine-readable error code (e.g. ``"CONFLICT"``).
        message: A human-readable description of the error.
        trace_id: Optional correlation identifier for log tracing.
    """

    code: str
    message: str
    trace_id: Optional[str] = None
