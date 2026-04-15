"""OS-level USB drive mount operations.

Provides a :class:`DriveMountProvider` protocol and the Linux reference
implementation that shells out to ``mount(8)``.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional, Protocol, Tuple

from app.config import settings
from app.infrastructure.device_path import validate_device_path

logger = logging.getLogger(__name__)

_MOUNT_BIN = settings.mount_binary_path


def _with_sudo(cmd: list[str]) -> list[str]:
    if settings.use_sudo and os.geteuid() != 0:
        return ["sudo", "-n", *cmd]
    return cmd


def _find_mountable_device(device_path: str) -> str:
    """Return the first partition path if partitions exist, else the raw device.

    Checks ``/sys/block/<dev>/`` for partition sub-directories (e.g. ``sdb1``,
    ``nvme0n1p1``).  Returns ``/dev/<partition>`` when found, otherwise returns
    the original *device_path* so the caller can attempt a whole-device mount.
    """
    base = os.path.basename(device_path)  # e.g. "sdb"
    block_dir = os.path.join(settings.sysfs_block_path, base)
    try:
        for entry in sorted(os.listdir(block_dir)):
            if entry.startswith(base) and entry != base:
                return f"/dev/{entry}"
    except OSError:
        pass
    return device_path


def _find_current_mount_point(device_path: str) -> Optional[str]:
    """Return the mount point for *device_path* from ``/proc/mounts``, or ``None``.

    Parses ``/proc/mounts`` (space-separated: device mountpoint fstype options ...)
    and returns the first mount point whose device field matches *device_path*
    after resolving symlinks on both sides.
    """
    try:
        real_device = os.path.realpath(device_path)
    except (OSError, ValueError):
        real_device = device_path
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 2:
                    continue
                dev, mnt = parts[0], parts[1]
                try:
                    real_dev = os.path.realpath(dev)
                except (OSError, ValueError):
                    real_dev = dev
                if real_dev == real_device:
                    return mnt
    except OSError:
        logger.debug("Unable to read /proc/mounts")
    return None


class DriveMountProvider(Protocol):
    """Mount a USB block device to a local directory."""

    def mount_drive(
        self, device_path: str, mount_point: str
    ) -> Tuple[bool, Optional[str]]:
        """Mount *device_path* (or its first partition) at *mount_point*.

        Creates *mount_point* if it does not exist.  Returns
        ``(True, None)`` on success or ``(False, error_message)`` on failure.
        """
        ...


class LinuxDriveMount:
    """Linux implementation using ``mount(8)``."""

    def mount_drive(
        self, device_path: str, mount_point: str
    ) -> Tuple[bool, Optional[str]]:
        if not validate_device_path(device_path):
            return False, f"invalid device path: {device_path!r}"

        mountable = _find_mountable_device(device_path)

        try:
            os.makedirs(mount_point, exist_ok=True)
        except OSError as exc:
            return False, f"failed to create mount point {mount_point}: {exc}"

        try:
            subprocess.run(
                _with_sudo([_MOUNT_BIN, mountable, mount_point]),
                check=True,
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, f"mount timed out after {settings.subprocess_timeout_seconds}s"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            if stderr and "already mounted" in stderr.lower():
                actual = _find_current_mount_point(mountable)
                if actual == mount_point:
                    return True, None
                if actual:
                    return False, (
                        f"{mountable} is already mounted at {actual}, "
                        f"not at requested {mount_point}"
                    )
                return False, f"{mountable} reported already mounted but not found in /proc/mounts"
            msg = f"mount failed for {mountable}"
            if stderr:
                msg += f": {stderr}"
            return False, msg
        except OSError as exc:
            return False, f"mount error: {exc}"

        return True, None
