import subprocess
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.network import MountStatus, MountType, NetworkMount
from app.config import settings
from app.schemas.network import MountUpdate
from app.services.mount_check_utils import check_mounted_with_configured_timeout
from app.services.mount_service import (
    LinuxMountProvider,
    _cleanup_generated_mount_directory,
    _ensure_mount_directory,
    sanitize_error_message,
    validate_mount_candidate,
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
                "project_id": "PROJ-001",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "NFS"
    assert data["project_id"] == "PROJ-001"
    assert data["nfs_client_version"] is None
    assert data["local_mount_point"] == "/nfs/evidence"
    assert data["status"] == "MOUNTED"


def test_add_mount_uses_nfs_v4_1_to_avoid_slow_negotiation(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.20.240:/volume1/demo-case-001",
                "project_id": "PROJ-NFS41",
            },
        )

    assert response.status_code == 200
    first_call = mock_run.call_args_list[0]
    assert first_call.args[0][:5] == [
        "sudo",
        "-n",
        settings.mount_binary_path,
        "-t",
        "nfs",
    ] or first_call.args[0][:9] == [
        "sudo",
        "-n",
        "/usr/bin/nsenter",
        "-t",
        "1",
        "-m",
        settings.mount_binary_path,
        "-t",
        "nfs",
    ]
    assert "vers=4.1" in first_call.args[0]

    mount = db.query(NetworkMount).filter(NetworkMount.project_id == "PROJ-NFS41").one()
    assert mount.nfs_client_version is None


def test_add_mount_persists_requested_nfs_client_version(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.20.240:/volume1/demo-case-001",
                "project_id": "PROJ-NFS42",
                "nfs_client_version": "4.2",
            },
        )

    assert response.status_code == 200
    assert response.json()["nfs_client_version"] == "4.2"
    mount = db.query(NetworkMount).filter(NetworkMount.project_id == "PROJ-NFS42").one()
    assert mount.nfs_client_version == "4.2"
    assert "vers=4.2" in mock_run.call_args_list[0].args[0]


