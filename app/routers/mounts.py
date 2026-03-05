from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.schemas.network import MountCreate, NetworkMountSchema
from app.services import mount_service

router = APIRouter(prefix="/mounts", tags=["mounts"])


@router.post("", response_model=NetworkMountSchema)
def add_mount(body: MountCreate, db: Session = Depends(get_db)):
    return mount_service.add_mount(body, db)


@router.delete("/{mount_id}", status_code=204)
def remove_mount(mount_id: int, db: Session = Depends(get_db)):
    mount_service.remove_mount(mount_id, db)


@router.get("", response_model=List[NetworkMountSchema])
def list_mounts(db: Session = Depends(get_db)):
    return mount_service.list_mounts(db)
