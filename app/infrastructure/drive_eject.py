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

import codecs
import os.path
import re
import subprocess
from typing import List, Optional, Tuple

# Allowed block-device path pattern: /dev/<name>, e.g. /dev/sdb, /dev/sdc1.
_DEVICE_PATH_RE = re.compile(r"^/dev/[a-zA-Z][a-zA-Z0-9]*$")

# Absolute paths to system utilities so PATH manipulation cannot redirect them.
_SYNC_BIN = "/bin/sync"
_UMOUNT_BIN = "/bin/umount"


def _unescape_mountpoint(escaped_path: str) -> str:
    """Unescape special characters in /proc/mounts path.

    /proc/mounts uses POSIX escape sequences: \\040 for space, \\011 for tab, etc.
    This function converts escaped sequences back to actual characters.

    Args:
        escaped_path: Path string with escape sequences (from /proc/mounts)

    Returns:
        Unescaped path ready to pass to system calls.
    """
    try:
        return codecs.decode(escaped_path, 'unicode_escape')
    except (UnicodeDecodeError, AttributeError):
        # If unescaping fails, return the original path
        return escaped_path


def _normalize_device_path(path: str) -> str:
    """Normalize a device path, resolving symlinks if possible.

    Handles paths like /dev/disk/by-id/* or /dev/disk/by-path/* by resolving
    them to their actual device paths (e.g., /dev/sda).

    Paths that don't exist (common in tests) are returned as-is.
    Device-mapper paths (/dev/mapper/*, /dev/dm-*) and paths with no parent
    directory are not normalized to avoid issues in test environments.

    Args:
        path: Device path, possibly a symlink

    Returns:
        Normalized path with symlinks resolved, or original path if realpath fails.
    """
    try:
        # Only normalize if path looks like it could be a symlink
        # (i.e., not device-mapper paths which are special)
        if path.startswith("/dev/mapper/") or path.startswith("/dev/dm-"):
            return path
        return os.path.realpath(path)
    except (OSError, TypeError):
        return path


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


def _resolve_mapper_device_to_parent(mapper_path: str) -> Optional[str]:
    """Resolve a device-mapper device back to its parent block device via sysfs.
    
    Examples:
    - /dev/mapper/crypto_XXXXX (LUKS) -> /dev/sdb (if backed by sdb)
    - /dev/dm-0 (LVM/device-mapper) -> /dev/sda (if backed by sda)
    
    Uses /sys/block/<device>/slaves/ to find parent block device(s).
    Returns the parent device name (e.g., "sdb") if found, None otherwise.
    
    Args:
        mapper_path: Full device path, e.g. /dev/mapper/luks_vol or /dev/dm-0
        
    Returns:
        Parent device base name (e.g., "sdb") if traceable via sysfs, None if not found or not a mapper device.
    """
    # Extract device name from path (e.g., "crypto_XXXXX" from "/dev/mapper/crypto_XXXXX")
    device_name = os.path.basename(mapper_path)
    
    # For /dev/mapper/* devices, the sysfs entry is often under a sanitized name.
    # Try the device name as-is first, then try via dm-* major/minor if needed.
    sysfs_paths = [
        f"/sys/block/{device_name}",  # e.g. /sys/block/crypto_XXXXX
    ]
    
    for sysfs_path in sysfs_paths:
        slaves_path = os.path.join(sysfs_path, "slaves")
        try:
            if os.path.isdir(slaves_path):
                # Read symlinks in slaves/ directory; each points to a parent device.
                entries = os.listdir(slaves_path)
                if entries:
                    # Return the first (typically only) slave as the parent device base name
                    return entries[0]
        except OSError:
            # sysfs path may not exist or not be readable; continue to next attempt
            pass
    
    return None


def _find_device_mountpoints(device_base: str) -> Tuple[List[str], Optional[str]]:
    """Find all mountpoints for a device and its partitions from /proc/mounts.
    
    Parses /proc/mounts to locate mount points (e.g., /media/usb, /media/usb1)
    for a given block device and any partitions. Handles:
    - Traditional partition naming: sdb -> sdb1, sdb2 (partitions)
    - NVMe partition naming: nvme0n1 -> nvme0n1p1, nvme0n1p2
    - MMC partition naming: mmcblk0 -> mmcblk0p1, mmcblk0p2
    - Device-mapper (LUKS, LVM): /dev/mapper/crypto_XXXXX, /dev/dm-N
    
    Args:
        device_base: Base device name (e.g., "sdb" from "/dev/sdb")
        
    Returns:
        Tuple of (mountpoints_list, error_message):
        - On success: (["/media/usb", "/media/usb1"], None)
        - On read failure: ([], "could not read /proc/mounts: <reason>")
        - If no mounts found: ([], None)
        
    Note:
        Read errors are returned in the tuple, not logged, so callers can decide
        how to handle them (propagate, retry, or treat as "no mounts").
        Device-mapper parent resolution failures are silently ignored (mapper
        device not found or sysfs inaccessible); only mounts via direct device
        or partition paths are reported in such cases.
    """
    try:
        with open("/proc/mounts", "r") as f:
            mountpoints = []
            device_prefix = f"/dev/{device_base}"
            
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    source = parts[0]
                    mount_point_escaped = parts[1]
                    
                    # Normalize source path to handle symlinks like /dev/disk/by-id/*
                    normalized_source = _normalize_device_path(source)
                    normalized_prefix = _normalize_device_path(device_prefix)
                    
                    # Unescape mount point (handles \040 for space, \011 for tab, etc.)
                    mount_point = _unescape_mountpoint(mount_point_escaped)
                    
                    # Match the device itself (exact match)
                    if normalized_source == normalized_prefix:
                        mountpoints.append(mount_point)
                    # Match partitions: suffix must be either digits (sdb1) or p+digits (nvme0n1p1)
                    elif normalized_source.startswith(normalized_prefix) and len(normalized_source) > len(normalized_prefix):
                        suffix = normalized_source[len(normalized_prefix):]
                        # Match traditional (1, 2, 3...) or modern p-prefixed (p1, p2, p3...)
                        if re.match(r"^(p?\d+)$", suffix):
                            mountpoints.append(mount_point)
                    # Match device-mapper devices (LUKS, LVM) backed by this device
                    elif normalized_source.startswith("/dev/mapper/") or normalized_source.startswith("/dev/dm-"):
                        parent_device = _resolve_mapper_device_to_parent(normalized_source)
                        if parent_device == device_base:
                            mountpoints.append(mount_point)
            
            return mountpoints, None
    except OSError as exc:
        # Return read error in tuple; caller decides whether to treat as fatal or no-op
        return [], f"could not read /proc/mounts: {exc}"


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
    mountpoints, read_error = _find_device_mountpoints(device_base)

    # If we couldn't read /proc/mounts, propagate the error
    if read_error:
        return False, read_error

    # If nothing is mounted, treat as success (nothing to do)
    if not mountpoints:
        return True, None

    # Sort mountpoints by depth (deepest first) to safely unmount nested mounts.
    # If we unmount a parent before its children, we get "target is busy" errors.
    # Sorting by descending path length ensures children are unmounted first.
    sorted_mountpoints = sorted(mountpoints, key=lambda p: len(p), reverse=True)

    # Attempt to unmount all mountpoints; collect errors
    errors = []
    for mount_point in sorted_mountpoints:
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