def test_add_mount_persists_credentials_encrypted(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={
                "type": "SMB",
                "remote_path": "//server/secured-share",
                "project_id": "PROJ-SECURE",
                "username": "svc-reader",
                "password": "super-secret",
                "credentials_file": "/etc/ecube/mount.creds",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "username" not in data
    assert "password" not in data
    assert "credentials_file" not in data

    db.expire_all()
    mount = db.query(NetworkMount).filter(NetworkMount.id == data["id"]).one()
    assert mount.encrypted_username
    assert mount.encrypted_password
    assert mount.encrypted_credentials_file
    assert mount.encrypted_username != "svc-reader"
    assert mount.encrypted_password != "super-secret"
    assert mount.encrypted_credentials_file != "/etc/ecube/mount.creds"


def test_add_mount_requires_project_id(manager_client, db):
    response = manager_client.post(
        "/mounts",
        json={
            "type": "NFS",
            "remote_path": "192.168.1.1:/exports/evidence",
        },
    )

    assert response.status_code == 422


def test_update_mount_updates_existing_record_without_creating_new_one(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.10:/exports/original",
        project_id="PROJ-OLD",
        local_mount_point="/nfs/original",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()
    mount_id = mount.id

    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.patch(
            f"/mounts/{mount_id}",
            json={
                "type": "SMB",
                "remote_path": "//server/updated-share",
                "project_id": "proj-new",
                "username": "updated-user",
                "password": "updated-pass",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == mount_id
    assert data["type"] == "SMB"
    assert data["remote_path"] == "//server/updated-share"
    assert data["project_id"] == "PROJ-NEW"
    assert data["local_mount_point"] == "/nfs/original"
    assert data["status"] == "MOUNTED"

    db.expire_all()
    mounts = db.query(NetworkMount).order_by(NetworkMount.id).all()
    assert len(mounts) == 1
    assert mounts[0].id == mount_id
    assert mounts[0].project_id == "PROJ-NEW"


def test_update_mount_rejects_conflicting_remote_path(manager_client, db):
    existing = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.20:/exports/existing",
        project_id="PROJ-EXISTING",
        local_mount_point="/nfs/existing",
        status=MountStatus.UNMOUNTED,
    )
    target = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.21:/exports/target",
        project_id="PROJ-TARGET",
        local_mount_point="/nfs/target",
        status=MountStatus.UNMOUNTED,
    )
    db.add_all([existing, target])
    db.commit()

    response = manager_client.patch(
        f"/mounts/{target.id}",
        json={
            "type": "NFS",
            "remote_path": "192.168.1.20:/exports/existing",
            "project_id": "PROJ-TARGET",
        },
    )

    assert response.status_code == 409
    assert "already configured" in response.json()["message"].lower()


def test_update_mount_not_found(manager_client, db):
    response = manager_client.patch(
        "/mounts/999",
        json={
            "type": "NFS",
            "remote_path": "192.168.1.22:/exports/missing",
            "project_id": "PROJ-MISSING",
        },
    )

    assert response.status_code == 404


def test_update_mount_preserves_existing_credentials_when_not_resubmitted(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        created = manager_client.post(
            "/mounts",
            json={
                "type": "SMB",
                "remote_path": "//server/original-share",
                "project_id": "PROJ-ORIGINAL",
                "username": "svc-reader",
                "password": "super-secret",
            },
        )

        assert created.status_code == 200
        mount_id = created.json()["id"]

        original = db.query(NetworkMount).filter(NetworkMount.id == mount_id).one()
        original_encrypted_username = original.encrypted_username
        original_encrypted_password = original.encrypted_password

        updated = manager_client.patch(
            f"/mounts/{mount_id}",
            json={
                "type": "SMB",
                "remote_path": "//server/updated-share",
                "project_id": "PROJ-UPDATED",
            },
        )

    assert updated.status_code == 200

    db.expire_all()
    saved = db.query(NetworkMount).filter(NetworkMount.id == mount_id).one()
    assert saved.encrypted_username == original_encrypted_username
    assert saved.encrypted_password == original_encrypted_password


def test_update_mount_api_remounts_live_nfs_share_with_new_client_version(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.10:/exports/original",
        project_id="PROJ-OLD",
        local_mount_point="/nfs/original",
        status=MountStatus.MOUNTED,
        nfs_client_version="4.1",
    )
    db.add(mount)
    db.commit()

    class StatefulProvider:
        def __init__(self):
            self.mount_calls = []
            self.unmount_calls = []

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.mount_calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                    "nfs_client_version": nfs_client_version,
                }
            )
            return True, None

        def os_unmount(self, local_mount_point: str):
            self.unmount_calls.append(local_mount_point)
            return True, None

    provider = StatefulProvider()

    with patch("app.services.mount_service._default_provider", return_value=provider), \
         patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        response = manager_client.patch(
            f"/mounts/{mount.id}",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.10:/exports/updated",
                "project_id": "proj-new",
                "nfs_client_version": "4.2",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == mount.id
    assert data["type"] == "NFS"
    assert data["remote_path"] == "192.168.1.10:/exports/updated"
    assert data["project_id"] == "PROJ-NEW"
    assert data["nfs_client_version"] == "4.2"
    assert data["status"] == "MOUNTED"

    db.expire_all()
    saved = db.query(NetworkMount).filter(NetworkMount.id == mount.id).one()
    assert saved.remote_path == "192.168.1.10:/exports/updated"
    assert saved.project_id == "PROJ-NEW"
    assert saved.nfs_client_version == "4.2"
    assert saved.status == MountStatus.MOUNTED

    assert provider.unmount_calls == ["/nfs/original"]
    assert provider.mount_calls == [
        {
            "mount_type": MountType.NFS,
            "remote_path": "192.168.1.10:/exports/updated",
            "local_mount_point": "/nfs/original",
            "credentials_file": None,
            "username": None,
            "password": None,
            "nfs_client_version": "4.2",
        }
    ]


def test_update_mount_uses_stored_credentials_when_not_resubmitted(db):
    from app.schemas.network import MountUpdate
    from app.services import mount_service

    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//server/original-share",
        project_id="PROJ-ORIGINAL",
        local_mount_point="/smb/original-share",
        status=MountStatus.UNMOUNTED,
        encrypted_username="gAAAAABmocked-user",
        encrypted_password="gAAAAABmocked-pass",
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                }
            )
            return True, None

    provider = FakeProvider()

    with patch("app.services.mount_service.decrypt_mount_secret", side_effect=["svc-reader", "super-secret", None]), \
         patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        result = mount_service.update_mount(
            mount.id,
            MountUpdate(
                type=MountType.SMB,
                remote_path="//server/updated-share",
                project_id="PROJ-UPDATED",
            ),
            db,
            provider=provider,
        )

    assert result.status == MountStatus.MOUNTED
    assert provider.calls == [
        {
            "mount_type": MountType.SMB,
            "remote_path": "//server/updated-share",
            "local_mount_point": "/smb/original-share",
            "credentials_file": None,
            "username": "svc-reader",
            "password": "super-secret",
        }
    ]


def test_update_mount_remounts_live_nfs_share_with_new_client_version(db):
    from app.schemas.network import MountUpdate
    from app.services import mount_service

    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.10:/exports/original",
        project_id="PROJ-ORIGINAL",
        local_mount_point="/nfs/original",
        status=MountStatus.MOUNTED,
        nfs_client_version="4.1",
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)

    class StatefulProvider:
        def __init__(self):
            self.mount_calls = []
            self.unmount_calls = []

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.mount_calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                    "nfs_client_version": nfs_client_version,
                }
            )
            return True, None

        def os_unmount(self, local_mount_point: str):
            self.unmount_calls.append(local_mount_point)
            return True, None

    provider = StatefulProvider()

    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        result = mount_service.update_mount(
            mount.id,
            MountUpdate(
                type=MountType.NFS,
                remote_path="192.168.1.10:/exports/updated",
                project_id="PROJ-UPDATED",
                nfs_client_version="4.2",
            ),
            db,
            provider=provider,
        )

    assert result.status == MountStatus.MOUNTED
    assert result.remote_path == "192.168.1.10:/exports/updated"
    assert result.project_id == "PROJ-UPDATED"
    assert result.nfs_client_version == "4.2"
    assert provider.unmount_calls == ["/nfs/original"]
    assert provider.mount_calls == [
        {
            "mount_type": MountType.NFS,
            "remote_path": "192.168.1.10:/exports/updated",
            "local_mount_point": "/nfs/original",
            "credentials_file": None,
            "username": None,
            "password": None,
            "nfs_client_version": "4.2",
        }
    ]


