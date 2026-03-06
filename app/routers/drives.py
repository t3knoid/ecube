from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.hardware import DriveInitialize, UsbDriveSchema
from app.services import drive_service, discovery_service

router = APIRouter(prefix="/drives", tags=["drives"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.get("", response_model=List[UsbDriveSchema])
def list_drives(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """List all USB drives with their current state and project assignments.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return drive_service.get_all_drives(db)


@router.post("/{drive_id}/initialize", response_model=UsbDriveSchema)
def initialize_drive(
    drive_id: int,
    body: DriveInitialize,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Initialize a drive and bind it to a project for isolation enforcement.

    Transitions the drive from ``AVAILABLE`` to ``IN_USE`` and records the project binding.
    Once bound, the drive can only accept data for its designated project.

    **Roles:** ``admin``, ``manager``
    """
    return drive_service.initialize_drive(drive_id, body.project_id, db, actor=current_user.username)


@router.post("/{drive_id}/prepare-eject", response_model=UsbDriveSchema)
def prepare_eject(
    drive_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Prepare a drive for safe ejection and return it to available state.

    Completes the copy/verify process and transitions the drive back to ``AVAILABLE``.
    After ejection, the drive can be safely removed and reassigned to a different project.

    **Roles:** ``admin``, ``manager``
    """
    return drive_service.prepare_eject(drive_id, db, actor=current_user.username)


@router.post("/refresh")
def refresh_drives(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Trigger a USB discovery sync and drive state refresh.

    Discovers hubs, ports, and drives from system sources, upserts the
    topology into the database, and recomputes drive states according to
    the finite-state machine rules.  The operation is idempotent.

    **Roles:** ``admin``, ``manager``
    """
    return discovery_service.run_discovery_sync(db, actor=current_user.username)
