"""Unit tests for app.infrastructure.drive_eject module."""
from unittest.mock import patch, mock_open, call
import subprocess

from app.infrastructure.drive_eject import _find_device_mountpoints, unmount_device


class TestFindDeviceMountpoints:
    """Tests for partition discovery and mounting detection."""

    def test_find_traditional_partitions(self):
        """Correctly identify traditional partition naming (sdb1, sdb2)."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/sdb /media/usb ext4 rw 0 0
/dev/sdb1 /media/usb1 ext4 rw 0 0
/dev/sdb2 /media/usb2 ext4 rw 0 0
/dev/sdc1 /media/other ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("sdb")

        assert "/media/usb" in result
        assert "/media/usb1" in result
        assert "/media/usb2" in result
        assert "/media/other" not in result
        assert len(result) == 3

    def test_find_nvme_partitions(self):
        """Correctly identify NVMe partition naming (nvme0n1p1, nvme0n1p2)."""
        proc_mounts_content = """/dev/nvme0n1 /media/nvme ext4 rw 0 0
/dev/nvme0n1p1 /media/nvme1 ext4 rw 0 0
/dev/nvme0n1p2 /media/nvme2 ext4 rw 0 0
/dev/nvme1n1p1 /media/other ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("nvme0n1")

        assert "/media/nvme" in result
        assert "/media/nvme1" in result
        assert "/media/nvme2" in result
        assert "/media/other" not in result
        assert len(result) == 3

    def test_find_mmc_partitions(self):
        """Correctly identify MMC partition naming (mmcblk0p1, mmcblk0p2)."""
        proc_mounts_content = """/dev/mmcblk0 /media/mmc ext4 rw 0 0
/dev/mmcblk0p1 /media/mmc1 ext4 rw 0 0
/dev/mmcblk0p2 /media/mmc2 ext4 rw 0 0
/dev/mmcblk1p1 /media/other ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("mmcblk0")

        assert "/media/mmc" in result
        assert "/media/mmc1" in result
        assert "/media/mmc2" in result
        assert "/media/other" not in result
        assert len(result) == 3

    def test_device_not_mounted(self):
        """Return empty list when device has no mountpoints."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/sdb1 /media/other ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("sdc")

        assert result == []

    def test_base_device_only(self):
        """Correctly identify only base device when no partitions mounted."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/sdb /media/usb ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("sdb")

        assert result == ["/media/usb"]

    def test_proc_mounts_read_error(self):
        """Return empty list if /proc/mounts cannot be read."""
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result = _find_device_mountpoints("sdb")

        assert result == []

    def test_reject_invalid_partition_suffixes(self):
        """Do not match invalid partition suffixes (e.g., p, p-1, pXa)."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/sdbp /media/invalid1 ext4 rw 0 0
/dev/sdbp-1 /media/invalid2 ext4 rw 0 0
/dev/sdbpXa /media/invalid3 ext4 rw 0 0
/dev/sdba /media/invalid4 ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("sdb")

        # Only the base device should match
        assert result == ["/media/usb"]

    def test_mixed_naming_schemes(self):
        """Handle multiple naming schemes in same /proc/mounts."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/sdb1 /media/usb1 ext4 rw 0 0
/dev/nvme0n1 /media/nvme ext4 rw 0 0
/dev/nvme0n1p1 /media/nvme1 ext4 rw 0 0
/dev/mmcblk0 /media/mmc ext4 rw 0 0
/dev/mmcblk0p1 /media/mmc1 ext4 rw 0 0
"""
        # Test traditional naming
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("sdb")
        assert set(result) == {"/media/usb", "/media/usb1"}

        # Test NVMe naming
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("nvme0n1")
        assert set(result) == {"/media/nvme", "/media/nvme1"}

        # Test MMC naming
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result = _find_device_mountpoints("mmcblk0")
        assert set(result) == {"/media/mmc", "/media/mmc1"}


class TestUnmountDevice:
    """Tests for unmount_device function: partition discovery + unmount execution."""

    def test_unmount_traditional_partitions(self):
        """Successfully unmount traditional partitions (sdb, sdb1, sdb2)."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/sdb1 /media/usb1 ext4 rw 0 0
/dev/sdb2 /media/usb2 ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/sdb")

        assert success is True
        assert error is None
        # Verify unmount was called for all three mountpoints
        assert mock_run.call_count == 3
        called_mounts = {call_args[0][0][1] for call_args in mock_run.call_args_list}
        assert called_mounts == {"/media/usb", "/media/usb1", "/media/usb2"}

    def test_unmount_nvme_partitions(self):
        """Successfully unmount NVMe partitions (nvme0n1, nvme0n1p1, nvme0n1p2)."""
        proc_mounts_content = """/dev/nvme0n1 /media/nvme ext4 rw 0 0