def test_validate_mount_uses_stored_credentials_when_share_is_not_active(db):
    from app.services import mount_service

    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//server/validate-share",
        project_id="PROJ-VALIDATE",
        local_mount_point="/smb/validate-share",
        status=MountStatus.UNMOUNTED,
        encrypted_username="gAAAAABmocked-user",
        encrypted_password="gAAAAABmocked-pass",
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                }
            )
            return True, None

    provider = FakeProvider()

    with patch("app.services.mount_service.decrypt_mount_secret", side_effect=["svc-reader", "super-secret", None]), \
         patch("app.services.mount_service.check_mounted_with_configured_timeout", return_value=False), \
         patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        result = mount_service.validate_mount(mount.id, db, provider=provider)

    assert result.status == MountStatus.MOUNTED
    assert provider.calls == [
        {
            "mount_type": MountType.SMB,
            "remote_path": "//server/validate-share",
            "local_mount_point": "/smb/validate-share",
            "credentials_file": None,
            "username": "svc-reader",
            "password": "super-secret",
        }
    ]


def test_update_mount_requires_admin_or_manager(auditor_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.23:/exports/protected",
        project_id="PROJ-PROTECTED",
        local_mount_point="/nfs/protected",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()

    response = auditor_client.patch(
        f"/mounts/{mount.id}",
        json={
            "type": "NFS",
            "remote_path": "192.168.1.23:/exports/protected-updated",
            "project_id": "PROJ-PROTECTED",
        },
    )

    assert response.status_code == 403


def test_add_mount_normalizes_project_id(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.1:/exports/normalized",
                "project_id": "  proj-001  ",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == "PROJ-001"


def test_network_mount_model_normalizes_project_id(db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.9:/exports/direct-model",
        project_id="  proj-model  ",
        local_mount_point="/nfs/direct-model",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)

    assert mount.project_id == "PROJ-MODEL"


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
                    "project_id": "PROJ-AUDIT",
                },
            )

    assert response.status_code == 200
    messages = [r.getMessage() for r in caplog.records]
    assert any("Mount attempt started" in m for m in messages)
    assert any("Mount attempt succeeded" in m for m in messages)
    assert not any("/exports/audit" in m for m in messages)
    assert not any("/nfs/audit" in m for m in messages)
    assert not any("sudo -n" in m for m in messages)


