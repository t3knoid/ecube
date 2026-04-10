from datetime import datetime


def test_health_live_returns_alive_status(unauthenticated_client, db):
    response = unauthenticated_client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "alive"


def test_health_live_returns_iso8601_utc_timestamp(unauthenticated_client, db):
    response = unauthenticated_client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    timestamp = payload.get("timestamp")
    assert isinstance(timestamp, str)
    assert timestamp.endswith("Z")

    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
