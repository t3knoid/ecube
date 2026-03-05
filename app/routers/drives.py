from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.hardware import DriveInitialize, UsbDriveSchema
from app.services import drive_service

router = APIRouter(prefix="/drives", tags=["drives"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.get("", response_model=List[UsbDriveSchema])
def list_drives(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    return drive_service.get_all_drives(db)


@router.post("/{drive_id}/initialize", response_model=UsbDriveSchema)
def initialize_drive(
    drive_id: int,
    body: DriveInitialize,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    return drive_service.initialize_drive(drive_id, body.project_id, db, actor=current_user.username)


@router.post("/{drive_id}/prepare-eject", response_model=UsbDriveSchema)
def prepare_eject(
    drive_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    return drive_service.prepare_eject(drive_id, db, actor=current_user.username)
