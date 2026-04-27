import pytest


@pytest.mark.integration
def test_system_health_reports_connected_database(integration_client):
    response = integration_client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["database"] in {"connected", "error"}
    assert data["status"] in {"ok", "degraded"}
    assert "ecube_process" in data
    assert "active_copy_threads" in data["ecube_process"]


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

