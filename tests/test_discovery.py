"""Tests for the USB discovery sync service and the /drives/refresh endpoint.

All tests use the in-memory SQLite database from conftest.py and inject
synthetic hardware topology via the *topology_source* parameter so that no
physical USB hardware is required.
"""

from __future__ import annotations

import pytest

from app.infrastructure.usb_discovery import (
    DiscoveredDrive,
    DiscoveredHub,
    DiscoveredPort,
    DiscoveredTopology,
)
from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort
from app.services.discovery_service import run_discovery_sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_topology() -> DiscoveredTopology:
    return DiscoveredTopology()


def _simple_topology(
    hub_id: str = "usb1",
    port_path: str = "1-1",
    drive_id: str = "SN-ABC123",
) -> DiscoveredTopology:
    hub = DiscoveredHub(system_identifier=hub_id, name="Test Hub")
    port = DiscoveredPort(
        hub_system_identifier=hub_id,
        port_number=1,
        system_path=port_path,
    )
    drive = DiscoveredDrive(
        device_identifier=drive_id,
        port_system_path=port_path,
        filesystem_path="/dev/sdb",
        capacity_bytes=64_000_000_000,
    )
    return DiscoveredTopology(hubs=[hub], ports=[port], drives=[drive])


# ---------------------------------------------------------------------------
# Initial sync — empty DB
# ---------------------------------------------------------------------------


def test_initial_sync_inserts_hub_port_drive(db):
    topology = _simple_topology()
    summary = run_discovery_sync(db, topology_source=lambda: topology)

    assert summary["hubs_upserted"] == 1
    assert summary["ports_upserted"] == 1
    assert summary["drives_inserted"] == 1
    assert summary["drives_updated"] == 0
    assert summary["drives_removed"] == 0

    hubs = db.query(UsbHub).all()
    assert len(hubs) == 1
    assert hubs[0].system_identifier == "usb1"

    ports = db.query(UsbPort).all()
    assert len(ports) == 1
    assert ports[0].system_path == "1-1"

    drives = db.query(UsbDrive).all()
    assert len(drives) == 1
    assert drives[0].device_identifier == "SN-ABC123"
    assert drives[0].current_state == DriveState.AVAILABLE
    assert drives[0].filesystem_path == "/dev/sdb"
    assert drives[0].capacity_bytes == 64_000_000_000


def test_initial_sync_no_hardware(db):
    summary = run_discovery_sync(db, topology_source=_empty_topology)

    assert summary["hubs_upserted"] == 0
    assert summary["drives_inserted"] == 0
    assert summary["drives_removed"] == 0

    assert db.query(UsbDrive).count() == 0


def test_initial_sync_emits_audit_log(db):
    summary = run_discovery_sync(db, actor="admin-user", topology_source=_empty_topology)

    logs = db.query(AuditLog).filter(AuditLog.action == "USB_DISCOVERY_SYNC").all()
    assert len(logs) == 1
    assert logs[0].user == "admin-user"
    assert logs[0].details["drives_inserted"] == 0


# ---------------------------------------------------------------------------
# Idempotency — running sync twice should not produce duplicate rows
# ---------------------------------------------------------------------------


def test_sync_is_idempotent(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology)
    summary2 = run_discovery_sync(db, topology_source=lambda: topology)

    assert summary2["drives_inserted"] == 0
    assert summary2["drives_updated"] == 0
    assert summary2["drives_removed"] == 0

    assert db.query(UsbDrive).count() == 1
    assert db.query(UsbHub).count() == 1
    assert db.query(UsbPort).count() == 1


# ---------------------------------------------------------------------------
# Update — hardware attributes change between syncs
# ---------------------------------------------------------------------------


def test_sync_updates_drive_filesystem_path(db):
    first = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: first)

    # Device re-enumerated to a different block node
    second = _simple_topology()
    second.drives[0].filesystem_path = "/dev/sdc"
    summary = run_discovery_sync(db, topology_source=lambda: second)

    assert summary["drives_updated"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.filesystem_path == "/dev/sdc"


def test_sync_updates_drive_capacity(db):
    first = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: first)

    second = _simple_topology()
    second.drives[0].capacity_bytes = 128_000_000_000
    summary = run_discovery_sync(db, topology_source=lambda: second)

    assert summary["drives_updated"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.capacity_bytes == 128_000_000_000


def test_sync_updates_hub_name(db):
    first = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: first)

    second = _simple_topology()
    second.hubs[0].name = "Updated Hub Name"
    run_discovery_sync(db, topology_source=lambda: second)

    hub = db.query(UsbHub).one()
    assert hub.name == "Updated Hub Name"


# ---------------------------------------------------------------------------
# Drive removal — device no longer present
# ---------------------------------------------------------------------------


