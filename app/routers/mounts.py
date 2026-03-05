from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.network import MountCreate, NetworkMountSchema
from app.services import mount_service

router = APIRouter(prefix="/mounts", tags=["mounts"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.post("", response_model=NetworkMountSchema)
def add_mount(
    body: MountCreate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    return mount_service.add_mount(body, db, actor=current_user.username)


@router.delete("/{mount_id}", status_code=204)
def remove_mount(
    mount_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    mount_service.remove_mount(mount_id, db, actor=current_user.username)


@router.get("", response_model=List[NetworkMountSchema])
def list_mounts(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    return mount_service.list_mounts(db)


@router.post("/{mount_id}/validate", response_model=NetworkMountSchema)
def validate_mount(
    mount_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    return mount_service.validate_mount(mount_id, db, actor=current_user.username)
