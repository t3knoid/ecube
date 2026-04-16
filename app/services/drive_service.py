import logging
import os
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.infrastructure.drive_eject import DriveEjectProvider
from app.infrastructure.drive_format import DriveFormatter
from app.infrastructure.drive_mount import DriveMountProvider
from app.infrastructure import validate_device_path
from app.models.hardware import DriveState, UsbDrive
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository

logger = logging.getLogger(__name__)


def _default_eject_provider() -> DriveEjectProvider:
    """Lazy import to avoid circular dependency at module level."""
    from app.infrastructure import get_drive_eject
    return get_drive_eject()


def _default_mount_provider() -> DriveMountProvider:
    """Lazy import to avoid circular dependency at module level."""
    from app.infrastructure import get_drive_mount
    return get_drive_mount()


def get_all_drives(
    db: Session,
    project_id: Optional[str] = None,
    states: Optional[List[str]] = None,
) -> List[UsbDrive]:
    repo = DriveRepository(db)
    if project_id is not None:
        return repo.list_by_project(project_id)
    if states:
        try:
            parsed = [DriveState(s) for s in states]
        except ValueError:
            valid = ", ".join(e.value for e in DriveState)
            raise HTTPException(
                status_code=422,
                detail=f"Invalid state filter. Valid values: {valid}",
            )
        return repo.list_by_states(parsed)
    return repo.list_all()


