from typing import List, Optional

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.exceptions import ConflictError
from app.models.hardware import DriveState, UsbDrive


class DriveRepository:
    """Data-access layer for :class:`~app.models.hardware.UsbDrive`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> List[UsbDrive]:
        """Return all drives."""
        return self.db.query(UsbDrive).all()

    def list_by_project(self, project_id: str) -> List[UsbDrive]:
        """Return drives whose ``current_project_id`` matches *project_id*."""
        return (
            self.db.query(UsbDrive)
            .filter(UsbDrive.current_project_id == project_id)
            .all()
        )

    def get(self, drive_id: int) -> Optional[UsbDrive]:
        """Return a single drive by primary key, or ``None``."""
        return self.db.get(UsbDrive, drive_id)

    def get_for_update(self, drive_id: int) -> Optional[UsbDrive]:
        """Return a single drive locked for update, or ``None`` if not found.

        Issues a ``SELECT … FOR UPDATE NOWAIT`` so that concurrent transactions
        attempting to modify the same drive row are serialized.  If the row is
        already held by another transaction the database raises an
        ``OperationalError`` which is translated to
        :class:`~app.exceptions.ConflictError` (HTTP 409).

        On backends that do not enforce ``FOR UPDATE`` at the row level
        (e.g. SQLite used in tests) the clause is silently ignored and a
        normal ``SELECT`` is executed instead.
        """
        try:
            return (
                self.db.query(UsbDrive)
                .filter(UsbDrive.id == drive_id)
                .with_for_update(nowait=True)
                .one_or_none()
            )
        except OperationalError as exc:
            self.db.rollback()
            orig = getattr(exc, "orig", None)
            sqlstate = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
            if sqlstate == "55P03":
                raise ConflictError(
                    "Drive is currently locked by another operation."
                ) from exc
            raise

    def add(self, drive: UsbDrive) -> UsbDrive:
        """Persist a new drive and flush it to obtain its ID."""
        self.db.add(drive)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(drive)
        return drive

    def save(self, drive: UsbDrive) -> UsbDrive:
        """Commit pending changes to an existing drive and refresh it."""
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(drive)
        return drive

    def count_available_for_project(self, project_id: str) -> int:
        """Return the number of ``AVAILABLE`` drives bound to *project_id*.

        This is an **unlocked** count used for disambiguation: the caller
        must know the true total (including rows locked by other
        transactions) to decide whether auto-assignment is unambiguous.
        """
        return (
            self.db.query(UsbDrive)
            .filter(
                UsbDrive.current_state == DriveState.AVAILABLE,
                UsbDrive.current_project_id == project_id,
            )
            .count()
        )

    def get_one_available_for_project(self, project_id: str) -> Optional[UsbDrive]:
        """Return a single ``AVAILABLE`` drive bound to *project_id*, row-locked.

        Uses ``FOR UPDATE SKIP LOCKED`` so that a drive held by a concurrent
        transaction is skipped rather than blocking.  Returns ``None`` if no
        unlocked candidate exists.
        """
        return (
            self.db.query(UsbDrive)
            .filter(
                UsbDrive.current_state == DriveState.AVAILABLE,
                UsbDrive.current_project_id == project_id,
            )
            .order_by(UsbDrive.id)
            .with_for_update(skip_locked=True)
            .first()
        )

    def get_next_unbound_available(self) -> Optional[UsbDrive]:
        """Return the first ``AVAILABLE`` drive with no project binding, locked with ``FOR UPDATE SKIP LOCKED``.

        Used as a fallback when no project-bound drives are available.
        Orders by ``UsbDrive.id`` for deterministic selection; drives locked
        by concurrent transactions are silently skipped.
        """
        return (
            self.db.query(UsbDrive)
            .filter(
                UsbDrive.current_state == DriveState.AVAILABLE,
                UsbDrive.current_project_id.is_(None),
            )
            .order_by(UsbDrive.id)
            .with_for_update(skip_locked=True)
            .first()
        )
