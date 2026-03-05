from pydantic import BaseModel
from typing import Optional
from app.models.jobs import JobStatus, FileStatus


class JobCreate(BaseModel):
    project_id: str
    evidence_number: str
    source_path: str
    target_mount_path: Optional[str] = None
    drive_id: Optional[int] = None
    thread_count: int = 4
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
    created_by: Optional[str] = None

    model_config = {"from_attributes": True}