/dev/nvme0n1p1 /media/nvme1 ext4 rw 0 0
/dev/nvme0n1p2 /media/nvme2 ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/nvme0n1")

        assert success is True
        assert error is None
        # Verify unmount was called for all three mountpoints
        assert mock_run.call_count == 3
        called_mounts = {call_args[0][0][1] for call_args in mock_run.call_args_list}
        assert called_mounts == {"/media/nvme", "/media/nvme1", "/media/nvme2"}

    def test_unmount_mmc_partitions(self):
        """Successfully unmount MMC partitions (mmcblk0, mmcblk0p1, mmcblk0p2)."""
        proc_mounts_content = """/dev/mmcblk0 /media/mmc ext4 rw 0 0
/dev/mmcblk0p1 /media/mmc1 ext4 rw 0 0
/dev/mmcblk0p2 /media/mmc2 ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/mmcblk0")

        assert success is True
        assert error is None
        # Verify unmount was called for all three mountpoints
        assert mock_run.call_count == 3
        called_mounts = {call_args[0][0][1] for call_args in mock_run.call_args_list}
        assert called_mounts == {"/media/mmc", "/media/mmc1", "/media/mmc2"}

    def test_unmount_nothing_mounted(self):
        """Return success (no-op) when device has no mounted partitions."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/other /media/other ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/sdb")

        assert success is True
        assert error is None
        # No unmount calls should be made
        mock_run.assert_not_called()

    def test_unmount_proc_mounts_read_failure(self):
        """Return success when /proc/mounts cannot be read (graceful no-op)."""
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/sdb")

        # Should treat unreadable /proc/mounts as "nothing mounted" (success)
        assert success is True
        assert error is None
        # No unmount calls should be made
        mock_run.assert_not_called()

    def test_unmount_single_unmount_failure(self):
        """Return failure if one partition fails to unmount."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/sdb1 /media/usb1 ext4 rw 0 0
"""
        def subprocess_side_effect(*args, **kwargs):
            # First call (umount /media/usb) succeeds
            if args[0][1] == "/media/usb":
                return None
            # Second call (umount /media/usb1) fails
            raise subprocess.CalledProcessError(1, "umount", stderr=b"Device busy\n")

        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run", side_effect=subprocess_side_effect) as mock_run:
                success, error = unmount_device("/dev/sdb")

        assert success is False
        assert error is not None
        assert "umount failed for /media/usb1" in error
        assert "Device busy" in error
        # Both unmount calls should have been attempted
        assert mock_run.call_count == 2

    def test_unmount_multiple_failures(self):
        """Return aggregated error when multiple partitions fail to unmount."""
        proc_mounts_content = """/dev/sdb1 /media/usb1 ext4 rw 0 0
/dev/sdb2 /media/usb2 ext4 rw 0 0
"""
        def subprocess_side_effect(*args, **kwargs):
            # Both calls fail
            mount_point = args[0][1]
            raise subprocess.CalledProcessError(1, "umount", stderr=f"Error at {mount_point}\n".encode())

        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run", side_effect=subprocess_side_effect):
                success, error = unmount_device("/dev/sdb")

        assert success is False
        assert error is not None
        # Both errors should be in the aggregated message, separated by semicolon
        assert "umount failed for /media/usb1" in error
        assert "umount failed for /media/usb2" in error
        assert "; " in error  # Errors should be joined with semicolon-space

    def test_unmount_timeout(self):
        """Return failure if unmount times out."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("umount", 30)):
                success, error = unmount_device("/dev/sdb")

        assert success is False
        assert error is not None
        assert "timed out" in error.lower()

    def test_unmount_invalid_device_path(self):
        """Return failure for invalid device paths without attempting unmount."""
        with patch("subprocess.run") as mock_run:
            success, error = unmount_device("/tmp/../../etc/passwd")

        # Should fail validation without calling subprocess
        assert success is False
        assert "invalid device path" in error
        mock_run.assert_not_called()

    def test_unmount_invalid_device_path_no_slash(self):
        """Return failure for device paths missing /dev/ prefix."""
        with patch("subprocess.run") as mock_run:
            success, error = unmount_device("sdb")

        assert success is False
        assert "invalid device path" in error
        mock_run.assert_not_called()

    def test_unmount_only_base_device_mounted(self):
        """Successfully unmount when only base device (no partitions) is mounted."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/sdb")

        assert success is True
        assert error is None
        mock_run.assert_called_once()
        mock_run.assert_called_with(
            ["/bin/umount", "/media/usb"],
            check=True,
            capture_output=True,
            timeout=30,
        )

