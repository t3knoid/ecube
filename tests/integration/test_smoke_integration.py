import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.integration
def test_health_endpoint_is_reachable_without_auth():
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"


@pytest.mark.integration
def test_system_health_reports_database_connected(integration_client):
    response = integration_client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["database"] == "connected"
    assert data["status"] == "ok"
