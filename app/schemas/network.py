from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.jobs import JobStatus
from app.models.network import MountType, MountStatus
from app.utils.sanitize import ProjectIdStr, SafeStr, StrictSafeStr


NfsClientVersion = Literal["4.2", "4.1", "4.0", "3"]


class ShareCreate(BaseModel):
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: StrictSafeStr = Field(..., min_length=1, description="Remote path on the network share (e.g., //server/share for SMB or server:/export for NFS)")
    project_id: ProjectIdStr = Field(..., min_length=1, description="Project assigned to this share")
    nfs_client_version: Optional[NfsClientVersion] = Field(default=None, description="Requested NFS client protocol version when type is NFS")
    username: Optional[SafeStr] = Field(default=None, description="Username for authentication (if required)")
    password: Optional[SafeStr] = Field(default=None, description="Password for authentication (if required)")
    credentials_file: Optional[StrictSafeStr] = Field(default=None, description="Path to credentials file (alternative to username/password)")

    model_config = {"extra": "forbid"}


class ShareUpdate(ShareCreate):
    pass


class MountShareDiscoveryRequest(BaseModel):
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: StrictSafeStr = Field(..., min_length=1, description="Server address seed for share discovery (for example //server or server)")
    username: Optional[SafeStr] = Field(default=None, description="Username for discovery when required")
    password: Optional[SafeStr] = Field(default=None, description="Password for discovery when required")
    credentials_file: Optional[StrictSafeStr] = Field(default=None, description="Path to credentials file used for discovery")

    model_config = {"extra": "forbid"}


class MountShareDiscoveryItem(BaseModel):
    remote_path: str = Field(..., description="Discovered remote path that can populate the Add Mount dialog")
    display_name: str = Field(..., description="Short operator-facing label for the discovered share")


class MountShareDiscoveryResponse(BaseModel):
    shares: list[MountShareDiscoveryItem] = Field(default_factory=list, description="Discovered shares or exports for the requested server")


class ShareRelatedJobSchema(BaseModel):
    job_id: Optional[int] = Field(default=None, description="Related job ID for the share's current project workflow")
    status: JobStatus | Literal["STATUS_UNAVAILABLE", "NO_RELATED_JOB"] = Field(
        ...,
        description="Trusted lifecycle status for the related job, or a safe fallback when no authoritative job status is available",
    )
    custody_status: Literal["HANDOFF_RECORDED", "PENDING_HANDOFF", "STATUS_UNAVAILABLE", "NO_RELATED_JOB"] = Field(
        default="STATUS_UNAVAILABLE",
        description="Trusted custody status for the related job workflow when available",
    )


class NetworkShareSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the share configuration")
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: str = Field(..., description="Remote path on the network share")
    project_id: str = Field(..., description="Project assigned to the share")
    nfs_client_version: Optional[NfsClientVersion] = Field(default=None, description="Configured NFS client protocol version when type is NFS")
    local_mount_point: str = Field(..., description="Local filesystem path where the share is attached")
    status: MountStatus = Field(..., description="Current share status (MOUNTED, UNMOUNTED, ERROR)")
    last_checked_at: Optional[datetime] = Field(default=None, description="Timestamp of last connectivity check")
    throughput_read_mbps: Optional[float] = Field(default=None, description="Most recent measured manual share read speed in MB/s when available")
    throughput_tested_at: Optional[datetime] = Field(default=None, description="Timestamp of the most recent manual throughput test for this share")
    related_job: Optional[ShareRelatedJobSchema] = Field(
        default=None,
        description="Trusted related job context for the share's current project workflow when available",
    )

    model_config = {"from_attributes": True}


class CandidateNetworkShareSchema(BaseModel):
    id: Optional[int] = Field(default=None, description="Identifier for a persisted share configuration, when available")
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: str = Field(..., description="Remote path on the network share")
    project_id: str = Field(..., description="Project assigned to the share")
    nfs_client_version: Optional[NfsClientVersion] = Field(default=None, description="Configured NFS client protocol version when type is NFS")
    local_mount_point: str = Field(..., description="Local filesystem path that would be used for the share")
    status: MountStatus = Field(..., description="Current share status (MOUNTED, UNMOUNTED, ERROR)")
    last_checked_at: Optional[datetime] = Field(default=None, description="Timestamp of last connectivity check")
    validation_warning: Optional[str] = Field(default=None, description="Optional operator-facing warning produced during validation-only probing")

    model_config = {"from_attributes": True}