def initialize_drive(
    drive_id: int, project_id: str, db: Session, actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> UsbDrive:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    drive = drive_repo.get_for_update(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    # Archived drives are permanently retired and must never re-enter operational use.
    if drive.current_state == DriveState.ARCHIVED:
        try:
            audit_repo.add(
                action="INIT_REJECTED_ARCHIVED",
                user=actor,
                project_id=project_id,
                drive_id=drive_id,
                details={
                    "actor": actor,
                    "drive_id": drive_id,
                    "current_state": drive.current_state.value,
                    "existing_project_id": drive.current_project_id,
                    "requested_project_id": project_id,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.error("Failed to write audit log for INIT_REJECTED_ARCHIVED")
        raise HTTPException(
            status_code=409,
            detail="Drive is archived and cannot be re-initialized.",
        )

    # EMPTY drives are not physically accessible (not present or on a disabled port).
    # Initialization requires the drive to be AVAILABLE so that a filesystem is
    # present and the drive is reachable.  Attempting to initialize from EMPTY is
    # always a precondition failure.
    if drive.current_state == DriveState.EMPTY:
        try:
            audit_repo.add(
                action="INIT_REJECTED_NOT_AVAILABLE",
                user=actor,
                project_id=project_id,
                drive_id=drive_id,
                details={
                    "actor": actor,
                    "drive_id": drive_id,
                    "current_state": drive.current_state.value,
                    "requested_project_id": project_id,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.error("Failed to write audit log for INIT_REJECTED_NOT_AVAILABLE")
        raise HTTPException(
            status_code=409,
            detail="Drive is EMPTY (not present or port disabled) and cannot be initialized.",
        )

    # Project isolation is state-dependent:
    # - IN_USE + different project: hard deny (403) — cannot steal an active drive.
    # - AVAILABLE + different project: require format first (409) — the previous
    #   project's data is still on disk; a wipe is mandatory before re-assignment.
    # - AVAILABLE + same project, or no prior project: allow (re-insert or fresh drive).
    if drive.current_project_id and drive.current_project_id != project_id:
        if drive.current_state == DriveState.IN_USE:
            try:
                audit_repo.add(
                    action="PROJECT_ISOLATION_VIOLATION",
                    user=actor,
                    project_id=project_id,
                    drive_id=drive_id,
                    details={
                        "actor": actor,
                        "drive_id": drive_id,
                        "existing_project_id": drive.current_project_id,
                        "requested_project_id": project_id,
                    },
                    client_ip=client_ip,
                )
            except Exception:
                logger.error("Failed to write audit log for PROJECT_ISOLATION_VIOLATION")
            raise HTTPException(
                status_code=403,
                detail=f"Drive is already assigned to project '{drive.current_project_id}'",
            )
        else:
            # Drive is AVAILABLE but still carries data from a different project.
            # A format (wipe) is required before it can be re-assigned.
            try:
                audit_repo.add(
                    action="INIT_REJECTED_PROJECT_MISMATCH",
                    user=actor,
                    project_id=project_id,
                    drive_id=drive_id,
                    details={
                        "actor": actor,
                        "drive_id": drive_id,
                        "existing_project_id": drive.current_project_id,
                        "requested_project_id": project_id,
                    },
                    client_ip=client_ip,
                )
            except Exception:
                logger.error("Failed to write audit log for INIT_REJECTED_PROJECT_MISMATCH")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Drive previously used for project '{drive.current_project_id}'. "
                    "Format the drive to wipe existing data before assigning to a new project."
                ),
            )

    # Reject drives without a recognized filesystem.
    _unrecognized_fs = {"unformatted", "unknown", None}
    if drive.filesystem_type in _unrecognized_fs:
        current_val = drive.filesystem_type if drive.filesystem_type is not None else "NULL"
        try:
            audit_repo.add(
                action="INIT_REJECTED_FILESYSTEM",
                user=actor,
                project_id=project_id,
                drive_id=drive_id,
                details={
                    "actor": actor,
                    "drive_id": drive_id,
                    "project_id": project_id,
                    "filesystem_type": drive.filesystem_type,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for INIT_REJECTED_FILESYSTEM")
        raise HTTPException(
            status_code=409,
            detail=(
                "Drive must have a recognized filesystem before initialization. "
                f"Current filesystem_type: {current_val}"
            ),
        )

    drive.current_project_id = project_id
    drive.current_state = DriveState.IN_USE
    try:
        drive_repo.save(drive)
    except Exception:
        logger.exception("DB commit failed while initializing drive %s", drive_id)
        raise HTTPException(
            status_code=500,
            detail="Database error while initializing drive",
        )
    try:
        audit_repo.add(
            action="DRIVE_INITIALIZED",
            user=actor,
            project_id=project_id,
            drive_id=drive_id,
            details={"drive_id": drive_id, "project_id": project_id},
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for DRIVE_INITIALIZED")
    return drive


def mount_drive(
    drive_id: int,
    db: Session,
    actor: Optional[str] = None,
    mount_provider: Optional[DriveMountProvider] = None,
    client_ip: Optional[str] = None,
) -> UsbDrive:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)
    provider = mount_provider or _default_mount_provider()

    drive = drive_repo.get_for_update(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    if drive.current_state not in (DriveState.AVAILABLE, DriveState.IN_USE):
        raise HTTPException(
            status_code=409,
            detail="Drive must be AVAILABLE or IN_USE before it can be mounted",
        )

    if not drive.filesystem_path:
        raise HTTPException(
            status_code=400,
            detail="Drive has no filesystem_path and cannot be mounted",
        )

    if not validate_device_path(drive.filesystem_path):
        raise HTTPException(
            status_code=400,
            detail="Drive filesystem_path is invalid and cannot be mounted",
        )

    if drive.mount_path:
        raise HTTPException(
            status_code=409,
            detail="Drive is already mounted",
        )

    mount_point = os.path.join(settings.usb_mount_base_path, str(drive.id))
    success, error = provider.mount_drive(drive.filesystem_path, mount_point)
    if not success:
        try:
            audit_repo.add(
                action="DRIVE_MOUNT_FAILED",
                user=actor,
                project_id=drive.current_project_id,
                drive_id=drive_id,
                details={
                    "drive_id": drive_id,
                    "filesystem_path": drive.filesystem_path,
                    "mount_path": mount_point,
                    "error": error,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_MOUNT_FAILED")
        raise HTTPException(
            status_code=500,
            detail=error or "Drive mount failed",
        )

    drive.mount_path = mount_point
    try:
        drive_repo.save(drive)
    except Exception:
        logger.exception(
            "DB commit failed after successful OS mount for drive %s",
            drive_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Drive mounted at OS level but database update failed; manual intervention may be required",
        )

    try:
        audit_repo.add(
            action="DRIVE_MOUNTED",
            user=actor,
            project_id=drive.current_project_id,
            drive_id=drive_id,
            details={
                "drive_id": drive_id,
                "filesystem_path": drive.filesystem_path,
                "mount_path": drive.mount_path,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for DRIVE_MOUNTED")

    return drive


def prepare_eject(drive_id: int, db: Session, actor: Optional[str] = None,
                  eject_provider: Optional[DriveEjectProvider] = None,
                  client_ip: Optional[str] = None) -> UsbDrive:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)
    provider = eject_provider or _default_eject_provider()

    # Read the drive WITHOUT row lock so OS operations don't hold the lock.
    drive = drive_repo.get(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    # Capture the precondition state for later validation.
    initial_state = drive.current_state
    initial_device_path = drive.filesystem_path

    # Fail fast if the drive is not in the required IN_USE state.
    # Don't waste time on expensive OS operations for invalid preconditions.
    if initial_state != DriveState.IN_USE:
        raise HTTPException(
            status_code=409,
            detail=f"Drive is not in IN_USE state; cannot prepare eject (current state: {initial_state.value})",
        )

    # Perform potentially slow OS operations without holding a database lock.
    # prepare_eject handles sync + unmount internally and returns a structured result.
    result = provider.prepare_eject(initial_device_path)

    # Re-lock only for the validation and state transition; the audit write happens
    # in a separate transaction after this state change is committed.
    drive = drive_repo.get_for_update(drive_id)
    if not drive:
        # Drive was deleted between reads (unlikely but possible).
        raise HTTPException(status_code=404, detail="Drive not found")

    # Verify the drive state is still IN_USE (required precondition for prepare-eject).
    # If another request changed the state, reject with 409 Conflict.
    if drive.current_state != initial_state:
        raise HTTPException(
            status_code=409,
            detail=f"Drive state changed during prepare-eject (was: {initial_state.value}, now: {drive.current_state.value}); operation aborted",
        )

    # Verify the device path hasn't changed (e.g., via discovery refresh).
    # If it changed, the OS operations we performed are stale and the audit log would be inconsistent.
    if drive.filesystem_path != initial_device_path:
        raise HTTPException(
            status_code=409,
            detail=f"Device path changed during prepare-eject (was: {initial_device_path!r}, now: {drive.filesystem_path!r}); operation aborted",
        )

    if result.success:
        drive.current_state = DriveState.AVAILABLE
        drive.mount_path = None
        try:
            drive_repo.save(drive)
        except Exception:
            logger.exception(
                "DB commit failed after successful OS eject for drive %s",
                drive_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Drive ejected at OS level but database update failed; manual intervention may be required",
            )
        try:
            audit_repo.add(
                action="DRIVE_EJECT_PREPARED",
                user=actor,
                project_id=drive.current_project_id,
                drive_id=drive_id,
                details={
                    "drive_id": drive_id,
                    "filesystem_path": initial_device_path,
                    "flush_ok": result.flush_ok,
                    "unmount_ok": result.unmount_ok,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_EJECT_PREPARED")
    else:
        if not result.unmount_ok:
            try:
                audit_repo.add(
                    action="DRIVE_UNMOUNT_FAILED",
                    user=actor,
                    project_id=drive.current_project_id,
                    drive_id=drive_id,
                    details={
                        "drive_id": drive_id,
                        "filesystem_path": initial_device_path,
                        "mount_path": drive.mount_path,
                        "unmount_error": result.unmount_error,
                    },
                    client_ip=client_ip,
                )
            except Exception:
                logger.exception("Failed to write audit log for DRIVE_UNMOUNT_FAILED")
        try:
            audit_repo.add(
                action="DRIVE_EJECT_FAILED",
                user=actor,
                project_id=drive.current_project_id,
                drive_id=drive_id,
                details={
                    "drive_id": drive_id,
                    "filesystem_path": initial_device_path,
                    "flush_ok": result.flush_ok,
                    "flush_error": result.flush_error,
                    "unmount_ok": result.unmount_ok,
                    "unmount_error": result.unmount_error,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_EJECT_FAILED")
        raise HTTPException(
            status_code=500,
            detail="Drive eject preparation failed",
        )

    return drive


def format_drive(
    drive_id: int,
    filesystem_type: str,
    db: Session,
    *,
    formatter: DriveFormatter,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> UsbDrive:
    """Format a drive with the specified filesystem type."""
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    drive = drive_repo.get_for_update(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    if drive.current_state != DriveState.AVAILABLE:
        raise HTTPException(
            status_code=409,
            detail=f"Drive must be in AVAILABLE state to format (current: {drive.current_state.value})",
        )

    if not drive.filesystem_path:
        raise HTTPException(
            status_code=400,
            detail="Drive has no filesystem_path; cannot format",
        )

    if not validate_device_path(drive.filesystem_path):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid device path: {drive.filesystem_path!r}",
        )

    if formatter.is_mounted(drive.filesystem_path):
        raise HTTPException(
            status_code=409,
            detail="Drive is currently mounted; unmount before formatting",
        )

    try:
        formatter.format(drive.filesystem_path, filesystem_type)
    except RuntimeError as exc:
        try:
            audit_repo.add(
                action="DRIVE_FORMAT_FAILED",
                user=actor,
                project_id=drive.current_project_id,
                drive_id=drive_id,
                details={
                    "drive_id": drive_id,
                    "filesystem_path": drive.filesystem_path,
                    "filesystem_type": filesystem_type,
                    "error": str(exc),
                    "actor": actor,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_FORMAT_FAILED")
        raise HTTPException(
            status_code=500,
            detail=f"Drive format failed: {exc}",
        )

    drive.filesystem_type = filesystem_type
    # Formatting wipes all previous data, so the project binding is cleared.
    # The drive is now clean and can be initialized for any project.
    prior_project_id = drive.current_project_id
    drive.current_project_id = None
    try:
        drive_repo.save(drive)
    except Exception:
        logger.exception("DB commit failed after formatting drive %s", drive_id)
        try:
            audit_repo.add(
                action="DRIVE_FORMAT_DB_UPDATE_FAILED",
                user=actor,
                project_id=prior_project_id,
                drive_id=drive_id,
                details={
                    "drive_id": drive_id,
                    "filesystem_path": drive.filesystem_path,
                    "filesystem_type": filesystem_type,
                    "actor": actor,
                },
                client_ip=client_ip,
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_FORMAT_DB_UPDATE_FAILED")
        raise HTTPException(
            status_code=500,
            detail="Drive formatted at OS level but database update failed",
        )

    try:
        audit_repo.add(
            action="DRIVE_FORMATTED",
            user=actor,
            project_id=prior_project_id,
            drive_id=drive_id,
            details={
                "drive_id": drive_id,
                "filesystem_path": drive.filesystem_path,
                "filesystem_type": filesystem_type,
                "actor": actor,
            },
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for DRIVE_FORMATTED")

    return drive