def test_add_mount_uses_unique_generated_local_mount_point(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.1.1:/exports/evidence", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.1.2:/exports/evidence", "project_id": "PROJ-002"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["local_mount_point"] == "/nfs/evidence"
    assert second.json()["local_mount_point"] == "/nfs/evidence-2"


def test_add_mount_acquires_create_lock(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("app.services.mount_service.MountRepository.acquire_create_lock") as mock_lock, \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.1.1:/exports/locked", "project_id": "PROJ-LOCK"},
        )

    assert response.status_code == 200
    mock_lock.assert_called_once()


def test_add_mount_rejects_exact_duplicate_remote_path_even_same_project(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1", "project_id": "PROJ-001"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "already configured" in second.json()["message"].lower()


def test_add_mount_rejects_nested_remote_path_for_different_project(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1/myfolder", "project_id": "PROJ-002"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "overlap" in second.json()["message"].lower()


def test_add_mount_rejects_parent_remote_path_for_different_project(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1/myfolder", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1", "project_id": "PROJ-999"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "overlap" in second.json()["message"].lower()


def test_add_mount_allows_nested_remote_path_for_same_project(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "NFS", "remote_path": "192.168.2.250:/mnt/Data/ecube/project1/myfolder", "project_id": "PROJ-001"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["project_id"] == "PROJ-001"


def test_add_mount_rejects_exact_duplicate_smb_remote_path(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "SMB", "remote_path": "//192.168.2.250/ecube/project1", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "SMB", "remote_path": "\\\\192.168.2.250\\ecube\\project1", "project_id": "PROJ-001"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "already configured" in second.json()["message"].lower()


def test_add_mount_rejects_nested_smb_remote_path_for_different_project(manager_client, db):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        first = manager_client.post(
            "/mounts",
            json={"type": "SMB", "remote_path": "//192.168.2.250/ecube/project1", "project_id": "PROJ-001"},
        )
        second = manager_client.post(
            "/mounts",
            json={"type": "SMB", "remote_path": "//192.168.2.250/ecube/project1/myfolder", "project_id": "PROJ-002"},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "overlap" in second.json()["message"].lower()


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
                "project_id": "PROJ-FAIL",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ERROR"

    audit = db.query(AuditLog).filter(AuditLog.action == "MOUNT_ADDED").first()
    assert audit is not None
    assert audit.details["error_code"] == "MOUNT_FAILED"
    assert audit.details["message"] == "Provider mount operation failed"
    assert "remote_path" not in audit.details
    assert "/exports/evidence" not in str(audit.details)
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
                "project_id": "PROJ-ROOT",
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
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="mount.nfs: access denied by server while mounting 192.168.1.3:/exports/audit",
            stdout="",
        )
        with caplog.at_level("DEBUG"):
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.1.3:/exports/audit",
                    "project_id": "PROJ-AUDIT-FAIL",
                },
            )

    assert response.status_code == 200
    messages = [r.getMessage() for r in caplog.records]
    assert any("Mount attempt started" in m for m in messages)
    assert any("Mount attempt failed" in m for m in messages)
    assert any(
        "Mount command raw error" in m
        and "access denied by server while mounting 192.168.1.3:/exports/audit" in m
        and "remote_path=192.168.1.3:/exports/audit" in m
        and "local_mount_point=/nfs/audit" in m
        for m in messages
    )
    assert not any("/exports/audit" in m for m in messages if "Mount attempt failed" in m)
    assert not any("/nfs/audit" in m for m in messages if "Mount attempt failed" in m)
    assert not any("sudo -n" in m for m in messages)


def test_add_mount_logs_useful_info_on_nfs_failure(manager_client, db, caplog):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="mount.nfs: access denied by server while mounting 192.168.1.3:/exports/info",
            stdout="",
        )
        with caplog.at_level("INFO"):
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.1.3:/exports/info",
                    "project_id": "PROJ-AUDIT-INFO",
                },
            )

    assert response.status_code == 200
    info_messages = [record.getMessage() for record in caplog.records if record.levelname == "INFO"]
    assert any("Mount attempt started" in message for message in info_messages)
    assert any(
        "Mount attempt failed" in message
        and "type=NFS" in message
        and "mount_label=info" in message
        and "failure_category=mount_add" in message
        and "reason=Permission or authentication failure" in message
        and "/exports/info" not in message
        and "/nfs/info" not in message
        for message in info_messages
    )


def test_list_mounts(manager_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    response = manager_client.get("/mounts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["local_mount_point"] == "/mnt/data"


def test_list_mounts_redacts_sensitive_paths_for_auditor(auditor_client, db):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/data",
        local_mount_point="/mnt/data",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    response = auditor_client.get("/mounts")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["remote_path"] == "[REDACTED]"
    assert data[0]["local_mount_point"] == "[REDACTED]"


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


def test_delete_mount_returns_conflict_when_unmount_fails(manager_client, db, caplog):
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/share",
        local_mount_point="/mnt/share",
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="umount: /mnt/share: target is busy", stdout="")
        with caplog.at_level("DEBUG"):
            response = manager_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 409
    assert db.get(NetworkMount, mount.id) is not None
    messages = [r.getMessage() for r in caplog.records]
    assert not any("/mnt/share" in m for m in messages if "Unmount command failed" in m)
    assert any(
        "Unmount command raw error" in m
        and "local_mount_point=/mnt/share" in m
        and "umount: /mnt/share: target is busy" in m
        for m in messages
    )


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
    assert data["status"] == "ERROR"
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


def test_validate_mount_candidate_returns_candidate_without_persisting(manager_client, db, caplog):
    class StatefulProvider:
        def __init__(self):
            self.mounted = False
            self.mount_calls = []
            self.unmount_calls = []

        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            return self.mounted

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.mount_calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                }
            )
            self.mounted = True
            return True, None

        def os_unmount(self, local_mount_point: str):
            self.unmount_calls.append(local_mount_point)
            self.mounted = False
            return True, None

    provider = StatefulProvider()

    with patch("app.services.mount_service._default_provider", return_value=provider), \
         patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        with caplog.at_level("INFO"):
            response = manager_client.post(
                "/mounts/test",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.1.1:/exports/evidence",
                    "project_id": "proj-new",
                    "username": "svc-reader",
                    "password": "top-secret",
                },
            )

    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "NFS"
    assert data["remote_path"] == "192.168.1.1:/exports/evidence"
    assert data["project_id"] == "PROJ-NEW"
    assert data["nfs_client_version"] is None
    assert data["local_mount_point"] == "/nfs/evidence"
    assert data["status"] == "MOUNTED"
    assert data["last_checked_at"] is not None
    assert db.query(NetworkMount).count() == 0
    assert provider.mount_calls == [
        {
            "mount_type": MountType.NFS,
            "remote_path": "192.168.1.1:/exports/evidence",
            "local_mount_point": "/nfs/evidence",
            "credentials_file": None,
            "username": "svc-reader",
            "password": "top-secret",
        }
    ]
    assert provider.unmount_calls == ["/nfs/evidence"]
    info_messages = [record.getMessage() for record in caplog.records if record.levelname == "INFO"]
    assert any("Mount candidate validation started" in message for message in info_messages)
    assert any("Mount candidate validation succeeded" in message for message in info_messages)


