from pydantic import BaseModel, Field
from typing import Literal, Optional
from app.models.hardware import DriveState
from app.utils.sanitize import SafeStr


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


class UsbDriveSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the drive")
    port_id: Optional[int] = Field(default=None, description="ID of the port the drive is connected to")
    device_identifier: str = Field(
        ...,
        description=(
            "Stable hardware identifier for the drive (USB serial when available, otherwise sysfs path); "
            "distinct from the /dev block node reported in filesystem_path"
        ),
    )
    filesystem_path: Optional[str] = Field(
        default=None,
        description="Current OS block device node for the drive (e.g., /dev/sdb); may be used in place of a mount point"
    )
    capacity_bytes: Optional[int] = Field(default=None, description="Total storage capacity in bytes")
    encryption_status: Optional[str] = Field(default=None, description="Encryption status (e.g., 'encrypted', 'none')")
    filesystem_type: Optional[str] = Field(default=None, description="Detected filesystem label (e.g. ext4, exfat, unformatted, unknown, or null if not yet detected)")
    current_state: DriveState = Field(..., description="Current drive state (EMPTY, AVAILABLE, IN_USE)")
    current_project_id: Optional[str] = Field(default=None, description="Bound project ID if IN_USE, enforces isolation")

    model_config = {"from_attributes": True}


class DriveInitialize(BaseModel):
    project_id: SafeStr = Field(..., description="Project ID to bind the drive to for isolation enforcement")


class DriveFormatRequest(BaseModel):
    filesystem_type: Literal["ext4", "exfat"] = Field(..., description="Target filesystem type for formatting")


class PortEnableRequest(BaseModel):
    enabled: bool = Field(..., description="Set port enabled state")


class HubUpdateRequest(BaseModel):
    location_hint: SafeStr = Field(..., description="Physical location label for the hub")


class PortUpdateRequest(BaseModel):
    friendly_label: SafeStr = Field(..., description="Human-readable label for the port")
