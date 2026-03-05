from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.hardware import UsbDrive


class DriveRepository:
    """Data-access layer for :class:`~app.models.hardware.UsbDrive`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> List[UsbDrive]:
        """Return all drives."""
        return self.db.query(UsbDrive).all()

    def get(self, drive_id: int) -> Optional[UsbDrive]:
        """Return a single drive by primary key, or ``None``."""
        return self.db.get(UsbDrive, drive_id)

    def add(self, drive: UsbDrive) -> UsbDrive:
        """Persist a new drive and flush it to obtain its ID."""
        self.db.add(drive)
        self.db.commit()
        self.db.refresh(drive)
        return drive

    def save(self, drive: UsbDrive) -> UsbDrive:
        """Commit pending changes to an existing drive and refresh it."""
        self.db.commit()
        self.db.refresh(drive)
        return drive
