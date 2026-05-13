from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.exceptions import ConflictError
from app.utils.sanitize import normalize_project_id

from app.models.network import MountStatus, NetworkShare


class ShareRepository:
    """Data-access layer for :class:`~app.models.network.NetworkShare`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> List[NetworkShare]:
        """Return all network mounts."""
        return self.db.query(NetworkShare).all()

    def get(self, mount_id: int) -> Optional[NetworkShare]:
        """Return a single mount by primary key, or ``None``."""
        return self.db.get(NetworkShare, mount_id)

    def acquire_create_lock(self) -> None:
        """Serialize mount-creation validation and insert operations.

        This protects the duplicate/overlap isolation checks from concurrent
        requests that would otherwise both pass the pre-insert validation.
        PostgreSQL uses a transaction-scoped advisory lock keyed to mount
        creation; other backends fall back to row locking when available.
        """
        dialect = self.db.bind.dialect.name if self.db.bind is not None else ""
        if dialect == "postgresql":
            self.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 221212})
            return

        if dialect == "sqlite":
            return

        try:
            self.db.query(NetworkShare.id).order_by(NetworkShare.id).with_for_update(nowait=True).all()
        except OperationalError as exc:
            self.db.rollback()
            orig = getattr(exc, "orig", None)
            sqlstate = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
            if sqlstate == "55P03":
                raise ConflictError(
                    "Network mount configuration is currently being updated by another operation."
                ) from exc
            raise

    def add(self, mount: NetworkShare) -> NetworkShare:
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
            self.db.query(NetworkShare.id)
            .filter(
                NetworkShare.status == MountStatus.MOUNTED,
                NetworkShare.project_id == normalized_project_id,
            )
            .first()
            is not None
        )

    def get_mounted_project_for_update(self, project_id: str) -> Optional[NetworkShare]:
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
                self.db.query(NetworkShare)
                .filter(
                    NetworkShare.status == MountStatus.MOUNTED,
                    NetworkShare.project_id == normalized_project_id,
                )
                .order_by(NetworkShare.id)
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

    def save(self, mount: NetworkShare) -> NetworkShare:
        """Commit pending changes to an existing mount and refresh it."""
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(mount)
        return mount

    def delete(self, mount: NetworkShare) -> None:
        """Delete a mount and commit."""
        self.db.delete(mount)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
