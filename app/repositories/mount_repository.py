from typing import List, Optional

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.exceptions import ConflictError
from app.utils.sanitize import normalize_project_id

from app.models.network import MountStatus, NetworkMount


class MountRepository:
    """Data-access layer for :class:`~app.models.network.NetworkMount`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> List[NetworkMount]:
        """Return all network mounts."""
        return self.db.query(NetworkMount).all()

    def get(self, mount_id: int) -> Optional[NetworkMount]:
        """Return a single mount by primary key, or ``None``."""
        return self.db.get(NetworkMount, mount_id)

    def add(self, mount: NetworkMount) -> NetworkMount:
        """Persist a new mount and flush it to obtain its ID."""
        self.db.add(mount)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(mount)
        return mount

    def has_mounted_project(self, project_id: str) -> bool:
        """Return ``True`` when a mounted share is assigned to ``project_id``."""
        normalized_project_id = normalize_project_id(project_id)
        if not isinstance(normalized_project_id, str) or not normalized_project_id:
            return False
        return (
            self.db.query(NetworkMount.id)
            .filter(
                NetworkMount.status == MountStatus.MOUNTED,
                NetworkMount.project_id == normalized_project_id,
            )
            .first()
            is not None
        )

    def get_mounted_project_for_update(self, project_id: str) -> Optional[NetworkMount]:
        """Return one mounted share for ``project_id`` and request an update lock.

        On backends that support row-level locking, this uses ``FOR UPDATE NOWAIT``
        so initialization fails fast instead of blocking behind a concurrent
        mount or unmount operation.
        """
        normalized_project_id = normalize_project_id(project_id)
        if not isinstance(normalized_project_id, str) or not normalized_project_id:
            return None
        try:
            return (
                self.db.query(NetworkMount)
                .filter(
                    NetworkMount.status == MountStatus.MOUNTED,
                    NetworkMount.project_id == normalized_project_id,
                )
                .order_by(NetworkMount.id)
                .with_for_update(nowait=True)
                .first()
            )
        except OperationalError as exc:
            self.db.rollback()
            orig = getattr(exc, "orig", None)
            sqlstate = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
            if sqlstate == "55P03":
                raise ConflictError(
                    "Project source is currently being updated by another operation."
                ) from exc
            raise

    def save(self, mount: NetworkMount) -> NetworkMount:
        """Commit pending changes to an existing mount and refresh it."""
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(mount)
        return mount

    def delete(self, mount: NetworkMount) -> None:
        """Delete a mount and commit."""
        self.db.delete(mount)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
