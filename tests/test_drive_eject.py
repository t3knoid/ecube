"""Unit tests for app.infrastructure.drive_eject module."""
from unittest.mock import patch, mock_open

from app.infrastructure.drive_eject import _find_device_mountpoints


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
