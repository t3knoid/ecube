from unittest.mock import MagicMock, patch

import pytest

from app.models.network import MountStatus, MountType, NetworkMount
from app.config import settings
from app.services.mount_check_utils import check_mounted_with_configured_timeout
from app.services.mount_service import (
    LinuxMountProvider,
    _cleanup_generated_mount_directory,
    _ensure_mount_directory,
    validate_mount,
)


def test_list_mounts_empty(client, db):
    response = client.get("/mounts")
    assert response.status_code == 200
    assert response.json() == []


def test_add_mount(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.1:/exports/evidence",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "NFS"
    assert data["local_mount_point"] == "/nfs/evidence"
    assert data["status"] == "MOUNTED"


def test_add_mount_rejects_client_local_mount_point(manager_client, db):
    response = manager_client.post(
        "/mounts",
        json={
            "type": "NFS",
            "remote_path": "192.168.1.1:/exports/evidence",
            "local_mount_point": "/mnt/should-not-be-allowed",
        },
    )
    assert response.status_code == 422


def test_add_mount_logs_attempt_and_success(manager_client, db, caplog):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with caplog.at_level("INFO"):
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.1.2:/exports/audit",
                },
            )

    assert response.status_code == 200
    messages = [r.getMessage() for r in caplog.records]
    assert any("Mount attempt started" in m for m in messages)
    assert any("Mount attempt succeeded" in m for m in messages)


def test_add_mount_uses_unique_generated_local_mount_point(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.1.1:/exports/evidence"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.1.2:/exports/evidence"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["local_mount_point"] == "/nfs/evidence"
    assert second.json()["local_mount_point"] == "/nfs/evidence-2"


def test_add_mount_failure(manager_client, db):
    from app.models.audit import AuditLog

    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="mount.nfs: access denied by server while mounting 192.168.1.1:/exports/evidence on /nfs/evidence",
            stdout="",
        )
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.1:/exports/evidence",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ERROR"

    audit = db.query(AuditLog).filter(AuditLog.action == "MOUNT_ADDED").first()
    assert audit is not None
    assert audit.details["error_code"] == "MOUNT_FAILED"
    assert audit.details["message"] == "Provider mount operation failed"
    assert "/nfs/evidence" not in str(audit.details)


def test_add_mount_fails_when_mountpoint_owned_by_root(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch(
             "app.services.mount_service._validate_mount_directory_owner",
             return_value="local mount point directory is owned by root; it must be owned by the ECUBE service account",
         ), \
         patch("subprocess.run") as mock_run:
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.1:/exports/evidence",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ERROR"
    mock_run.assert_not_called()


def test_add_mount_logs_failure(manager_client, db, caplog):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Permission denied", stdout="")
        with caplog.at_level("INFO"):
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.1.3:/exports/audit",
                },
            )

    assert response.status_code == 200
    messages = [r.getMessage() for r in caplog.records]
    assert any("Mount attempt started" in m for m in messages)
    assert any("Mount attempt failed" in m for m in messages)


