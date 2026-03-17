from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.network import NetworkMount


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
