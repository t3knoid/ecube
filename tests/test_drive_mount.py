"""Unit tests for LinuxDriveMount.mount_drive() mount-point validation.

These tests exercise the path-safety checks (absolute, direct-child of
usb_mount_base_path) without actually calling mount(8).
"""

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
    # Patch makedirs and subprocess so we don't actually mount
    with patch("os.makedirs"):
        with patch("subprocess.run"):
            ok, err = _mount(f"{_BASE}/7")
    assert ok is True
    assert err is None
