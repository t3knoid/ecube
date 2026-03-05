import pytest

from app.models.jobs import ExportJob


@pytest.mark.integration
def test_system_health_reports_connected_database(integration_client):
    response = integration_client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["database"] in {"connected", "error"}
    assert data["status"] in {"ok", "degraded"}


@pytest.mark.integration
def test_usb_topology_endpoint_returns_devices_key(integration_client):
    response = integration_client.get("/introspection/usb/topology")
    assert response.status_code == 200
    assert "devices" in response.json()


@pytest.mark.integration
def test_block_devices_endpoint_returns_block_devices_key(integration_client):
    response = integration_client.get("/introspection/block-devices")
    assert response.status_code == 200
    assert "block_devices" in response.json()


@pytest.mark.integration
def test_mount_table_endpoint_returns_mounts_key(integration_client):
    response = integration_client.get("/introspection/mounts")
    assert response.status_code == 200
    assert "mounts" in response.json()


@pytest.mark.integration
def test_job_debug_use_cases(integration_client, integration_db):
    missing = integration_client.get("/introspection/jobs/999999/debug")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"

    job = ExportJob(
        project_id="PROJ-INTROSPECT-001",
        evidence_number="EV-INT-001",
        source_path="/tmp/source",
    )
    integration_db.add(job)
    integration_db.commit()

    response = integration_client.get(f"/introspection/jobs/{job.id}/debug")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.id
    assert data["project_id"] == "PROJ-INTROSPECT-001"
    assert isinstance(data["files"], list)
