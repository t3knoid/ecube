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

    If sysfs access fails (``OSError``), silently falls back to the raw
    device path.
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


def _validate_managed_mount_point(mount_point: str) -> str | None:
    """Validate that the mount point is a managed direct child of the base path."""
    if not os.path.isabs(mount_point):
        return f"mount_point must be an absolute path, got {mount_point!r}"
    expected_base = os.path.realpath(settings.usb_mount_base_path)
    real_mp = os.path.realpath(mount_point)
    if os.path.dirname(real_mp) != expected_base:
        return (
            f"mount_point must be a direct child of {expected_base}, "
            f"got {mount_point!r} (resolves to {real_mp!r})"
        )
    return None


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

    def unmount_drive(
        self, mount_point: str
    ) -> tuple[bool, str | None]:
        """Unmount a previously managed mount point.

        Returns ``(True, None)`` on success or ``(False, error_message)`` on failure.
        """
        ...


class LinuxDriveMount:
    """Linux implementation using ``mount(8)``."""

    def mount_drive(
        self, device_path: str, mount_point: str
    ) -> tuple[bool, str | None]:
        if not validate_device_path(device_path):
            return False, f"invalid device path: {device_path!r}"

        mount_point_error = _validate_managed_mount_point(mount_point)
        if mount_point_error:
            return False, mount_point_error

        mountable = _find_mountable_device(device_path)
        logger.info(
            "Attempting drive mount: device_name=%s mount_slot=%s",
            os.path.basename(mountable),
            os.path.basename(mount_point.rstrip("/")),
        )

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
            logger.warning(
                "Drive mount timed out: device_name=%s mount_slot=%s timeout=%ss",
                os.path.basename(mountable),
                os.path.basename(mount_point.rstrip("/")),
                settings.subprocess_timeout_seconds,
            )
            return False, f"mount timed out after {settings.subprocess_timeout_seconds}s"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            logger.warning(
                "Drive mount command failed: device_name=%s mount_slot=%s returncode=%s reason=%s",
                os.path.basename(mountable),
                os.path.basename(mount_point.rstrip("/")),
                exc.returncode,
                stderr or "mount command failed",
            )
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
            logger.warning(
                "Drive mount OS error: device_name=%s mount_slot=%s reason=%s",
                os.path.basename(mountable),
                os.path.basename(mount_point.rstrip("/")),
                str(exc),
            )
            return False, f"mount error: {exc}"

        logger.info(
            "Drive mount succeeded: device_name=%s mount_slot=%s",
            os.path.basename(mountable),
            os.path.basename(mount_point.rstrip("/")),
        )
        return True, None

    def unmount_drive(
        self, mount_point: str
    ) -> tuple[bool, str | None]:
        mount_point_error = _validate_managed_mount_point(mount_point)
        if mount_point_error:
            return False, mount_point_error

        try:
            subprocess.run(
                _with_sudo([settings.umount_binary_path, mount_point]),
                check=True,
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, f"unmount timed out after {settings.subprocess_timeout_seconds}s"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            msg = "unmount failed"
            if stderr:
                msg += f": {stderr}"
            return False, msg
        except OSError as exc:
            return False, f"unmount error: {exc}"

        return True, None
