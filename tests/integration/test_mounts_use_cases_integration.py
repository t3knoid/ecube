from unittest.mock import MagicMock, patch

import pytest

from app.models.audit import AuditLog
from app.models.network import MountStatus, MountType, NetworkMount


@pytest.mark.integration
def test_list_mounts_empty(integration_client):
    response = integration_client.get("/mounts")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
def test_add_mount_success_persists_and_audits(integration_client, integration_db):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        response = integration_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "10.0.0.5:/evidence",
                "local_mount_point": "/mnt/it-evidence",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "MOUNTED"

    mount = integration_db.query(NetworkMount).filter_by(id=data["id"]).first()
    assert mount is not None
    assert mount.status == MountStatus.MOUNTED

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "MOUNT_ADDED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["status"] == "MOUNTED"


@pytest.mark.integration
def test_add_mount_failure_sets_error_and_audits(integration_client, integration_db):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Permission denied",
        )
        response = integration_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "10.0.0.6:/restricted",
                "local_mount_point": "/mnt/it-restricted",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ERROR"

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "MOUNT_ADDED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["status"] == "ERROR"
    assert "permission denied" in audit.details["error"].lower()


@pytest.mark.integration
def test_remove_mount_deletes_record_and_audits(integration_client, integration_db):
    mount = NetworkMount(
        type=MountType.SMB,
        remote_path="//fileserver/share",
        local_mount_point="/mnt/it-share",
        status=MountStatus.MOUNTED,
    )
    integration_db.add(mount)
    integration_db.commit()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        response = integration_client.delete(f"/mounts/{mount.id}")

    assert response.status_code == 204
    assert integration_db.get(NetworkMount, mount.id) is None

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "MOUNT_REMOVED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["mount_id"] == mount.id


@pytest.mark.integration
def test_remove_mount_not_found(integration_client):
    response = integration_client.delete("/mounts/999999")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
