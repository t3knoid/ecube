"""Tests for Hub & Port Identification Enrichment (issue #100).

Covers:
- Discovery enrichment (vendor_id, product_id, speed)
- Preservation of admin-assigned labels during re-sync
- Repository label update methods
- GET /admin/hubs, PATCH /admin/hubs/{hub_id}
- PATCH /admin/ports/{port_id}/label
- Auth enforcement and audit logging
"""

from __future__ import annotations

from app.infrastructure.usb_discovery import (
    DiscoveredHub,
    DiscoveredPort,
    DiscoveredTopology,
)
from app.models.audit import AuditLog
from app.models.hardware import UsbHub, UsbPort
from app.repositories.hardware_repository import HubRepository, PortRepository
from app.services.discovery_service import run_discovery_sync


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NullDetector:
    def detect(self, device_path: str) -> str:
        return "unformatted"


_NULL_DETECTOR = _NullDetector()


def _enriched_topology() -> DiscoveredTopology:
    hub = DiscoveredHub(
        system_identifier="usb1",
        name="xHCI Host Controller",
        vendor_id="8086",
        product_id="a36d",
    )
    port = DiscoveredPort(
        hub_system_identifier="usb1",
        port_number=1,
        system_path="1-1",
        vendor_id="0781",
        product_id="5583",
        speed="5000",
    )
    return DiscoveredTopology(hubs=[hub], ports=[port])


def _seed_hub(db) -> UsbHub:
    hub = UsbHub(name="Test Hub", system_identifier="usb-enrich-1")
    db.add(hub)
    db.commit()
    db.refresh(hub)
    return hub


def _seed_port(db, hub: UsbHub) -> UsbPort:
    port = UsbPort(hub_id=hub.id, port_number=1, system_path="1-1")
    db.add(port)
    db.commit()
    db.refresh(port)
    return port


# ---------------------------------------------------------------------------
# Discovery enrichment — new sysfs fields populated
# ---------------------------------------------------------------------------


def test_discovery_populates_hub_vendor_product(db):
    """vendor_id and product_id are written on hub during discovery."""
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    hub = db.query(UsbHub).one()
    assert hub.vendor_id == "8086"
    assert hub.product_id == "a36d"


def test_discovery_populates_port_vendor_product_speed(db):
    """vendor_id, product_id, and speed are written on port during discovery."""
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    port = db.query(UsbPort).one()
    assert port.vendor_id == "0781"
    assert port.product_id == "5583"
    assert port.speed == "5000"


# ---------------------------------------------------------------------------
# Discovery preserves admin-assigned labels
# ---------------------------------------------------------------------------


def test_discovery_preserves_location_hint(db):
    """Re-sync must not overwrite an admin-set location_hint."""
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    hub = db.query(UsbHub).one()
    hub.location_hint = "Rear panel – PCIe card"
    db.commit()

    # Re-sync — location_hint should survive.
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    db.refresh(hub)
    assert hub.location_hint == "Rear panel – PCIe card"


def test_discovery_preserves_friendly_label(db):
    """Re-sync must not overwrite an admin-set friendly_label."""
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    port = db.query(UsbPort).one()
    port.friendly_label = "Bay 1 – Top Left"
    db.commit()

    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    db.refresh(port)
    assert port.friendly_label == "Bay 1 – Top Left"


# ---------------------------------------------------------------------------
# Discovery updates enrichment fields on re-sync
# ---------------------------------------------------------------------------