def test_validate_mount_candidate_timeout_returns_conflict(manager_client, db, caplog):
    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None), \
         patch(
             "subprocess.run",
             side_effect=subprocess.TimeoutExpired(
                 cmd=["sudo", "-n", "/usr/bin/nsenter", "-t", "1", "-m", "/bin/mount"],
                 timeout=30,
             ),
         ):
        with caplog.at_level("INFO"):
            response = manager_client.post(
                "/mounts/test",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.20.240:/volume1/demo-case-001",
                    "project_id": "proj-timeout",
                },
            )

    assert response.status_code == 409
    assert response.json()["message"] == "Operation timed out"
    info_messages = [record.getMessage() for record in caplog.records if record.levelname == "INFO"]
    warning_messages = [record.getMessage() for record in caplog.records if record.levelname == "WARNING"]
    assert any(
        "Mount candidate validation failed" in message
        and "type=NFS" in message
        and "mount_label=demo-case-001" in message
        and "failure_category=mount_validate_candidate" in message
        and "reason=Operation timed out" in message
        for message in info_messages
    )
    assert any(
        "Mount command timed out" in message
        and "type=NFS" in message
        and "mount_label=demo-case-001" in message
        and "reason=Operation timed out" in message
        for message in warning_messages
    )


def test_discover_mount_shares_returns_sanitized_remote_paths_and_reuses_credentials(manager_client, db):
    class FakeProvider:
        def __init__(self):
            self.calls = []

        def discover_shares(self, mount_type, remote_path, *, credentials_file=None, username=None, password=None):
            self.calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                }
            )
            return ["//fileserver/CaseDrop", "//fileserver/Review"]

    provider = FakeProvider()

    with patch("app.services.mount_service._default_provider", return_value=provider):
        response = manager_client.post(
            "/mounts/discover",
            json={
                "type": "SMB",
                "remote_path": "//fileserver",
                "username": "svc-reader",
                "password": "top-secret",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "shares": [
            {"remote_path": "//fileserver/CaseDrop", "display_name": "CaseDrop"},
            {"remote_path": "//fileserver/Review", "display_name": "Review"},
        ]
    }
    assert provider.calls == [
        {
            "mount_type": MountType.SMB,
            "remote_path": "//fileserver",
            "credentials_file": None,
            "username": "svc-reader",
            "password": "top-secret",
        }
    ]


def test_discover_mount_shares_allows_admin_role(admin_client, db):
    class FakeProvider:
        def discover_shares(self, mount_type, remote_path, *, credentials_file=None, username=None, password=None):
            return ["//fileserver/AdminShare"]

    with patch("app.services.mount_service._default_provider", return_value=FakeProvider()):
        response = admin_client.post(
            "/mounts/discover",
            json={
                "type": "SMB",
                "remote_path": "//fileserver",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "shares": [
            {"remote_path": "//fileserver/AdminShare", "display_name": "AdminShare"},
        ]
    }


def test_discover_mount_shares_requires_authentication(unauthenticated_client, db):
    response = unauthenticated_client.post(
        "/mounts/discover",
        json={
            "type": "SMB",
            "remote_path": "//fileserver",
        },
    )

    assert response.status_code == 401


def test_discover_mount_shares_requires_admin_or_manager(auditor_client, db):
    response = auditor_client.post(
        "/mounts/discover",
        json={
            "type": "SMB",
            "remote_path": "//fileserver",
        },
    )

    assert response.status_code == 403


def test_discover_mount_shares_rejected_in_demo_mode(manager_client, db):
    with patch.object(type(settings), "is_demo_mode_enabled", return_value=True):
        response = manager_client.post(
            "/mounts/discover",
            json={
                "type": "NFS",
                "remote_path": "nfs-server",
            },
        )

    assert response.status_code == 403


def test_discover_mount_shares_requires_server_seed(manager_client, db):
    response = manager_client.post(
        "/mounts/discover",
        json={
            "type": "SMB",
            "remote_path": "//",
        },
    )

    assert response.status_code == 422
    assert "Enter a server address before browsing shares" in response.text


def test_discover_mount_shares_returns_actionable_message_when_host_tool_is_missing(manager_client, db):
    class MissingToolProvider:
        def discover_shares(self, mount_type, remote_path, *, credentials_file=None, username=None, password=None):
            raise FileNotFoundError("smbclient not available")

    with patch("app.services.mount_service._default_provider", return_value=MissingToolProvider()):
        response = manager_client.post(
            "/mounts/discover",
            json={
                "type": "SMB",
                "remote_path": "//fileserver",
            },
        )

    assert response.status_code == 500
    assert "Share browsing requires the host smbclient tool. Install smbclient on the ECUBE host, then try again." in response.text


def test_validate_mount_with_candidate_payload_uses_unsaved_values_without_persisting(db):
    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//server/original-share",
        project_id="PROJ-OLD",
        local_mount_point="/smb/original-share",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()

    class StatefulProvider:
        def __init__(self):
            self.mounted = False
            self.mount_calls = []
            self.unmount_calls = []

        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            return self.mounted

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.mount_calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                }
            )
            self.mounted = True
            return True, None

        def os_unmount(self, local_mount_point: str):
            self.unmount_calls.append(local_mount_point)
            self.mounted = False
            return True, None

    provider = StatefulProvider()

    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        result = validate_mount(
            mount.id,
            db,
            provider=provider,
            mount_data=MountUpdate(
                type=MountType.SMB,
                remote_path="//server/edited-share",
                project_id="proj-new",
                username="svc-reader",
                password="top-secret",
                credentials_file=None,
            ),
        )

    db.expire_all()
    persisted = db.query(NetworkMount).filter(NetworkMount.id == mount.id).one()

    assert result.remote_path == "//server/edited-share"
    assert result.project_id == "PROJ-NEW"
    assert result.status == MountStatus.MOUNTED
    assert result.last_checked_at is not None

    assert persisted.remote_path == "//server/original-share"
    assert persisted.project_id == "PROJ-OLD"
    assert persisted.status == MountStatus.UNMOUNTED
    assert persisted.last_checked_at is not None

    assert provider.mount_calls == [
        {
            "mount_type": MountType.SMB,
            "remote_path": "//server/edited-share",
            "local_mount_point": "/smb/original-share",
            "credentials_file": None,
            "username": "svc-reader",
            "password": "top-secret",
        }
    ]
    assert provider.unmount_calls == ["/smb/original-share"]


