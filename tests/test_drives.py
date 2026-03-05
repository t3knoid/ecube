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

    response = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert response.status_code == 200
    data = response.json()
    assert data["current_state"] == "AVAILABLE"


def test_prepare_eject_not_found(manager_client, db):
    response = manager_client.post("/drives/999/prepare-eject")
    assert response.status_code == 404
