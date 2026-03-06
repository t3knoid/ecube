from pydantic import BaseModel, Field
from typing import Optional
from app.models.jobs import JobStatus, FileStatus


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
    project_id: str = Field(..., description="Project ID for isolation enforcement")
    evidence_number: str = Field(..., description="Evidence case number or identifier")
    source_path: str = Field(..., description="Path to source data on network mount or local filesystem")
    target_mount_path: Optional[str] = Field(default=None, description="Alternative target mount; defaults to assigned drive")
    drive_id: Optional[int] = Field(default=None, description="Pre-assigned USB drive ID")
    thread_count: int = Field(default=4, description="Number of parallel copy threads (1-8)")
    created_by: Optional[str] = Field(default=None, description="Username of the job creator")


class JobStart(BaseModel):
    thread_count: Optional[int] = Field(default=None, description="Override thread count for this job start")


class ExportFileSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the file")
    job_id: int = Field(..., description="ID of the parent export job")
    relative_path: str = Field(..., description="Relative path from source root")
    size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    checksum: Optional[str] = Field(default=None, description="SHA-256 checksum computed during copy")
    status: FileStatus = Field(..., description="Current copy/verification status (PENDING, COPYING, DONE, ERROR)")
    error_message: Optional[str] = Field(default=None, description="Error details if status is ERROR")

    model_config = {"from_attributes": True}


class ExportJobSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the job")
    project_id: str = Field(..., description="Project ID for audit and isolation")
    evidence_number: str = Field(..., description="Evidence case number")
    source_path: str = Field(..., description="Source path of evidence data")
    target_mount_path: Optional[str] = Field(default=None, description="Target mount path for copied data")
    status: JobStatus = Field(..., description="Current job status (PENDING, RUNNING, COMPLETED, FAILED, VERIFYING, VERIFIED)")
    total_bytes: int = Field(..., description="Total bytes to copy")
    copied_bytes: int = Field(..., description="Bytes copied so far")
    file_count: int = Field(..., description="Total number of files to copy")
    thread_count: int = Field(..., description="Number of parallel threads used")
    created_by: Optional[str] = Field(default=None, description="Username of the job creator")

    model_config = {"from_attributes": True}
