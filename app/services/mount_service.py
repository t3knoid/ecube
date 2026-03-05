import subprocess
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.network import MountStatus, MountType, NetworkMount
from app.schemas.network import MountCreate
from app.services.audit_service import create_audit_log


def add_mount(mount_data: MountCreate, db: Session) -> NetworkMount:
    mount = NetworkMount(
        type=mount_data.type,
        remote_path=mount_data.remote_path,
        local_mount_point=mount_data.local_mount_point,
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)

    try:
        if mount_data.type == MountType.NFS:
            cmd = ["mount", "-t", "nfs", mount_data.remote_path, mount_data.local_mount_point]
        else:
            cmd = ["mount", "-t", "cifs", mount_data.remote_path, mount_data.local_mount_point]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            mount.status = MountStatus.MOUNTED
        else:
            mount.status = MountStatus.ERROR
        db.commit()
    except Exception:
        mount.status = MountStatus.ERROR
        db.commit()

    create_audit_log(
        db=db,
        action="MOUNT_ADDED",
        details={
            "mount_id": mount.id,
            "remote_path": mount_data.remote_path,
            "status": mount.status.value,
        },
    )
    return mount


def remove_mount(mount_id: int, db: Session) -> None:
    mount = db.get(NetworkMount, mount_id)
    if not mount:
        raise HTTPException(status_code=404, detail="Mount not found")

    try:
        subprocess.run(
            ["umount", mount.local_mount_point],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass

    create_audit_log(
        db=db,
        action="MOUNT_REMOVED",
        details={"mount_id": mount_id, "local_mount_point": mount.local_mount_point},
    )
    db.delete(mount)
    db.commit()


def list_mounts(db: Session):
    return db.query(NetworkMount).all()


def validate_mount(mount_id: int, db: Session) -> NetworkMount:
    mount = db.get(NetworkMount, mount_id)
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
    db.commit()
    db.refresh(mount)
    return mount
