"""Pydantic schemas for introspection and diagnostic endpoints."""

from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response for ``GET /health``."""

    status: str = Field(..., description="Health status ('ok')")


class HealthLiveResponse(BaseModel):
    """Response for ``GET /health/live``."""

    status: str = Field(..., description="Liveness status ('alive')")
    timestamp: str = Field(..., description="UTC timestamp in ISO 8601 format")


class HealthReadyChecks(BaseModel):
    """Dependency check breakdown for ``GET /health/ready``."""

    database: str = Field(..., description="Database readiness check result")
    file_system: str = Field(..., description="Filesystem mount readiness result")
    usb_discovery: str = Field(..., description="USB discovery readiness result")


class HealthReadyResponse(BaseModel):
    """Response for ready state from ``GET /health/ready``."""

    status: str = Field(..., description="Readiness status ('ready')")
    timestamp: str = Field(..., description="UTC timestamp in ISO 8601 format")
    checks: HealthReadyChecks = Field(..., description="Per-dependency readiness checks")


class HealthNotReadyResponse(BaseModel):
    """Response for non-ready state from ``GET /health/ready``."""

    status: str = Field(..., description="Readiness status ('not_ready')")
    reason: str = Field(..., description="Machine-readable reason code")
    details: str = Field(..., description="Human-readable failure detail")
    timestamp: str = Field(..., description="UTC timestamp in ISO 8601 format")
    checks: HealthReadyChecks = Field(
        ...,
        description="Per-dependency readiness checks for the current failure state",
    )


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
    port_system_path: Optional[str] = Field(default=None, description="Port-based USB identifier (for example '2-1')")
    device_identifier: str = Field(..., description="Stable hardware identifier")
    serial_number: Optional[str] = Field(default=None, description="USB serial number when available")
    capacity_bytes: Optional[int] = Field(default=None, description="Storage capacity in bytes")
    current_state: Optional[str] = Field(default=None, description="Drive state (DISCONNECTED, AVAILABLE, IN_USE)")
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
    serial: Optional[str] = Field(default=None, description="USB serial number")
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


class EcubeCopyThreadResponse(BaseModel):
    """Single active ECUBE copy worker correlated to its parent job."""

    job_id: int = Field(..., description="Export job identifier that owns this active worker")
    project_id: Optional[str] = Field(default=None, description="Project ID for the parent job when available")
    job_status: Optional[str] = Field(default=None, description="Current parent job status when available")
    configured_thread_count: Optional[int] = Field(default=None, description="Configured parallel thread count for the parent job")
    worker_label: str = Field(..., description="ECUBE-owned worker label for the active thread")
    started_at: str = Field(..., description="UTC timestamp when the active worker began its current file")
    elapsed_seconds: Optional[float] = Field(default=None, description="Elapsed runtime for the current active worker task")
    cpu_user_seconds: Optional[float] = Field(default=None, description="Per-thread user CPU time when available")
    cpu_system_seconds: Optional[float] = Field(default=None, description="Per-thread system CPU time when available")
    cpu_time_seconds: Optional[float] = Field(default=None, description="Combined per-thread CPU time when available")
    memory_bytes: Optional[int] = Field(default=None, description="Per-thread memory usage when the host can provide it")
    metrics_available: bool = Field(default=False, description="Whether per-thread CPU metrics were collected reliably")
    metrics_note: Optional[str] = Field(default=None, description="Operator-facing note when thread metrics are partially unavailable")


class EcubeProcessMetricsResponse(BaseModel):
    """ECUBE-process diagnostics shown beside host-level system health."""

    cpu_percent: Optional[float] = Field(default=None, description="CPU utilisation percent for the ECUBE process when available")
    cpu_time_seconds: Optional[float] = Field(default=None, description="Combined user and system CPU time consumed by the ECUBE process")
    memory_rss_bytes: Optional[int] = Field(default=None, description="Resident memory used by the ECUBE process in bytes")
    memory_vms_bytes: Optional[int] = Field(default=None, description="Virtual memory reserved by the ECUBE process in bytes")
    thread_count: Optional[int] = Field(default=None, description="Total OS threads currently owned by the ECUBE process")
    active_copy_thread_count: int = Field(default=0, description="Number of active ECUBE copy workers currently tracked")
    active_copy_threads: List[EcubeCopyThreadResponse] = Field(default_factory=list, description="Active ECUBE copy workers correlated to their parent export job")


class SystemHealthResponse(BaseModel):
    """Response for ``GET /introspection/system-health``."""

    status: str = Field(..., description="Overall health status ('ok' or 'degraded')")
    database: str = Field(..., description="Database connectivity ('connected' or 'error')")
    database_error: Optional[str] = Field(default=None, description="Error detail if database is unreachable")
    active_jobs: int = Field(default=0, description="Number of currently running export jobs")
    cpu_percent: Optional[float] = Field(default=None, description="CPU utilisation percent (0–100)")
    memory_percent: Optional[float] = Field(default=None, description="Memory utilisation percent (0–100)")
    memory_used_bytes: Optional[int] = Field(default=None, description="Used physical memory in bytes")
    memory_total_bytes: Optional[int] = Field(default=None, description="Total physical memory in bytes")
    disk_read_bytes: Optional[int] = Field(default=None, description="Cumulative disk read bytes since boot")
    disk_write_bytes: Optional[int] = Field(default=None, description="Cumulative disk write bytes since boot")
    worker_queue_size: Optional[int] = Field(default=None, description="Number of pending (queued) export jobs; null when the database is unreachable or the count query fails")
    ecube_process: EcubeProcessMetricsResponse = Field(..., description="ECUBE-process diagnostics and active copy worker correlation")


class ManualManagedMountReconciliationResponse(BaseModel):
    """Response for ``POST /introspection/reconcile-managed-mounts``."""

    status: str = Field(..., description="Run status ('ok' or 'partial')")
    scope: str = Field(..., description="Reconciliation scope for this run")
    network_mounts_checked: int = Field(default=0, description="Managed network mounts inspected")
    network_mounts_corrected: int = Field(default=0, description="Managed network mounts corrected")
    usb_mounts_checked: int = Field(default=0, description="Managed USB mount slots inspected")
    usb_mounts_corrected: int = Field(default=0, description="Managed USB mount slots corrected")
    failure_count: int = Field(default=0, description="Number of corrective operations that failed")
