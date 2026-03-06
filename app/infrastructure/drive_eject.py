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
from typing import Optional, Tuple

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


def unmount_device(device_path: str) -> Tuple[bool, Optional[str]]:
    """Unmount the block device at *device_path* via ``umount(8)``.

    *device_path* must match ``/dev/<name>`` (e.g. ``/dev/sdb``).  Any path
    that does not match this pattern is rejected before any subprocess is
    spawned.

    Returns ``(True, None)`` on success or ``(False, error_message)`` on
    failure.
    """
    if not _DEVICE_PATH_RE.match(device_path):
        return False, f"invalid device path: {device_path!r}"
    try:
        subprocess.run(
            [_UMOUNT_BIN, device_path],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True, None
    except subprocess.TimeoutExpired:
        return False, f"umount timed out for {device_path}"
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip()
        return False, f"umount failed: {stderr}" if stderr else f"umount failed for {device_path}"
    except OSError as exc:
        return False, f"umount error: {exc}"
