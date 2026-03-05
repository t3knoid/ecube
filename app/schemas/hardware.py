from pydantic import BaseModel
from typing import Optional
from app.models.hardware import DriveState


class UsbHubSchema(BaseModel):
    id: int
    name: str
    system_identifier: str
    location_hint: Optional[str] = None

    model_config = {"from_attributes": True}


class UsbPortSchema(BaseModel):
    id: int
    hub_id: int
    port_number: int
    system_path: str
    friendly_label: Optional[str] = None

    model_config = {"from_attributes": True}


class UsbDriveSchema(BaseModel):
    id: int
    port_id: Optional[int] = None
    device_identifier: str
    filesystem_path: Optional[str] = None
    capacity_bytes: Optional[int] = None
    encryption_status: Optional[str] = None
    current_state: DriveState
    current_project_id: Optional[str] = None

    model_config = {"from_attributes": True}


class DriveInitialize(BaseModel):
    project_id: str