def test_list_mounts(client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    response = client.get("/mounts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["local_mount_point"] == "/mnt/data"


def test_delete_mount(manager_client, db):
    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//192.168.1.1/share",
        local_mount_point="/mnt/share",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()
    mount_id = mount.id

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.delete(f"/mounts/{mount_id}")
    assert response.status_code == 204


def test_delete_mount_removes_generated_mount_directory(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/share",
        local_mount_point="/nfs/share",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    with patch("subprocess.run") as mock_run, patch("os.rmdir") as mock_rmdir:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 204
    mock_rmdir.assert_called_once_with("/nfs/share")


def test_delete_mount_does_not_remove_legacy_mount_directory(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/share",
        local_mount_point="/mnt/share",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    with patch("subprocess.run") as mock_run, patch("os.rmdir") as mock_rmdir:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 204
    mock_rmdir.assert_not_called()


def test_delete_mount_does_not_remove_nested_managed_path(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/share",
        local_mount_point="/nfs/team/music",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    with patch("subprocess.run") as mock_run, patch("os.rmdir") as mock_rmdir:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 204
    mock_rmdir.assert_not_called()


def test_cleanup_generated_mount_directory_does_not_use_sudo(monkeypatch):
    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("app.services.mount_service.os.rmdir", side_effect=PermissionError("denied")), \
         patch("subprocess.run") as mock_run:
        _cleanup_generated_mount_directory("/nfs/share")

    mock_run.assert_not_called()


def test_ensure_mount_directory_uses_sudo_mkdir_and_chown_for_managed_paths(monkeypatch):
    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)
    monkeypatch.setattr("app.services.mount_service.os.getegid", lambda: 1000)

    with patch("app.services.mount_service.os.makedirs", side_effect=PermissionError("denied")), \
         patch("app.services.mount_service.pwd.getpwuid") as mock_getpwuid, \
         patch("app.services.mount_service.grp.getgrgid") as mock_getgrgid, \
         patch("subprocess.run") as mock_run:
        mock_getpwuid.return_value = type("U", (), {"pw_name": "ecube"})()
        mock_getgrgid.return_value = type("G", (), {"gr_name": "ecube"})()
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr="", stdout=""),
            MagicMock(returncode=0, stderr="", stdout=""),
        ]

        err = _ensure_mount_directory("/nfs/music")

    assert err is None
    first_cmd = mock_run.call_args_list[0].args[0]
    second_cmd = mock_run.call_args_list[1].args[0]
    assert first_cmd == ["sudo", "-n", "mkdir", "-p", "/nfs", "/nfs/music"]
    assert second_cmd == ["sudo", "-n", "chown", "ecube:ecube", "/nfs", "/nfs/music"]


def test_delete_mount_not_found(manager_client, db):
    response = manager_client.delete("/mounts/999")
    assert response.status_code == 404


def test_delete_mount_returns_conflict_when_unmount_fails(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/share",
        local_mount_point="/mnt/share",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="target is busy", stdout="")
        response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 409
    assert db.get(NetworkMount, mount.id) is not None


def test_delete_unmounted_mount_skips_os_unmount_and_removes_record(manager_client, db):
    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//server/share",
        local_mount_point="/smb/project2",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()

    provider = MagicMock()

    with patch("app.services.mount_service._default_provider", return_value=provider):
        response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 204
    provider.os_unmount.assert_not_called()
    assert db.get(NetworkMount, mount.id) is None


def test_delete_mount_treats_not_mounted_error_as_success(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/share",
        local_mount_point="/mnt/share",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    provider = MagicMock()
    provider.check_mounted.return_value = None
    provider.os_unmount.return_value = (False, "umount: /mnt/share: not mounted")

    with patch("app.services.mount_service._default_provider", return_value=provider):
        response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 204
    provider.os_unmount.assert_called_once_with("/mnt/share")
    assert db.get(NetworkMount, mount.id) is None


def test_validate_mount_success(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()
    mount_id = mount.id

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(f"/mounts/{mount_id}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "MOUNTED"
    assert data["last_checked_at"] is not None
    # Sensitive credentials must not be present in the response
    assert "username" not in data
    assert "password" not in data
    assert "credentials_file" not in data


def test_validate_mount_unmounted(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()
    mount_id = mount.id

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        response = manager_client.post(f"/mounts/{mount_id}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UNMOUNTED"
    assert data["last_checked_at"] is not None


def test_validate_mount_command_failure(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()
    mount_id = mount.id

    with patch("subprocess.run", side_effect=Exception("command not found")):
        response = manager_client.post(f"/mounts/{mount_id}/validate")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ERROR"
    assert data["last_checked_at"] is not None


def test_validate_mount_not_found(manager_client, db):
    response = manager_client.post("/mounts/999/validate")
    assert response.status_code == 404


def test_validate_all_mounts(manager_client, db):
    for i in range(3):
        db.add(
            NetworkMount(
                type=MountType.NFS,
                remote_path=f"192.168.1.1:/data{i}",
                local_mount_point=f"/mnt/data{i}",
                status=MountStatus.UNMOUNTED,
            )
        )
    db.commit()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post("/mounts/validate")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    for item in data:
        assert item["status"] == "MOUNTED"
        assert item["last_checked_at"] is not None


def test_validate_all_mounts_empty(manager_client, db):
    response = manager_client.post("/mounts/validate")

    assert response.status_code == 200
    assert response.json() == []


def test_linux_mount_provider_check_mounted_uses_configured_default_timeout():
    provider = LinuxMountProvider()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        mounted = provider.check_mounted("/mnt/data")

    assert mounted is True
    assert mock_run.call_args.kwargs["timeout"] == settings.subprocess_timeout_seconds


def test_linux_mount_provider_uses_sudo_for_mount_when_configured(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/mnt/music",
        )

    assert ok is True
    assert err is None
    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:2] == ["sudo", "-n"]


def test_linux_mount_provider_treats_returncode_zero_with_inactive_mountpoint_as_failure():
    provider = LinuxMountProvider()

    with patch("subprocess.run") as mock_run, patch.object(provider, "check_mounted", return_value=False):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/nfs/music",
        )

    assert ok is False
    assert "not active" in (err or "")


def test_linux_mount_provider_uses_mount_namespace_flag_when_mount_namespace_differs(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("app.services.mount_service.os.readlink", side_effect=["mnt:[2]", "mnt:[1]"]), \
         patch("subprocess.run") as mock_run, \
         patch.object(provider, "check_mounted", return_value=True):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/nfs/music",
        )

    assert ok is True
    assert err is None
    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:5] == ["sudo", "-n", "/bin/mount", "-N", "/proc/1/ns/mnt"]


def test_check_mounted_uses_mount_namespace_flag_when_mount_namespace_differs(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    mount_output = "server:/export on /nfs/music type nfs4 (rw,relatime)\n"

    with patch("app.services.mount_service.os.readlink", side_effect=["mnt:[2]", "mnt:[1]"]), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=mount_output, stderr="")

        mounted = provider.check_mounted("/nfs/music")

    assert mounted is True
    cmd = mock_run.call_args.args[0]
    assert cmd[:5] == ["sudo", "-n", "/bin/mount", "-N", "/proc/1/ns/mnt"]


def test_linux_mount_provider_uses_mount_namespace_flag_when_host_namespace_read_fails(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("app.services.mount_service.os.readlink", side_effect=["mnt:[2]", PermissionError("denied")]), \
         patch("subprocess.run") as mock_run, \
         patch.object(provider, "check_mounted", return_value=True):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        ok, err = provider.os_mount(
            MountType.SMB,
            "//192.168.2.250/music",
            "/smb/music",
        )

    assert ok is True
    assert err is None
    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:5] == ["sudo", "-n", "/bin/mount", "-N", "/proc/1/ns/mnt"]


def test_linux_mount_provider_uses_direct_helper_on_fstab_option_failure():
    provider = LinuxMountProvider()

    first = MagicMock(returncode=32, stderr="mount.nfs: failed to apply fstab options", stdout="")
    second = MagicMock(returncode=0, stderr="", stdout="")

    with patch("app.services.mount_service._resolve_mount_nfs_binary", return_value="/sbin/mount.nfs"), \
         patch("subprocess.run", side_effect=[first, second]) as mock_run:
        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/mnt/music",
        )

    assert ok is True
    assert err is None
    assert mock_run.call_count == 2
    direct_cmd = mock_run.call_args_list[1].args[0]
    assert "/sbin/mount.nfs" in direct_cmd


def test_linux_mount_provider_returns_retry_error_when_fstab_retry_fails():
    provider = LinuxMountProvider()

    first = MagicMock(returncode=32, stderr="mount.nfs: failed to apply fstab options", stdout="")
    second = MagicMock(returncode=1, stderr="mount.nfs: access denied by server", stdout="")

    with patch("app.services.mount_service._resolve_mount_nfs_binary", return_value=None), \
         patch("subprocess.run", side_effect=[first, second]):
        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/mnt/music",
        )

    assert ok is False
    assert "failed to apply fstab options" in (err or "")


def test_linux_mount_provider_uses_direct_nfs_helper_after_fstab_failures():
    provider = LinuxMountProvider()

    first = MagicMock(returncode=32, stderr="mount.nfs: failed to apply fstab options", stdout="")
    second = MagicMock(returncode=0, stderr="", stdout="")

    with patch("app.services.mount_service._resolve_mount_nfs_binary", return_value="/sbin/mount.nfs"), \
         patch("subprocess.run", side_effect=[first, second]) as mock_run:
        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/mnt/music",
        )

    assert ok is True
    assert err is None
    assert mock_run.call_count == 2
    direct_cmd = mock_run.call_args_list[1].args[0]
    assert "/sbin/mount.nfs" in direct_cmd


def test_linux_mount_provider_treats_active_mountpoint_as_success_after_failures():
    provider = LinuxMountProvider()

    first = MagicMock(returncode=32, stderr="mount.nfs: failed to apply fstab options", stdout="")
    second = MagicMock(returncode=1, stderr="still failing", stdout="")

    with patch("app.services.mount_service._resolve_mount_nfs_binary", return_value="/sbin/mount.nfs"), \
         patch("subprocess.run", side_effect=[first, second]), \
         patch.object(provider, "check_mounted", return_value=True):
        ok, err = provider.os_mount(
            MountType.NFS,
            "192.168.2.250:/mnt/Data/music",
            "/mnt/music",
        )

    assert ok is True
    assert err is None


def test_linux_mount_provider_check_mounted_non_positive_timeout_uses_default():
    provider = LinuxMountProvider()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        mounted = provider.check_mounted("/mnt/data", timeout_seconds=0)

    assert mounted is True
    assert mock_run.call_args.kwargs["timeout"] == settings.subprocess_timeout_seconds


def test_validate_mount_passes_configured_timeout_to_provider(db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data-timeout",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()

    class TimeoutCapturingProvider:
        def __init__(self):
            self.timeout_seconds = None

        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            self.timeout_seconds = timeout_seconds
            return True

    provider = TimeoutCapturingProvider()
    updated = validate_mount(mount.id, db, provider=provider)

    assert updated.status == MountStatus.MOUNTED
    assert provider.timeout_seconds == settings.subprocess_timeout_seconds


def test_check_mounted_with_configured_timeout_does_not_mask_provider_type_error():
    class BrokenProvider:
        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            raise TypeError("provider internal type mismatch")

    provider = BrokenProvider()

    with pytest.raises(TypeError, match="provider internal type mismatch"):
        check_mounted_with_configured_timeout(provider, "/mnt/data")


def test_check_mounted_with_configured_timeout_caches_capability(monkeypatch):
    """Verify capability check is only done once per provider instance."""
    import app.services.mount_check_utils as utils_module

    call_count = [0]
    original_check = utils_module._check_accepts_timeout_seconds

    def counting_check(provider):
        call_count[0] += 1
        return original_check(provider)

    monkeypatch.setattr(utils_module, "_check_accepts_timeout_seconds", counting_check)

    class CachingTestProvider:
        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            return True

    provider = CachingTestProvider()

    call_count[0] = 0
    utils_module.check_mounted_with_configured_timeout(provider, "/mnt/1")
    first_call_count = call_count[0]
    assert first_call_count == 1, "First call should invoke _check_accepts_timeout_seconds"

    utils_module.check_mounted_with_configured_timeout(provider, "/mnt/2")
    second_call_count = call_count[0]
    assert second_call_count == 1, "Second call should use cached result, not re-inspect"


def test_check_mounted_with_configured_timeout_gracefully_handles_signature_inspection_failure(monkeypatch):
    """If inspect.signature fails, provider is treated as not supporting timeout_seconds."""
    import app.services.mount_check_utils as utils_module

    class InspectFailureProvider:
        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            return True

    provider = InspectFailureProvider()

    call_count = [0]

    def _raising_signature(_):
        call_count[0] += 1
        raise ValueError("signature unavailable")

    monkeypatch.setattr(utils_module.inspect, "signature", _raising_signature)

    # This should not raise; instead it should call without timeout_seconds
    result = utils_module.check_mounted_with_configured_timeout(provider, "/mnt/data")
    assert result is True
    assert call_count[0] == 1

    # Verify the capability was cached as False (conservative fallback)
    cached = getattr(provider, utils_module._SUPPORTS_TIMEOUT_SECONDS_ATTR, None)
    assert cached is False

