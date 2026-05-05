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


def test_read_mount_table_prefers_host_mounts_when_namespace_differs(monkeypatch):
    monkeypatch.setattr(mount_info.settings, "procfs_mounts_path", "/proc/mounts")

    def fake_readlink(path: str) -> str:
        mapping = {
            "/proc/self/ns/mnt": "mnt:[4026534000]",
            "/proc/1/ns/mnt": "mnt:[4026531840]",
        }
        return mapping[path]

    opened_paths = []

    def fake_open(path, *args, **kwargs):
        opened_paths.append(path)
        return mock_open(read_data="/dev/sdb1 /mnt/ecube/7 ext4 rw 0 0\n")()

    monkeypatch.setattr(mount_info.os, "readlink", fake_readlink)

    with patch("builtins.open", side_effect=fake_open):
        result = mount_info.read_mount_table()

    assert result == {"/mnt/ecube/7": "/dev/sdb1"}
    assert opened_paths == ["/proc/1/mounts"]


def test_read_mount_table_prefers_host_mounts_when_host_namespace_probe_fails(monkeypatch, caplog):
    monkeypatch.setattr(mount_info.settings, "procfs_mounts_path", "/proc/mounts")
    monkeypatch.setattr(mount_info, "_host_namespace_probe_warning_emitted", False)

    def fake_readlink(path: str) -> str:
        if path == "/proc/self/ns/mnt":
            return "mnt:[4026534000]"
        if path == "/proc/1/ns/mnt":
            raise OSError("permission denied")
        raise AssertionError(f"unexpected path {path}")

    opened_paths = []

    def fake_open(path, *args, **kwargs):
        opened_paths.append(path)
        return mock_open(read_data="/dev/sdc /mnt/ecube/8 exfat rw 0 0\n")()

    monkeypatch.setattr(mount_info.os, "readlink", fake_readlink)

    with caplog.at_level("WARNING"):
        with patch("builtins.open", side_effect=fake_open):
            result = mount_info.read_mount_table()

    assert result == {"/mnt/ecube/8": "/dev/sdc"}
    assert opened_paths == ["/proc/1/mounts"]
    assert any(
        record.getMessage() == "Unable to read host mount namespace; assuming namespace differs"
        for record in caplog.records
    )


def test_read_mount_table_logs_host_namespace_probe_failure_only_once(monkeypatch, caplog):
    monkeypatch.setattr(mount_info.settings, "procfs_mounts_path", "/proc/mounts")
    monkeypatch.setattr(mount_info, "_host_namespace_probe_warning_emitted", False)

    def fake_readlink(path: str) -> str:
        if path == "/proc/self/ns/mnt":
            return "mnt:[4026534000]"
        if path == "/proc/1/ns/mnt":
            raise OSError("permission denied")
        raise AssertionError(f"unexpected path {path}")

    def fake_open(path, *args, **kwargs):
        return mock_open(read_data="/dev/sdc /mnt/ecube/8 exfat rw 0 0\n")()

    monkeypatch.setattr(mount_info.os, "readlink", fake_readlink)

    with caplog.at_level("DEBUG"):
        with patch("builtins.open", side_effect=fake_open):
            first = mount_info.read_mount_table()
            second = mount_info.read_mount_table()

    assert first == {"/mnt/ecube/8": "/dev/sdc"}
    assert second == {"/mnt/ecube/8": "/dev/sdc"}
    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING"
    ]
    debug_messages = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "DEBUG"
    ]
    assert warning_messages.count("Unable to read host mount namespace; assuming namespace differs") == 1
    assert debug_messages.count(
        "Unable to read host mount namespace; continuing with host mount table fallback"
    ) == 1


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


def test_is_active_mount_point_matches_normalized_mount_root(monkeypatch):
    monkeypatch.setattr(
        mount_info,
        "read_mount_table",
        lambda: {"/mnt/ecube/7": "/dev/sdb1"},
    )

    assert mount_info.is_active_mount_point("/mnt/ecube/7/") is True
    assert mount_info.is_active_mount_point("/mnt/ecube/8") is False