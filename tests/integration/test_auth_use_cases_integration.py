import pytest


@pytest.mark.integration
def test_health_is_public(integration_unauthenticated_client):
    response = integration_unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_protected_route_requires_token(integration_unauthenticated_client):
    response = integration_unauthenticated_client.get("/drives")
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "UNAUTHORIZED"
    assert "missing" in data["message"].lower()
    assert data["trace_id"]


@pytest.mark.integration
def test_protected_route_rejects_invalid_token(integration_unauthenticated_client):
    response = integration_unauthenticated_client.get(
        "/drives",
        headers={"Authorization": "Bearer not.a.real.token"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "UNAUTHORIZED"
    assert "invalid" in data["message"].lower()
    assert data["trace_id"]


@pytest.mark.integration
def test_protected_route_accepts_valid_token(integration_client):
    response = integration_client.get("/drives")
    assert response.status_code == 200
    assert response.json() == []
