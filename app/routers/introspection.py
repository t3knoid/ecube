import logging
import os
import traceback

try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
    _PSUTIL_IMPORT_TRACEBACK: "str | None" = None
except Exception:  # pragma: no cover  # ImportError or dynamic-loader / ABI failures
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False
    _PSUTIL_IMPORT_TRACEBACK = traceback.format_exc()


def prime_cpu_sampler() -> None:  # pragma: no cover
    """Prime psutil's internal CPU baseline by making one blocking sample.

    Intended to be called from a background thread during application startup
    (via ``asyncio.to_thread``) so the 1-second blocking sample does not add
    latency to the startup sequence.  Subsequent non-blocking
    ``cpu_percent(interval=None)`` calls in the system-health endpoint will
    return a meaningful value rather than 0.0.

    When psutil could not be imported the failure is logged here (once, at
    startup) rather than at module-import time so that logging is already
    configured before the warning is emitted.
    """
    _log = logging.getLogger(__name__)
    if not _PSUTIL_AVAILABLE:
        _log.warning(
            "psutil could not be imported; system-health metrics will be null.\n%s",
            _PSUTIL_IMPORT_TRACEBACK,
        )
        return
    try:
        _psutil.cpu_percent(interval=1.0)
    except Exception:
        # Log rather than silently discard so failures are observable.
        # cpu_percent(interval=None) will fall back to 0.0 until psutil recovers.
        _log.exception(
            "Failed to prime psutil CPU sampler; cpu_percent will report 0.0 "
            "until a successful sample is collected.",
        )

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.config import settings
from app.database import get_db
from app.infrastructure import get_drive_mount, get_mount_provider
from app.models.hardware import UsbDrive
from app.schemas.errors import R_401, R_403, R_404, R_409, R_422, R_500
from app.schemas.introspection import (
    BlockDevicesResponse,
    IntrospectionDrivesResponse,
    ManualManagedMountReconciliationResponse,
    SystemHealthResponse,
    SystemMountsResponse,
    UsbTopologyResponse,
)
from app.services import introspection_service, reconciliation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/introspection", tags=["introspection"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_AUDITOR = require_roles("admin", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.get("/drives", response_model=IntrospectionDrivesResponse, responses={**R_401, **R_403})
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
                "port_system_path": d.port.system_path if d.port else None,
                "device_identifier": d.device_identifier,
                "serial_number": (None if d.port and d.device_identifier == d.port.system_path else d.device_identifier),
                "capacity_bytes": d.capacity_bytes,
                "current_state": d.current_state.value if d.current_state else None,
                "current_project_id": d.current_project_id,
                "encryption_status": d.encryption_status,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in drives
        ]
    }


@router.get("/usb/topology", response_model=UsbTopologyResponse, responses={**R_401, **R_403})
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
                for attr in ["serial", "idVendor", "idProduct", "product", "manufacturer"]:
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


@router.get("/block-devices", response_model=BlockDevicesResponse, responses={**R_401, **R_403})
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


@router.get("/mounts", response_model=SystemMountsResponse, responses={**R_401, **R_403})
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


@router.get("/system-health", response_model=SystemHealthResponse, responses={**R_401, **R_403})
def system_health(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    """Check the health of critical system components: database and job engine.

    Reports connectivity status, error details if applicable, and active job count.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return introspection_service.get_system_health(
        db,
        psutil_available=_PSUTIL_AVAILABLE,
        psutil_module=_psutil if _PSUTIL_AVAILABLE else None,
    )


@router.post(
    "/reconcile-managed-mounts",
    response_model=ManualManagedMountReconciliationResponse,
    responses={**R_401, **R_403, **R_409, **R_500},
)
def reconcile_managed_mounts(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Run a manual, live-safe managed-mount reconciliation pass.

    This endpoint only reconciles managed network and managed USB mounts.
    It does not perform startup-only identity, job, or drive discovery passes.

    **Roles:** ``admin``, ``manager``
    """
    return reconciliation_service.run_manual_managed_mount_reconciliation(
        db,
        get_mount_provider(),
        drive_mount_provider=get_drive_mount(),
        actor=current_user.username,
    )


