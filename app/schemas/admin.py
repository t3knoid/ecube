"""Pydantic schemas for administrative endpoints (log file access)."""

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class LogFileInfo(BaseModel):
    """Metadata about a single log file."""

    name: str = Field(..., description="Log file name (e.g. app.log, app.log.1)")
    size: int = Field(..., description="File size in bytes")
    created: datetime = Field(..., description="File creation timestamp (ISO 8601)")
    modified: datetime = Field(..., description="File last-modified timestamp (ISO 8601)")


class LogFilesResponse(BaseModel):
    """Response for ``GET /admin/logs``."""

    log_files: List[LogFileInfo] = Field(default_factory=list, description="Available log files")
    total_size: int = Field(..., description="Total size of all log files in bytes")
    log_directory: str = Field(..., description="Absolute path to the log directory")
