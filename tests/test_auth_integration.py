def test_protected_endpoint_missing_token_returns_401(unauthenticated_client, db):
    response = unauthenticated_client.get("/drives")
    assert response.status_code == 401
    data = response.json()
    assert "missing" in data.get("message", "").lower()


def test_protected_endpoint_invalid_token_returns_401(unauthenticated_client, db):
    response = unauthenticated_client.get(
        "/drives",
        headers={"Authorization": "Bearer not.a.valid.token"},
    )
    assert response.status_code == 401
    data = response.json()
    assert "invalid" in data.get("message", "").lower()


def test_protected_endpoint_valid_token_returns_200(client, db):
    response = client.get("/drives")
    assert response.status_code == 200


def test_public_health_endpoint_is_unauthenticated(unauthenticated_client, db):
    response = unauthenticated_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