def test_discovery_updates_vendor_on_resync(db):
    """If vendor_id changes in sysfs, discovery updates the stored value."""
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )

    def _updated_topology():
        hub = DiscoveredHub(
            system_identifier="usb1",
            name="xHCI Host Controller",
            vendor_id="1b21",
            product_id="2142",
        )
        port = DiscoveredPort(
            hub_system_identifier="usb1",
            port_number=1,
            system_path="1-1",
            vendor_id="abcd",
            product_id="1234",
            speed="480",
        )
        return DiscoveredTopology(hubs=[hub], ports=[port])

    run_discovery_sync(
        db,
        topology_source=_updated_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    hub = db.query(UsbHub).one()
    assert hub.vendor_id == "1b21"
    assert hub.product_id == "2142"
    port = db.query(UsbPort).one()
    assert port.vendor_id == "abcd"
    assert port.product_id == "1234"
    assert port.speed == "480"


# ---------------------------------------------------------------------------
# Repository — label update methods
# ---------------------------------------------------------------------------


def test_hub_repo_update_location_hint(db):
    hub = _seed_hub(db)
    result = HubRepository(db).update_location_hint(hub.id, "Front panel")
    assert result is not None
    assert result.location_hint == "Front panel"


def test_hub_repo_update_location_hint_missing(db):
    result = HubRepository(db).update_location_hint(99999, "Nowhere")
    assert result is None


def test_port_repo_update_friendly_label(db):
    hub = _seed_hub(db)
    port = _seed_port(db, hub)
    result = PortRepository(db).update_friendly_label(port.id, "Bay 3")
    assert result is not None
    assert result.friendly_label == "Bay 3"


def test_port_repo_update_friendly_label_missing(db):
    result = PortRepository(db).update_friendly_label(99999, "Nowhere")
    assert result is None


# ---------------------------------------------------------------------------
# GET /admin/hubs
# ---------------------------------------------------------------------------


def test_list_hubs_requires_auth(unauthenticated_client):
    response = unauthenticated_client.get("/admin/hubs")
    assert response.status_code == 401


def test_list_hubs_processor_forbidden(client):
    response = client.get("/admin/hubs")
    assert response.status_code == 403


def test_list_hubs_admin_succeeds(admin_client, db):
    hub = _seed_hub(db)
    response = admin_client.get("/admin/hubs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert any(h["system_identifier"] == hub.system_identifier for h in data)


def test_list_hubs_manager_succeeds(manager_client, db):
    _seed_hub(db)
    response = manager_client.get("/admin/hubs")
    assert response.status_code == 200


def test_list_hubs_returns_enriched_fields(admin_client, db):
    hub = UsbHub(
        name="Intel xHCI",
        system_identifier="usb-enriched",
        vendor_id="8086",
        product_id="a36d",
    )
    db.add(hub)
    db.commit()

    response = admin_client.get("/admin/hubs")
    assert response.status_code == 200
    data = response.json()
    enriched = [h for h in data if h["system_identifier"] == "usb-enriched"][0]
    assert enriched["vendor_id"] == "8086"
    assert enriched["product_id"] == "a36d"


# ---------------------------------------------------------------------------
# PATCH /admin/hubs/{hub_id}
# ---------------------------------------------------------------------------


def test_update_hub_label_requires_auth(unauthenticated_client):
    response = unauthenticated_client.patch(
        "/admin/hubs/1", json={"location_hint": "Test"}
    )
    assert response.status_code == 401


def test_update_hub_label_processor_forbidden(client, db):
    hub = _seed_hub(db)
    response = client.patch(
        f"/admin/hubs/{hub.id}", json={"location_hint": "Test"}
    )
    assert response.status_code == 403


def test_update_hub_label_not_found(admin_client):
    response = admin_client.patch(
        "/admin/hubs/99999", json={"location_hint": "Nowhere"}
    )
    assert response.status_code == 404


def test_update_hub_label_admin_succeeds(admin_client, db):
    hub = _seed_hub(db)
    response = admin_client.patch(
        f"/admin/hubs/{hub.id}",
        json={"location_hint": "Rear panel – PCIe card"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["location_hint"] == "Rear panel – PCIe card"


def test_update_hub_label_manager_succeeds(manager_client, db):
    hub = _seed_hub(db)
    response = manager_client.patch(
        f"/admin/hubs/{hub.id}",
        json={"location_hint": "Front panel"},
    )
    assert response.status_code == 200
    assert response.json()["location_hint"] == "Front panel"


def test_update_hub_label_creates_audit_log(admin_client, db):
    hub = _seed_hub(db)
    hub.location_hint = "Old label"
    db.commit()

    admin_client.patch(
        f"/admin/hubs/{hub.id}",
        json={"location_hint": "New label"},
    )

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "HUB_LABEL_UPDATED")
        .first()
    )
    assert log is not None
    assert log.user == "admin-user"
    assert log.details["hub_id"] == hub.id
    assert log.details["field"] == "location_hint"
    assert log.details["old_value"] == "Old label"
    assert log.details["new_value"] == "New label"
    assert log.details["path"] == f"/admin/hubs/{hub.id}"


# ---------------------------------------------------------------------------
# PATCH /admin/ports/{port_id}/label
# ---------------------------------------------------------------------------


def test_update_port_label_requires_auth(unauthenticated_client):
    response = unauthenticated_client.patch(
        "/admin/ports/1/label", json={"friendly_label": "Test"}
    )
    assert response.status_code == 401


def test_update_port_label_processor_forbidden(client, db):
    hub = _seed_hub(db)
    port = _seed_port(db, hub)
    response = client.patch(
        f"/admin/ports/{port.id}/label", json={"friendly_label": "Test"}
    )
    assert response.status_code == 403


def test_update_port_label_not_found(admin_client):
    response = admin_client.patch(
        "/admin/ports/99999/label", json={"friendly_label": "Nowhere"}
    )
    assert response.status_code == 404


def test_update_port_label_admin_succeeds(admin_client, db):
    hub = _seed_hub(db)
    port = _seed_port(db, hub)
    response = admin_client.patch(
        f"/admin/ports/{port.id}/label",
        json={"friendly_label": "Bay 1 – Top Left"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["friendly_label"] == "Bay 1 – Top Left"


def test_update_port_label_manager_succeeds(manager_client, db):
    hub = _seed_hub(db)
    port = _seed_port(db, hub)
    response = manager_client.patch(
        f"/admin/ports/{port.id}/label",
        json={"friendly_label": "Bay 2"},
    )
    assert response.status_code == 200
    assert response.json()["friendly_label"] == "Bay 2"


def test_update_port_label_creates_audit_log(admin_client, db):
    hub = _seed_hub(db)
    port = _seed_port(db, hub)
    port.friendly_label = "Old label"
    db.commit()

    admin_client.patch(
        f"/admin/ports/{port.id}/label",
        json={"friendly_label": "New label"},
    )

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "PORT_LABEL_UPDATED")
        .first()
    )
    assert log is not None
    assert log.user == "admin-user"
    assert log.details["port_id"] == port.id
    assert log.details["field"] == "friendly_label"
    assert log.details["old_value"] == "Old label"
    assert log.details["new_value"] == "New label"
    assert log.details["path"] == f"/admin/ports/{port.id}/label"


# ---------------------------------------------------------------------------
# GET /admin/ports returns enriched fields
# ---------------------------------------------------------------------------


def test_list_ports_returns_enriched_fields(admin_client, db):
    hub = _seed_hub(db)
    port = UsbPort(
        hub_id=hub.id,
        port_number=1,
        system_path="1-1",
        vendor_id="0781",
        product_id="5583",
        speed="5000",
    )
    db.add(port)
    db.commit()

    response = admin_client.get("/admin/ports")
    assert response.status_code == 200
    data = response.json()
    enriched = [p for p in data if p["system_path"] == "1-1"][0]
    assert enriched["vendor_id"] == "0781"
    assert enriched["product_id"] == "5583"
    assert enriched["speed"] == "5000"


# ---------------------------------------------------------------------------
# Empty sysfs attributes must not overwrite stored values
# ---------------------------------------------------------------------------


def test_empty_sysfs_attrs_do_not_overwrite_stored_values(db):
    """When sysfs returns empty strings for vendor/product/speed, previously
    stored non-empty values must be preserved (empty → None normalisation)."""
    # First sync — store real enrichment data.
    run_discovery_sync(
        db,
        topology_source=_enriched_topology,
        filesystem_detector=_NULL_DETECTOR,
    )
    hub = db.query(UsbHub).one()
    assert hub.vendor_id == "8086"
    port = db.query(UsbPort).one()
    assert port.vendor_id == "0781"
    assert port.speed == "5000"

    # Second sync — sysfs attributes are now None (simulating empty files).
    def _empty_attrs_topology():
        h = DiscoveredHub(
            system_identifier="usb1",
            name="xHCI Host Controller",
            vendor_id=None,
            product_id=None,
        )
        p = DiscoveredPort(
            hub_system_identifier="usb1",
            port_number=1,
            system_path="1-1",
            vendor_id=None,
            product_id=None,
            speed=None,
        )
        return DiscoveredTopology(hubs=[h], ports=[p])

    run_discovery_sync(
        db,
        topology_source=_empty_attrs_topology,
        filesystem_detector=_NULL_DETECTOR,
    )

    db.refresh(hub)
    db.refresh(port)
    # Values must survive — None from discovery should not clobber them.
    assert hub.vendor_id == "8086"
    assert hub.product_id == "a36d"
    assert port.vendor_id == "0781"
    assert port.product_id == "5583"
    assert port.speed == "5000"


def test_read_sysfs_attr_empty_file_returns_none(tmp_path):
    """_read_sysfs_attr must return None for an empty attribute file."""
    from app.infrastructure.usb_discovery import _read_sysfs_attr

    # Create an empty file.
    attr_file = tmp_path / "idVendor"
    attr_file.write_text("")

    result = _read_sysfs_attr(str(tmp_path), "idVendor")
    assert result is None


def test_read_sysfs_attr_whitespace_only_returns_none(tmp_path):
    """_read_sysfs_attr must return None for a whitespace-only file."""
    from app.infrastructure.usb_discovery import _read_sysfs_attr

    attr_file = tmp_path / "idVendor"
    attr_file.write_text("   \n")

    result = _read_sysfs_attr(str(tmp_path), "idVendor")
    assert result is None


def test_read_sysfs_attr_nonempty_returns_stripped(tmp_path):
    """_read_sysfs_attr returns stripped content for normal files."""
    from app.infrastructure.usb_discovery import _read_sysfs_attr

    attr_file = tmp_path / "idVendor"
    attr_file.write_text("0781\n")

    result = _read_sysfs_attr(str(tmp_path), "idVendor")
    assert result == "0781"
