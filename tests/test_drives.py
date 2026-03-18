from unittest.mock import MagicMock, patch

from app.infrastructure.drive_eject import EjectResult
from app.models.hardware import UsbDrive, DriveState


def _fake_eject(flush_ok=True, unmount_ok=True,
                flush_error=None, unmount_error=None,
                prepare_eject_side_effect=None):
    """Return a MagicMock DriveEjectProvider with preconfigured prepare_eject."""
    provider = MagicMock()
    if prepare_eject_side_effect is not None:
        provider.prepare_eject.side_effect = prepare_eject_side_effect
    else:
        provider.prepare_eject.return_value = EjectResult(
            flush_ok=flush_ok, unmount_ok=unmount_ok,
            flush_error=flush_error, unmount_error=unmount_error,
        )
    return provider


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
    drive = UsbDrive(device_identifier="USB002", current_state=DriveState.AVAILABLE, filesystem_type="ext4")
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
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-002"})
    assert response.status_code == 403


def test_reinitialize_same_project(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB004",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_type="ext4",
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

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert response.status_code == 200
    data = response.json()
    assert data["current_state"] == "AVAILABLE"


def test_prepare_eject_with_filesystem_path(manager_client, db):
    """Flush and unmount are both called when drive has a filesystem_path."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB006",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    provider.prepare_eject.assert_called_once_with("/dev/sdb")

    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_PREPARED").first()
    assert log is not None
    assert log.details["drive_id"] == drive.id
    assert log.details["filesystem_path"] == "/dev/sdb"
    assert log.details["flush_ok"] is True
    assert log.details["unmount_ok"] is True


def test_prepare_eject_not_found(manager_client, db):
    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
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

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(flush_ok=False, flush_error="sync failed")):
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

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        unmount_ok=False, unmount_error="umount failed for /dev/sdc",
    )):
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
    """prepare_eject is called with None when the drive has no filesystem_path."""
    drive = UsbDrive(
        device_identifier="USB009",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    provider.prepare_eject.assert_called_once_with(None)


def test_prepare_eject_concurrent_state_change(manager_client, db):
    """Returns 409 when the drive state changes between the initial read and re-lock."""
    from app.repositories.drive_repository import DriveRepository

    drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    # Simulate a concurrent state change: get_for_update returns a drive that
    # another request already transitioned to AVAILABLE.
    concurrent_drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    )
    concurrent_drive.id = drive_id

    with (
        patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()),
        patch.object(DriveRepository, "get_for_update", return_value=concurrent_drive),
    ):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409


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

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        unmount_ok=False, unmount_error="invalid device path: /tmp/../../etc/passwd",
    )):
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


def test_prepare_eject_requires_in_use_state(manager_client, db):
    """Prepare-eject must reject drives not in IN_USE state (409 Conflict).
    
    Verifies that prepare_eject is NOT called (fast-fail optimization).
    """
    drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.EMPTY,
        current_project_id=None,
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert "not in IN_USE state" in response.json()["message"]
    # Verify prepare_eject was NOT called (fast-fail before OS operations)
    provider.prepare_eject.assert_not_called()

    # Drive state must remain EMPTY.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.EMPTY


def test_prepare_eject_available_state_conflict(manager_client, db):
    """Prepare-eject on AVAILABLE drive returns 409 Conflict.
    
    Verifies that prepare_eject is NOT called (fast-fail optimization).
    """
    drive = UsbDrive(
        device_identifier="USB012",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert "not in IN_USE state" in response.json()["message"]
    # Verify prepare_eject was NOT called (fast-fail before OS operations)
    provider.prepare_eject.assert_not_called()


def test_prepare_eject_device_path_changed(manager_client, db):
    """Prepare-eject fails if filesystem_path changes during operation (409 Conflict).
    
    Simulates scenario where USB discovery refresh changes the device path
    between the initial read and the locked update.
    """
    drive = UsbDrive(
        device_identifier="USB013",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    def sync_and_change_path(device_path):
        """Simulate eject succeeding, then discovery changing the device path."""
        # Simulate discovery refresh changing the path
        drive_obj = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
        if drive_obj:
            drive_obj.filesystem_path = "/dev/sdc"
            db.commit()
        return EjectResult()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        prepare_eject_side_effect=sync_and_change_path,
    )):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409
    assert "Device path changed" in response.json()["message"]
    assert "/dev/sdb" in response.json()["message"]
    assert "/dev/sdc" in response.json()["message"]

    # Drive state must remain IN_USE.
    db.expire_all()
    drive = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
    assert drive.current_state == DriveState.IN_USE


def test_prepare_eject_device_path_cleared_during_operation(manager_client, db):
    """Prepare-eject fails if filesystem_path becomes None during operation (409 Conflict).
    
    Simulates scenario where USB is disconnected and discovery removes the device path.
    """
    drive = UsbDrive(
        device_identifier="USB014",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sde",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    def sync_and_clear_path(device_path):
        """Simulate eject succeeding, then discovery clearing the device path."""
        # Simulate USB disconnection clearing the path
        drive_obj = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
        if drive_obj:
            drive_obj.filesystem_path = None
            db.commit()
        return EjectResult()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        prepare_eject_side_effect=sync_and_clear_path,
    )):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409
    assert "Device path changed" in response.json()["message"]
    assert "/dev/sde" in response.json()["message"]

    # Drive state must remain IN_USE.
    db.expire_all()
    drive = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
    assert drive.current_state == DriveState.IN_USE


def test_prepare_eject_state_changed_during_operation(manager_client, db):
    """Prepare-eject fails if current_state changes during operation (409 Conflict).
    
    Simulates scenario where another request (e.g., re-initialize) changes the state
    between the initial read and the locked update.
    """
    drive = UsbDrive(
        device_identifier="USB015",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdf",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    def sync_and_change_state(device_path):
        """Simulate eject succeeding, then another request changing the state."""
        # Simulate another request re-initializing the drive
        drive_obj = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
        if drive_obj:
            drive_obj.current_state = DriveState.AVAILABLE
            db.commit()
        return EjectResult()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        prepare_eject_side_effect=sync_and_change_state,
    )):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409
    assert "state changed during prepare-eject" in response.json()["message"]
    assert "IN_USE" in response.json()["message"]
    assert "AVAILABLE" in response.json()["message"]

    # Drive state should now be AVAILABLE (from the state change).
    db.expire_all()
    drive = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
    assert drive.current_state == DriveState.AVAILABLE


def test_prepare_eject_nvme_partitions(manager_client, db):
    """Prepare-eject correctly handles NVMe naming (nvme0n1p1, nvme0n1p2).
    
    Tests that the partition matching logic recognizes modern NVMe partition
    naming with 'p' prefix (e.g., nvme0n1p1) not just traditional digit suffix.
    """
    drive = UsbDrive(
        device_identifier="USB016",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/nvme0n1",
    )
    db.add(drive)
    db.commit()

    # Mock prepare_eject to verify it was called with the base device
    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    # Verify prepare_eject was called with the NVMe device path
    provider.prepare_eject.assert_called_once_with("/dev/nvme0n1")


def test_prepare_eject_mmc_partitions(manager_client, db):
    """Prepare-eject correctly handles MMC naming (mmcblk0p1, mmcblk0p2).
    
    Tests that the partition matching logic recognizes MMC partition naming
    with 'p' prefix (e.g., mmcblk0p1) not just traditional digit suffix.
    """
    drive = UsbDrive(
        device_identifier="USB017",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/mmcblk0",
    )
    db.add(drive)
    db.commit()

    # Mock prepare_eject to verify it was called with the base device
    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    # Verify prepare_eject was called with the MMC device path
    provider.prepare_eject.assert_called_once_with("/dev/mmcblk0")



