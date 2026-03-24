from datetime import datetime

from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator
from typing import Optional
from urllib.parse import urlparse

from app.models.hardware import DriveState
from app.models.jobs import JobStatus, FileStatus
from app.utils.sanitize import SafeStr, StrictSafeStr


class FileHashesResponse(BaseModel):
    file_id: int = Field(..., description="Unique identifier for the file")
    relative_path: str = Field(..., description="Relative path of the file from source root")
    md5: Optional[str] = Field(default=None, description="MD5 hash (computed live if file is on disk)")
    sha256: Optional[str] = Field(default=None, description="SHA-256 hash (computed live or from stored checksum)")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")

    model_config = {"from_attributes": True}


class FileCompareRequest(BaseModel):
    file_id_a: int = Field(..., description="First file ID to compare")
    file_id_b: int = Field(..., description="Second file ID to compare")


class FileCompareItem(BaseModel):
    file_id: int = Field(..., description="Unique identifier for the file")
    relative_path: str = Field(..., description="Relative path of the file from source root")
    md5: Optional[str] = Field(default=None, description="MD5 hash if available")
    sha256: Optional[str] = Field(default=None, description="SHA-256 hash if available")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")

    model_config = {"from_attributes": True}


class FileCompareResponse(BaseModel):
    match: bool = Field(
        ...,
        description=(
            "Overall comparison result: True only when hash_match and path_match are True and "
            "size_match is not explicitly False (size_match may be None if size is unknown)"
        ),
    )
    hash_match: Optional[bool] = Field(default=None, description="Hash comparison result (None if unknown)")
    size_match: Optional[bool] = Field(default=None, description="Size comparison result (None if unknown)")
    path_match: Optional[bool] = Field(default=None, description="Relative path comparison result")
    file_a: FileCompareItem = Field(..., description="First file details")
    file_b: FileCompareItem = Field(..., description="Second file details")


class JobCreate(BaseModel):
    project_id: SafeStr = Field(..., min_length=1, description="Project ID for isolation enforcement")
    evidence_number: SafeStr = Field(..., min_length=1, description="Evidence case number or identifier")
    source_path: StrictSafeStr = Field(..., min_length=1, description="Path to source data on network mount or local filesystem")
    target_mount_path: Optional[StrictSafeStr] = Field(default=None, description="Alternative target mount; defaults to assigned drive")
    drive_id: Optional[int] = Field(default=None, description="Pre-assigned USB drive ID")
    thread_count: StrictInt = Field(default=4, ge=1, le=8, description="Number of parallel copy threads (1-8)")
    max_file_retries: StrictInt = Field(default=3, ge=0, description="Maximum number of retries for failed files (0+)")
    retry_delay_seconds: StrictInt = Field(default=1, ge=0, description="Delay between retries in seconds (0+)")
    created_by: Optional[SafeStr] = Field(default=None, description="Username of the job creator")
    callback_url: Optional[SafeStr] = Field(default=None, description="HTTPS URL to receive a POST callback when the job reaches a terminal state (COMPLETED or FAILED)")

    @field_validator("callback_url")
    @classmethod
    def _callback_url_must_be_valid_https(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        try:
            parsed = urlparse(v)
        except Exception:
            raise ValueError("callback_url is not a valid URL")
        if parsed.scheme.lower() != "https":
            raise ValueError("callback_url must use HTTPS")
        if not parsed.hostname:
            raise ValueError("callback_url must include a hostname")
        if parsed.username or parsed.password:
            raise ValueError("callback_url must not contain embedded credentials")
        return v


class JobStart(BaseModel):
    thread_count: Optional[int] = Field(default=None, ge=1, le=8, description="Override thread count for this job start (1-8, optional)")


class ExportFileSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the file")
    job_id: int = Field(..., description="ID of the parent export job")
    relative_path: str = Field(..., description="Relative path from source root")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    checksum: Optional[str] = Field(default=None, description="SHA-256 checksum computed during copy")
    status: FileStatus = Field(..., description="Current copy/verification status (PENDING, COPYING, DONE, ERROR)")
    error_message: Optional[str] = Field(default=None, description="Error details if status is ERROR")
    retry_attempts: int = Field(default=0, description="Number of retry attempts for the file")

    model_config = {"from_attributes": True}


class DriveInfoSchema(BaseModel):
    """Subset of drive metadata embedded in job responses."""

    id: int = Field(..., description="Unique identifier for the drive")
    device_identifier: str = Field(..., description="Stable hardware identifier for the drive")
    filesystem_path: Optional[str] = Field(default=None, description="Current OS block device node (e.g. /dev/sdb)")
    capacity_bytes: Optional[int] = Field(default=None, description="Total storage capacity in bytes")
    filesystem_type: Optional[str] = Field(default=None, description="Detected filesystem label (e.g. ext4, exfat)")
    current_state: DriveState = Field(..., description="Current drive state (EMPTY, AVAILABLE, IN_USE)")
    current_project_id: Optional[str] = Field(default=None, description="Bound project ID if IN_USE")

    model_config = {"from_attributes": True}


class ExportJobSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the job")
    project_id: str = Field(..., description="Project ID for audit and isolation")
    evidence_number: str = Field(..., description="Evidence case number")
    source_path: str = Field(..., description="Source path of evidence data")
    target_mount_path: Optional[str] = Field(default=None, description="Target mount path for copied data")
    status: JobStatus = Field(..., description="Current job status (PENDING, RUNNING, COMPLETED, FAILED, VERIFYING)")
    total_bytes: int = Field(..., description="Total bytes to copy")
    copied_bytes: int = Field(..., description="Bytes copied so far")
    file_count: int = Field(..., description="Total number of files to copy")
    files_succeeded: int = Field(default=0, description="Number of files successfully copied")
    files_failed: int = Field(default=0, description="Number of files that failed")
    thread_count: int = Field(..., ge=1, le=8, description="Number of parallel threads used (1-8)")
    max_file_retries: int = Field(default=3, ge=0, description="Maximum number of retries for failed files (0+)")
    retry_delay_seconds: int = Field(default=1, ge=0, description="Delay between retries in seconds (0+)")
    created_by: Optional[str] = Field(default=None, description="Username of the job creator")
    started_by: Optional[str] = Field(default=None, description="Username of the user who started the job")
    callback_url: Optional[str] = Field(default=None, description="HTTPS callback URL (null if none was provided)")
    created_at: Optional[datetime] = Field(default=None, description="When the job was created")
    started_at: Optional[datetime] = Field(default=None, description="When the copy was started")
    completed_at: Optional[datetime] = Field(default=None, description="When the job reached a terminal state")
    drive: Optional[DriveInfoSchema] = Field(default=None, description="Assigned drive metadata (null if no drive assigned)")
    error_summary: Optional[str] = Field(default=None, description="Brief summary of file failures (null on success)")
    client_ip: Optional[str] = Field(default=None, description="IP address of the client that created the job (null for background tasks or when redacted; 'unknown' when the client address could not be resolved)")

    model_config = {"from_attributes": True}
