from unittest.mock import MagicMock, patch

from app.models.network import MountStatus, MountType, NetworkMount


def test_list_mounts_empty(client, db):
    response = client.get("/mounts")
    assert response.status_code == 200
    assert response.json() == []


def test_add_mount(manager_client, db):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.1:/exports/evidence",
                "local_mount_point": "/mnt/evidence",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "NFS"
    assert data["status"] == "MOUNTED"


def test_add_mount_failure(manager_client, db):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="Permission denied", stdout="")
        response = manager_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "192.168.1.1:/exports/evidence",
                "local_mount_point": "/mnt/evidence2",
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ERROR"


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


def test_delete_mount_not_found(manager_client, db):
    response = manager_client.delete("/mounts/999")
    assert response.status_code == 404


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

