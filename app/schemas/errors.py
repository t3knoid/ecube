"""Pydantic schemas for standardized error responses."""

from typing import Optional

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Uniform error payload returned by all exception handlers.

    Attributes:
        code: A machine-readable error code (e.g. ``"CONFLICT"``).
        message: A human-readable description of the error.
        trace_id: Optional correlation identifier for log tracing.
    """

    code: str = Field(..., description="Machine-readable error code (e.g., CONFLICT, NOT_FOUND, UNAUTHORIZED)")
    message: str = Field(..., description="Human-readable description of the error")
    trace_id: Optional[str] = Field(default=None, description="Unique correlation ID for tracing in logs")
