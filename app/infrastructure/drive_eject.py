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

import os.path
import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple

from app.config import settings
from app.infrastructure.device_path import validate_device_path

# Absolute paths to system utilities so PATH manipulation cannot redirect them.
# Actual values come from settings; these module-level names kept for readability.
_SYNC_BIN = settings.sync_binary_path
_UMOUNT_BIN = settings.umount_binary_path


# ---------------------------------------------------------------------------
# EjectError / EjectResult
# ---------------------------------------------------------------------------

class EjectError(RuntimeError):
    """Raised when a drive eject operation fails."""


@dataclass
class EjectResult:
    """Structured result of a :meth:`DriveEjectProvider.prepare_eject` call."""

    flush_ok: bool = True
    unmount_ok: bool = True
    flush_error: Optional[str] = None
    unmount_error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.flush_ok and self.unmount_ok


# ---------------------------------------------------------------------------
# DriveEjectProvider Protocol
# ---------------------------------------------------------------------------

class DriveEjectProvider(Protocol):
    """Platform-agnostic interface for drive flush and unmount operations.

    Low-level methods (``sync_filesystem``, ``unmount_device``) raise
    :class:`EjectError` on failure so callers don't need to unpack tuples.

    ``prepare_eject`` is the high-level orchestrator: it flushes writes,
    unmounts partitions when *device_path* is provided, and returns a
    structured :class:`EjectResult` (never raises for OS-level failures).
    """

    def sync_filesystem(self) -> None: ...

    def unmount_device(self, device_path: str) -> None: ...

    def prepare_eject(self, device_path: Optional[str]) -> EjectResult: ...


class LinuxDriveEject:
    """Linux implementation using ``sync(1)`` and ``umount(8)``."""

    def sync_filesystem(self) -> None:
        ok, err = sync_filesystem()
        if not ok:
            raise EjectError(err or "sync failed")

    def unmount_device(self, device_path: str) -> None:
        ok, err = unmount_device(device_path)
        if not ok:
            raise EjectError(err or "unmount failed")

    def prepare_eject(self, device_path: Optional[str]) -> EjectResult:
        flush_ok, flush_err = sync_filesystem()
        umount_ok: bool = True
        umount_err: Optional[str] = None
        if device_path:
            umount_ok, umount_err = unmount_device(device_path)
        return EjectResult(
            flush_ok=flush_ok,
            unmount_ok=umount_ok,
            flush_error=flush_err,
            unmount_error=umount_err,
        )


def _unescape_mountpoint(escaped_path: str) -> str:
    """Unescape special characters in /proc/mounts path.

    /proc/mounts uses POSIX octal escape sequences (``\\040`` for space,
    ``\\011`` for tab, etc.) to encode raw bytes of the filesystem path.
    These are *raw bytes*, not Unicode code points, so we build a
    ``bytearray`` first and then decode it as UTF-8.  This correctly handles
    multi-byte UTF-8 sequences (e.g. ``\\303\\251`` for the UTF-8 encoding
    of ``é``), whereas the ``unicode_escape`` codec would misinterpret each
    octal value as a Latin-1 code point, producing mojibake.

    Args:
        escaped_path: Path string with escape sequences (from /proc/mounts)

    Returns:
        Unescaped path ready to pass to system calls.
    """
    try:
        buf = bytearray()
        for part in re.split(r'(\\[0-7]{3})', escaped_path):
            if part and part[0] == '\\':
                # Octal escape — convert to the corresponding byte value
                buf.append(int(part[1:], 8))
            else:
                buf.extend(part.encode('utf-8', errors='surrogateescape'))
        return buf.decode('utf-8', errors='surrogateescape')
    except (ValueError, UnicodeDecodeError):
        # If unescaping fails, return the original path
        return escaped_path


def _normalize_device_path(path: str) -> str:
    """Normalize a device path, resolving symlinks if possible.

    Handles paths like /dev/disk/by-id/* or /dev/disk/by-path/* by resolving
    them to their actual device paths (e.g., /dev/sda). Also resolves 
    /dev/mapper/* symlinks to their actual /dev/dm-N device nodes.

    Paths that don't exist (common in tests) are returned as-is.

    Args:
        path: Device path, possibly a symlink

    Returns:
        Normalized path with symlinks resolved, or original path if realpath fails.
    """
    try:
        return os.path.realpath(path)
    except (OSError, TypeError):
        return path


