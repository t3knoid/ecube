"""Tests for frontend UI telemetry ingestion endpoint."""


def test_ui_telemetry_requires_auth(unauthenticated_client):
    response = unauthenticated_client.post(
        "/telemetry/ui-navigation",
        json={
            "event_type": "UI_NAVIGATION_CLICK",
            "action": "button",
            "source": "/jobs",
            "destination": "/jobs/1",
        },
    )
    assert response.status_code == 401


def test_ui_telemetry_accepts_authenticated_payload(manager_client):
    response = manager_client.post(
        "/telemetry/ui-navigation",
        json={
            "event_type": "UI_NAVIGATION_CLICK",
            "action": "button",
            "label": "Open",
            "source": "/jobs",
            "destination": "/jobs/1",
            "route_name": "job-detail",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"


def test_ui_telemetry_rejects_invalid_event_type(manager_client):
    response = manager_client.post(
        "/telemetry/ui-navigation",
        json={
            "event_type": "UNSUPPORTED_EVENT",
            "source": "/jobs",
            "destination": "/jobs/1",
        },
    )
    assert response.status_code == 422


def test_ui_telemetry_logs_debug_line(manager_client, caplog):
    caplog.set_level("DEBUG")

    response = manager_client.post(
        "/telemetry/ui-navigation",
        json={
            "event_type": "UI_NAVIGATION_COMPLETED",
            "source": "/jobs",
            "destination": "/jobs/1",
            "route_name": "job-detail",
        },
    )

    assert response.status_code == 202
    assert any("UI_NAVIGATION_TELEMETRY" in record.getMessage() for record in caplog.records)
