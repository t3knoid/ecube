import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.config import settings
from app.database import get_db
from app.models.hardware import UsbDrive
from app.models.jobs import ExportJob, JobStatus
from app.schemas.errors import R_401, R_403, R_404, R_422

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/introspection", tags=["introspection"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_AUDITOR = require_roles("admin", "auditor")


@router.get("/drives", responses={**R_401, **R_403})
def drives_inventory(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """List all registered USB drives and their current state.

    Returns drive identifiers, capacity, state, and project bindings
    for diagnostic and inventory purposes.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    **Restricted:** Sensitive filesystem paths are not exposed.
    """
    drives = db.query(UsbDrive).all()
    return {
        "drives": [
            {
                "id": d.id,
                "device_identifier": d.device_identifier,
                "capacity_bytes": d.capacity_bytes,
                "current_state": d.current_state.value if d.current_state else None,
                "current_project_id": d.current_project_id,
                "encryption_status": d.encryption_status,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in drives
        ]
    }


@router.get("/usb/topology", responses={**R_401, **R_403})
def usb_topology(_: CurrentUser = Depends(_ALL_ROLES)):
    """Introspect USB hubs, ports, and connected devices from system sysfs.

    Returns raw device identifiers and attributes for diagnostic purposes.
    Information is read-only and does not modify system state.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    **Restricted:** Outputs are scrubbed and do not expose sensitive paths.
    """
    devices = []
    usb_path = settings.sysfs_usb_devices_path
    try:
        if os.path.exists(usb_path):
            for dev in os.listdir(usb_path):
                dev_path = os.path.join(usb_path, dev)
                info = {"device": dev}
                for attr in ["idVendor", "idProduct", "product", "manufacturer"]:
                    attr_file = os.path.join(dev_path, attr)
                    if os.path.isfile(attr_file):
                        try:
                            with open(attr_file) as f:
                                info[attr] = f.read().strip()
                        except Exception:
                            pass
                devices.append(info)
    except Exception as exc:
        return {"error": str(exc), "devices": []}
    return {"devices": devices}


@router.get("/block-devices", responses={**R_401, **R_403})
def block_devices(_: CurrentUser = Depends(_ALL_ROLES)):
    """List all block devices (disks, partitions) detected by the kernel.

    Returns device names and major/minor numbers. Does not expose partition contents.
    Information is for diagnostic and drive discovery purposes only.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    **Restricted:** Sensitive mount points and credentials are not exposed.
    """
    stats = []
    try:
        with open(settings.procfs_diskstats_path) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    stats.append(
                        {"major": parts[0], "minor": parts[1], "name": parts[2]}
                    )
    except Exception:
        pass
    return {"block_devices": stats}


@router.get("/mounts", responses={**R_401, **R_403})
def system_mounts(_: CurrentUser = Depends(_ALL_ROLES)):
    """List all currently mounted filesystems on the system.

    Returns mount points and filesystem types. Mount options are filtered to remove
    sensitive keys (credentials, paths, UIDs) while preserving important metadata
    for diagnostics (ro/rw, relatime, etc).

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    **Redaction:** Username, password, credentials, uid, gid, and other sensitive option keys are removed.
    """
    # Sensitive mount option keys to redact (case-insensitive)
    sensitive_keys = {
        "username", "user", "password", "passwd", "credentials",
        "uid", "gid", "file_mode", "dir_mode",
        "key", "secret", "token", "auth", "authtoken"
    }

    mounts = []
    try:
        with open(settings.procfs_mounts_path) as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    # Redact sensitive option keys
                    raw_options = parts[3]
                    filtered_options = []
                    
                    for opt in raw_options.split(","):
                        # Check if option contains a sensitive key (before the =)
                        opt_key = opt.split("=")[0].lower()
                        if opt_key not in sensitive_keys:
                            filtered_options.append(opt)
                    
                    mounts.append(
                        {
                            "device": parts[0],
                            "mount_point": parts[1],
                            "fs_type": parts[2],
                            "options": ",".join(filtered_options) if filtered_options else "[REDACTED]",
                        }
                    )
    except Exception:
        pass
    return {"mounts": mounts}


@router.get("/system-health", responses={**R_401, **R_403})
def system_health(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """Check the health of critical system components: database and job engine.

    Reports connectivity status, error details if applicable, and active job count.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    db_status = "connected"
    db_error = None
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = str(exc)

    active_jobs = 0
    if db_status == "connected":
        try:
            active_jobs = (
                db.query(ExportJob).filter(ExportJob.status == JobStatus.RUNNING).count()
            )
        except Exception:
            pass

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "database_error": db_error,
        "active_jobs": active_jobs,
    }


@router.get("/jobs/{job_id}/debug", responses={**R_401, **R_403, **R_404, **R_422})
def job_debug(
    job_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ADMIN_AUDITOR),
):
    """Retrieve detailed debug information for a specific export job.

    Returns internal state, paths, and progress metrics for troubleshooting.
    Restricted to administrators and auditors who need to investigate job issues.

    Includes source and target paths as these are necessary for debugging copy operations.

    **Roles:** ``admin``, ``auditor``
    """
    job = db.get(ExportJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "job_id": job.id,
        "status": job.status.value,
        "project_id": job.project_id,
        "source_path": job.source_path,
        "target_mount_path": job.target_mount_path,
        "total_bytes": job.total_bytes,
        "copied_bytes": job.copied_bytes,
        "file_count": job.file_count,
        "thread_count": job.thread_count,
        "files": [
            {
                "id": f.id,
                "relative_path": f.relative_path,
                "status": f.status.value,
                "checksum": f.checksum,
                "error_message": f.error_message,
            }
            for f in job.files
        ],
    }
