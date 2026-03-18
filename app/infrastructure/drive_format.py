"""Drive formatting infrastructure.

Defines the :class:`DriveFormatter` protocol and the Linux reference
implementation that shells out to ``mkfs.*`` utilities.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Protocol

from app.config import settings
from app.infrastructure.device_path import validate_device_path

logger = logging.getLogger(__name__)

# Mapping from canonical filesystem type to settings attribute for binary path.
_MKFS_SETTINGS_MAP = {
    "ext4": "mkfs_ext4_path",
    "exfat": "mkfs_exfat_path",
}


class DriveFormatter(Protocol):
    """Format a block device and check mount status."""

    def format(self, device_path: str, filesystem_type: str) -> None:
        """Format the block device with the given filesystem type.

        Raises :class:`RuntimeError` on failure.  Implementations must
        validate ``device_path`` before any destructive operation.
        """
        ...

    def is_mounted(self, device_path: str) -> bool:
        """Return ``True`` if the device (or any partition) is currently mounted."""
        ...


class LinuxDriveFormatter:
    """Linux implementation using ``mkfs.*`` and ``/proc/mounts``."""

    def format(self, device_path: str, filesystem_type: str) -> None:
        if not validate_device_path(device_path):
            raise RuntimeError(f"Invalid device path: {device_path!r}")

        settings_attr = _MKFS_SETTINGS_MAP.get(filesystem_type)
        if settings_attr is None:
            raise RuntimeError(f"Unsupported filesystem type: {filesystem_type!r}")

        mkfs_binary = getattr(settings, settings_attr)

        try:
            subprocess.run(
                [mkfs_binary, device_path],
                check=True,
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Format timed out after {settings.subprocess_timeout_seconds}s"
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            raise RuntimeError(f"mkfs failed: {stderr}" if stderr else "mkfs failed")
        except OSError as exc:
            raise RuntimeError(f"mkfs error: {exc}")

    def is_mounted(self, device_path: str) -> bool:
        if not validate_device_path(device_path):
            return False

        device_base = device_path.split("/")[-1]  # e.g. "sdb"
        try:
            with open(settings.procfs_mounts_path, "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        source = parts[0]
                        if source == device_path or (
                            source.startswith(f"/dev/{device_base}")
                            and len(source) > len(f"/dev/{device_base}")
                        ):
                            return True
        except OSError:
            logger.warning("Could not read %s for mount check", settings.procfs_mounts_path)
        return False
