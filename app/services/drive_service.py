from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.hardware import DriveState, UsbDrive
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository


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
        raise HTTPException(
            status_code=403,
            detail=f"Drive is already assigned to project '{drive.current_project_id}'",
        )

    drive.current_project_id = project_id
    drive.current_state = DriveState.IN_USE
    drive_repo.save(drive)
    audit_repo.add(
        action="DRIVE_INITIALIZED",
        user=actor,
        details={"drive_id": drive_id, "project_id": project_id},
    )
    return drive


def prepare_eject(drive_id: int, db: Session, actor: Optional[str] = None) -> UsbDrive:
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    drive = drive_repo.get_for_update(drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    drive.current_state = DriveState.AVAILABLE
    drive_repo.save(drive)
    audit_repo.add(
        action="DRIVE_EJECT_PREPARED",
        user=actor,
        details={"drive_id": drive_id},
    )
    return drive
