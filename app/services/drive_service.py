import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.infrastructure.drive_eject import sync_filesystem, unmount_device
from app.models.hardware import DriveState, UsbDrive
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository

logger = logging.getLogger(__name__)


def get_all_drives(db: Session):
    return DriveRepository(db).list_all()


def initialize_drive(
    drive_id: int, project_id: str, db: Session, actor: Optional[str] = None
) -> UsbDrive:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    drive = drive_repo.get_for_update(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    if drive.current_project_id and drive.current_project_id != project_id:
        try:
            audit_repo.add(
                action="PROJECT_ISOLATION_VIOLATION",
                user=actor,
                details={
                    "actor": actor,
                    "drive_id": drive_id,
                    "existing_project_id": drive.current_project_id,
                    "requested_project_id": project_id,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for PROJECT_ISOLATION_VIOLATION")
        raise HTTPException(
            status_code=403,
            detail=f"Drive is already assigned to project '{drive.current_project_id}'",
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
            details={"drive_id": drive_id, "project_id": project_id},
        )
    except Exception:
        logger.exception("Failed to write audit log for DRIVE_INITIALIZED")
    return drive


def prepare_eject(drive_id: int, db: Session, actor: Optional[str] = None) -> UsbDrive:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

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
    flush_ok, flush_err = sync_filesystem()
    unmount_ok: bool = True
    unmount_err: Optional[str] = None
    if initial_device_path:
        unmount_ok, unmount_err = unmount_device(initial_device_path)

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

    if flush_ok and unmount_ok:
        drive.current_state = DriveState.AVAILABLE
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
                details={
                    "drive_id": drive_id,
                    "filesystem_path": initial_device_path,
                    "flush_ok": flush_ok,
                    "unmount_ok": unmount_ok,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_EJECT_PREPARED")
    else:
        try:
            audit_repo.add(
                action="DRIVE_EJECT_FAILED",
                user=actor,
                details={
                    "drive_id": drive_id,
                    "filesystem_path": initial_device_path,
                    "flush_ok": flush_ok,
                    "flush_error": flush_err,
                    "unmount_ok": unmount_ok,
                    "unmount_error": unmount_err,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for DRIVE_EJECT_FAILED")
        raise HTTPException(
            status_code=500,
            detail="Drive eject preparation failed",
        )

    return drive
