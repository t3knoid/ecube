"""Shared ``/proc/mounts`` parsing utilities.

Both :mod:`usb_discovery` and :mod:`drive_mount` need to read the kernel
mount table.  This module provides a single implementation so the parsing
logic is not duplicated.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def read_mount_points() -> dict[str, str]:
    """Return a mapping of *device path → mount point* from ``/proc/mounts``.

    Each key is a block-device path (e.g. ``"/dev/sdb1"``) and each value is
    the corresponding mount point (e.g. ``"/mnt/ecube/7"``).  Only entries
    whose device field starts with ``/dev/`` are included.

    Returns an empty dict when the file cannot be read (non-Linux, container,
    permission error, etc.).
    """
    mounts_path = settings.procfs_mounts_path
    result: dict[str, str] = {}
    try:
        with open(mounts_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("/dev/"):
                    result[parts[0]] = parts[1]
    except OSError:
        logger.debug("Unable to read %s", mounts_path)
    return result


def find_device_mount_point(device_path: str) -> Optional[str]:
    """Return the mount point for *device_path*, or ``None``.

    Resolves symlinks on both the target *device_path* and each ``/dev/``
    entry in the mount table so that device-mapper aliases, ``/dev/disk/``
    links, etc. are matched correctly.
    """
    try:
        real_device = os.path.realpath(device_path)
    except (OSError, ValueError):
        real_device = device_path

    mount_map = read_mount_points()
    for dev, mnt in mount_map.items():
        try:
            real_dev = os.path.realpath(dev)
        except (OSError, ValueError):
            real_dev = dev
        if real_dev == real_device:
            return mnt
    return None
