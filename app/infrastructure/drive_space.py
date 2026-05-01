"""Drive free-space probing infrastructure.

Provides a trusted interface for reading currently available bytes from a
mounted USB filesystem without exposing raw host details through the API.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Protocol


logger = logging.getLogger(__name__)


class DriveSpaceProbe(Protocol):
    """Read the available free space for a mounted drive path."""

    def probe_available_bytes(self, mount_path: str) -> Optional[int]:
        """Return best-effort available bytes for *mount_path*, or ``None``."""
        ...


class LinuxDriveSpaceProbe:
    """Linux implementation using ``os.statvfs`` on the mounted filesystem."""

    def probe_available_bytes(self, mount_path: str) -> Optional[int]:
        if not mount_path:
            return None

        try:
            stats = os.statvfs(mount_path)
        except OSError as exc:
            logger.debug(
                "Drive available-space probe failed",
                extra={"mount_path": mount_path, "raw_error": str(exc)},
            )
            return None

        return int(stats.f_bavail) * int(stats.f_frsize)