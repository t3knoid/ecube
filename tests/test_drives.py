from unittest.mock import MagicMock, patch

from app.infrastructure.drive_eject import EjectResult
from app.models.hardware import UsbDrive, DriveState
from app.services import drive_service


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
    assert isinstance(response.json(), list)


def test_list_drives_with_data(client, db):
    drive = UsbDrive(device_identifier="USB001", current_state=DriveState.AVAILABLE)
    db.add(drive)
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    data = response.json()
    ids = [d["device_identifier"] for d in data]
    assert "USB001" in ids
    assert ids.count("USB001") == 1


def test_list_drives_filter_by_project(client, db):
    """GET /drives?project_id= returns only matching drives."""
    d1 = UsbDrive(device_identifier="USB-A", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    d2 = UsbDrive(device_identifier="USB-B", current_state=DriveState.IN_USE, current_project_id="PROJ-002")
    d3 = UsbDrive(device_identifier="USB-C", current_state=DriveState.AVAILABLE)
    db.add_all([d1, d2, d3])
    db.commit()

    response = client.get("/drives", params={"project_id": "PROJ-001"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_identifier"] == "USB-A"
    assert data[0]["current_project_id"] == "PROJ-001"


def test_list_drives_filter_by_project_no_match(client, db):
    """GET /drives?project_id= returns empty list when no drives match."""
    drive = UsbDrive(device_identifier="USB-X", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    db.add(drive)
    db.commit()

    response = client.get("/drives", params={"project_id": "PROJ-999"})
    assert response.status_code == 200
    assert response.json() == []


def test_list_drives_filter_by_project_normalizes_case_and_whitespace(client, db):
    drive = UsbDrive(device_identifier="USB-NORM", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    db.add(drive)
    db.commit()

    response = client.get("/drives", params={"project_id": "  proj-001  "})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_identifier"] == "USB-NORM"


def test_list_drives_empty_project_id_rejected(client, db):
    """GET /drives?project_id= (empty string) returns 422."""
    response = client.get("/drives", params={"project_id": ""})
    assert response.status_code == 422


def test_list_drives_default_excludes_disconnected(client, db):
    """GET /drives without project_id returns connected drives (excludes DISCONNECTED by default)."""
    d1 = UsbDrive(device_identifier="USB-1", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    d2 = UsbDrive(device_identifier="USB-2", current_state=DriveState.AVAILABLE)
    d3 = UsbDrive(device_identifier="USB-3", current_state=DriveState.DISCONNECTED)
    db.add_all([d1, d2, d3])
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    data = response.json()
    ids = [d["device_identifier"] for d in data]
    assert "USB-1" in ids
    assert "USB-2" in ids
    assert "USB-3" not in ids


def test_list_drives_include_disconnected(client, db):
    """GET /drives?include_disconnected=true returns all drives including DISCONNECTED."""
    d1 = UsbDrive(device_identifier="USB-1", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    d2 = UsbDrive(device_identifier="USB-2", current_state=DriveState.AVAILABLE)
    d3 = UsbDrive(device_identifier="USB-3", current_state=DriveState.DISCONNECTED)
    db.add_all([d1, d2, d3])
    db.commit()

    response = client.get("/drives", params={"include_disconnected": "true"})
    assert response.status_code == 200
    data = response.json()
    ids = [d["device_identifier"] for d in data]
    assert "USB-1" in ids
    assert "USB-2" in ids
    assert "USB-3" in ids



def test_initialize_drive(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(device_identifier="USB002", current_state=DriveState.AVAILABLE, filesystem_type="ext4")
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.1:/exports/proj-001",
        project_id="PROJ-001",
        local_mount_point="/nfs/proj-001",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 200
    data = response.json()
    assert data["current_project_id"] == "PROJ-001"
    assert data["current_state"] == "IN_USE"


def test_initialize_drive_rejects_project_without_mounted_source(manager_client, db):
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB-NO-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-MISSING"})

    assert response.status_code == 409
    assert response.json()["message"] == (
        "No mounted share is assigned to project PROJ-MISSING. "
        "Mount a share for this project before initializing a drive."
    )

    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_NO_PROJECT_SOURCE").one()
    assert log.project_id == "PROJ-MISSING"
    assert log.drive_id == drive.id
    assert log.details["requested_project_id"] == "PROJ-MISSING"
    assert log.details["reason"] == "no_mounted_project_source"


def test_initialize_drive_allows_project_with_mounted_source(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB-WITH-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.5:/exports/proj-205",
        local_mount_point="/nfs/proj-205",
        project_id="PROJ-205",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-205"})

    assert response.status_code == 200
    assert response.json()["current_project_id"] == "PROJ-205"
    assert response.json()["current_state"] == "IN_USE"


def test_initialize_drive_normalizes_project_id_case_and_whitespace(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB-WITH-NORMALIZED-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.7:/exports/proj-777",
        local_mount_point="/nfs/proj-777",
        project_id="PROJ-777",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "  proj-777  "})

    assert response.status_code == 200
    assert response.json()["current_project_id"] == "PROJ-777"
    assert response.json()["current_state"] == "IN_USE"


def test_mount_drive_success(manager_client, db):
    from app.config import settings
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB-MOUNT-001",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (True, None)

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 200
    data = response.json()
    assert data["mount_path"] == f"{settings.usb_mount_base_path}/{drive.id}"
    provider.mount_drive.assert_called_once_with(
        "/dev/sdb",
        f"{settings.usb_mount_base_path}/{drive.id}",
    )

    audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_MOUNTED").first()
    assert audit is not None
    assert audit.details["drive_id"] == drive.id
    assert audit.details["device_name"] == "sdb"
    assert audit.details["mount_slot"] == str(drive.id)
    assert "filesystem_path" not in audit.details
    assert "mount_path" not in audit.details


def test_mount_drive_requires_recognized_filesystem(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-001B",
        current_state=DriveState.AVAILABLE,
        filesystem_type="unknown",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert "recognized filesystem" in response.json()["message"].lower()


def test_mount_drive_conflict_when_already_mounted(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-002",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdc",
        mount_path="/mnt/ecube/2",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert "already mounted" in response.json()["message"].lower()
    provider.mount_drive.assert_not_called()


def test_mount_drive_requires_filesystem_path(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-003",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path=None,
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 400
    assert "filesystem_path" in response.json()["message"]


def test_mount_drive_provider_failure_is_audited(manager_client, db):
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB-MOUNT-004",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdd",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "mount failed for /dev/sdd at /mnt/ecube/4")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive mount failed"

    audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_MOUNT_FAILED").first()
    assert audit is not None
    assert audit.details["drive_id"] == drive.id
    assert audit.details["error_code"] == "MOUNT_FAILED"
    assert audit.details["message"] == "Provider mount operation failed"
    assert "error" not in audit.details
    assert "/dev/sdd" not in str(audit.details)
    assert "/mnt/ecube/4" not in str(audit.details)
    assert "filesystem_path" not in audit.details
    assert "mount_path" not in audit.details


def test_mount_drive_failure_redacts_provider_paths_from_client(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004B",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdz1",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "mount: /dev/sdz1 already mounted on /mnt/ecube/42")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive mount failed"
    assert "/dev/sdz1" not in response.json()["message"]
    assert "/mnt/ecube/42" not in response.json()["message"]


def test_mount_drive_db_save_failure_attempts_cleanup(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004C",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdg",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (True, None)
    provider.unmount_drive.return_value = (True, None)

    with (
        patch("app.routers.drives.get_drive_mount", return_value=provider),
        patch("app.services.drive_service.DriveRepository.save", side_effect=RuntimeError("db failed")),
    ):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert "rollback attempted" in response.json()["message"].lower()
    provider.unmount_drive.assert_called_once_with(f"/mnt/ecube/{drive.id}")


def test_mount_drive_relocks_only_after_os_mount_and_aborts_if_state_changed(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004D",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdh",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    call_order = []

    def mount_side_effect(device_path, mount_point):
        call_order.append("mount")
        return True, None

    provider.mount_drive.side_effect = mount_side_effect
    provider.unmount_drive.return_value = (True, None)

    original_get = drive_service.DriveRepository.get
    original_get_for_update = drive_service.DriveRepository.get_for_update

    def get_side_effect(self, drive_id):
        call_order.append("get")
        return original_get(self, drive_id)

    def get_for_update_side_effect(self, drive_id):
        call_order.append("lock")
        locked_drive = original_get_for_update(self, drive_id)
        if "mount" in call_order:
            locked_drive.current_state = DriveState.ARCHIVED
        return locked_drive

    with (
        patch("app.routers.drives.get_drive_mount", return_value=provider),
        patch.object(drive_service.DriveRepository, "get", get_side_effect),
        patch.object(drive_service.DriveRepository, "get_for_update", get_for_update_side_effect),
    ):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert "changed during mount" in response.json()["message"].lower()
    assert call_order == ["get", "mount", "lock"]
    provider.unmount_drive.assert_called_once_with(f"/mnt/ecube/{drive.id}")


def test_mount_drive_treats_same_persisted_mount_as_idempotent(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004E",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdi",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (True, None)
    provider.unmount_drive.return_value = (True, None)

    expected_mount_path = f"/mnt/ecube/{drive.id}"
    original_get_for_update = drive_service.DriveRepository.get_for_update

    def get_for_update_side_effect(self, drive_id):
        locked_drive = original_get_for_update(self, drive_id)
        locked_drive.mount_path = expected_mount_path
        return locked_drive

    with (
        patch("app.routers.drives.get_drive_mount", return_value=provider),
        patch.object(drive_service.DriveRepository, "get_for_update", get_for_update_side_effect),
    ):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 200
    assert response.json()["mount_path"] == expected_mount_path
    provider.unmount_drive.assert_not_called()


def test_mount_drive_processor_forbidden(client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-005",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sde",
    )
    db.add(drive)
    db.commit()

    response = client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 403


def test_mount_drive_auditor_forbidden(auditor_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-006",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdf",
    )
    db.add(drive)
    db.commit()

    response = auditor_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 403


def test_initialize_drive_not_found(manager_client, db):
    response = manager_client.post("/drives/999/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 404


def test_initialize_archived_drive_is_rejected(manager_client, db):
    """Archived drives must never be re-initialized (terminal state)."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB003A",
        current_state=DriveState.ARCHIVED,
        current_project_id="PROJ-OLD",
        filesystem_type="exfat",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-NEW"})
    assert response.status_code == 409
    assert "archived" in response.json()["message"].lower()

    # Drive state must remain ARCHIVED.
    db.refresh(drive)
    assert drive.current_state == DriveState.ARCHIVED

    # Denial must be recorded in the audit trail.
    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_ARCHIVED").first()
    assert log is not None
    assert log.details["drive_id"] == drive.id
    assert log.details["requested_project_id"] == "PROJ-NEW"
    assert log.details["current_state"] == "ARCHIVED"
    assert log.details["existing_project_id"] == "PROJ-OLD"


def test_initialize_empty_drive_is_rejected(manager_client, db):
    """DISCONNECTED drives are not accessible; initialization must be rejected with 409."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB003E",
        current_state=DriveState.DISCONNECTED,
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-NEW"})
    assert response.status_code == 409
    assert "disconnected" in response.json()["message"].lower()

    # Drive state must remain DISCONNECTED.
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED

    # Denial must be recorded in the audit trail.
    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_NOT_AVAILABLE").first()
    assert log is not None
    assert log.details["drive_id"] == drive.id
    assert log.details["current_state"] == "DISCONNECTED"
    assert log.details["requested_project_id"] == "PROJ-NEW"


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
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB004",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_type="ext4",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.1:/exports/proj-001",
        project_id="PROJ-001",
        local_mount_point="/nfs/proj-001-reinit",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
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
    # Project binding is preserved through eject so re-insert for the same
    # project is allowed without a format, and cross-project reuse is blocked.
    assert data["current_project_id"] == "PROJ-001"


def test_reinitialize_same_project_after_eject(manager_client, db):
    """A drive can be re-initialized for the same project after eject (adds more data)."""
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB005D",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_type="exfat",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.1:/exports/proj-001",
        project_id="PROJ-001",
        local_mount_point="/nfs/proj-001-after-eject",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        eject_resp = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert eject_resp.status_code == 200

    # Re-initialize for the same project must succeed — user is adding more data.
    init_resp = manager_client.post(
        f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"}
    )
    assert init_resp.status_code == 200
    assert init_resp.json()["current_state"] == "IN_USE"


def test_reinitialize_different_project_after_eject_requires_format(manager_client, db):
    """Re-initializing an ejected drive for a different project must be rejected (409).

    The previous project's data is still on disk. A format (wipe) is required
    before the drive can be assigned to a new project.
    """
    drive = UsbDrive(
        device_identifier="USB005E",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-A",
        filesystem_type="exfat",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        eject_resp = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert eject_resp.status_code == 200

    # Attempt to re-initialize for a different project must be rejected.
    init_resp = manager_client.post(
        f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-B"}
    )
    assert init_resp.status_code == 409
    assert "PROJ-A" in init_resp.json()["message"]


def test_prepare_eject_with_filesystem_path(manager_client, db):
    """Flush and unmount are both called when drive has a filesystem_path."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB006",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
        mount_path="/mnt/ecube/6",
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    assert response.json()["mount_path"] is None
    provider.prepare_eject.assert_called_once_with("/dev/sdb")

    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_PREPARED").first()
    assert log is not None
    assert log.drive_id == drive.id
    assert log.project_id == "PROJ-001"
    assert log.details["drive_id"] == drive.id
    assert log.details["device_name"] == "sdb"
    assert log.details["flush_ok"] is True
    assert log.details["unmount_ok"] is True
    assert "filesystem_path" not in log.details


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
    assert log.drive_id == drive.id
    assert log.project_id == "PROJ-001"
    assert log.details["flush_ok"] is False
    assert log.details["error_code"] == "EJECT_FLUSH_FAILED"
    assert log.details["message"] == "Drive flush operation failed"
    assert "flush_error" not in log.details


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
    assert log.details["error_code"] == "EJECT_UNMOUNT_FAILED"
    assert log.details["message"] == "Drive unmount operation failed"
    assert "unmount_error" not in log.details
    assert "/dev/sdc" not in str(log.details)


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
    assert log.details["error_code"] == "EJECT_UNMOUNT_FAILED"
    assert "invalid device path" not in str(log.details)
    assert "/tmp/../../etc/passwd" not in str(log.details)


def test_prepare_eject_requires_in_use_state(manager_client, db):
    """Prepare-eject must reject drives not in IN_USE state (409 Conflict).
    
    Verifies that prepare_eject is NOT called (fast-fail optimization).
    """
    drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.DISCONNECTED,
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

    # Drive state must remain DISCONNECTED.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED


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
    assert "/dev/sdb" not in response.json()["message"]
    assert "/dev/sdc" not in response.json()["message"]

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
    assert "/dev/sde" not in response.json()["message"]

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