def test_available_drive_removed_becomes_empty(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology)

    # Remove the drive from the hardware snapshot
    summary = run_discovery_sync(db, topology_source=_empty_topology)

    assert summary["drives_removed"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.EMPTY


def test_in_use_drive_removal_preserves_project(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology)

    # Manually set drive to IN_USE (simulating initialized state)
    drive = db.query(UsbDrive).one()
    drive.current_state = DriveState.IN_USE
    drive.current_project_id = "PROJ-001"
    db.commit()

    # Drive disappears from hardware
    summary = run_discovery_sync(db, topology_source=_empty_topology)

    assert summary["drives_removed"] == 0  # IN_USE drives are NOT removed
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.IN_USE
    assert drive.current_project_id == "PROJ-001"


def test_empty_drive_removal_stays_empty(db):
    """A drive already EMPTY that is absent from HW remains EMPTY."""
    # Insert an EMPTY drive directly (e.g. legacy record)
    drive = UsbDrive(device_identifier="LEGACY-001", current_state=DriveState.EMPTY)
    db.add(drive)
    db.commit()

    summary = run_discovery_sync(db, topology_source=_empty_topology)

    assert summary["drives_removed"] == 0
    db.refresh(drive)
    assert drive.current_state == DriveState.EMPTY


# ---------------------------------------------------------------------------
# Re-appearance — previously-removed drive reconnects
# ---------------------------------------------------------------------------


def test_empty_drive_reconnects_becomes_available(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology)

    # Remove the drive
    run_discovery_sync(db, topology_source=_empty_topology)
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.EMPTY

    # Reconnect
    summary = run_discovery_sync(db, topology_source=lambda: topology)
    assert summary["drives_updated"] == 1
    db.refresh(drive)
    assert drive.current_state == DriveState.AVAILABLE


# ---------------------------------------------------------------------------
# Multiple drives
# ---------------------------------------------------------------------------


def test_sync_handles_multiple_drives(db):
    hub = DiscoveredHub(system_identifier="usb1", name="Hub")
    port1 = DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")
    port2 = DiscoveredPort(hub_system_identifier="usb1", port_number=2, system_path="1-2")
    drive1 = DiscoveredDrive(device_identifier="SN-001", port_system_path="1-1", filesystem_path="/dev/sdb")
    drive2 = DiscoveredDrive(device_identifier="SN-002", port_system_path="1-2", filesystem_path="/dev/sdc")
    topology = DiscoveredTopology(hubs=[hub], ports=[port1, port2], drives=[drive1, drive2])

    summary = run_discovery_sync(db, topology_source=lambda: topology)

    assert summary["drives_inserted"] == 2
    assert db.query(UsbDrive).count() == 2

    # Remove one drive
    topology2 = DiscoveredTopology(hubs=[hub], ports=[port1], drives=[drive1])
    summary2 = run_discovery_sync(db, topology_source=lambda: topology2)

    assert summary2["drives_removed"] == 1
    remaining = (
        db.query(UsbDrive)
        .filter(UsbDrive.current_state == DriveState.AVAILABLE)
        .all()
    )
    assert len(remaining) == 1
    assert remaining[0].device_identifier == "SN-001"


# ---------------------------------------------------------------------------
# Port auto-creates hub when hub not present in topology
# ---------------------------------------------------------------------------


def test_port_without_hub_in_topology_auto_creates_hub(db):
    port = DiscoveredPort(hub_system_identifier="usb2", port_number=3, system_path="2-3")
    topology = DiscoveredTopology(ports=[port])

    run_discovery_sync(db, topology_source=lambda: topology)

    hubs = db.query(UsbHub).all()
    assert len(hubs) == 1
    assert hubs[0].system_identifier == "usb2"


# ---------------------------------------------------------------------------
# HTTP endpoint — POST /drives/refresh
# ---------------------------------------------------------------------------


def test_refresh_endpoint_requires_auth(unauthenticated_client):
    response = unauthenticated_client.post("/drives/refresh")
    assert response.status_code == 401


def test_refresh_endpoint_processor_forbidden(client):
    """Processor role is not allowed to trigger a refresh."""
    response = client.post("/drives/refresh")
    assert response.status_code == 403


def test_refresh_endpoint_manager_succeeds(manager_client, db, monkeypatch):
    monkeypatch.setattr(
        "app.services.discovery_service.discover_usb_topology",
        _empty_topology,
    )
    response = manager_client.post("/drives/refresh")
    assert response.status_code == 200
    data = response.json()
    assert "drives_inserted" in data


def test_refresh_endpoint_admin_succeeds(admin_client, db, monkeypatch):
    monkeypatch.setattr(
        "app.services.discovery_service.discover_usb_topology",
        _empty_topology,
    )
    response = admin_client.post("/drives/refresh")
    assert response.status_code == 200
    data = response.json()
    assert "hubs_upserted" in data
    assert "ports_upserted" in data
    assert "drives_inserted" in data
    assert "drives_updated" in data
    assert "drives_removed" in data
