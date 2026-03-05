from pydantic import BaseModel
from typing import Optional
from app.models.network import MountType, MountStatus


class MountCreate(BaseModel):
    type: MountType
    remote_path: str
    local_mount_point: str


class NetworkMountSchema(BaseModel):
    id: int
    type: MountType
    remote_path: str
    local_mount_point: str
    status: MountStatus

    model_config = {"from_attributes": True}
