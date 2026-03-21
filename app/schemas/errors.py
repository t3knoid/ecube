"""Pydantic schemas for standardized error responses."""

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Uniform error payload returned by all exception handlers.

    Attributes:
        code: A machine-readable error code (e.g. ``"CONFLICT"``).
        message: A human-readable description of the error.
        trace_id: Correlation identifier for log tracing.
    """

    code: str = Field(..., description="Machine-readable error code (e.g., CONFLICT, NOT_FOUND, UNAUTHORIZED)")
    message: str = Field(..., description="Human-readable description of the error")
    trace_id: str = Field(..., description="Unique correlation ID for tracing in logs")


# ---------------------------------------------------------------------------
# Reusable OpenAPI response declarations
# ---------------------------------------------------------------------------
# Combine these dicts via ``{**R_401, **R_403}`` in route ``responses=``.

_err = {"model": ErrorResponse}

R_400 = {400: {**_err, "description": "Bad request"}}
R_401 = {401: {**_err, "description": "Missing or invalid authentication token"}}
R_403 = {403: {**_err, "description": "Insufficient permissions"}}
R_404 = {404: {**_err, "description": "Resource not found"}}
R_409 = {409: {**_err, "description": "Conflict — resource already exists or operation in progress"}}
R_422 = {422: {**_err, "description": "Validation error"}}
R_500 = {500: {**_err, "description": "Internal server error"}}
R_503 = {503: {**_err, "description": "Service unavailable"}}
R_504 = {504: {**_err, "description": "Operation timed out"}}
