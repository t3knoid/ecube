from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_serializer
from app.models.hardware import DriveFormatStatus, DriveState
from app.utils.sanitize import ProjectIdStr, SafeStr


def _serialize_utc_datetime(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return f"{dt.isoformat()}Z"
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class UsbHubSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the USB hub")
    name: str = Field(..., description="Human-readable name of the USB hub")
    system_identifier: str = Field(..., description="System-level identifier from udev/sysfs")
    location_hint: Optional[str] = Field(default=None, description="Physical location hint (e.g., 'back-left')")
    vendor_id: Optional[str] = Field(default=None, description="USB vendor ID (e.g. '8086' for Intel)")
    product_id: Optional[str] = Field(default=None, description="USB product ID")

    model_config = {"from_attributes": True}


class UsbPortSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the USB port")
    hub_id: int = Field(..., description="ID of the parent hub")
    port_number: int = Field(..., description="Port number on the hub (1-based)")
    system_path: str = Field(..., description="USB device identifier from sysfs, e.g. '1-1'")
    friendly_label: Optional[str] = Field(default=None, description="User-assigned label for the port")
    enabled: bool = Field(default=False, description="Whether this port is enabled for ECUBE use")
    vendor_id: Optional[str] = Field(default=None, description="Vendor ID of device at this port")
    product_id: Optional[str] = Field(default=None, description="Product ID of device at this port")
    speed: Optional[str] = Field(default=None, description="Port speed in Mbps (e.g. '480', '5000')")

    model_config = {"from_attributes": True}


class DriveRelatedJobSchema(BaseModel):
    job_id: Optional[int] = Field(default=None, description="Related job ID for the current drive lifecycle")
    evidence_number: Optional[str] = Field(default=None, description="Evidence number for the related job")
    custody_status: Literal["HANDOFF_RECORDED", "PENDING_HANDOFF", "STATUS_UNAVAILABLE", "NO_RELATED_JOB"] = Field(
        ...,
        description="Trusted custody status for the related job drive lifecycle",
    )
    delivery_time: Optional[datetime] = Field(
        default=None,
        description="Recorded handoff delivery time in RFC 3339 UTC when custody is complete",
    )

    @field_serializer("delivery_time")
    def _serialize_delivery_time(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc_datetime(dt)


class UsbDriveSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the drive")
    port_id: Optional[int] = Field(default=None, description="ID of the port the drive is connected to")
    port_number: Optional[int] = Field(default=None, description="Port number on the parent USB hub when available")
    speed: Optional[str] = Field(default=None, description="Port speed in Mbps when available")
    port_system_path: Optional[str] = Field(
        default=None,
        description="Port-based USB identifier for the parent port (for example '2-1')",
    )
    manufacturer: Optional[str] = Field(default=None, description="USB manufacturer string when available")
    product_name: Optional[str] = Field(default=None, description="USB product string when available")
    display_device_label: str = Field(..., description="Operator-friendly drive label built from safe USB metadata")
    device_identifier: str = Field(
        ...,
        description=(
            "Stable hardware identifier for the drive built from available USB metadata "
            "(for example vendor ID, product ID, USB serial, optional disk serial, and bus path); "
            "distinct from the /dev block node reported in filesystem_path"
        ),
    )
    vendor_id: Optional[str] = Field(
        default=None,
        description="USB vendor ID when available; derived from the stable identifier when present",
    )
    product_id: Optional[str] = Field(
        default=None,
        description="USB product ID when available; derived from the stable identifier when present",
    )
    serial_number: Optional[str] = Field(
        default=None,
        description="USB serial number when available; derived from the stable identifier for composite-key rows",
    )
    filesystem_path: Optional[str] = Field(
        default=None,
        description="Current OS block device node for the drive (e.g., /dev/sdb); may be used in place of a mount point"
    )
    capacity_bytes: Optional[int] = Field(default=None, description="Total storage capacity in bytes")
    available_bytes: Optional[int] = Field(default=None, description="Last known available space in bytes for the mounted drive")
    encryption_status: Optional[str] = Field(default=None, description="Encryption status (e.g., 'encrypted', 'none')")
    filesystem_type: Optional[str] = Field(default=None, description="Detected filesystem label (e.g. ext4, exfat, unformatted, unknown, or null if not yet detected)")
    current_state: DriveState = Field(..., description="Current drive state (DISCONNECTED, DISABLED, AVAILABLE, IN_USE)")
    current_project_id: Optional[str] = Field(default=None, description="Bound project ID if IN_USE, enforces isolation")
    mount_path: Optional[str] = Field(default=None, description="Active mount path for this drive (e.g. /mnt/ecube/7); null when not mounted")
    throughput_write_mbps: Optional[float] = Field(default=None, description="Most recent measured manual drive write speed as a bit-based Mb/s value when available")
    throughput_tested_at: Optional[datetime] = Field(default=None, description="Timestamp of the most recent manual throughput test for this drive")
    format_status: Optional[DriveFormatStatus] = Field(
        default=None,
        description="Current asynchronous drive-format state; null when no format request is pending and no retained format failure is present",
    )
    format_failure_message: Optional[str] = Field(
        default=None,
        description="Sanitized operator-safe reason for the most recent failed drive-format request when available",
    )
    format_started_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the current or most recent asynchronous drive-format request started",
    )
    format_finished_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the most recent asynchronous drive-format request completed or failed",
    )
    related_job: Optional[DriveRelatedJobSchema] = Field(
        default=None,
        description="Trusted related job context for this drive lifecycle when requested",
    )

    @field_serializer("format_started_at", "format_finished_at")
    def _serialize_format_datetimes(self, dt: Optional[datetime]) -> Optional[str]:
        return _serialize_utc_datetime(dt)

    model_config = {"from_attributes": True}


class DiscoverySyncResponse(BaseModel):
    """Summary returned by ``POST /drives/refresh``."""

    hubs_upserted: int = Field(default=0, description="Number of USB hubs upserted")
    ports_upserted: int = Field(default=0, description="Number of USB ports upserted")
    drives_inserted: int = Field(default=0, description="Number of new drives inserted")
    drives_updated: int = Field(default=0, description="Number of existing drives updated")
    drives_removed: int = Field(default=0, description="Number of drives removed")


class DriveInitialize(BaseModel):
    project_id: ProjectIdStr = Field(..., min_length=1, description="Project ID to bind the drive to for isolation enforcement")


class DriveFormatRequest(BaseModel):
    filesystem_type: Literal["ext4", "exfat"] = Field(..., description="Target filesystem type for formatting")


class PortEnableRequest(BaseModel):
    enabled: bool = Field(..., description="Set port enabled state")


class HubUpdateRequest(BaseModel):
    location_hint: Optional[SafeStr] = Field(..., min_length=1, description="Physical location label for the hub (null to clear)")


class PortUpdateRequest(BaseModel):
    friendly_label: Optional[SafeStr] = Field(..., min_length=1, description="Human-readable label for the port (null to clear)")
