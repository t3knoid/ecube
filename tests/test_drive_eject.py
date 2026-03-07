"""Unit tests for app.infrastructure.drive_eject module."""
from unittest.mock import patch, mock_open
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
            result, error = _find_device_mountpoints("sdb")

        assert error is None
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
            result, error = _find_device_mountpoints("nvme0n1")

        assert error is None
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
            result, error = _find_device_mountpoints("mmcblk0")

        assert error is None
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
            result, error = _find_device_mountpoints("sdc")

        assert error is None
        assert result == []

    def test_base_device_only(self):
        """Correctly identify only base device when no partitions mounted."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/sdb /media/usb ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result, error = _find_device_mountpoints("sdb")

        assert error is None
        assert result == ["/media/usb"]

    def test_proc_mounts_read_error(self):
        """Return error if /proc/mounts cannot be read."""
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result, error = _find_device_mountpoints("sdb")

        assert error is not None
        assert "could not read /proc/mounts" in error
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
            result, error = _find_device_mountpoints("sdb")

        assert error is None
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
            result, error = _find_device_mountpoints("sdb")
        assert error is None
        assert set(result) == {"/media/usb", "/media/usb1"}

        # Test NVMe naming
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result, error = _find_device_mountpoints("nvme0n1")
        assert error is None
        assert set(result) == {"/media/nvme", "/media/nvme1"}

        # Test MMC naming
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result, error = _find_device_mountpoints("mmcblk0")
        assert error is None
        assert set(result) == {"/media/mmc", "/media/mmc1"}

    def test_unescape_mountpoint_with_spaces(self):
        """Correctly unescape mountpoints with escaped spaces from /proc/mounts."""
        from app.infrastructure.drive_eject import _unescape_mountpoint
        
        # /proc/mounts encodes spaces as \040
        escaped_path = "/media/my\\040files"
        result = _unescape_mountpoint(escaped_path)
        assert result == "/media/my files"

    def test_unescape_mountpoint_with_tabs(self):
        """Correctly unescape mountpoints with escaped tabs from /proc/mounts."""
        from app.infrastructure.drive_eject import _unescape_mountpoint
        
        # /proc/mounts encodes tabs as \011
        escaped_path = "/media/usb\\011backup"
        result = _unescape_mountpoint(escaped_path)
        assert result == "/media/usb\tbackup"

    def test_unescape_mountpoint_multiple_escapes(self):
        """Correctly unescape mountpoints with multiple escape sequences."""
        from app.infrastructure.drive_eject import _unescape_mountpoint
        
        # Multiple escapes: space, newline (as literal \n), etc.
        escaped_path = "/mnt/my\\040files\\011here"
        result = _unescape_mountpoint(escaped_path)
        assert result == "/mnt/my files\there"

    def test_unescape_mountpoint_no_escapes(self):
        """Mountpoint with no escapes should remain unchanged."""
        from app.infrastructure.drive_eject import _unescape_mountpoint
        
        path = "/media/usb"
        result = _unescape_mountpoint(path)
        assert result == "/media/usb"

    def test_unescape_mountpoint_utf8_non_ascii(self):
        """Correctly decode multi-byte UTF-8 sequences encoded as octal escapes.

        /proc/mounts encodes raw filesystem bytes as POSIX octal escapes.
        A UTF-8 path like ``/mnt/café`` (where ``é`` is the two-byte sequence
        0xC3 0xA9) appears in /proc/mounts as ``/mnt/caf\\303\\251``.
        The bytes-first decoding must reconstruct the original UTF-8 string;
        the old ``unicode_escape`` codec would produce mojibake (``cafÃ©``).
        """
        from app.infrastructure.drive_eject import _unescape_mountpoint

        # UTF-8 bytes for 'é' are 0xC3 0xA9 → octal \303 \251
        escaped_path = "/mnt/caf\\303\\251"
        result = _unescape_mountpoint(escaped_path)
        assert result == "/mnt/café"

    def test_find_device_with_escaped_mountpoint(self):
        """Parse /proc/mounts correctly when mountpoints have escapes."""
        # Simulate /proc/mounts with path containing space
        proc_mounts_content = """/dev/sdb /media/my\\040usb ext4 rw 0 0