def test_validate_mount_with_candidate_payload_returns_sanitized_failure_and_preserves_original_mount(db):
    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//server/original-share",
        project_id="PROJ-OLD",
        local_mount_point="/smb/original-share",
        status=MountStatus.UNMOUNTED,
    )
    db.add(mount)
    db.commit()

    class StatefulProvider:
        def __init__(self):
            self.mounted = False
            self.mount_calls = []
            self.unmount_calls = []

        def check_mounted(self, local_mount_point: str, *, timeout_seconds=None):
            return self.mounted

        def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
            self.mount_calls.append(
                {
                    "mount_type": mount_type,
                    "remote_path": remote_path,
                    "local_mount_point": local_mount_point,
                    "credentials_file": credentials_file,
                    "username": username,
                    "password": password,
                }
            )
            self.mounted = False
            return False, "Authentication failed for edited share."

        def os_unmount(self, local_mount_point: str):
            self.unmount_calls.append(local_mount_point)
            self.mounted = False
            return True, None

    provider = StatefulProvider()

    with patch("app.services.mount_service._ensure_mount_directory", return_value=None), \
         patch("app.services.mount_service._validate_mount_directory_owner", return_value=None):
        with pytest.raises(HTTPException) as exc_info:
            validate_mount(
                mount.id,
                db,
                provider=provider,
                mount_data=MountUpdate(
                    type=MountType.SMB,
                    remote_path="//server/edited-share",
                    project_id="proj-new",
                    username="svc-reader",
                    password="top-secret",
                    credentials_file=None,
                ),
            )

    db.expire_all()
    persisted = db.query(NetworkMount).filter(NetworkMount.id == mount.id).one()

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == sanitize_error_message(
        "Authentication failed for edited share.",
        "Mount validation failed",
    )
    assert persisted.remote_path == "//server/original-share"
    assert persisted.project_id == "PROJ-OLD"
    assert persisted.status == MountStatus.UNMOUNTED
    assert persisted.last_checked_at is not None
    assert provider.mount_calls == [
        {
            "mount_type": MountType.SMB,
            "remote_path": "//server/edited-share",
            "local_mount_point": "/smb/original-share",
            "credentials_file": None,
            "username": "svc-reader",
            "password": "top-secret",
        }
    ]
    assert provider.unmount_calls == []


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


