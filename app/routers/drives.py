import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.exceptions import EncodingError
from app.schemas.hardware import DriveFormatRequest, DriveInitialize, UsbDriveSchema
from app.services import drive_service, discovery_service
from app.infrastructure import get_drive_eject, get_drive_formatter, get_filesystem_detector
from app.utils.client_ip import get_client_ip
from app.utils.sanitize import sanitize_string

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drives", tags=["drives"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.get("", response_model=List[UsbDriveSchema])
def list_drives(
    project_id: Optional[str] = Query(
        default=None,
        min_length=1,
        description="Filter drives by project. When provided, only drives bound to this project are returned.",
    ),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """List all USB drives with their current state and project assignments.

    When *project_id* is provided, only drives bound to that project are
    returned.  When omitted, all drives are returned.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    if project_id is not None:
        project_id = sanitize_string(project_id)
        if not project_id:
            raise EncodingError("project_id is empty after removing invalid characters")
    return drive_service.get_all_drives(db, project_id=project_id)


@router.post("/{drive_id}/initialize", response_model=UsbDriveSchema)
def initialize_drive(
    drive_id: int,
    body: DriveInitialize,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Initialize a drive and bind it to a project for isolation enforcement.

    Transitions the drive from ``AVAILABLE`` to ``IN_USE`` and records the project binding.
    Once bound, the drive can only accept data for its designated project.

    **Roles:** ``admin``, ``manager``
    """
    return drive_service.initialize_drive(drive_id, body.project_id, db, actor=current_user.username, client_ip=get_client_ip(request))


@router.post("/{drive_id}/prepare-eject", response_model=UsbDriveSchema)
def prepare_eject(
    drive_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Prepare a drive for safe ejection and return it to available state.

    Completes the copy/verify process and transitions the drive back to ``AVAILABLE``.
    After ejection, the drive can be safely removed and reassigned to a different project.

    **Roles:** ``admin``, ``manager``
    """
    return drive_service.prepare_eject(
        drive_id, db, actor=current_user.username,
        eject_provider=get_drive_eject(),
        client_ip=get_client_ip(request),
    )


@router.post("/refresh")
def refresh_drives(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Trigger a USB discovery sync and drive state refresh.

    Discovers hubs, ports, and drives from system sources, upserts the
    topology into the database, and recomputes drive states according to
    the finite-state machine rules.  The operation is idempotent.

    **Roles:** ``admin``, ``manager``
    """
    return discovery_service.run_discovery_sync(
        db,
        actor=current_user.username,
        filesystem_detector=get_filesystem_detector(),
        client_ip=get_client_ip(request),
    )


@router.post("/{drive_id}/format", response_model=UsbDriveSchema)
def format_drive(
    drive_id: int,
    body: DriveFormatRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Format a drive with the specified filesystem type.

    Supported filesystem types: ``ext4``, ``exfat``.  The drive must be in
    ``AVAILABLE`` state, not currently mounted, and have a valid device path.

    **Roles:** ``admin``, ``manager``
    """
    formatter = get_drive_formatter()
    return drive_service.format_drive(
        drive_id, body.filesystem_type, db, formatter=formatter, actor=current_user.username,
        client_ip=get_client_ip(request),
    )
