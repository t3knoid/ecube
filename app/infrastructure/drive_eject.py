"""OS-level drive flush and unmount operations.

.. note::
   This module is **Linux-only**.  It shells out to ``/bin/sync`` and
   ``/bin/umount``, which are standard Linux utilities.  Running on
   macOS, Windows, or other non-Linux platforms will fail at the
   ``OSError`` level when the binaries are not present.

These thin wrappers isolate subprocess calls so they can be patched in tests
without requiring physical hardware.
"""
from __future__ import annotations

import re
import subprocess
from typing import List, Optional, Tuple

# Allowed block-device path pattern: /dev/<name>, e.g. /dev/sdb, /dev/sdc1.
_DEVICE_PATH_RE = re.compile(r"^/dev/[a-zA-Z][a-zA-Z0-9]*$")

# Absolute paths to system utilities so PATH manipulation cannot redirect them.
_SYNC_BIN = "/bin/sync"
_UMOUNT_BIN = "/bin/umount"


def sync_filesystem() -> Tuple[bool, Optional[str]]:
    """Issue a system-wide filesystem sync via ``sync(1)``.

    Flushes all pending writes to block devices.  Returns ``(True, None)`` on
    success or ``(False, error_message)`` on failure.
    """
    try:
        subprocess.run([_SYNC_BIN], check=True, capture_output=True, timeout=30)
        return True, None
    except subprocess.TimeoutExpired:
        return False, "sync timed out after 30 seconds"
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip()
        return False, f"sync failed: {stderr}" if stderr else "sync failed"
    except OSError as exc:
        return False, f"sync error: {exc}"


def _find_device_mountpoints(device_base: str) -> List[str]:
    """Find all mountpoints for a device and its partitions from /proc/mounts.
    
    Args:
        device_base: Base device name (e.g., "sdb" from "/dev/sdb")
        
    Returns:
        List of mount points for this device and its partitions (e.g., /dev/sdb, /dev/sdb1, /dev/sdb2).
    """
    try:
        with open("/proc/mounts", "r") as f:
            mountpoints = []
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    source = parts[0]
                    mount_point = parts[1]
                    # Match the device itself or its partitions (e.g., /dev/sdb or /dev/sdb1)
                    if source == f"/dev/{device_base}" or (
                        source.startswith(f"/dev/{device_base}")
                        and len(source) > len(f"/dev/{device_base}")
                        and source[len(f"/dev/{device_base}")].isdigit()
                    ):
                        mountpoints.append(mount_point)
            return mountpoints
    except (OSError, IOError):
        # If we can't read /proc/mounts, log the issue but continue
        return []


def unmount_device(device_path: str) -> Tuple[bool, Optional[str]]:
    """Unmount all partitions and mount points belonging to a block device.

    *device_path* must match ``/dev/<name>`` (e.g. ``/dev/sdb``).  Any path
    that does not match this pattern is rejected before any subprocess is
    spawned.
    
    If the device is not currently mounted, returns success (no-op).
    If the device has multiple partitions mounted, all are unmounted.

    Returns ``(True, None)`` on success or ``(False, error_message)`` on
    failure.
    """
    if not _DEVICE_PATH_RE.match(device_path):
        return False, f"invalid device path: {device_path!r}"

    # Extract base device name (e.g., "sdb" from "/dev/sdb")
    device_base = device_path[5:]  # Remove "/dev/" prefix

    # Find all mountpoints for this device and its partitions
    mountpoints = _find_device_mountpoints(device_base)

    # If nothing is mounted, treat as success (nothing to do)
    if not mountpoints:
        return True, None

    # Attempt to unmount all mountpoints; collect errors
    errors = []
    for mount_point in mountpoints:
        try:
            subprocess.run(
                [_UMOUNT_BIN, mount_point],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"umount timed out for {mount_point}")
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            error_msg = f"umount failed for {mount_point}"
            if stderr:
                error_msg += f": {stderr}"
            errors.append(error_msg)
        except OSError as exc:
            errors.append(f"umount error for {mount_point}: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, None
