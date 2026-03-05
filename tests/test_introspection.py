from unittest.mock import mock_open, patch


def test_system_health(client, db):
    response = client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "active_jobs" in data


def test_system_mounts(client, db):
    mock_content = "sysfs /sys sysfs rw,nosuid 0 0\ntmpfs /tmp tmpfs rw 0 0\n"
    with patch("builtins.open", mock_open(read_data=mock_content)):
        response = client.get("/introspection/mounts")
    assert response.status_code == 200
    data = response.json()
    assert "mounts" in data


def test_block_devices(client, db):
    response = client.get("/introspection/block-devices")
    assert response.status_code == 200
    assert "block_devices" in response.json()


def test_usb_topology(client, db):
    response = client.get("/introspection/usb/topology")
    assert response.status_code == 200
    assert "devices" in response.json()


def test_system_health_degraded(client, db):
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError

    with patch("sqlalchemy.orm.Session.execute", side_effect=OperationalError("", {}, None)):
        response = client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["database"] == "error"
    assert data["database_error"] is not None


def test_job_debug_not_found(client, db):
    response = client.get("/introspection/jobs/999/debug")
    assert response.status_code == 404


def test_job_debug(client, db):
    from app.models.jobs import ExportJob

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path="/data/evidence",
    )
    db.add(job)
    db.commit()

    response = client.get(f"/introspection/jobs/{job.id}/debug")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.id
    assert data["project_id"] == "PROJ-001"
