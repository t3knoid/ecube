import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from typing import List

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.network import MountCreate, NetworkMountSchema
from app.schemas.errors import R_401, R_403, R_404, R_422, R_500
from app.services import mount_service
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mounts", tags=["mounts"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.post("", response_model=NetworkMountSchema, responses={**R_401, **R_403, **R_422, **R_500})
def add_mount(
    body: MountCreate,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Register a new network mount (SMB, NFS, etc.) as a data source.

    Stores mount credentials and configuration, and attempts to connect immediately,
    updating the mount status based on the result of the system ``mount`` command.
    Connectivity can be explicitly re-tested via ``POST /mounts/{mount_id}/validate``.

    **Roles:** ``admin``, ``manager``
    """
    return mount_service.add_mount(body, db, actor=current_user.username, client_ip=get_client_ip(request))


@router.get("", response_model=List[NetworkMountSchema], responses={**R_401, **R_403})
def list_mounts(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """List all registered network mounts and their connectivity status.

    Returns mount details without exposing credentials.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return mount_service.list_mounts(db)


@router.post("/validate", response_model=List[NetworkMountSchema], responses={**R_401, **R_403, **R_500})
def validate_all_mounts(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Test connectivity and credentials for all registered network mounts.

    Updates each mount's connectivity status and ``last_checked_at`` timestamp; any
    errors encountered are reflected in the returned mount status.

    **Roles:** ``admin``, ``manager``
    """
    return mount_service.validate_all_mounts(db, actor=current_user.username, client_ip=get_client_ip(request))


@router.delete("/validate", status_code=405, responses={**R_401, **R_403}, include_in_schema=False)
def _delete_validate_not_allowed(
    _: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Reject DELETE on the /validate path with 405 Method Not Allowed."""
    from fastapi import HTTPException
    raise HTTPException(status_code=405, detail="Method Not Allowed")


@router.delete("/{mount_id}", status_code=204, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def remove_mount(
    mount_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Remove a network mount from the system.

    Deletes the mount configuration and credentials. In-progress jobs using this mount may fail.

    **Roles:** ``admin``, ``manager``
    """
    mount_service.remove_mount(mount_id, db, actor=current_user.username, client_ip=get_client_ip(request))


@router.post("/{mount_id}/validate", response_model=NetworkMountSchema, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def validate_mount(
    mount_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Test connectivity and credentials for a specific network mount.

    Attempts to connect using stored credentials and reports success or error.

    **Roles:** ``admin``, ``manager``
    """
    return mount_service.validate_mount(mount_id, db, actor=current_user.username, client_ip=get_client_ip(request))
