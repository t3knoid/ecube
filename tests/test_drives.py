from unittest.mock import patch

from app.models.hardware import UsbDrive, DriveState


def test_list_drives(client, db):
    response = client.get("/drives")
    assert response.status_code == 200
    assert response.json() == []


def test_list_drives_with_data(client, db):
    drive = UsbDrive(device_identifier="USB001", current_state=DriveState.AVAILABLE)
    db.add(drive)
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_identifier"] == "USB001"


def test_initialize_drive(manager_client, db):
    drive = UsbDrive(device_identifier="USB002", current_state=DriveState.AVAILABLE)
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 200
    data = response.json()
    assert data["current_project_id"] == "PROJ-001"
    assert data["current_state"] == "IN_USE"


def test_initialize_drive_not_found(manager_client, db):
    response = manager_client.post("/drives/999/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 404


def test_project_isolation_violation(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB003",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-002"})
    assert response.status_code == 409


def test_reinitialize_same_project(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB004",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 200


def test_prepare_eject(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB005",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert response.status_code == 200
    data = response.json()
    assert data["current_state"] == "AVAILABLE"


def test_prepare_eject_with_filesystem_path(manager_client, db):
    """Flush and unmount are both called when drive has a filesystem_path."""
    drive = UsbDrive(
        device_identifier="USB006",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    with (
        patch("app.services.drive_service.sync_filesystem", return_value=(True, None)) as mock_sync,
        patch("app.services.drive_service.unmount_device", return_value=(True, None)) as mock_umount,
    ):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    mock_sync.assert_called_once()
    mock_umount.assert_called_once_with("/dev/sdb")


def test_prepare_eject_not_found(manager_client, db):
    with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)):
        response = manager_client.post("/drives/999/prepare-eject")
    assert response.status_code == 404


def test_prepare_eject_flush_failure(manager_client, db):
    """When sync fails the drive stays IN_USE and DRIVE_EJECT_FAILED is logged."""
    drive = UsbDrive(
        device_identifier="USB007",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    with patch("app.services.drive_service.sync_filesystem", return_value=(False, "sync failed")):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive eject preparation failed"

    # Drive state must remain IN_USE.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE

    # Audit log must record the failure.
    from app.models.audit import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_FAILED").first()
    assert log is not None
    assert log.details["flush_ok"] is False
    assert log.details["flush_error"] == "sync failed"


def test_prepare_eject_unmount_failure(manager_client, db):
    """When umount fails the drive stays IN_USE and DRIVE_EJECT_FAILED is logged."""
    drive = UsbDrive(
        device_identifier="USB008",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdc",
    )
    db.add(drive)
    db.commit()

    with (
        patch("app.services.drive_service.sync_filesystem", return_value=(True, None)),
        patch("app.services.drive_service.unmount_device", return_value=(False, "umount failed for /dev/sdc")),
    ):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive eject preparation failed"

    # Drive state must remain IN_USE.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE

    # Audit log must record the failure.
    from app.models.audit import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_FAILED").first()
    assert log is not None
    assert log.details["unmount_ok"] is False
    assert log.details["unmount_error"] == "umount failed for /dev/sdc"


def test_prepare_eject_no_unmount_when_no_path(manager_client, db):
    """unmount_device is NOT called when the drive has no filesystem_path."""
    drive = UsbDrive(
        device_identifier="USB009",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    with (
        patch("app.services.drive_service.sync_filesystem", return_value=(True, None)) as mock_sync,
        patch("app.services.drive_service.unmount_device") as mock_umount,
    ):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    mock_sync.assert_called_once()
    mock_umount.assert_not_called()


def test_prepare_eject_invalid_device_path(manager_client, db):
    """A drive with an invalid filesystem_path is rejected without spawning a process."""
    drive = UsbDrive(
        device_identifier="USB010",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/tmp/../../etc/passwd",
    )
    db.add(drive)
    db.commit()

    with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive eject preparation failed"

    # Drive state must remain IN_USE.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE

    from app.models.audit import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_FAILED").first()
    assert log is not None
    assert "invalid device path" in (log.details.get("unmount_error") or "")
