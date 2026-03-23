"""Pydantic schemas for introspection and diagnostic endpoints."""

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response for ``GET /health``."""

    status: str = Field(..., description="Health status ('ok')")


# ---------------------------------------------------------------------------
# /introspection/version
# ---------------------------------------------------------------------------


class VersionResponse(BaseModel):
    """Response for ``GET /introspection/version``."""

    version: str = Field(..., description="Application version")
    api_version: str = Field(..., description="API version")


# ---------------------------------------------------------------------------
# /introspection/drives
# ---------------------------------------------------------------------------


class IntrospectionDriveItem(BaseModel):
    """Single drive in the inventory snapshot."""

    id: int = Field(..., description="Unique drive identifier")
    device_identifier: str = Field(..., description="Stable hardware identifier")
    capacity_bytes: Optional[int] = Field(default=None, description="Storage capacity in bytes")
    current_state: Optional[str] = Field(default=None, description="Drive state (EMPTY, AVAILABLE, IN_USE)")
    current_project_id: Optional[str] = Field(default=None, description="Bound project ID")
    encryption_status: Optional[str] = Field(default=None, description="Encryption status")
    last_seen_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp of last detection")


class IntrospectionDrivesResponse(BaseModel):
    """Response for ``GET /introspection/drives``."""

    drives: List[IntrospectionDriveItem] = Field(default_factory=list, description="Registered USB drives")


# ---------------------------------------------------------------------------
# /introspection/usb/topology
# ---------------------------------------------------------------------------


class UsbDeviceInfo(BaseModel):
    """Single USB device from sysfs enumeration."""

    device: str = Field(..., description="Device name from sysfs")
    idVendor: Optional[str] = Field(default=None, description="USB vendor ID")
    idProduct: Optional[str] = Field(default=None, description="USB product ID")
    product: Optional[str] = Field(default=None, description="Product description")
    manufacturer: Optional[str] = Field(default=None, description="Manufacturer name")


class UsbTopologyResponse(BaseModel):
    """Response for ``GET /introspection/usb/topology``."""

    devices: List[UsbDeviceInfo] = Field(default_factory=list, description="USB devices detected via sysfs")
    error: Optional[str] = Field(default=None, description="Error message if enumeration failed")


# ---------------------------------------------------------------------------
# /introspection/block-devices
# ---------------------------------------------------------------------------


class BlockDeviceItem(BaseModel):
    """Single block device from /proc/diskstats."""

    major: str = Field(..., description="Major device number")
    minor: str = Field(..., description="Minor device number")
    name: str = Field(..., description="Device name (e.g. sda, sdb1)")


class BlockDevicesResponse(BaseModel):
    """Response for ``GET /introspection/block-devices``."""

    block_devices: List[BlockDeviceItem] = Field(default_factory=list, description="Block devices detected by the kernel")


# ---------------------------------------------------------------------------
# /introspection/mounts
# ---------------------------------------------------------------------------


class SystemMountItem(BaseModel):
    """Single mount entry from /proc/mounts."""

    device: str = Field(..., description="Mounted device path")
    mount_point: str = Field(..., description="Local mount point")
    fs_type: str = Field(..., description="Filesystem type")
    options: str = Field(..., description="Mount options (sensitive keys redacted)")


class SystemMountsResponse(BaseModel):
    """Response for ``GET /introspection/mounts``."""

    mounts: List[SystemMountItem] = Field(default_factory=list, description="Currently mounted filesystems")


# ---------------------------------------------------------------------------
# /introspection/system-health
# ---------------------------------------------------------------------------


class SystemHealthResponse(BaseModel):
    """Response for ``GET /introspection/system-health``."""

    status: str = Field(..., description="Overall health status ('ok' or 'degraded')")
    database: str = Field(..., description="Database connectivity ('connected' or 'error')")
    database_error: Optional[str] = Field(default=None, description="Error detail if database is unreachable")
    active_jobs: int = Field(default=0, description="Number of currently running export jobs")


# ---------------------------------------------------------------------------
# /introspection/jobs/{job_id}/debug
# ---------------------------------------------------------------------------


class DebugFileItem(BaseModel):
    """Single file in a job debug snapshot."""

    id: int = Field(..., description="Unique file identifier")
    relative_path: str = Field(..., description="Relative path from source root")
    status: str = Field(..., description="Copy/verification status")
    checksum: Optional[str] = Field(default=None, description="SHA-256 checksum")
    error_message: Optional[str] = Field(default=None, description="Error detail if status is ERROR")


class JobDebugResponse(BaseModel):
    """Response for ``GET /introspection/jobs/{job_id}/debug``."""

    job_id: int = Field(..., description="Export job ID")
    status: str = Field(..., description="Current job status")
    project_id: str = Field(..., description="Project ID")
    source_path: str = Field(..., description="Source data path")
    target_mount_path: Optional[str] = Field(default=None, description="Target mount path")
    total_bytes: int = Field(default=0, description="Total bytes to copy")
    copied_bytes: int = Field(default=0, description="Bytes copied so far")
    file_count: int = Field(default=0, description="Total number of files")
    thread_count: int = Field(default=0, description="Parallel thread count")
    files: List[DebugFileItem] = Field(default_factory=list, description="File-level status details")
