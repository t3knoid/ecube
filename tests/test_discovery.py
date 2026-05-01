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
from app.utils.drive_identity import (
    build_persistent_device_identifier,
    build_readable_device_label,
    extract_usb_serial_number,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_topology() -> DiscoveredTopology:
    return DiscoveredTopology()


class _NullDetector:
    """Lightweight no-op filesystem detector for hermetic tests."""

    def detect(self, device_path: str) -> str:
        return "unformatted"


_NULL_DETECTOR = _NullDetector()


def _enable_all_ports(db) -> None:
    """Enable all ports in the DB so drives can transition to AVAILABLE."""
    for port in db.query(UsbPort).all():
        port.enabled = True
    db.commit()


def _simple_topology(
    hub_id: str = "usb1",
    port_path: str = "1-1",
    drive_id: str = "SN-ABC123",
) -> DiscoveredTopology:
    hub = DiscoveredHub(system_identifier=hub_id, name="Test Hub", vendor_id="1d6b", product_id="0002")
    port = DiscoveredPort(
        hub_system_identifier=hub_id,
        port_number=1,
        system_path=port_path,
        vendor_id="0781",
        product_id="5583",
        speed="5000",
    )
    drive = DiscoveredDrive(
        device_identifier=drive_id,
        port_system_path=port_path,
        filesystem_path="/dev/sdb",
        capacity_bytes=64_000_000_000,
        manufacturer="SanDisk",
        product_name="Ultra",
        speed="5000",
    )
    return DiscoveredTopology(hubs=[hub], ports=[port], drives=[drive])


# ---------------------------------------------------------------------------
# Initial sync — empty DB
# ---------------------------------------------------------------------------


def test_initial_sync_inserts_hub_port_drive(db):
    topology = _simple_topology()
    # First sync discovers ports (disabled by default) — drives inserted as EMPTY.
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    # Re-sync to transition drives to AVAILABLE on enabled ports.
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    # Summary contract: second pass updates the existing drive, no new inserts.
    assert summary["hubs_upserted"] == 1
    assert summary["drives_inserted"] == 0
    assert summary["drives_updated"] == 1
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
    summary = run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["hubs_upserted"] == 0
    assert summary["drives_inserted"] == 0
    assert summary["drives_removed"] == 0

    assert db.query(UsbDrive).count() == 0


def test_initial_sync_emits_audit_log(db):
    summary = run_discovery_sync(db, actor="admin-user", topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    logs = db.query(AuditLog).filter(AuditLog.action == "USB_DISCOVERY_SYNC").all()
    assert len(logs) == 1
    assert logs[0].user == "admin-user"
    assert logs[0].details["drives_inserted"] == 0


def test_initial_sync_audit_includes_safe_drive_metadata_shape(db):
    run_discovery_sync(db, actor="admin-user", topology_source=_simple_topology, filesystem_detector=_NULL_DETECTOR)

    log = db.query(AuditLog).filter(AuditLog.action == "USB_DISCOVERY_SYNC").order_by(AuditLog.id.desc()).first()
    assert log is not None
    observed = log.details["observed_drives"]
    assert len(observed) == 1
    assert observed[0]["device_label"] == "SanDisk Ultra - Port 1 (60GB)"
    assert observed[0]["manufacturer"] == "SanDisk"
    assert observed[0]["product_name"] == "Ultra"
    assert observed[0]["port_number"] == 1
    assert observed[0]["speed"] == "5000"
    assert observed[0]["serial_number_present"] is True
    assert observed[0]["serial_number_masked"].endswith("C123")
    assert "filesystem_path" not in observed[0]


def test_initial_sync_emits_drive_discovered_audit_log(db):
    run_discovery_sync(db, actor="admin-user", topology_source=_simple_topology, filesystem_detector=_NULL_DETECTOR)

    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_DISCOVERED").one()
    drive = db.query(UsbDrive).one()
    assert log.user == "admin-user"
    assert log.drive_id == drive.id
    assert log.details["drive_id"] == drive.id
    assert log.details["device_identifier"] == drive.device_identifier
    assert log.details["device_label"] == "SanDisk Ultra - Port 1 (60GB)"
    assert log.details["filesystem_path"] == "[redacted]"
    assert log.details["filesystem_type"] == "unformatted"
    assert log.details["capacity_bytes"] == 64_000_000_000
    assert log.details["port_number"] == 1
    assert log.details["vendor_id"] == "0781"
    assert log.details["product_id"] == "5583"
    assert log.details["speed"] == "5000"
    assert log.details["discovery_actor"] == "admin-user"
    assert log.details["serial_number_masked"].endswith("C123")
    assert log.details["discovered_at"]


def test_initial_sync_drive_discovered_audit_handles_missing_optional_fields(db):
    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Test Hub")],
        ports=[DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")],
        drives=[DiscoveredDrive(device_identifier="SN-NOMETA", port_system_path="1-1")],
    )

    run_discovery_sync(db, actor="admin-user", topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_DISCOVERED").one()
    assert log.details["manufacturer"] is None
    assert log.details["product_name"] is None
    assert log.details["filesystem_path"] is None
    assert log.details["filesystem_type"] is None
    assert log.details["capacity_bytes"] is None
    assert log.details["vendor_id"] is None
    assert log.details["product_id"] is None
    assert log.details["speed"] is None


def test_build_readable_device_label_appends_scaled_capacity_suffix():
    assert (
        build_readable_device_label(
            "General",
            "USB Flash Disk",
            2,
            capacity_bytes=32_000_000_000,
        )
        == "General USB Flash Disk - Port 2 (30GB)"
    )
    assert (
        build_readable_device_label(
            "Archive",
            "Drive",
            3,
            capacity_bytes=2 * 1024 ** 4,
        )
        == "Archive Drive - Port 3 (2TB)"
    )


def test_legacy_serial_identifier_is_upgraded_to_composite_identifier(db):
    legacy = UsbDrive(device_identifier="SN-ABC123", current_state=DriveState.DISCONNECTED)
    db.add(legacy)
    db.commit()

    composite_identifier = build_persistent_device_identifier(
        "0781",
        "5583",
        "SN-ABC123",
        "1-1",
    )
    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Test Hub", vendor_id="1d6b", product_id="0002")],
        ports=[DiscoveredPort(
            hub_system_identifier="usb1",
            port_number=1,
            system_path="1-1",
            vendor_id="0781",
            product_id="5583",
            speed="5000",
        )],
        drives=[DiscoveredDrive(
            device_identifier=composite_identifier,
            port_system_path="1-1",
            filesystem_path="/dev/sdb",
            capacity_bytes=64_000_000_000,
            manufacturer="SanDisk",
            product_name="Ultra",
            speed="5000",
        )],
    )

    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_inserted"] == 0
    assert summary["drives_updated"] == 1
    assert db.query(UsbDrive).count() == 1

    drive = db.query(UsbDrive).one()
    assert drive.device_identifier == composite_identifier
    assert drive.serial_number == "SN-ABC123"


def test_extract_usb_serial_number_from_composite_identifier():
    identifier = build_persistent_device_identifier(
        "090c",
        "1000",
        "0414150000001328",
        "2-2",
    )

    assert extract_usb_serial_number(identifier, port_system_path="2-2") == "0414150000001328"


def test_sync_does_not_duplicate_drive_discovered_audit_for_unchanged_drive(db):
    topology = _simple_topology()
    run_discovery_sync(db, actor="admin-user", topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    run_discovery_sync(db, actor="admin-user", topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    assert db.query(AuditLog).filter(AuditLog.action == "DRIVE_DISCOVERED").count() == 1


def test_initial_sync_continues_when_drive_discovered_audit_write_fails(db, monkeypatch):
    from app.repositories.audit_repository import AuditRepository

    original_add = AuditRepository.add

    def flaky_add(self, action, *args, **kwargs):
        if action == "DRIVE_DISCOVERED":
            raise RuntimeError("audit unavailable")
        return original_add(self, action, *args, **kwargs)

    monkeypatch.setattr(AuditRepository, "add", flaky_add)

    summary = run_discovery_sync(
        db,
        actor="admin-user",
        topology_source=_simple_topology,
        filesystem_detector=_NULL_DETECTOR,
    )

    assert summary["drives_inserted"] == 1
    assert db.query(UsbDrive).count() == 1
    assert db.query(AuditLog).filter(AuditLog.action == "USB_DISCOVERY_SYNC").count() == 1


def test_initial_sync_emits_app_log_lines(db, caplog):
    caplog.set_level("INFO")

    run_discovery_sync(db, actor="admin-user", topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    messages = [record.getMessage() for record in caplog.records]
    assert any("USB discovery sync started" in message for message in messages)
    assert any("USB discovery sync completed" in message for message in messages)

    start_record = next(record for record in caplog.records if record.getMessage() == "USB discovery sync started")
    completed_record = next(record for record in caplog.records if record.getMessage() == "USB discovery sync completed")
    assert start_record.actor == "admin-user"
    assert completed_record.actor == "admin-user"


# ---------------------------------------------------------------------------
# Idempotency — running sync twice should not produce duplicate rows
# ---------------------------------------------------------------------------


def test_sync_is_idempotent(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    summary2 = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

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
    run_discovery_sync(db, topology_source=lambda: first, filesystem_detector=_NULL_DETECTOR)

    # Device re-enumerated to a different block node
    second = _simple_topology()
    second.drives[0].filesystem_path = "/dev/sdc"
    summary = run_discovery_sync(db, topology_source=lambda: second, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_updated"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.filesystem_path == "/dev/sdc"


def test_sync_updates_drive_capacity(db):
    first = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: first, filesystem_detector=_NULL_DETECTOR)

    second = _simple_topology()
    second.drives[0].capacity_bytes = 128_000_000_000
    summary = run_discovery_sync(db, topology_source=lambda: second, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_updated"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.capacity_bytes == 128_000_000_000


def test_sync_updates_hub_name(db):
    first = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: first, filesystem_detector=_NULL_DETECTOR)

    second = _simple_topology()
    second.hubs[0].name = "Updated Hub Name"
    run_discovery_sync(db, topology_source=lambda: second, filesystem_detector=_NULL_DETECTOR)

    hub = db.query(UsbHub).one()
    assert hub.name == "Updated Hub Name"


# ---------------------------------------------------------------------------
# Drive removal — device no longer present
# ---------------------------------------------------------------------------


def test_available_drive_removed_becomes_empty(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    # Remove the drive from the hardware snapshot
    summary = run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_removed"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.DISCONNECTED


def test_available_drive_removed_clears_stale_filesystem_path(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    drive = db.query(UsbDrive).one()
    assert drive.filesystem_path == "/dev/sdb"

    run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED
    assert drive.filesystem_path is None
    assert drive.mount_path is None


def test_available_drive_removed_emits_audit(db):
    """DRIVE_REMOVED audit entry is created when an AVAILABLE drive disappears."""
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    drive = db.query(UsbDrive).one()

    run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DRIVE_REMOVED")
        .first()
    )
    assert log is not None
    assert log.details["drive_id"] == drive.id
    assert log.details["device_identifier"] == drive.device_identifier


def test_in_use_drive_removal_preserves_project(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    # Manually set drive to IN_USE (simulating initialized state)
    drive = db.query(UsbDrive).one()
    drive.current_state = DriveState.IN_USE
    drive.current_project_id = "PROJ-001"
    db.commit()

    # Drive disappears from hardware
    summary = run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_removed"] == 0  # IN_USE drives are NOT removed
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.IN_USE
    assert drive.current_project_id == "PROJ-001"


def test_empty_drive_removal_stays_empty(db):
    """A drive already EMPTY that is absent from HW remains EMPTY."""
    # Insert an EMPTY drive directly (e.g. legacy record)
    drive = UsbDrive(device_identifier="LEGACY-001", current_state=DriveState.DISCONNECTED)
    db.add(drive)
    db.commit()

    summary = run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_removed"] == 0
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED


# ---------------------------------------------------------------------------
# Re-appearance — previously-removed drive reconnects
# ---------------------------------------------------------------------------


def test_empty_drive_reconnects_becomes_available(db):
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    # Remove the drive
    run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.DISCONNECTED

    # Reconnect
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
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

    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    assert db.query(UsbDrive).count() == 2

    # Remove one drive
    topology2 = DiscoveredTopology(hubs=[hub], ports=[port1], drives=[drive1])
    summary2 = run_discovery_sync(db, topology_source=lambda: topology2, filesystem_detector=_NULL_DETECTOR)

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

    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

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
    monkeypatch.setattr(
        "app.routers.drives.get_filesystem_detector",
        lambda: _NULL_DETECTOR,
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
    monkeypatch.setattr(
        "app.routers.drives.get_filesystem_detector",
        lambda: _NULL_DETECTOR,
    )
    response = admin_client.post("/drives/refresh")
    assert response.status_code == 200
    data = response.json()
    assert "hubs_upserted" in data
    assert "ports_upserted" in data
    assert "drives_inserted" in data
    assert "drives_updated" in data
    assert "drives_removed" in data


# ---------------------------------------------------------------------------
# Port enablement — drives on disabled ports
# ---------------------------------------------------------------------------


def test_new_drive_on_disabled_port_inserted_as_empty(db):
    """A newly discovered drive on a disabled port should be EMPTY, not AVAILABLE."""
    topology = _simple_topology()
    # Port defaults to enabled=False, so all new ports are disabled.
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_inserted"] == 1
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.DISCONNECTED
    assert drive.filesystem_path == "/dev/sdb"


def test_new_drive_on_enabled_port_inserted_as_available(db):
    """A newly discovered drive on an enabled port should be AVAILABLE."""
    topology = _simple_topology()
    # First sync to create the port (disabled by default).
    run_discovery_sync(db, topology_source=lambda: _simple_topology(drive_id="TEMP"), filesystem_detector=_NULL_DETECTOR)

    # Enable the port.
    port = db.query(UsbPort).one()
    port.enabled = True
    db.commit()

    # Now sync with the actual drive — should be AVAILABLE.
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    assert summary["drives_inserted"] == 1
    drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "SN-ABC123").one()
    assert drive.current_state == DriveState.AVAILABLE


def test_reconnecting_drive_on_disabled_port_stays_empty(db):
    """A drive reconnecting to a disabled port should stay EMPTY."""
    topology = _simple_topology()

    # Create port as enabled so the drive gets AVAILABLE.
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    port = db.query(UsbPort).one()
    port.enabled = True
    db.commit()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.AVAILABLE

    # Remove the drive (becomes EMPTY).
    run_discovery_sync(db, topology_source=_empty_topology, filesystem_detector=_NULL_DETECTOR)
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED

    # Disable the port.
    port.enabled = False
    db.commit()

    # Reconnect the drive — should stay EMPTY because port is disabled.
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED


def test_existing_tests_still_pass_with_enabled_port(db):
    """The original test_initial_sync flow works when port is enabled."""
    topology = _simple_topology()
    # Pre-create the port as enabled.
    run_discovery_sync(db, topology_source=lambda: _simple_topology(drive_id="SEED"), filesystem_detector=_NULL_DETECTOR)
    port = db.query(UsbPort).one()
    port.enabled = True
    db.commit()

    # Run the original scenario — drive should get AVAILABLE.
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "SN-ABC123").one()
    assert drive.current_state == DriveState.AVAILABLE


def test_disabled_port_drive_reconciles_to_available_when_reenabled_and_mounted_without_project(db):
    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Test Hub", vendor_id="1d6b", product_id="0002")],
        ports=[DiscoveredPort(
            hub_system_identifier="usb1",
            port_number=1,
            system_path="1-1",
            vendor_id="0781",
            product_id="5583",
            speed="5000",
        )],
        drives=[DiscoveredDrive(
            device_identifier="SN-MOUNTED-REENABLE",
            port_system_path="1-1",
            filesystem_path="/dev/sdb",
            mount_path="/media/ecube/usb-mounted",
            capacity_bytes=64_000_000_000,
            manufacturer="SanDisk",
            product_name="Ultra",
            speed="5000",
        )],
    )

    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "SN-MOUNTED-REENABLE").one()
    assert drive.current_state == DriveState.DISCONNECTED

    port = db.query(UsbPort).one()
    port.enabled = True
    db.commit()

    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    db.refresh(drive)
    assert summary["drives_updated"] == 1
    assert drive.current_state == DriveState.AVAILABLE
    assert drive.current_project_id is None
    assert drive.mount_path == "/media/ecube/usb-mounted"


def test_disabled_port_drive_reconciles_to_in_use_when_reenabled_and_mounted_with_project(db):
    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Test Hub", vendor_id="1d6b", product_id="0002")],
        ports=[DiscoveredPort(
            hub_system_identifier="usb1",
            port_number=1,
            system_path="1-1",
            vendor_id="0781",
            product_id="5583",
            speed="5000",
        )],
        drives=[DiscoveredDrive(
            device_identifier="SN-MOUNTED-BOUND",
            port_system_path="1-1",
            filesystem_path="/dev/sdb",
            mount_path="/media/ecube/usb-mounted",
            capacity_bytes=64_000_000_000,
            manufacturer="SanDisk",
            product_name="Ultra",
            speed="5000",
        )],
    )

    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "SN-MOUNTED-BOUND").one()
    assert drive.current_state == DriveState.DISCONNECTED

    drive.current_project_id = "PROJ-BOUND"
    db.commit()

    port = db.query(UsbPort).one()
    port.enabled = True
    db.commit()

    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)

    db.refresh(drive)
    assert summary["drives_updated"] == 1
    assert drive.current_state == DriveState.IN_USE
    assert drive.current_project_id == "PROJ-BOUND"
    assert drive.mount_path == "/media/ecube/usb-mounted"


def test_available_drive_demoted_when_port_disabled(db):
    """An AVAILABLE drive on a port that is later disabled should become EMPTY."""
    topology = _simple_topology()
    # First sync creates port (disabled by default) + drive (EMPTY).
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    # Second sync promotes the drive to AVAILABLE.
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.AVAILABLE

    # Disable the port while the drive is still physically present.
    port = db.query(UsbPort).one()
    port.enabled = False
    db.commit()

    # Next sync should demote the drive to EMPTY.
    summary = run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED
    assert summary["drives_updated"] == 1


def test_in_use_drive_not_demoted_when_port_disabled(db):
    """An IN_USE drive must stay IN_USE even if the port is disabled."""
    topology = _simple_topology()
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    _enable_all_ports(db)
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    drive = db.query(UsbDrive).one()
    assert drive.current_state == DriveState.AVAILABLE

    # Simulate the drive being assigned to a job.
    drive.current_state = DriveState.IN_USE
    drive.current_project_id = "PROJ-001"
    db.commit()

    # Disable the port.
    port = db.query(UsbPort).one()
    port.enabled = False
    db.commit()

    # Sync should leave IN_USE untouched.
    run_discovery_sync(db, topology_source=lambda: topology, filesystem_detector=_NULL_DETECTOR)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE
    assert drive.current_project_id == "PROJ-001"
