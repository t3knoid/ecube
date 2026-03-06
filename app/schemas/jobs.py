from pydantic import BaseModel
from typing import Optional
from app.models.jobs import JobStatus, FileStatus


class FileHashesResponse(BaseModel):
    file_id: int
    relative_path: str
    md5: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None

    model_config = {"from_attributes": True}


class FileCompareRequest(BaseModel):
    file_id_a: int
    file_id_b: int


class FileCompareItem(BaseModel):
    file_id: int
    relative_path: str
    md5: Optional[str] = None
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None

    model_config = {"from_attributes": True}


class FileCompareResponse(BaseModel):
    match: bool
    hash_match: Optional[bool] = None
    size_match: Optional[bool] = None
    path_match: Optional[bool] = None
    file_a: FileCompareItem
    file_b: FileCompareItem


class JobCreate(BaseModel):
    project_id: str
    evidence_number: str
    source_path: str
    target_mount_path: Optional[str] = None
    drive_id: Optional[int] = None
    thread_count: int = 4
    max_file_retries: int = 3
    retry_delay_seconds: int = 1
    created_by: Optional[str] = None


class JobStart(BaseModel):
    thread_count: Optional[int] = None


class ExportFileSchema(BaseModel):
    id: int
    job_id: int
    relative_path: str
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None
    status: FileStatus
    error_message: Optional[str] = None
    retry_attempts: int = 0

    model_config = {"from_attributes": True}


class ExportJobSchema(BaseModel):
    id: int
    project_id: str
    evidence_number: str
    source_path: str
    target_mount_path: Optional[str] = None
    status: JobStatus
    total_bytes: int
    copied_bytes: int
    file_count: int
    thread_count: int
    max_file_retries: int = 3
    retry_delay_seconds: int = 1
    created_by: Optional[str] = None

    model_config = {"from_attributes": True}
