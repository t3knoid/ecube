import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.network import MountStatus, MountType, NetworkMount
from app.repositories.audit_repository import AuditRepository
from app.repositories.mount_repository import MountRepository
from app.schemas.network import MountCreate
from app.config import settings

logger = logging.getLogger(__name__)


def add_mount(mount_data: MountCreate, db: Session, actor: Optional[str] = None) -> NetworkMount:
    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)

    mount = NetworkMount(
        type=mount_data.type,
        remote_path=mount_data.remote_path,
        local_mount_point=mount_data.local_mount_point,
        status=MountStatus.UNMOUNTED,
    )
    mount_repo.add(mount)

    _mount_error = None
    try:
        if mount_data.type == MountType.NFS:
            cmd = ["mount", "-t", "nfs", mount_data.remote_path, mount_data.local_mount_point]
        else:
            cmd = ["mount", "-t", "cifs", mount_data.remote_path, mount_data.local_mount_point]
            if mount_data.credentials_file:
                cmd += ["-o", f"credentials={mount_data.credentials_file}"]
            elif mount_data.username:
                # Pass only the username on the command line; password must be
                # supplied via credentials_file to avoid exposure in process listings.
                cmd += ["-o", f"username={mount_data.username}"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=settings.subprocess_timeout_seconds)
        if result.returncode == 0:
            mount.status = MountStatus.MOUNTED
        else:
            mount.status = MountStatus.ERROR
            _mount_error = (result.stderr or result.stdout or "").strip() or "mount failed"
        mount_repo.save(mount)
    except Exception as exc:
        mount.status = MountStatus.ERROR
        mount_repo.save(mount)
        _mount_error = str(exc)

    audit_repo.add(
        action="MOUNT_ADDED",
        user=actor,
        details={
            "mount_id": mount.id,
            "remote_path": mount_data.remote_path,
            "status": mount.status.value,
            "error": _mount_error,
        },
    )
    return mount


def remove_mount(mount_id: int, db: Session, actor: Optional[str] = None) -> None:
    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)

    mount = mount_repo.get(mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    try:
        subprocess.run(
            ["umount", mount.local_mount_point],
            capture_output=True,
            text=True,
            timeout=settings.subprocess_timeout_seconds,
        )
    except Exception:
        # Unmount failures are non-fatal; the record is still deleted so the
        # operator can manually clean up the mount point if needed.
        pass

    audit_repo.add(
        action="MOUNT_REMOVED",
        user=actor,
        details={"mount_id": mount_id, "local_mount_point": mount.local_mount_point},
    )
    mount_repo.delete(mount)


def list_mounts(db: Session):
    return MountRepository(db).list_all()


def validate_all_mounts(db: Session, actor: Optional[str] = None) -> list[NetworkMount]:
    mount_repo = MountRepository(db)
    mounts = mount_repo.list_all()
    return [validate_mount(mount.id, db, actor=actor) for mount in mounts]


def validate_mount(mount_id: int, db: Session, actor: Optional[str] = None) -> NetworkMount:
    mount_repo = MountRepository(db)
    audit_repo = AuditRepository(db)

    mount = mount_repo.get(mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    try:
        result = subprocess.run(
            ["mountpoint", "-q", mount.local_mount_point],
            capture_output=True,
            timeout=10,
        )
        mount.status = (
            MountStatus.MOUNTED if result.returncode == 0 else MountStatus.UNMOUNTED
        )
    except Exception:
        mount.status = MountStatus.ERROR

    mount.last_checked_at = datetime.now(timezone.utc)
    mount = mount_repo.save(mount)

    audit_repo.add(
        action="MOUNT_VALIDATED",
        user=actor,
        details={
            "mount_id": mount_id,
            "local_mount_point": mount.local_mount_point,
            "status": mount.status.value,
        },
    )
    return mount
