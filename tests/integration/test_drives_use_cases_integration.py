import pytest

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive


@pytest.mark.integration
def test_list_drives_empty(integration_client):
    response = integration_client.get("/drives")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
def test_initialize_drive_updates_state_and_writes_audit(integration_client, integration_db):
    drive = UsbDrive(device_identifier="IT-DRV-001", current_state=DriveState.AVAILABLE)
    integration_db.add(drive)
    integration_db.commit()

    response = integration_client.post(
        f"/drives/{drive.id}/initialize",
        json={"project_id": "PROJ-IT-001"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["current_project_id"] == "PROJ-IT-001"
    assert data["current_state"] == "IN_USE"

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "DRIVE_INITIALIZED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["drive_id"] == drive.id


@pytest.mark.integration
def test_initialize_drive_conflict_logs_isolation_violation(integration_client, integration_db):
    drive = UsbDrive(
        device_identifier="IT-DRV-002",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-A",
    )
    integration_db.add(drive)
    integration_db.commit()

    response = integration_client.post(
        f"/drives/{drive.id}/initialize",
        json={"project_id": "PROJ-B"},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN"

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "PROJECT_ISOLATION_VIOLATION")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["requested_project_id"] == "PROJ-B"


@pytest.mark.integration
def test_prepare_eject_updates_drive_and_audit(integration_client, integration_db):
    drive = UsbDrive(
        device_identifier="IT-DRV-003",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-IT-003",
    )
    integration_db.add(drive)
    integration_db.commit()

    response = integration_client.post(f"/drives/{drive.id}/prepare-eject")
    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"

    audit = (
        integration_db.query(AuditLog)
        .filter(AuditLog.action == "DRIVE_EJECT_PREPARED")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.details["drive_id"] == drive.id


@pytest.mark.integration
def test_prepare_eject_not_found(integration_client):
    response = integration_client.post("/drives/999999/prepare-eject")
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
