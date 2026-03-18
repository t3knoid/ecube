from pydantic import BaseModel, Field
from typing import Literal, Optional
from app.models.hardware import DriveState


class UsbHubSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the USB hub")
    name: str = Field(..., description="Human-readable name of the USB hub")
    system_identifier: str = Field(..., description="System-level identifier from udev/sysfs")
    location_hint: Optional[str] = Field(default=None, description="Physical location hint (e.g., 'back-left')")

    model_config = {"from_attributes": True}


class UsbPortSchema(BaseModel):
    id: int = Field(..., description="Unique identifier for the USB port")
    hub_id: int = Field(..., description="ID of the parent hub")
    port_number: int = Field(..., description="Port number on the hub (1-based)")
    system_path: str = Field(..., description="Kernel sysfs path to the port")
    friendly_label: Optional[str] = Field(default=None, description="User-assigned label for the port")

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
    project_id: str = Field(..., description="Project ID to bind the drive to for isolation enforcement")


class DriveFormatRequest(BaseModel):
    filesystem_type: Literal["ext4", "exfat"] = Field(..., description="Target filesystem type for formatting")
