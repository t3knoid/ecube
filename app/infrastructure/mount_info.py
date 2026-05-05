"""Shared ``/proc/mounts`` parsing utilities.

Both :mod:`usb_discovery` and :mod:`drive_mount` need to read the kernel
mount table.  This module provides a single implementation so the parsing
logic is not duplicated.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from app.config import settings
from app.infrastructure.mount_namespace import shares_host_mount_namespace

logger = logging.getLogger(__name__)

_DEFAULT_PROCFS_MOUNTS_PATH = "/proc/mounts"
_HOST_PROCFS_MOUNTS_PATH = "/proc/1/mounts"
_host_namespace_probe_warning_emitted = False


def _log_host_namespace_probe_failure_once(_exc: OSError) -> None:
    global _host_namespace_probe_warning_emitted
    if _host_namespace_probe_warning_emitted:
        logger.debug("Unable to read host mount namespace; continuing with host mount table fallback")
        return
    _host_namespace_probe_warning_emitted = True
    logger.warning("Unable to read host mount namespace; assuming namespace differs")


def _mounts_path_for_current_context() -> str:
    """Return the authoritative mount table path for the current runtime."""
    mounts_path = settings.procfs_mounts_path
    if mounts_path == _DEFAULT_PROCFS_MOUNTS_PATH and not shares_host_mount_namespace(
        on_self_read_error=True,
        on_host_read_error=False,
        on_host_read_error_callback=_log_host_namespace_probe_failure_once,
    ):
        return _HOST_PROCFS_MOUNTS_PATH
    return mounts_path


def _normalize_mount_path(path: str) -> str:
    normalized = path.rstrip("/")
    return normalized or "/"


def unescape_mountpoint(escaped_path: str) -> str:
    """Unescape octal escape sequences used in ``/proc/mounts``.

    ``/proc/mounts`` uses POSIX octal escape sequences (``\\040`` for space,
    ``\\011`` for tab, etc.) to encode raw bytes of the filesystem path.
    These are *raw bytes*, not Unicode code points, so we build a
    ``bytearray`` first and then decode it as UTF-8.  This correctly handles
    multi-byte UTF-8 sequences (e.g. ``\\303\\251`` for the UTF-8 encoding
    of ``é``), whereas the ``unicode_escape`` codec would misinterpret each
    octal value as a Latin-1 code point, producing mojibake.
    """
    try:
        buf = bytearray()
        for part in re.split(r'(\\[0-7]{3})', escaped_path):
            if part and part[0] == '\\':
                buf.append(int(part[1:], 8))
            else:
                buf.extend(part.encode('utf-8', errors='surrogateescape'))
        return buf.decode('utf-8', errors='surrogateescape')
    except (ValueError, UnicodeDecodeError):
        return escaped_path


def read_mount_table() -> dict[str, str]:
    """Return a mapping of *mount point → source* from ``/proc/mounts``.

    Returns an empty dict when the file cannot be read (non-Linux, container,
    permission error, etc.).
    """
    mounts_path = _mounts_path_for_current_context()
    result: dict[str, str] = {}
    try:
        with open(mounts_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    source = unescape_mountpoint(parts[0])
                    mount_point = unescape_mountpoint(parts[1])
                    result[mount_point] = source
    except OSError:
        logger.debug("Unable to read %s", mounts_path)
    return result


def read_mount_points() -> dict[str, str]:
    """Return a mapping of *device path → mount point* from ``/proc/mounts``.

    Each key is a block-device path (e.g. ``"/dev/sdb1"``) and each value is
    the corresponding mount point (e.g. ``"/mnt/ecube/7"``). Only entries
    whose source field starts with ``/dev/`` are included.
    """
    mount_table = read_mount_table()
    return {
        source: mount_point
        for mount_point, source in mount_table.items()
        if source.startswith("/dev/")
    }


def is_active_mount_point(mount_point: str) -> bool:
    """Return whether *mount_point* is present in the authoritative mount table."""
    target = _normalize_mount_path(mount_point)
    try:
        real_target = os.path.realpath(target)
    except (OSError, ValueError):
        real_target = target

    for mounted_path in read_mount_table().keys():
        normalized_mounted = _normalize_mount_path(mounted_path)
        if normalized_mounted == target:
            return True
        try:
            real_mounted = os.path.realpath(normalized_mounted)
        except (OSError, ValueError):
            real_mounted = normalized_mounted
        if real_mounted == real_target:
            return True

    return False


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
