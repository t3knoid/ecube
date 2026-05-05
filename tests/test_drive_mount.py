"""Unit tests for LinuxDriveMount.mount_drive() mount-point validation.

These tests exercise the path-safety checks (absolute, direct-child of
usb_mount_base_path) without actually calling mount(8).
"""

import logging
import subprocess

from unittest.mock import patch

from app.infrastructure.drive_mount import LinuxDriveMount


# A valid device path that passes validate_device_path()
_VALID_DEVICE = "/dev/sdb"

# The base path that settings.usb_mount_base_path resolves to in tests.
_BASE = "/mnt/ecube"


def _mount(mount_point: str) -> tuple[bool, str | None]:
    """Call mount_drive with patched settings so we only test path validation."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        # realpath of _BASE is itself (no symlinks in test)
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                return dm.mount_drive(_VALID_DEVICE, mount_point)


def test_mount_drive_rejects_relative_path():
    """A relative mount point should be rejected."""
    ok, err = _mount("mnt/ecube/7")
    assert ok is False
    assert "absolute path" in err


def test_mount_drive_rejects_path_outside_base():
    """A path that is not under usb_mount_base_path should be rejected."""
    ok, err = _mount("/tmp/evil")
    assert ok is False
    assert "direct child" in err


def test_mount_drive_rejects_nested_path_under_base():
    """A deeply nested path under base (e.g. /mnt/ecube/a/b) should be rejected."""
    ok, err = _mount(f"{_BASE}/a/b")
    assert ok is False
    assert "direct child" in err


def test_mount_drive_accepts_direct_child_of_base():
    """A direct child of the base path should pass validation."""
    # Patch makedirs and subprocess so we don't actually mount.
    with patch("os.makedirs"):
        with patch("os.access", return_value=True):
            with patch("subprocess.run"):
                ok, err = _mount(f"{_BASE}/7")
    assert ok is True
    assert err is None


def test_unmount_drive_rejects_path_outside_base():
    """Unmount must also be restricted to managed direct-child mount points."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.umount_binary_path = "/bin/umount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        with patch("os.path.realpath", side_effect=lambda p: p):
            ok, err = dm.unmount_drive("/tmp/evil")
    assert ok is False
    assert "direct child" in err


def test_unmount_drive_accepts_direct_child_of_base():
    """A managed direct child under the base path can be safely unmounted."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.umount_binary_path = "/bin/umount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("subprocess.run"):
                ok, err = dm.unmount_drive(f"{_BASE}/7")
    assert ok is True
    assert err is None


def test_mount_drive_uses_service_uid_gid_options_for_exfat_media():
    """exFAT-style media should be mounted with service ownership options."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("app.infrastructure.drive_mount.LinuxFilesystemDetector.detect", return_value="exfat"):
                    with patch("os.makedirs"):
                        with patch("os.geteuid", return_value=1234):
                            with patch("os.getegid", return_value=5678):
                                with patch("os.access", return_value=True):
                                    with patch("subprocess.run") as mock_run:
                                        ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is True
    assert err is None
    mount_call = mock_run.call_args_list[0].args[0]
    assert "-o" in mount_call
    options = mount_call[mount_call.index("-o") + 1]
    assert "uid=1234" in options
    assert "gid=5678" in options
    assert "umask=022" in options


def test_mount_drive_uses_mount_namespace_flag_when_mount_namespace_differs():
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = True
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("app.infrastructure.drive_mount.LinuxFilesystemDetector.detect", return_value="ext4"):
                    with patch("os.readlink", side_effect=["mnt:[2]", "mnt:[1]"]):
                        with patch("os.makedirs"):
                            with patch("os.geteuid", return_value=1000):
                                with patch("os.access", return_value=True):
                                    with patch("subprocess.run") as mock_run:
                                        ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is True
    assert err is None
    mount_call = mock_run.call_args_list[0].args[0]
    assert mount_call[:5] == ["sudo", "-n", "/bin/mount", "-N", "/proc/1/ns/mnt"]


def test_unmount_drive_uses_mount_namespace_flag_when_mount_namespace_differs():
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.umount_binary_path = "/bin/umount"
        mock_settings.use_sudo = True
        mock_settings.subprocess_timeout_seconds = 10
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("os.readlink", side_effect=["mnt:[2]", "mnt:[1]"]):
                with patch("os.geteuid", return_value=1000):
                    with patch("subprocess.run") as mock_run:
                        ok, err = dm.unmount_drive(f"{_BASE}/7")

    assert ok is True
    assert err is None
    mount_call = mock_run.call_args_list[0].args[0]
    assert mount_call[:5] == ["sudo", "-n", "/bin/umount", "-N", "/proc/1/ns/mnt"]


def test_mount_drive_repairs_mount_point_access_for_service_user():
    """Successful mounts should repair access so the service account can write to the target."""
    dm = LinuxDriveMount()
    access_results = iter([False, True])

    def fake_access(path, mode):
        if path == f"{_BASE}/7" and mode == 3:
            return next(access_results)
        return True

    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = True
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("app.infrastructure.drive_mount.LinuxFilesystemDetector.detect", return_value="ext4"):
                    with patch("os.makedirs"):
                        with patch("os.geteuid", return_value=1234):
                            with patch("os.getegid", return_value=5678):
                                with patch("os.access", side_effect=fake_access):
                                    with patch("subprocess.run") as mock_run:
                                        ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is True
    assert err is None
    assert mock_run.call_count >= 2
    repair_calls = [call.args[0] for call in mock_run.call_args_list if call.args and call.args[0][:3] == ["sudo", "-n", "chown"]]
    assert repair_calls
    assert repair_calls[0][-1] == f"{_BASE}/7"


