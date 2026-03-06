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
    """Register a new network mount (SMB, NFS, etc.) as a data source.

    Stores mount credentials and configuration; does not immediately connect.
    Connection is validated via ``POST /mounts/{mount_id}/validate``.

    **Roles:** ``admin``, ``manager``
    """
    return mount_service.add_mount(body, db, actor=current_user.username)


@router.delete("/{mount_id}", status_code=204)
def remove_mount(
    mount_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Remove a network mount from the system.

    Deletes the mount configuration and credentials. In-progress jobs using this mount may fail.

    **Roles:** ``admin``, ``manager``
    """
    mount_service.remove_mount(mount_id, db, actor=current_user.username)


@router.get("", response_model=List[NetworkMountSchema])
def list_mounts(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """List all registered network mounts and their connectivity status.

    Returns mount details without exposing credentials.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return mount_service.list_mounts(db)


@router.post("/validate", response_model=List[NetworkMountSchema])
def validate_all_mounts(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Test connectivity and credentials for all registered network mounts.

    Updates each mount's connectivity status and ``last_checked_at`` timestamp; any
    errors encountered are reflected in the returned mount status.

    **Roles:** ``admin``, ``manager``
    """
    return mount_service.validate_all_mounts(db, actor=current_user.username)


@router.post("/{mount_id}/validate", response_model=NetworkMountSchema)
def validate_mount(
    mount_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Test connectivity and credentials for a specific network mount.

    Attempts to connect using stored credentials and reports success or error.

    **Roles:** ``admin``, ``manager``
    """
    return mount_service.validate_mount(mount_id, db, actor=current_user.username)