/dev/sdb1 /media/usb\\011sub ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            result, error = _find_device_mountpoints("sdb")
        
        assert error is None
        # Results should be unescaped
        assert "/media/my usb" in result  # space unescaped
        assert "/media/usb\tsub" in result  # tab unescaped
        assert len(result) == 2


class TestResolveMapperDevice:
    """Tests for device-mapper resolution (LUKS, LVM, dm devices)."""

    def test_resolve_luks_mapper_device(self):
        """Resolve LUKS mapper device back to parent block device via sysfs."""
        from app.infrastructure.drive_eject import _resolve_mapper_device_to_parent
        
        def mock_realpath(path):
            # Simulate /dev/mapper/* → /dev/dm-N symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_XXXXX":
                return "/dev/dm-0"  # symlink to dm-0
            return path
        
        def mock_isdir(path):
            # After normalization, sysfs path is /sys/block/dm-0/slaves
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdb"]  # dm-0 is backed by sdb
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
            with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                    result = _resolve_mapper_device_to_parent("/dev/mapper/crypto_XXXXX")
        
        assert result == ["sdb"]

    def test_resolve_lvm_mapper_device(self):
        """Resolve LVM mapper device back to parent block device."""
        from app.infrastructure.drive_eject import _resolve_mapper_device_to_parent
        
        def mock_realpath(path):
            # Simulate /dev/mapper/vg0-lv0 → /dev/dm-1 symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/vg0-lv0":
                return "/dev/dm-1"  # symlink to dm-1
            return path
        
        def mock_isdir(path):
            # After normalization, sysfs path is /sys/block/dm-1/slaves
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-1/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-1/slaves":
                return ["sdc"]  # dm-1 is backed by sdc
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
            with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                    result = _resolve_mapper_device_to_parent("/dev/mapper/vg0-lv0")
        
        assert result == ["sdc"]

    def test_resolve_dm_device(self):
        """Resolve /dev/dm-N style device back to parent block device."""
        from app.infrastructure.drive_eject import _resolve_mapper_device_to_parent
        
        def mock_realpath(path):
            # Already a /dev/dm-N path, no resolution needed
            return path
        
        def mock_isdir(path):
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdb"]
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
            with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                    result = _resolve_mapper_device_to_parent("/dev/dm-0")
        
        assert result == ["sdb"]

    def test_resolve_mapper_device_not_found(self):
        """Return empty list when sysfs slaves directory doesn't exist."""
        from app.infrastructure.drive_eject import _resolve_mapper_device_to_parent
        
        import app.infrastructure.drive_eject as drive_eject_module

        def mock_realpath(path):
            # Simulate /dev/mapper/unknown resolving to a /dev/dm-N device
            return "/dev/dm-9"

        with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
            with patch.object(drive_eject_module.os.path, "isdir", return_value=False):
                result = _resolve_mapper_device_to_parent("/dev/mapper/unknown")
        
        assert result == []

    def test_resolve_mapper_device_listdir_fails(self):
        """Return empty list when sysfs listdir fails."""
        from app.infrastructure.drive_eject import _resolve_mapper_device_to_parent

        def mock_realpath(path):
            # Simulate /dev/mapper/* → /dev/dm-N symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_X":
                return "/dev/dm-0"
            return path

        def mock_isdir(path):
            # Pretend the slaves directory exists for dm-0
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"

        def mock_listdir(path):
            # Simulate a failure when listing the slaves directory
            raise OSError("Permission denied")

        import app.infrastructure.drive_eject as drive_eject_module
        with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
            with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                    result = _resolve_mapper_device_to_parent("/dev/mapper/crypto_X")
        assert result == []

    def test_find_luks_mounted_partition(self):
        """Correctly identify LUKS-encrypted partition mounted via mapper."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/mapper/crypto_sdb /media/encrypted ext4 rw 0 0
/dev/sdb1 /media/unencrypted ext4 rw 0 0
"""
        def mock_realpath(path):
            # Simulate /dev/mapper/* → /dev/dm-N symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_sdb":
                return "/dev/dm-0"  # symlink to dm-0
            return path
        
        def mock_isdir(path):
            # After normalization, sysfs path is /sys/block/dm-0/slaves
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdb"]  # LUKS device is backed by sdb
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        result, error = _find_device_mountpoints("sdb")
        
        assert error is None
        # Should find both the LUKS mount and the partition mount
        assert "/media/encrypted" in result
        assert "/media/unencrypted" in result
        assert len(result) == 2

    def test_find_lvm_logical_volume(self):
        """Correctly identify LVM logical volumes backed by the device."""
        proc_mounts_content = """/dev/sda1 / ext4 rw 0 0
/dev/mapper/vg0-data /mnt/data ext4 rw 0 0
/dev/mapper/vg0-backup /mnt/backup ext4 rw 0 0
/dev/sdb1 /media/direct ext4 rw 0 0
"""
        def mock_realpath(path):
            # Simulate /dev/mapper/* → /dev/dm-N symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/vg0-data":
                return "/dev/dm-1"  # symlink to dm-1
            if path == "/dev/mapper/vg0-backup":
                return "/dev/dm-2"  # symlink to dm-2
            return path
        
        def mock_isdir(path):
            # After normalization, sysfs paths are /sys/block/dm-N/slaves
            path = path.replace("\\", "/")
            return path in ["/sys/block/dm-1/slaves", "/sys/block/dm-2/slaves"]
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-1/slaves":
                return ["sdb"]  # dm-1 is backed by sdb
            if path == "/sys/block/dm-2/slaves":
                return ["sdb"]  # dm-2 is also backed by sdb (same VG)
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        result, error = _find_device_mountpoints("sdb")
        
        assert error is None
        assert set(result) == {"/mnt/data", "/mnt/backup", "/media/direct"}

    def test_mapper_device_backed_by_different_device(self):
        """Ignore mapper devices that are backed by a different block device."""
        proc_mounts_content = """/dev/mapper/crypto_sdc /media/encrypted ext4 rw 0 0
/dev/sdb /media/usb ext4 rw 0 0
"""
        def mock_realpath(path):
            # Simulate /dev/mapper/crypto_sdc → /dev/dm-0 symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_sdc":
                return "/dev/dm-0"  # symlink to dm-0
            return path
        
        def mock_isdir(path):
            # After normalization, sysfs path is /sys/block/dm-0/slaves
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdc"]  # backed by sdc, NOT sdb
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        result, error = _find_device_mountpoints("sdb")
        
        assert error is None
        # Should only find the direct device mount, not the LUKS mount backed by sdc
        assert result == ["/media/usb"]

    def test_unmount_with_mapper_device(self):
        """Successfully unmount device including mapper device mounts."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/mapper/crypto_sdb /media/encrypted ext4 rw 0 0
"""
        
        def mock_realpath(path):
            # Simulate /dev/mapper/crypto_sdb → /dev/dm-0 symlink resolution
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_sdb":
                return "/dev/dm-0"  # symlink to dm-0
            return path
        
        def mock_isdir(path):
            # After normalization, sysfs path is /sys/block/dm-0/slaves
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdb"]
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        with patch("subprocess.run") as mock_run:
                            success, error = unmount_device("/dev/sdb")
        
        assert success is True
        assert error is None
        # Verify both mount points were unmounted
        assert mock_run.call_count == 2
        called_mounts = {call_args[0][0][1] for call_args in mock_run.call_args_list}
        assert called_mounts == {"/media/usb", "/media/encrypted"}

    def test_find_mapper_device_backed_by_traditional_partition(self):
        """Discover mapper devices backed by partitions (e.g., LUKS on /dev/sdb1)."""
        proc_mounts_content = """/dev/sdb1 /media/data ext4 rw 0 0
/dev/mapper/crypto_sdb1 /media/encrypted ext4 rw 0 0
"""
        def mock_realpath(path):
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_sdb1":
                return "/dev/dm-0"
            return path
        
        def mock_isdir(path):
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdb1"]  # mapper backed by partition, not base device
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        result, error = _find_device_mountpoints("sdb")
        
        assert error is None
        # Both partition and mapper mount should be discovered
        assert set(result) == {"/media/data", "/media/encrypted"}

    def test_find_mapper_device_backed_by_nvme_partition(self):
        """Discover mapper devices backed by NVMe partitions (e.g., LUKS on /dev/nvme0n1p1)."""
        proc_mounts_content = """/dev/nvme0n1p1 /media/data ext4 rw 0 0
/dev/mapper/luks_nvme0n1p1 /media/encrypted ext4 rw 0 0
"""
        def mock_realpath(path):
            path = path.replace("\\", "/")
            if path == "/dev/mapper/luks_nvme0n1p1":
                return "/dev/dm-1"
            return path
        
        def mock_isdir(path):
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-1/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-1/slaves":
                return ["nvme0n1p1"]  # NVMe partition as dm slave
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        result, error = _find_device_mountpoints("nvme0n1")
        
        assert error is None
        # Both partition and mapper mount should be discovered
        assert set(result) == {"/media/data", "/media/encrypted"}

    def test_find_mapper_partition_ignores_different_device(self):
        """Do not pick up mapper devices backed by partitions of a different device."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/mapper/crypto_sdc1 /media/encrypted ext4 rw 0 0
"""
        def mock_realpath(path):
            path = path.replace("\\", "/")
            if path == "/dev/mapper/crypto_sdc1":
                return "/dev/dm-0"
            return path
        
        def mock_isdir(path):
            path = path.replace("\\", "/")
            return path == "/sys/block/dm-0/slaves"
        
        def mock_listdir(path):
            path = path.replace("\\", "/")
            if path == "/sys/block/dm-0/slaves":
                return ["sdc1"]  # backed by sdc1, not sdb or sdb1
            return []
        
        import app.infrastructure.drive_eject as drive_eject_module
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch.object(drive_eject_module.os.path, "realpath", side_effect=mock_realpath):
                with patch.object(drive_eject_module.os.path, "isdir", side_effect=mock_isdir):
                    with patch.object(drive_eject_module.os, "listdir", side_effect=mock_listdir):
                        result, error = _find_device_mountpoints("sdb")
        
        assert error is None
        # Should only find the direct device mount, not the mapper mount backed by sdc1
        assert result == ["/media/usb"]


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
        """Return failure when /proc/mounts cannot be read (error propagation)."""
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/sdb")

        # Should propagate the read error
        assert success is False
        assert error is not None
        assert "could not read /proc/mounts" in error
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

    def test_unmount_not_mounted_race_is_success(self):
        """CalledProcessError with 'not mounted' stderr is treated as success.

        If a mount disappears between the /proc/mounts read and the actual
        umount call (transient race), umount exits non-zero with a 'not
        mounted' message.  That condition already represents the desired
        end-state, so it should be treated as a no-op rather than a failure.
        """
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    32, "umount", stderr=b"umount: /media/usb: not mounted.\n"
                ),
            ):
                success, error = unmount_device("/dev/sdb")

        assert success is True
        assert error is None

    def test_unmount_no_mount_point_race_is_success(self):
        """CalledProcessError with 'no mount point' stderr is treated as success."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    1, "umount", stderr=b"umount: /media/usb: no mount point specified.\n"
                ),
            ):
                success, error = unmount_device("/dev/sdb")

        assert success is True
        assert error is None

    def test_unmount_nested_mounts_deepest_first(self):
        """Unmount nested mounts in correct order (deepest first) to avoid 'target is busy' errors."""
        proc_mounts_content = """/dev/sdb /media/usb ext4 rw 0 0
/dev/sdb1 /media/usb/sub ext4 rw 0 0
/dev/sdb2 /media/usb/sub/deep ext4 rw 0 0
"""
        with patch("builtins.open", mock_open(read_data=proc_mounts_content)):
            with patch("subprocess.run") as mock_run:
                success, error = unmount_device("/dev/sdb")

        assert success is True
        assert error is None
        assert mock_run.call_count == 3
        
        # Verify unmount calls were made in order of deepest-first
        # Extracting mount points from the calls in order
        unmount_order = [call_args[0][0][1] for call_args in mock_run.call_args_list]
        
        # Deepest paths should be unmounted first
        # /media/usb/sub/deep has depth 4, /media/usb/sub has depth 3, /media/usb has depth 2
        assert unmount_order[0] == "/media/usb/sub/deep"  # deepest: /media/usb/sub/deep
        assert unmount_order[1] == "/media/usb/sub"       # middle: /media/usb/sub
        assert unmount_order[2] == "/media/usb"           # parent: /media/usb

