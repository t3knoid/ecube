"""Drive formatting infrastructure.

Defines the :class:`DriveFormatter` protocol and the Linux reference
implementation that shells out to ``mkfs.*`` utilities.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Optional, Protocol

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

    def probe_free_bytes(self, device_path: str, filesystem_type: str) -> Optional[int]:
        """Return best-effort free bytes available after formatting."""
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
                _with_sudo([mkfs_binary, device_path]),
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
            logger.exception("Could not read %s for mount check", settings.procfs_mounts_path)
        return False

    def probe_free_bytes(self, device_path: str, filesystem_type: str) -> Optional[int]:
        if not validate_device_path(device_path):
            return None
        if filesystem_type != "ext4":
            return None

        try:
            proc = subprocess.run(
                _with_sudo([settings.dumpe2fs_path, "-h", device_path]),
                check=True,
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError) as exc:
            logger.debug(
                "dumpe2fs free-space probe failed",
                extra={"filesystem_path": device_path, "raw_error": str(exc)},
            )
            return None

        output = proc.stdout.decode(errors="replace")
        free_blocks = _extract_ext4_header_int(output, "Free blocks")
        block_size = _extract_ext4_header_int(output, "Block size")
        if free_blocks is None or block_size is None:
            return None
        return free_blocks * block_size


_EXT4_HEADER_FIELD_RE = re.compile(r"^(?P<key>[^:]+):\s*(?P<value>[0-9,]+)\s*$", re.MULTILINE)


def _extract_ext4_header_int(output: str, field_name: str) -> Optional[int]:
    for match in _EXT4_HEADER_FIELD_RE.finditer(output):
        if match.group("key").strip() != field_name:
            continue
        try:
            return int(match.group("value").replace(",", ""))
        except ValueError:
            return None
    return None


def _with_sudo(cmd: list[str]) -> list[str]:
    if settings.use_sudo and os.geteuid() != 0:
        return ["sudo", "-n", *cmd]
    return cmd
