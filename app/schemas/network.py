from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from app.models.network import MountType, MountStatus
from app.utils.sanitize import SafeStr, StrictSafeStr


class MountCreate(BaseModel):
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: StrictSafeStr = Field(..., min_length=1, description="Remote path on the network share (e.g., //server/share for SMB or server:/export for NFS)")
    local_mount_point: StrictSafeStr = Field(..., min_length=2, pattern=r"^/[^\x00-\x1f\x7f\s/][^\x00-\x1f\x7f\s]*$", description="Local filesystem path where the mount will be attached (must be an absolute path with at least one directory component)")
    username: Optional[SafeStr] = Field(default=None, description="Username for authentication (if required)")
    password: Optional[SafeStr] = Field(default=None, description="Password for authentication (if required)")
    credentials_file: Optional[StrictSafeStr] = Field(default=None, description="Path to credentials file (alternative to username/password)")

    @field_validator("local_mount_point")
    @classmethod
    def _validate_mount_point(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("local_mount_point must be an absolute path starting with '/'")
        import posixpath
        if posixpath.normpath(v) == "/":
            raise ValueError("local_mount_point cannot resolve to the root directory")
        if any(ord(c) < 0x20 or ord(c) == 0x7F or c in (' ', '\t', '\n', '\r', '\x0b', '\x0c', '\x85', '\xa0') for c in v):
            raise ValueError("local_mount_point must not contain control or whitespace characters")
        return v


class NetworkMountSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the mount configuration")
    type: MountType = Field(..., description="Mount protocol type (SMB, NFS, etc.)")
    remote_path: str = Field(..., description="Remote path on the network share")
    local_mount_point: str = Field(..., description="Local filesystem path where the mount is attached")
    status: MountStatus = Field(..., description="Current mount status (MOUNTED, UNMOUNTED, ERROR)")
    last_checked_at: Optional[datetime] = Field(default=None, description="Timestamp of last connectivity check")

    model_config = {"from_attributes": True}
