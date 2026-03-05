import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.models.jobs import ExportJob, JobStatus

router = APIRouter(prefix="/introspection", tags=["introspection"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")


@router.get("/usb/topology")
def usb_topology(_: CurrentUser = Depends(_ALL_ROLES)):
    devices = []
    usb_path = "/sys/bus/usb/devices"
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


@router.get("/block-devices")
def block_devices(_: CurrentUser = Depends(_ALL_ROLES)):
    stats = []
    try:
        with open("/proc/diskstats") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    stats.append(
                        {"major": parts[0], "minor": parts[1], "name": parts[2]}
                    )
    except Exception:
        pass
    return {"block_devices": stats}


@router.get("/mounts")
def system_mounts(_: CurrentUser = Depends(_ALL_ROLES)):
    mounts = []
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 4:
                    mounts.append(
                        {
                            "device": parts[0],
                            "mount_point": parts[1],
                            "fs_type": parts[2],
                            "options": parts[3],
                        }
                    )
    except Exception:
        pass
    return {"mounts": mounts}


@router.get("/system-health")
def system_health(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
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


@router.get("/jobs/{job_id}/debug")
def job_debug(
    job_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
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
