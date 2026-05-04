"""OS-level USB drive mount operations.

Provides a :class:`DriveMountProvider` protocol and the Linux reference
implementation that shells out to ``mount(8)``.
"""
from __future__ import annotations

import grp
import logging
import os
import pwd
import shutil
import subprocess
from typing import Protocol

from app.config import settings
from app.infrastructure.device_path import validate_device_path
from app.infrastructure.filesystem_detection import LinuxFilesystemDetector
from app.infrastructure.mount_info import find_device_mount_point
from app.infrastructure.mount_namespace import shares_host_mount_namespace
from app.utils.sanitize import sanitize_error_message

logger = logging.getLogger(__name__)


def _classify_drive_mount_failure(raw_error: object, *, phase: str) -> tuple[str, str]:
    raw_text = "" if raw_error is None else str(raw_error).strip()
    lowered = raw_text.lower()
    default_messages = {
        "mount_root_prepare": "Managed mount root is unavailable",
        "mount_timeout": "Mount operation timed out",
        "mount_command": "Mount command failed",
        "mount_os_error": "Mount operation failed unexpectedly",
        "mount_access_repair": "Mount succeeded but post-mount access repair failed",
    }
    safe_summary = sanitize_error_message(raw_error, default_messages.get(phase, "Mount operation failed"))

    if phase == "mount_root_prepare":
        if any(token in lowered for token in ("permission denied", "access denied", "not authorized")):
            return "managed_mount_root_inaccessible", safe_summary
        if "no such file" in lowered or "not found" in lowered:
            return "managed_mount_root_missing", safe_summary
        return "managed_mount_root_unavailable", safe_summary

    if phase == "mount_timeout":
        return "mount_timeout", safe_summary

    if phase == "mount_access_repair":
        return "post_mount_access_repair_failure", safe_summary

    if "unknown filesystem type" in lowered or "wrong fs type" in lowered or "bad superblock" in lowered:
        return "missing_filesystem_runtime", safe_summary
    if any(token in lowered for token in ("permission denied", "access denied", "not authorized")):
        return "mount_permission_failure", safe_summary
    if "no such file" in lowered or "not found" in lowered:
        return "mount_target_unavailable", safe_summary

    if phase == "mount_os_error":
        return "mount_runtime_error", safe_summary
    return "mount_command_failure", safe_summary


def _log_drive_mount_safe_warning(
    message: str,
    *,
    phase: str,
    mount_point: str,
    raw_error: object,
    returncode: int | None = None,
) -> None:
    failure_category, failure_summary = _classify_drive_mount_failure(raw_error, phase=phase)
    extra = {
        "failure_category": failure_category,
        "failure_summary": failure_summary,
        "mount_phase": phase,
        "mount_slot": os.path.basename(mount_point.rstrip("/")),
    }
    if returncode is not None:
        extra["returncode"] = returncode
    logger.warning(message, extra=extra)


def _log_drive_mount_debug_failure(
    message: str,
    *,
    device_path: str,
    mount_point: str,
    returncode: int | None = None,
    raw_error: object = None,
) -> None:
    raw_text = "" if raw_error is None else str(raw_error).strip()
    if not raw_text:
        raw_text = "(empty)"

    if returncode is None:
        logger.debug(
            "%s: device_path=%s mount_point=%s raw_error=%s",
            message,
            device_path,
            mount_point,
            raw_text,
        )
        return

    logger.debug(
        "%s: device_path=%s mount_point=%s returncode=%s raw_error=%s",
        message,
        device_path,
        mount_point,
        returncode,
        raw_text,
    )


def _with_sudo(cmd: list[str]) -> list[str]:
    if settings.use_sudo and os.geteuid() != 0:
        return ["sudo", "-n", *cmd]
    return cmd


def _with_mount_namespace_flag(cmd: list[str]) -> list[str] | None:
    if not cmd:
        return None

    binary = os.path.basename(cmd[0])
    if binary in ("mount", "umount"):
        return [cmd[0], "-N", "/proc/1/ns/mnt", *cmd[1:]]
    return None


def _in_host_mount_namespace() -> bool:
    return shares_host_mount_namespace(
        on_self_read_error=True,
        on_host_read_error=False,
        on_host_read_error_callback=lambda _exc: logger.warning(
            "Unable to read host mount namespace; assuming namespace differs"
        ),
    )


def _with_host_mount_namespace(cmd: list[str]) -> list[str]:
    if _in_host_mount_namespace():
        return _with_sudo(cmd)

    nsenter = shutil.which("nsenter")
    if nsenter:
        if os.geteuid() != 0:
            if not settings.use_sudo:
                logger.warning("Mount namespace differs from host but sudo is disabled; using current namespace")
                return cmd
            return ["sudo", "-n", nsenter, "-t", "1", "-m", *cmd]

        return [nsenter, "-t", "1", "-m", *cmd]

    ns_flag_cmd = _with_mount_namespace_flag(cmd)
    if ns_flag_cmd is not None:
        logger.warning("Mount namespace differs from host and nsenter is unavailable; falling back to util-linux namespace flag")
        return _with_sudo(ns_flag_cmd)

    logger.warning("Mount namespace differs from host but no namespace helper is available; using current namespace")
    return _with_sudo(cmd)


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


