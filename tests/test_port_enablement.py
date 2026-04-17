"""Tests for USB port enablement endpoints.

Covers GET /admin/ports, PATCH /admin/ports/{port_id}, auth enforcement,
404 handling, and audit logging.
"""

from unittest.mock import patch

import pytest

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_port(db) -> UsbPort:
    """Insert a hub and a port for testing."""
    hub = UsbHub(name="Test Hub", system_identifier="usb-test-1")
    db.add(hub)
    db.commit()
    db.refresh(hub)

    port = UsbPort(hub_id=hub.id, port_number=1, system_path="1-1")
    db.add(port)
    db.commit()
    db.refresh(port)
    return port


# ---------------------------------------------------------------------------
# GET /admin/ports
# ---------------------------------------------------------------------------


def test_list_ports_requires_auth(unauthenticated_client):
    response = unauthenticated_client.get("/admin/ports")
    assert response.status_code == 401


def test_list_ports_processor_forbidden(client):
    """Processor role should be rejected."""
    response = client.get("/admin/ports")
    assert response.status_code == 403


def test_list_ports_admin_succeeds(admin_client, db):
    port = _seed_port(db)
    response = admin_client.get("/admin/ports")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(item["id"] == port.id and item["enabled"] is False for item in data)


def test_list_ports_manager_succeeds(manager_client, db):
    port = _seed_port(db)
    response = manager_client.get("/admin/ports")
    assert response.status_code == 200
    data = response.json()
    match = next((item for item in data if item["id"] == port.id), None)
    assert match is not None
    assert "enabled" in match


# ---------------------------------------------------------------------------
# PATCH /admin/ports/{port_id}
# ---------------------------------------------------------------------------


def test_toggle_port_requires_auth(unauthenticated_client):
    response = unauthenticated_client.patch("/admin/ports/1", json={"enabled": True})
    assert response.status_code == 401


def test_toggle_port_processor_forbidden(client, db):
    port = _seed_port(db)
    response = client.patch(f"/admin/ports/{port.id}", json={"enabled": True})
    assert response.status_code == 403


def test_toggle_port_nonexistent_returns_404(admin_client):
    response = admin_client.patch("/admin/ports/9999", json={"enabled": True})
    assert response.status_code == 404


def test_toggle_port_enables(admin_client, db):
    port = _seed_port(db)
    assert port.enabled is False

    response = admin_client.patch(f"/admin/ports/{port.id}", json={"enabled": True})
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["id"] == port.id

    db.refresh(port)
    assert port.enabled is True


def test_toggle_port_disables(admin_client, db):
    port = _seed_port(db)
    port.enabled = True
    db.commit()

    response = admin_client.patch(f"/admin/ports/{port.id}", json={"enabled": False})
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False

    db.refresh(port)
    assert port.enabled is False


def test_toggle_port_manager_succeeds(manager_client, db):
    port = _seed_port(db)
    response = manager_client.patch(f"/admin/ports/{port.id}", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_toggle_port_enable_triggers_drive_reconciliation(admin_client, db):
    port = _seed_port(db)
    drive = UsbDrive(
        device_identifier="USB-PORT-ENABLE",
        current_state=DriveState.DISCONNECTED,
        port_id=port.id,
        filesystem_path="/dev/sdz",
        mount_path="/mnt/ecube/port-enable",
    )
    db.add(drive)
    db.commit()

    def fake_run_discovery_sync(db_session, actor=None, **kwargs):
        drive.current_state = DriveState.IN_USE
        db_session.commit()
        return {"drives_updated": 1}

    with patch("app.routers.admin.run_discovery_sync", side_effect=fake_run_discovery_sync) as sync_mock:
        response = admin_client.patch(f"/admin/ports/{port.id}", json={"enabled": True})

    assert response.status_code == 200
    sync_mock.assert_called_once()
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE


def test_toggle_port_enable_surfaces_reconciliation_failure(admin_client, db):
    port = _seed_port(db)

    with patch("app.routers.admin.run_discovery_sync", side_effect=RuntimeError("discovery unavailable")):
        response = admin_client.patch(f"/admin/ports/{port.id}", json={"enabled": True})

    assert response.status_code == 503
    assert response.json()["message"] == (
        "Port state updated, but drive discovery reconciliation failed; retry refresh or rescan"
    )

    db.refresh(port)
    assert port.enabled is True


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


def test_enable_port_creates_audit_log(admin_client, db):
    port = _seed_port(db)
    admin_client.patch(f"/admin/ports/{port.id}", json={"enabled": True})

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "PORT_ENABLED")
        .first()
    )
    assert log is not None
    assert log.user == "admin-user"
    assert log.details["port_id"] == port.id
    assert log.details["system_path"] == "[redacted]"
    assert log.details["hub_id"] == port.hub_id
    assert log.details["enabled"] is True
    assert log.details["path"] == f"/admin/ports/{port.id}"


def test_disable_port_creates_audit_log(admin_client, db):
    port = _seed_port(db)
    port.enabled = True
    db.commit()

    admin_client.patch(f"/admin/ports/{port.id}", json={"enabled": False})

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "PORT_DISABLED")
        .first()
    )
    assert log is not None
    assert log.user == "admin-user"
    assert log.details["port_id"] == port.id
    assert log.details["enabled"] is False
    assert log.details["path"] == f"/admin/ports/{port.id}"
