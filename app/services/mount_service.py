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

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            mount.status = MountStatus.MOUNTED
        else:
            mount.status = MountStatus.ERROR
            _mount_error = (result.stderr or result.stdout or "").strip() or "mount failed"
        db.commit()
    except Exception as exc:
        mount.status = MountStatus.ERROR
        db.commit()
        _mount_error = str(exc)

    create_audit_log(
        db=db,
        action="MOUNT_ADDED",
        details={
            "mount_id": mount.id,
            "remote_path": mount_data.remote_path,
            "status": mount.status.value,
            "error": _mount_error,
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
        # Unmount failures are non-fatal; the record is still deleted so the
        # operator can manually clean up the mount point if needed.
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