def test_linux_mount_provider_uses_guest_option_for_credentialless_smb_mount(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("subprocess.run") as mock_run, patch.object(provider, "check_mounted", return_value=True):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")

        ok, err = provider.os_mount(
            MountType.SMB,
            "//192.168.2.250/demo-case-001",
            "/smb/demo-case-001",
        )

    assert ok is True
    assert err is None
    cmd = mock_run.call_args_list[0].args[0]
    assert cmd[:2] == ["sudo", "-n"]
    assert "-o" in cmd
    assert "guest" in cmd


def test_linux_mount_provider_treats_returncode_zero_with_inactive_mountpoint_as_failure(caplog):
    provider = LinuxMountProvider()

    with patch("subprocess.run") as mock_run, patch.object(provider, "check_mounted", return_value=False):
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        with caplog.at_level("DEBUG"):
            ok, err = provider.os_mount(
                MountType.NFS,
                "192.168.2.250:/mnt/Data/music",
                "/nfs/music",
            )

    assert ok is False
    assert "not active" in (err or "")
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "Mount command verification details" in message
        and "remote_path=192.168.2.250:/mnt/Data/music" in message
        and "local_mount_point=/nfs/music" in message
        and "command_path=" in message
        for message in messages
    )


def test_linux_mount_provider_uses_nsenter_when_mount_namespace_differs(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("app.services.mount_service.os.readlink", side_effect=["mnt:[2]", "mnt:[1]"]), \
         patch("app.services.mount_service.shutil.which", return_value="/usr/bin/nsenter"), \
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
    assert cmd[:6] == ["sudo", "-n", "/usr/bin/nsenter", "-t", "1", "-m"]
    assert "-N" not in cmd


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


def test_linux_mount_provider_uses_nsenter_when_host_namespace_read_fails(monkeypatch):
    provider = LinuxMountProvider()

    monkeypatch.setattr("app.services.mount_service.settings.use_sudo", True)
    monkeypatch.setattr("app.services.mount_service.os.geteuid", lambda: 1000)

    with patch("app.services.mount_service.os.readlink", side_effect=["mnt:[2]", PermissionError("denied")]), \
         patch("app.services.mount_service.shutil.which", return_value="/usr/bin/nsenter"), \
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
    assert cmd[:6] == ["sudo", "-n", "/usr/bin/nsenter", "-t", "1", "-m"]
    assert "-N" not in cmd


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


def test_linux_mount_provider_uses_direct_nfs_helper_after_fstab_failures(caplog):
    provider = LinuxMountProvider()

    first = MagicMock(returncode=32, stderr="mount.nfs: failed to apply fstab options", stdout="")
    second = MagicMock(returncode=0, stderr="", stdout="")

    with patch("app.services.mount_service._resolve_mount_nfs_binary", return_value="/sbin/mount.nfs"), \
         patch("subprocess.run", side_effect=[first, second]) as mock_run:
        with caplog.at_level("DEBUG"):
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
    info_messages = [record.getMessage() for record in caplog.records if record.levelname == "INFO"]
    debug_messages = [record.getMessage() for record in caplog.records if record.levelname == "DEBUG"]
    assert any(
        "Executing NFS mount command" in message
        and "nfs_client_version=4.1" in message
        and "command_path=" in message
        for message in info_messages
    )
    assert any(
        "Direct NFS helper context" in message
        and "helper=/sbin/mount.nfs" in message
        and "remote_path=192.168.2.250:/mnt/Data/music" in message
        and "local_mount_point=/mnt/music" in message
        for message in debug_messages
    )


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

