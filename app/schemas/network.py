from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
from app.models.network import MountType, MountStatus
from app.utils.sanitize import SafeStr, StrictSafeStr


class MountCreate(BaseModel):
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: StrictSafeStr = Field(..., min_length=1, description="Remote path on the network share (e.g., //server/share for SMB or server:/export for NFS)")
    local_mount_point: StrictSafeStr = Field(..., min_length=1, description="Local filesystem path where the mount will be attached")
    username: Optional[SafeStr] = Field(default=None, description="Username for authentication (if required)")
    password: Optional[SafeStr] = Field(default=None, description="Password for authentication (if required)")
    credentials_file: Optional[StrictSafeStr] = Field(default=None, description="Path to credentials file (alternative to username/password)")


class NetworkMountSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the mount configuration")
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: str = Field(..., description="Remote path on the network share")
    local_mount_point: str = Field(..., description="Local filesystem path where the mount is attached")
    status: MountStatus = Field(..., description="Current mount status (MOUNTED, UNMOUNTED, ERROR)")
    last_checked_at: Optional[datetime] = Field(default=None, description="Timestamp of last connectivity check")

    model_config = {"from_attributes": True}
