"""Pydantic schemas for the directory browse endpoint."""

from datetime import datetime
from enum import StrEnum
from typing import List, Optional

from pydantic import BaseModel, Field


class EntryType(StrEnum):
    """Filesystem entry type returned by the browse endpoint."""

    FILE = "file"
    DIRECTORY = "directory"
    SYMLINK = "symlink"


class BrowseEntry(BaseModel):
    """A single entry returned by ``GET /browse``."""

    name: str = Field(..., description="File or directory name (basename only)")
    type: EntryType = Field(
        ..., description="Entry type: file, directory, or symlink (symlinks are not dereferenced)"
    )
    size_bytes: Optional[int] = Field(
        default=None,
        description="File size in bytes; null for directories and symlinks",
    )
    modified_at: Optional[datetime] = Field(
        default=None, description="Last-modified timestamp"
    )


class BrowseResponse(BaseModel):
    """Paginated directory listing returned by ``GET /browse``."""

    path: str = Field(..., description="The validated mount root that was browsed")
    subdir: str = Field(
        ..., description="Relative subdirectory within the mount root (empty string for root)"
    )
    entries: List[BrowseEntry] = Field(
        ..., description="Paginated list of directory entries"
    )
    total: int = Field(..., description="Total number of entries in the directory (before pagination)")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Number of entries per page")
