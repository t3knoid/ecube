"""OS-level USB drive mount operations.

Provides a :class:`DriveMountProvider` protocol and the Linux reference
implementation that shells out to ``mount(8)``.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Protocol

from app.config import settings
from app.infrastructure.device_path import validate_device_path
from app.infrastructure.mount_info import find_device_mount_point

logger = logging.getLogger(__name__)


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
                # Verify this is actually a partition, not an unrelated sysfs
                # attribute directory (e.g. power, queue, holders).  Real
                # partitions have a "partition" file inside their sysfs dir.
                partition_marker = os.path.join(block_dir, entry, "partition")
                if os.path.exists(partition_marker):
                    return f"/dev/{entry}"
    except OSError:
        pass
    return device_path


# Mount-point lookup moved to app.infrastructure.mount_info


class DriveMountProvider(Protocol):
    """Mount a USB block device to a local directory."""

    def mount_drive(
        self, device_path: str, mount_point: str
    ) -> tuple[bool, str | None]:
        """Mount *device_path* (or its first partition) at *mount_point*.

        Creates *mount_point* if it does not exist.  Returns
        ``(True, None)`` on success or ``(False, error_message)`` on failure.
        """
        ...


class LinuxDriveMount:
    """Linux implementation using ``mount(8)``."""

    def mount_drive(
        self, device_path: str, mount_point: str
    ) -> tuple[bool, str | None]:
        if not validate_device_path(device_path):
            return False, f"invalid device path: {device_path!r}"

        # Validate mount_point: must be an absolute path that resolves to a
        # direct child of the configured usb_mount_base_path.  This prevents
        # callers from creating arbitrary directories or mounting outside the
        # expected tree.
        if not os.path.isabs(mount_point):
            return False, f"mount_point must be an absolute path, got {mount_point!r}"
        expected_base = os.path.realpath(settings.usb_mount_base_path)
        real_mp = os.path.realpath(mount_point)
        if os.path.dirname(real_mp) != expected_base:
            return False, (
                f"mount_point must be a direct child of {expected_base}, "
                f"got {mount_point!r} (resolves to {real_mp!r})"
            )

        mountable = _find_mountable_device(device_path)

        try:
            os.makedirs(mount_point, exist_ok=True)
        except OSError as exc:
            return False, f"failed to create mount point {mount_point}: {exc}"

        try:
            subprocess.run(
                _with_sudo([settings.mount_binary_path, mountable, mount_point]),
                check=True,
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, f"mount timed out after {settings.subprocess_timeout_seconds}s"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            if stderr and "already mounted" in stderr.lower():
                actual = find_device_mount_point(mountable)
                if actual == mount_point:
                    return True, None
                if actual:
                    return False, (
                        f"{mountable} is already mounted at {actual}, "
                        f"not at requested {mount_point}"
                    )
                return False, f"{mountable} reported already mounted but not found in {settings.procfs_mounts_path}"
            msg = f"mount failed for {mountable}"
            if stderr:
                msg += f": {stderr}"
            return False, msg
        except OSError as exc:
            return False, f"mount error: {exc}"

        return True, None
