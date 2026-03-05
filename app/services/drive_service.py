from sqlalchemy.orm import Session
from app.models.hardware import UsbDrive, DriveState
from app.services.audit_service import create_audit_log
from fastapi import HTTPException


def get_all_drives(db: Session):
    return db.query(UsbDrive).all()


def initialize_drive(drive_id: int, project_id: str, db: Session) -> UsbDrive:
    drive = db.get(UsbDrive, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    if drive.current_project_id and drive.current_project_id != project_id:
        create_audit_log(
            db=db,
            action="PROJECT_ISOLATION_VIOLATION",
            details={
                "drive_id": drive_id,
                "existing_project_id": drive.current_project_id,
                "requested_project_id": project_id,
            },
        )
        raise HTTPException(
            status_code=409,
            detail=f"Drive is already assigned to project '{drive.current_project_id}'",
        )

    drive.current_project_id = project_id
    drive.current_state = DriveState.IN_USE
    db.commit()
    db.refresh(drive)
    create_audit_log(
        db=db,
        action="DRIVE_INITIALIZED",
        details={"drive_id": drive_id, "project_id": project_id},
    )
    return drive


def prepare_eject(drive_id: int, db: Session) -> UsbDrive:
    drive = db.get(UsbDrive, drive_id)
    if not drive:
        raise HTTPException(status_code=404, detail="Drive not found")

    drive.current_state = DriveState.AVAILABLE
    db.commit()
    db.refresh(drive)
    create_audit_log(
        db=db,
        action="DRIVE_EJECT_PREPARED",
        details={"drive_id": drive_id},
    )
    return drive
