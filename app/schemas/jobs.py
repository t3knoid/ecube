from datetime import datetime

from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationInfo, field_validator
from typing import Literal, Optional

from app.models.hardware import DriveState
from app.models.jobs import FileStatus, JobStatus, StartupAnalysisStatus
from app.schemas.types import StrictIntMixin
from app.utils.callback_url_validation import validate_callback_url_value
from app.utils.sanitize import ProjectIdStr, SafeStr, StrictSafeStr


class FileHashesResponse(BaseModel):
    file_id: int = Field(..., description="Unique identifier for the file")
    relative_path: str = Field(..., description="Relative path of the file from source root")
    md5: Optional[str] = Field(default=None, description="MD5 hash (computed live if file is on disk)")
    sha256: Optional[str] = Field(default=None, description="SHA-256 hash (computed live or from stored checksum)")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")

    model_config = {"from_attributes": True}


class FileCompareRequest(StrictIntMixin, BaseModel):
    file_id_a: StrictInt = Field(..., description="First file ID to compare")
    file_id_b: StrictInt = Field(..., description="Second file ID to compare")


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


class JobCreate(StrictIntMixin, BaseModel):
    project_id: ProjectIdStr = Field(..., min_length=1, description="Project ID for isolation enforcement")
    evidence_number: SafeStr = Field(..., min_length=1, description="Evidence case number or identifier")
    source_path: StrictSafeStr = Field(..., min_length=1, description="Path to source data on the selected mounted share or local filesystem")
    mount_id: Optional[StrictInt] = Field(default=None, ge=1, description="Mounted share selected as the trusted source root")
    drive_id: Optional[StrictInt] = Field(default=None, ge=1, description="Pre-assigned USB drive ID")
    overflow_drive_ids: list[StrictInt] = Field(default_factory=list, description="Reserved overflow drive IDs, in continuation order")
    thread_count: Optional[StrictInt] = Field(default=None, ge=1, le=32, description="Number of parallel copy threads (1-32, optional; defaults to the configured worker count)")
    copy_chunk_size_bytes: Optional[StrictInt] = Field(default=None, ge=262_144, le=67_108_864, description="Optional per-job copy chunk size override in bytes")
    copy_progress_flush_bytes: Optional[StrictInt] = Field(default=None, ge=1_048_576, le=1_073_741_824, description="Optional per-job progress flush threshold override in bytes")
    copy_file_fsync_enabled: Optional[bool] = Field(default=None, description="Optional per-job per-file fsync override")
    startup_analysis_auto_apply_recommended_profile: Optional[bool] = Field(default=False, description="Whether startup analysis should auto-apply the recommended workload profile for this job")
    max_file_retries: StrictInt = Field(default=3, ge=0, le=100, description="Maximum number of retries for failed files (0-100)")
    retry_delay_seconds: StrictInt = Field(default=1, ge=0, le=3600, description="Delay between retries in seconds (0-3600)")
    notes: Optional[SafeStr] = Field(default=None, description="Optional processor notes supplied during job creation")
    allow_insecure_callback_url: Optional[StrictBool] = Field(default=False, description="Must be true to allow an http:// callback_url for testing only")
    callback_url: Optional[SafeStr] = Field(default=None, json_schema_extra={"pattern": "^https?://[a-zA-Z0-9]"}, description="Callback URL to receive POST callbacks for persisted job lifecycle events such as creation, start, pause, completion, archive, and reconciliation. HTTPS is required unless allow_insecure_callback_url is explicitly true for testing.")

    @field_validator("source_path")
    @classmethod
    def _source_path_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Source path is required")
        return v

    @field_validator("notes")
    @classmethod
    def _notes_blank_to_none(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        return v

    @field_validator("callback_url")
    @classmethod
    def _validate_callback_fields(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        return validate_callback_url_value(
            field_name="callback_url",
            value=value,
            allow_insecure_http=bool(info.data.get("allow_insecure_callback_url")),
            confirmation_field_name="allow_insecure_callback_url",
        )

    @field_validator("overflow_drive_ids")
    @classmethod
    def _overflow_drive_ids_must_be_unique(cls, values: list[int]) -> list[int]:
        normalized = [int(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("overflow_drive_ids must not contain duplicates")
        return normalized


class JobStart(StrictIntMixin, BaseModel):
    thread_count: Optional[StrictInt] = Field(default=None, ge=1, le=32, description="Override thread count for this job start (1-32, optional)")


class JobOverflowContinueRequest(StrictIntMixin, BaseModel):
    drive_id: StrictInt = Field(..., ge=1, description="Mounted USB drive ID to use for overflow continuation")
    thread_count: Optional[StrictInt] = Field(default=None, ge=1, le=32, description="Override thread count for this overflow continuation run (1-32, optional)")


class JobStartupAnalysisClearRequest(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: bool = Field(..., description="Must be true to confirm startup analysis cache cleanup")


class JobArchiveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    confirm: bool = Field(..., description="Must be true to confirm job archival")


class JobAnalyzeRequest(BaseModel):
    model_config = {"extra": "forbid"}


class JobUpdate(StrictIntMixin, BaseModel):
    """Full job update payload for editable non-active jobs."""

    model_config = {"extra": "forbid"}

    project_id: ProjectIdStr = Field(..., min_length=1, description="Project ID for isolation enforcement")
    evidence_number: SafeStr = Field(..., min_length=1, description="Evidence case number or identifier")
    source_path: StrictSafeStr = Field(..., min_length=1, description="Path to source data on the selected mounted share or local filesystem")
    mount_id: Optional[StrictInt] = Field(default=None, ge=1, description="Mounted share selected as the trusted source root")
    drive_id: Optional[StrictInt] = Field(default=None, ge=1, description="Pre-assigned USB drive ID")
    overflow_drive_ids: list[StrictInt] = Field(default_factory=list, description="Reserved overflow drive IDs, in continuation order")
    thread_count: Optional[StrictInt] = Field(default=None, ge=1, le=32, description="Optional per-job copy thread override (1-32)")
    copy_chunk_size_bytes: Optional[StrictInt] = Field(default=None, ge=262_144, le=67_108_864, description="Optional per-job copy chunk size override in bytes")
    copy_progress_flush_bytes: Optional[StrictInt] = Field(default=None, ge=1_048_576, le=1_073_741_824, description="Optional per-job progress flush threshold override in bytes")
    copy_file_fsync_enabled: Optional[bool] = Field(default=None, description="Optional per-job per-file fsync override")
    max_file_retries: StrictInt = Field(default=3, ge=0, le=100, description="Maximum number of retries for failed files (0-100)")
    retry_delay_seconds: StrictInt = Field(default=1, ge=0, le=3600, description="Delay between retries in seconds (0-3600)")
    allow_insecure_callback_url: Optional[StrictBool] = Field(default=False, description="Must be true to allow an http:// callback_url for testing only")
    callback_url: Optional[SafeStr] = Field(default=None, json_schema_extra={"pattern": "^https?://[a-zA-Z0-9]"}, description="Callback URL to receive POST callbacks for persisted job lifecycle events such as creation, start, pause, completion, archive, and reconciliation. HTTPS is required unless allow_insecure_callback_url is explicitly true for testing.")

    @field_validator("source_path")
    @classmethod
    def _source_path_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Source path is required")
        return v

    @field_validator("overflow_drive_ids")
    @classmethod
    def _overflow_drive_ids_must_be_unique(cls, values: list[int]) -> list[int]:
        normalized = [int(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("overflow_drive_ids must not contain duplicates")
        return normalized

    @field_validator("callback_url")
    @classmethod
    def _validate_callback_fields(cls, value: Optional[str], info: ValidationInfo) -> Optional[str]:
        return validate_callback_url_value(
            field_name="callback_url",
            value=value,
            allow_insecure_http=bool(info.data.get("allow_insecure_callback_url")),
            confirmation_field_name="allow_insecure_callback_url",
        )


class JobDeleteResponse(BaseModel):
    job_id: int = Field(..., description="ID of the deleted job")
    status: str = Field(..., description="Deletion result status")


class JobCopyTuningDefaults(BaseModel):
    """Current configured copy tuning defaults used to seed new jobs.

    Bounds are intentionally permissive on this read-only response. Input
    validation lives on the Configuration write path; clamping responses to
    a stricter range here would cause readbacks to fail if a future settings
    value (e.g. an ``.env`` override) sits outside the input range. The
    ``ge=1`` floors only guard against logically invalid (zero/negative)
    values that should never be served.
    """

    thread_count: int = Field(..., ge=1, description="Configured default worker thread pool size")
    copy_chunk_size_bytes: int = Field(..., ge=1, description="Configured default copy chunk size in bytes")
    copy_progress_flush_bytes: int = Field(..., ge=1, description="Configured default progress flush threshold in bytes")
    copy_file_fsync_enabled: bool = Field(..., description="Configured default per-file fsync behavior")


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


class JobFileRowSchema(BaseModel):
    """Operator-safe file row for ``GET /jobs/{job_id}/files``."""

    id: int = Field(..., description="Unique identifier for the file")
    relative_path: str = Field(..., description="Relative path from source root")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes when available")
    status: FileStatus = Field(..., description="Current file status")
    checksum: Optional[str] = Field(default=None, description="Stored checksum when available")
    error_message: Optional[str] = Field(default=None, description="Operator-safe file error detail when available")
    drive_assignment_id: Optional[int] = Field(default=None, description="Drive-assignment record that completed this file copy when available")
    destination_drive_id: Optional[int] = Field(default=None, description="Drive ID that holds the copied file when available")
    destination_drive_label: Optional[str] = Field(default=None, description="Operator-friendly label for the destination drive when available")

    model_config = {"from_attributes": True}


class JobFilesResponse(BaseModel):
    """Response for ``GET /jobs/{job_id}/files``."""

    job_id: int = Field(..., description="Parent export job ID")
    page: int = Field(default=1, description="Current 1-based page of file rows returned")
    page_size: int = Field(default=40, description="Requested page size for file rows")
    total_files: int = Field(default=0, description="Total number of file rows available for this job")
    returned_files: int = Field(default=0, description="Number of file rows included in this response")
    files: list[JobFileRowSchema] = Field(default_factory=list, description="File-level status rows for the job")


class DriveInfoSchema(BaseModel):
    """Subset of drive metadata embedded in job responses."""

    id: int = Field(..., description="Unique identifier for the drive")
    port_number: Optional[int] = Field(default=None, description="Port number on the parent USB hub when available")
    speed: Optional[str] = Field(default=None, description="Port speed in Mbps when available")
    port_system_path: Optional[str] = Field(default=None, description="Port-based USB identifier (for example '2-1')")
    manufacturer: Optional[str] = Field(default=None, description="USB manufacturer string when available")
    product_name: Optional[str] = Field(default=None, description="USB product string when available")
    display_device_label: str = Field(..., description="Operator-friendly drive label built from safe USB metadata")
    device_identifier: str = Field(
        ...,
        description="Stable hardware identifier for the drive built from available USB metadata",
    )
    filesystem_path: Optional[str] = Field(default=None, description="Current OS block device node (e.g. /dev/sdb)")
    capacity_bytes: Optional[int] = Field(default=None, description="Total storage capacity in bytes")
    available_bytes: Optional[int] = Field(default=None, description="Last known available space in bytes for the mounted drive")
    filesystem_type: Optional[str] = Field(default=None, description="Detected filesystem label (e.g. ext4, exfat)")
    current_state: DriveState = Field(..., description="Current drive state (DISCONNECTED, DISABLED, AVAILABLE, IN_USE)")
    is_mounted: bool = Field(default=False, description="Whether the drive is still mounted on the host")
    current_project_id: Optional[str] = Field(default=None, description="Bound project ID if IN_USE")

    model_config = {"from_attributes": True}


class JobOverflowDriveSchema(BaseModel):
    """Redacted drive metadata embedded in overflow-assignment responses."""

    id: int = Field(..., description="Unique identifier for the drive")
    manufacturer: Optional[str] = Field(default=None, description="USB manufacturer string when available")
    product_name: Optional[str] = Field(default=None, description="USB product string when available")
    display_device_label: str = Field(..., description="Operator-friendly drive label built from safe USB metadata")
    available_bytes: Optional[int] = Field(default=None, description="Last known available space in bytes for the mounted drive")
    filesystem_type: Optional[str] = Field(default=None, description="Detected filesystem label (e.g. ext4, exfat)")
    current_state: DriveState = Field(..., description="Current drive state (DISCONNECTED, DISABLED, AVAILABLE, IN_USE)")
    is_mounted: bool = Field(default=False, description="Whether the drive is still mounted on the host")
    current_project_id: Optional[str] = Field(default=None, description="Bound project ID if IN_USE")

    model_config = {"from_attributes": True}


class JobOverflowAssignmentSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the drive-assignment record")
    drive_id: int = Field(..., description="Drive ID assigned for overflow continuation")
    file_count: int = Field(default=0, description="Number of files copied to this assignment so far")
    copied_bytes: int = Field(default=0, description="Number of bytes copied to this assignment so far")
    assigned_at: Optional[datetime] = Field(default=None, description="When this overflow drive was reserved for the job")
    activated_at: Optional[datetime] = Field(default=None, description="When this overflow drive became the active destination")
    released_at: Optional[datetime] = Field(default=None, description="When this overflow drive stopped being the active destination")
    state: str = Field(..., description="Operator-safe overflow assignment state (RESERVED, ACTIVE, RELEASED)")
    drive: Optional[JobOverflowDriveSchema] = Field(default=None, description="Assigned overflow drive metadata when available")

    model_config = {"from_attributes": True}


class JobStartupAnalysisSizeDistributionSchema(BaseModel):
    small_files: int = Field(default=0, ge=0, description="Count of discovered files with size <= 64 KiB")
    medium_files: int = Field(default=0, ge=0, description="Count of discovered files with size > 64 KiB and < 8 MiB")
    large_files: int = Field(default=0, ge=0, description="Count of discovered files with size >= 8 MiB")
    small_files_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of discovered files in the small bucket")
    medium_files_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of discovered files in the medium bucket")
    large_files_percent: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of discovered files in the large bucket")
    average_file_size_bytes: int = Field(default=0, ge=0, description="Average discovered file size in bytes")
    total_files: int = Field(default=0, ge=0, description="Total number of discovered files used to compute this summary")
    total_bytes: int = Field(default=0, ge=0, description="Total discovered bytes used to compute this summary")


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
    files_timed_out: int = Field(default=0, description="Number of files that timed out during copy (can be retried later)")
    thread_count: Optional[int] = Field(default=None, ge=1, le=32, description="Resolved thread count used at runtime after applying fallback rules")
    thread_count_override: Optional[int] = Field(default=None, ge=1, le=32, description="Stored per-job thread-count override (null when the job uses the configuration default)")
    effective_thread_count: Optional[int] = Field(default=None, ge=1, le=32, description="Resolved thread count used at runtime after applying fallback rules")
    thread_count_source: Optional[str] = Field(default=None, description="Whether the effective thread count came from the job override or the global configuration default")
    copy_chunk_size_bytes: Optional[int] = Field(default=None, ge=262_144, le=67_108_864, description="Stored per-job copy chunk size override in bytes")
    effective_copy_chunk_size_bytes: Optional[int] = Field(default=None, ge=262_144, le=67_108_864, description="Resolved copy chunk size used at runtime in bytes")
    copy_chunk_size_source: Optional[str] = Field(default=None, description="Whether the effective copy chunk size came from the job override or the global configuration default")
    copy_progress_flush_bytes: Optional[int] = Field(default=None, ge=1_048_576, le=1_073_741_824, description="Stored per-job progress flush threshold override in bytes")
    effective_copy_progress_flush_bytes: Optional[int] = Field(default=None, ge=1_048_576, le=1_073_741_824, description="Resolved progress flush threshold used at runtime in bytes")
    copy_progress_flush_source: Optional[str] = Field(default=None, description="Whether the effective progress flush threshold came from the job override or the global configuration default")
    copy_file_fsync_enabled: Optional[bool] = Field(default=None, description="Stored per-job per-file fsync override (null when the job uses the configuration default)")
    effective_copy_file_fsync_enabled: Optional[bool] = Field(default=None, description="Resolved per-file fsync behavior used at runtime")
    copy_file_fsync_source: Optional[str] = Field(default=None, description="Whether the effective per-file fsync behavior came from the job override or the global configuration default")
    startup_analysis_auto_apply_recommended_profile: bool = Field(default=False, description="Whether this job will auto-apply its startup-analysis recommendation when one is available")
    max_file_retries: int = Field(default=3, ge=0, description="Maximum number of retries for failed files (0+)")
    retry_delay_seconds: int = Field(default=1, ge=0, description="Delay between retries in seconds (0+)")
    active_duration_seconds: int = Field(default=0, ge=0, description="Total active copy duration across all run/resume cycles in seconds")
    created_by: Optional[str] = Field(default=None, description="Username of the job creator")
    started_by: Optional[str] = Field(default=None, description="Username of the user who started the job")
    notes: Optional[str] = Field(default=None, description="Optional operator notes captured when the job was created")
    callback_url: Optional[str] = Field(default=None, description="Configured callback URL (HTTPS recommended; HTTP is used only for test-only callbacks)")
    created_at: Optional[datetime] = Field(default=None, description="When the job was created")
    started_at: Optional[datetime] = Field(default=None, description="When the copy was started")
    copy_started_at: Optional[datetime] = Field(default=None, description="When the current active copy phase entered RUNNING")
    completed_at: Optional[datetime] = Field(default=None, description="When the job reached a terminal state")
    latest_manifest_created_at: Optional[datetime] = Field(default=None, description="When the most recent manifest for this job was generated")
    drive: Optional[DriveInfoSchema] = Field(default=None, description="Assigned drive metadata (null if no drive assigned)")
    custody_status: Optional[Literal["HANDOFF_RECORDED", "PENDING_HANDOFF", "STATUS_UNAVAILABLE"]] = Field(
        default=None,
        description="Trusted chain-of-custody summary for terminal jobs when it can be derived",
    )
    failure_reason: Optional[str] = Field(default=None, description="Persisted sanitized job-level failure reason (null when not available)")
    error_summary: Optional[str] = Field(default=None, description="Brief summary of file failures (null on success)")
    failure_log_entry: Optional[str] = Field(default=None, description="Correlated application log line for failed jobs (null on success)")
    startup_analysis_status: StartupAnalysisStatus = Field(default=StartupAnalysisStatus.NOT_ANALYZED, description="Current persisted startup-analysis lifecycle state")
    startup_analysis_last_analyzed_at: Optional[datetime] = Field(default=None, description="When startup analysis most recently completed successfully")
    startup_analysis_failure_reason: Optional[str] = Field(default=None, description="Persisted sanitized startup-analysis failure reason when the latest analysis failed")
    startup_analysis_file_count: Optional[int] = Field(default=None, description="Number of files discovered during the latest startup analysis")
    startup_analysis_total_bytes: Optional[int] = Field(default=None, description="Total bytes discovered during the latest startup analysis")
    startup_analysis_share_read_mbps: Optional[float] = Field(default=None, description="Measured startup-analysis source share read speed as a bit-based Mb/s value when available")
    startup_analysis_drive_write_mbps: Optional[float] = Field(default=None, description="Measured startup-analysis target drive write speed as a bit-based Mb/s value when available")
    startup_analysis_estimated_duration_seconds: Optional[int] = Field(default=None, description="Estimated copy duration in seconds based on startup-analysis throughput measurements")
    startup_analysis_cached: bool = Field(default=False, description="Whether a persisted startup-analysis cache is available for restart reuse")
    startup_analysis_ready: bool = Field(default=False, description="Whether a persisted startup-analysis result is ready for Start to reuse")
    startup_analysis_size_distribution: Optional[JobStartupAnalysisSizeDistributionSchema] = Field(default=None, description="Derived file-size distribution summary from persisted startup-analysis entries")
    startup_analysis_recommended_workload_profile: Optional[str] = Field(default=None, description="Deterministic startup-analysis recommendation (small_files, mixed, large_files, or greedy)")
    client_ip: Optional[str] = Field(default=None, description="IP address of the client that created the job (null for background tasks or when redacted; 'unknown' when the client address could not be resolved)")
    overflow_assignments: list[JobOverflowAssignmentSchema] = Field(default_factory=list, description="Overflow drive assignments for this job, excluding the primary destination assignment")

    model_config = {"from_attributes": True}
