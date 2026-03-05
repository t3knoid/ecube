from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.schemas.hardware import DriveInitialize, UsbDriveSchema
from app.services import drive_service

router = APIRouter(prefix="/drives", tags=["drives"])


@router.get("", response_model=List[UsbDriveSchema])
def list_drives(db: Session = Depends(get_db)):
    return drive_service.get_all_drives(db)


@router.post("/{drive_id}/initialize", response_model=UsbDriveSchema)
def initialize_drive(drive_id: int, body: DriveInitialize, db: Session = Depends(get_db)):
    return drive_service.initialize_drive(drive_id, body.project_id, db)


@router.post("/{drive_id}/prepare-eject", response_model=UsbDriveSchema)
def prepare_eject(drive_id: int, db: Session = Depends(get_db)):
    return drive_service.prepare_eject(drive_id, db)