def test_mount_drive_fails_when_mount_point_remains_unwritable():
    """Mount should fail fast when the mounted target is still not writable after repair."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = True
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("os.makedirs"):
                    with patch("os.geteuid", return_value=1234):
                        with patch("os.getegid", return_value=5678):
                            with patch("os.access", return_value=False):
                                with patch("subprocess.run"):
                                    ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is False
    assert "not writable" in err


def test_mount_drive_logs_raw_debug_error(caplog):
    """Warning logs should stay sanitized while debug logs retain the raw helper error text."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("app.infrastructure.drive_mount.LinuxFilesystemDetector.detect", return_value="ext4"):
                    with patch("os.makedirs"):
                        with patch(
                            "subprocess.run",
                            side_effect=subprocess.CalledProcessError(
                                returncode=32,
                                cmd=["/bin/mount"],
                                stderr=b"mount: unknown filesystem type 'exfat' while mounting /mnt/ecube/7",
                            ),
                        ):
                            with caplog.at_level("DEBUG"):
                                ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is False
    assert "unknown filesystem type" in (err or "")
    warning_records = [record for record in caplog.records if record.levelno == logging.WARNING]
    debug_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG]

    assert any(record.getMessage() == "Drive mount command failed" for record in warning_records)
    assert any(getattr(record, "failure_category", None) == "missing_filesystem_runtime" for record in warning_records)
    assert any(getattr(record, "failure_summary", None) == "Filesystem type is not supported by the host" for record in warning_records)
    assert all("/dev/sdb" not in record.getMessage() for record in warning_records)
    assert all("/mnt/ecube/7" not in record.getMessage() for record in warning_records)
    assert any(
        "Drive mount raw error" in message
        and "/dev/sdb" in message
        and "/mnt/ecube/7" in message
        and "unknown filesystem type 'exfat' while mounting /mnt/ecube/7" in message
        for message in debug_messages
    )


def test_mount_drive_logs_managed_mount_root_failure_with_safe_warning(caplog):
    """Mount-root preparation failures should log a safe normal-level classification and raw debug detail."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("os.makedirs", side_effect=PermissionError("[Errno 13] Permission denied: '/mnt/ecube/7'")):
                    with caplog.at_level("DEBUG"):
                        ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is False
    assert "failed to create mount point" in (err or "")
    warning_records = [record for record in caplog.records if record.levelno == logging.WARNING]
    debug_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG]

    assert any(record.getMessage() == "Drive mount root preparation failed" for record in warning_records)
    assert any(getattr(record, "failure_category", None) == "managed_mount_root_inaccessible" for record in warning_records)
    assert any(getattr(record, "failure_summary", None) == "Permission or authentication failure" for record in warning_records)
    assert any("Drive mount root preparation details" in message and "/mnt/ecube/7" in message for message in debug_messages)


def test_mount_drive_logs_access_repair_failure_with_safe_warning(caplog):
    """Post-mount access repair failures should be classifiable without leaking raw details at warning level."""
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = True
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("os.makedirs"):
                    with patch("os.geteuid", return_value=1234):
                        with patch("os.getegid", return_value=5678):
                            with patch("os.access", return_value=False):
                                with patch("subprocess.run"):
                                    with caplog.at_level("DEBUG"):
                                        ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is False
    assert "not writable" in (err or "")
    warning_records = [record for record in caplog.records if record.levelno == logging.WARNING]
    debug_messages = [record.getMessage() for record in caplog.records if record.levelno == logging.DEBUG]

    assert any(record.getMessage() == "Drive mount access repair failed" for record in warning_records)
    assert any(getattr(record, "failure_category", None) == "post_mount_access_repair_failure" for record in warning_records)
    assert any("Drive mount access repair details" in message and "/mnt/ecube/7" in message for message in debug_messages)


def test_mount_drive_uses_dedicated_mount_timeout():
    dm = LinuxDriveMount()
    with patch("app.infrastructure.drive_mount.settings") as mock_settings:
        mock_settings.usb_mount_base_path = _BASE
        mock_settings.sysfs_block_path = "/sys/block"
        mock_settings.mount_binary_path = "/bin/mount"
        mock_settings.use_sudo = False
        mock_settings.subprocess_timeout_seconds = 10
        mock_settings.drive_mount_timeout_seconds = 45
        mock_settings.procfs_mounts_path = "/proc/mounts"
        with patch("os.path.realpath", side_effect=lambda p: p):
            with patch("app.infrastructure.drive_mount.validate_device_path", return_value=True):
                with patch("app.infrastructure.drive_mount.LinuxFilesystemDetector.detect", return_value="exfat"):
                    with patch("os.makedirs"):
                        with patch("os.access", return_value=True):
                            with patch(
                                "subprocess.run",
                                side_effect=subprocess.TimeoutExpired(cmd=["/bin/mount"], timeout=45),
                            ):
                                ok, err = dm.mount_drive(_VALID_DEVICE, f"{_BASE}/7")

    assert ok is False
    assert err == "mount timed out after 45s"
