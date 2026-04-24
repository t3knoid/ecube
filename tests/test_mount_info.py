from unittest.mock import mock_open, patch

import app.infrastructure.mount_info as mount_info


def test_read_mount_table_unescapes_sources_and_mount_points(monkeypatch):
    monkeypatch.setattr(mount_info.settings, "procfs_mounts_path", "/proc/test-mounts")
    proc_mounts = (
        "/dev/sda1 /mnt/system ext4 rw 0 0\n"
        "server:/team\\040share /nfs/team\\040share nfs rw 0 0\n"
        "/dev/disk/by-id/usb-1 /mnt/caf\\303\\251 vfat rw 0 0\n"
    )

    with patch("builtins.open", mock_open(read_data=proc_mounts)):
        result = mount_info.read_mount_table()

    assert result == {
        "/mnt/system": "/dev/sda1",
        "/nfs/team share": "server:/team share",
        "/mnt/café": "/dev/disk/by-id/usb-1",
    }


def test_read_mount_table_returns_empty_dict_on_oserror(monkeypatch):
    monkeypatch.setattr(mount_info.settings, "procfs_mounts_path", "/proc/test-mounts")

    with patch("builtins.open", side_effect=OSError("unavailable")):
        result = mount_info.read_mount_table()

    assert result == {}


def test_read_mount_points_filters_non_device_sources(monkeypatch):
    monkeypatch.setattr(
        mount_info,
        "read_mount_table",
        lambda: {
            "/mnt/ecube/7": "/dev/sdb1",
            "/nfs/team": "server:/export",
            "/mnt/ecube/8": "/dev/disk/by-id/usb-2",
        },
    )

    result = mount_info.read_mount_points()

    assert result == {
        "/dev/sdb1": "/mnt/ecube/7",
        "/dev/disk/by-id/usb-2": "/mnt/ecube/8",
    }


def test_find_device_mount_point_matches_realpath_target(monkeypatch):
    monkeypatch.setattr(
        mount_info,
        "read_mount_points",
        lambda: {"/dev/disk/by-id/usb-drive": "/mnt/ecube/7"},
    )

    def fake_realpath(path: str) -> str:
        mapping = {
            "/dev/disk/by-id/usb-drive": "/dev/sdb1",
            "/dev/sdb1": "/dev/sdb1",
        }
        return mapping.get(path, path)

    monkeypatch.setattr(mount_info.os.path, "realpath", fake_realpath)

    assert mount_info.find_device_mount_point("/dev/sdb1") == "/mnt/ecube/7"


def test_find_device_mount_point_falls_back_when_realpath_raises(monkeypatch):
    monkeypatch.setattr(
        mount_info,
        "read_mount_points",
        lambda: {"/dev/sdb1": "/mnt/ecube/8"},
    )

    def fake_realpath(path: str) -> str:
        raise OSError(f"cannot resolve {path}")

    monkeypatch.setattr(mount_info.os.path, "realpath", fake_realpath)

    assert mount_info.find_device_mount_point("/dev/sdb1") == "/mnt/ecube/8"


def test_find_device_mount_point_returns_none_when_device_not_found(monkeypatch):
    monkeypatch.setattr(mount_info, "read_mount_points", lambda: {"/dev/sdb1": "/mnt/ecube/8"})

    assert mount_info.find_device_mount_point("/dev/sdz1") is None