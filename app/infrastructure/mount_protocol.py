"""Platform-neutral mount/unmount protocol.

This module contains only the :class:`MountProvider` typing Protocol so that
any module can import it without pulling in the service module's heavier
dependencies (FastAPI, SQLAlchemy ORM models, repositories).  The concrete
Linux implementation lives in :mod:`app.services.mount_service`.
"""

from __future__ import annotations

from typing import Optional, Protocol, Tuple

from app.models.network import MountType


class MountProvider(Protocol):
    """Platform-agnostic interface for OS-level mount/unmount operations."""

    def os_mount(self, mount_type: MountType, remote_path: str, local_mount_point: str,
                 *, credentials_file: Optional[str] = None, username: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """Mount a remote filesystem. Returns (success, error_message)."""
        ...

    def os_unmount(self, local_mount_point: str) -> Tuple[bool, Optional[str]]:
        """Unmount a filesystem. Returns (success, error_message)."""
        ...

    def check_mounted(self, local_mount_point: str) -> Optional[bool]:
        """Check if a path is an active mountpoint. Returns True/False/None on error."""
        ...