def sync_filesystem() -> Tuple[bool, Optional[str]]:
    """Issue a system-wide filesystem sync via ``sync(1)``.

    Flushes all pending writes to block devices.  Returns ``(True, None)`` on
    success or ``(False, error_message)`` on failure.
    """
    try:
        subprocess.run([_SYNC_BIN], check=True, capture_output=True, timeout=settings.subprocess_timeout_seconds)
        return True, None
    except subprocess.TimeoutExpired:
        return False, f"sync timed out after {settings.subprocess_timeout_seconds} seconds"
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip()
        return False, f"sync failed: {stderr}" if stderr else "sync failed"
    except OSError as exc:
        return False, f"sync error: {exc}"


def _resolve_mapper_device_to_parent(mapper_path: str) -> List[str]:
    """Resolve a device-mapper device back to its parent block-device slaves via sysfs.
    
    On Linux, /dev/mapper/<name> is a symlink to /dev/dm-N. This function:
    1. Normalizes the input path (resolves symlink to /dev/dm-N)
    2. Lists the slave devices via /sys/block/dm-N/slaves/
    
    Examples:
    - /dev/mapper/crypto_XXXXX (LUKS) -> resolved to /dev/dm-0 -> ["sdb"]
    - /dev/dm-0 (already direct) -> ["sdb"]
    - A multipath or RAID mapper may return multiple slave names.
    
    Args:
        mapper_path: Full device path, e.g. /dev/mapper/luks_vol or /dev/dm-0
        
    Returns:
        A list of parent device base names (e.g., ["sdb", "sdc"]). Returns an empty
        list if the mapper has no slaves, cannot be resolved via sysfs, or is not
        a device-mapper node.
    """
    # Normalize to real /dev/dm-N path (handles symlinks)
    normalized_path = _normalize_device_path(mapper_path)
    
    # Extract the dm device name (e.g., "dm-0" from "/dev/dm-0")
    # Only proceed if this looks like a device-mapper device
    if not normalized_path.startswith("/dev/dm-"):
        return []
    
    device_name = os.path.basename(normalized_path)  # e.g., "dm-0"
    slaves_path = f"{settings.sysfs_block_path}/{device_name}/slaves"
    
    try:
        if os.path.isdir(slaves_path):
            # Read entries in slaves/ directory; each entry name is a parent device.
            entries = os.listdir(slaves_path)
            # Return all slave device base names (may be empty).
            return sorted(entries)
    except OSError:
        # sysfs path may not exist or not be readable
        pass
    
    return []


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
        with open(settings.procfs_mounts_path, "r") as f:
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
                    # Match device-mapper devices (LUKS, LVM) backed by this device or its partitions
                    elif normalized_source.startswith("/dev/mapper/") or normalized_source.startswith("/dev/dm-"):
                        parent_devices = _resolve_mapper_device_to_parent(normalized_source)
                        for parent_device in parent_devices:
                            # Exact base-device match (e.g., parent 'sdb' for /dev/sdb)
                            if parent_device == device_base:
                                mountpoints.append(mount_point)
                                break
                            # Partition-backed mapper (e.g., parent 'sdb1' or 'nvme0n1p2')
                            elif parent_device.startswith(device_base) and len(parent_device) > len(device_base):
                                suffix = parent_device[len(device_base):]
                                if re.match(r"^(p?\d+)$", suffix):
                                    mountpoints.append(mount_point)
                                    break
            
            return mountpoints, None
    except OSError as exc:
        # Return read error in tuple; caller decides whether to treat as fatal or no-op
        return [], f"could not read {settings.procfs_mounts_path}: {exc}"


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
    if not validate_device_path(device_path):
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
                timeout=settings.subprocess_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"umount timed out for {mount_point}")
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            # "not mounted" / "no mount point" means the desired end-state is
            # already achieved (e.g. mount disappeared between the /proc/mounts
            # read and the umount call).  Treat these as a successful no-op so
            # a transient race doesn't cause the endpoint to return HTTP 500.
            if stderr and any(
                phrase in stderr.lower()
                for phrase in ("not mounted", "no mount point")
            ):
                continue
            error_msg = f"umount failed for {mount_point}"
            if stderr:
                error_msg += f": {stderr}"
            errors.append(error_msg)
        except OSError as exc:
            errors.append(f"umount error for {mount_point}: {exc}")

    if errors:
        return False, "; ".join(errors)
    return True, None