def _service_owner_spec() -> str:
    """Return the current service account as ``user:group`` for chown."""
    uid = os.geteuid()
    gid = os.getegid()
    try:
        user = pwd.getpwuid(uid).pw_name
    except Exception:
        user = str(uid)
    try:
        group = grp.getgrgid(gid).gr_name
    except Exception:
        group = str(gid)
    return f"{user}:{group}"


def _mount_options_for_filesystem(device_path: str) -> list[str]:
    """Return extra mount arguments for filesystems that need explicit ownership."""
    detected_fs = LinuxFilesystemDetector().detect(device_path)
    if detected_fs in {"exfat", "vfat", "fat", "fat32", "msdos", "ntfs", "ntfs3"}:
        uid = os.geteuid()
        gid = os.getegid()
        return ["-o", f"uid={uid},gid={gid},umask=022"]
    return []


def _ensure_mount_point_writable(mount_point: str) -> tuple[bool, str | None]:
    """Best-effort ownership repair so the service account can write to the mount."""
    required_mode = os.W_OK | os.X_OK
    if os.access(mount_point, required_mode):
        return True, None

    try:
        if settings.use_sudo and os.geteuid() != 0:
            subprocess.run(
                _with_sudo(["chown", _service_owner_spec(), mount_point]),
                check=True,
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
        else:
            os.chown(mount_point, os.geteuid(), os.getegid())
    except subprocess.TimeoutExpired:
        return False, f"mount succeeded but access repair timed out after {settings.subprocess_timeout_seconds}s"
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode(errors="replace").strip()
        if stderr:
            return False, f"mount succeeded but access repair failed: {stderr}"
        return False, "mount succeeded but access repair failed"
    except OSError as exc:
        return False, f"mount succeeded but access repair failed: {exc}"

    if os.access(mount_point, required_mode):
        return True, None
    return False, f"mount succeeded but target {mount_point} is not writable by the ECUBE service account"


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
            _log_drive_mount_safe_warning(
                "Drive mount root preparation failed",
                phase="mount_root_prepare",
                mount_point=mount_point,
                raw_error=exc,
            )
            _log_drive_mount_debug_failure(
                "Drive mount root preparation details",
                device_path=mountable,
                mount_point=mount_point,
                raw_error=exc,
            )
            return False, f"failed to create mount point {mount_point}: {exc}"

        mount_command = [
            settings.mount_binary_path,
            *_mount_options_for_filesystem(mountable),
            mountable,
            mount_point,
        ]
        mount_timeout_seconds = settings.drive_mount_timeout_seconds

        try:
            subprocess.run(
                _with_host_mount_namespace(mount_command),
                check=True,
                capture_output=True,
                timeout=mount_timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            _log_drive_mount_safe_warning(
                "Drive mount timed out",
                phase="mount_timeout",
                mount_point=mount_point,
                raw_error=f"mount timed out after {mount_timeout_seconds}s",
            )
            _log_drive_mount_debug_failure(
                "Drive mount timeout details",
                device_path=mountable,
                mount_point=mount_point,
                raw_error=f"mount timed out after {mount_timeout_seconds}s",
            )
            return False, f"mount timed out after {mount_timeout_seconds}s"
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            _log_drive_mount_safe_warning(
                "Drive mount command failed",
                phase="mount_command",
                mount_point=mount_point,
                raw_error=stderr or exc,
                returncode=exc.returncode,
            )
            _log_drive_mount_debug_failure(
                "Drive mount raw error",
                device_path=mountable,
                mount_point=mount_point,
                returncode=exc.returncode,
                raw_error=stderr or exc,
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
            _log_drive_mount_safe_warning(
                "Drive mount OS error",
                phase="mount_os_error",
                mount_point=mount_point,
                raw_error=exc,
            )
            _log_drive_mount_debug_failure(
                "Drive mount OS error details",
                device_path=mountable,
                mount_point=mount_point,
                raw_error=exc,
            )
            return False, f"mount error: {exc}"

        writable, access_error = _ensure_mount_point_writable(mount_point)
        if not writable:
            cleanup_ok, cleanup_error = self.unmount_drive(mount_point)
            _log_drive_mount_safe_warning(
                "Drive mount access repair failed",
                phase="mount_access_repair",
                mount_point=mount_point,
                raw_error=(
                    f"access_error={access_error or 'mount target is not writable'}; "
                    f"cleanup_error={cleanup_error or ''}"
                ),
            )
            _log_drive_mount_debug_failure(
                "Drive mount access repair details",
                device_path=mountable,
                mount_point=mount_point,
                raw_error=(
                    f"access_error={access_error or 'mount target is not writable'}; "
                    f"cleanup_error={cleanup_error or ''}"
                ),
            )
            detail = access_error or "mount target is not writable by the ECUBE service account"
            if not cleanup_ok and cleanup_error:
                detail += f"; cleanup failed: {cleanup_error}"
            return False, detail

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
                _with_host_mount_namespace([settings.umount_binary_path, mount_point]),
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
