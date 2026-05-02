"""USB discovery and drive-state refresh service.

This module orchestrates reading the current USB hardware topology and
synchronising it with the persisted database state.  It is the single
authoritative place where drive state transitions driven by hardware events
are evaluated and recorded.

Drive FSM transitions applied during a refresh:

+------------------+----------------------------+-------------------+
| Observed         | Current DB state           | New DB state      |
+==================+============================+===================+
| Present in HW    | EMPTY (previously removed) | AVAILABLE         |
| Present in HW    | AVAILABLE                  | AVAILABLE (kept)  |
| Present in HW    | IN_USE                     | IN_USE (kept)     |
+------------------+----------------------------+-------------------+
| Absent from HW   | AVAILABLE                  | EMPTY             |
| Absent from HW   | EMPTY                      | EMPTY (kept)      |
| Absent from HW   | IN_USE                     | IN_USE (kept –    |
|                  |                            | project isolation)|
+------------------+----------------------------+-------------------+

The refresh is idempotent: running it multiple times without hardware changes
produces no state mutations.

Operational notes
=================

Hub auto-creation:
  When a port is discovered but its parent hub is not present in the topology
  snapshot (e.g. due to sysfs race conditions or partial enumeration), a
  placeholder hub is automatically created with a default name matching the
  hub system identifier. This ensures port-to-hub relationships remain intact
  and avoids foreign-key violations. The placeholder hub name can be manually
  updated via the hub management API when the hub is fully enumerated.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.infrastructure.usb_discovery import DiscoveredTopology
from app.infrastructure import FilesystemDetector
from app.models.hardware import DriveState, UsbDrive, UsbPort
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.hardware_repository import HubRepository, PortRepository
from app.utils.drive_identity import (
    build_readable_device_label,
    extract_usb_serial_number,
    is_persistent_device_identifier,
    mask_serial_number,
)
from app.utils.sanitize import normalize_project_id

logger = logging.getLogger(__name__)


def _serial_number_from_identifier(device_identifier: Optional[str], port_system_path: Optional[str]) -> Optional[str]:
    return extract_usb_serial_number(
        device_identifier,
        port_system_path=port_system_path,
    )


def _build_discovered_drive_metadata(discovered_drive, discovered_port=None, *, drive_id: Optional[int] = None) -> dict:
    port_number = discovered_port.port_number if discovered_port else None
    speed = discovered_drive.speed or (discovered_port.speed if discovered_port else None)
    serial_number = _serial_number_from_identifier(
        discovered_drive.device_identifier,
        discovered_drive.port_system_path,
    )
    return {
        "drive_id": drive_id,
        "device_label": build_readable_device_label(
            discovered_drive.manufacturer,
            discovered_drive.product_name,
            port_number,
            capacity_bytes=discovered_drive.capacity_bytes,
            fallback_label=discovered_drive.port_system_path or "USB Drive",
        ),
        "manufacturer": discovered_drive.manufacturer,
        "product_name": discovered_drive.product_name,
        "port_number": port_number,
        "speed": speed,
        "serial_number_present": bool(serial_number),
        "serial_number_masked": mask_serial_number(serial_number),
    }


def _build_persisted_drive_metadata(drive: UsbDrive) -> dict:
    return {
        "drive_id": drive.id,
        "device_label": drive.display_device_label,
        "manufacturer": drive.manufacturer,
        "product_name": drive.product_name,
        "port_number": drive.port_number,
        "speed": drive.speed,
        "serial_number_present": bool(drive.serial_number),
        "serial_number_masked": mask_serial_number(drive.serial_number),
    }


def _build_drive_discovered_audit_details(drive: UsbDrive, *, actor: Optional[str] = None) -> dict:
    port = drive.port
    hub = port.hub if port else None
    return {
        "drive_id": drive.id,
        "device_identifier": drive.device_identifier,
        "device_label": drive.display_device_label,
        "manufacturer": drive.manufacturer,
        "product_name": drive.product_name,
        "filesystem_path": drive.filesystem_path,
        "filesystem_type": drive.filesystem_type,
        "capacity_bytes": drive.capacity_bytes,
        "port_id": port.id if port else None,
        "port_number": port.port_number if port else None,
        "port_system_path": port.system_path if port else None,
        "hub_id": hub.id if hub else None,
        "vendor_id": (port.vendor_id if port and port.vendor_id else (hub.vendor_id if hub else None)),
        "product_id": (port.product_id if port and port.product_id else (hub.product_id if hub else None)),
        "speed": drive.speed,
        "serial_number_masked": mask_serial_number(drive.serial_number),
        "discovery_actor": actor or "system",
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def discover_usb_topology() -> DiscoveredTopology:
    """Return the current USB topology from the platform discovery provider.

    This thin wrapper exists as a stable seam for tests that monkeypatch the
    discovery source at module scope.
    """
    from app.infrastructure import get_drive_discovery

    return get_drive_discovery().discover_topology()


def _default_topology_source() -> DiscoveredTopology:
    """Default topology provider used by ``run_discovery_sync``."""
    return discover_usb_topology()


def run_discovery_sync(
    db: Session,
    actor: Optional[str] = None,
    *,
    topology_source: Callable[[], DiscoveredTopology] = _default_topology_source,
    filesystem_detector: FilesystemDetector,
    client_ip: Optional[str] = None,
) -> dict:
    """Discover USB hardware state and synchronise the database.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    actor:
        Username of the user (or service account) that triggered the sync.
        Stored in the audit log.
    topology_source:
        Callable that returns a :class:`~app.infrastructure.usb_discovery.DiscoveredTopology`.
        Defaults to the platform-selected provider via
        :func:`~app.infrastructure.get_drive_discovery`; override in tests to
        inject synthetic hardware snapshots.
    filesystem_detector:
        Implementation of the :class:`FilesystemDetector` protocol.  Callers
        must supply an instance explicitly; production routers pass the result
        of :func:`get_filesystem_detector`, while tests inject a lightweight
        fake.

    Returns
    -------
    dict
        Summary with counts of hubs, ports, drives inserted/updated/removed.
    """
    logger.info("USB discovery sync started", extra={"actor": actor or "system"})
    topology = topology_source()

    hub_repo = HubRepository(db)
    port_repo = PortRepository(db)
    drive_repo = DriveRepository(db)
    audit_repo = AuditRepository(db)

    # ------------------------------------------------------------------ hubs
    hubs_upserted: List[str] = []
    hub_id_by_system_id: dict[str, int] = {}

    for discovered_hub in topology.hubs:
        hub = hub_repo.upsert(
            system_identifier=discovered_hub.system_identifier,
            name=discovered_hub.name,
            location_hint=discovered_hub.location_hint,
            vendor_id=discovered_hub.vendor_id,
            product_id=discovered_hub.product_id,
        )
        hub_id_by_system_id[discovered_hub.system_identifier] = hub.id
        hubs_upserted.append(discovered_hub.system_identifier)

    # ----------------------------------------------------------------- ports
    ports_upserted: List[str] = []
    port_id_by_system_path: dict[str, int] = {}
    discovered_port_by_system_path: dict[str, object] = {}

    for discovered_port in topology.ports:
        hub_id = hub_id_by_system_id.get(discovered_port.hub_system_identifier)
        if hub_id is None:
            # Hub not yet persisted for this port; create a placeholder hub.
            hub = hub_repo.upsert(
                system_identifier=discovered_port.hub_system_identifier,
                name=discovered_port.hub_system_identifier,
            )
            hub_id = hub.id
            hub_id_by_system_id[discovered_port.hub_system_identifier] = hub_id

        port = port_repo.upsert(
            hub_id=hub_id,
            port_number=discovered_port.port_number,
            system_path=discovered_port.system_path,
            vendor_id=discovered_port.vendor_id,
            product_id=discovered_port.product_id,
            speed=discovered_port.speed,
        )
        port_id_by_system_path[discovered_port.system_path] = port.id
        discovered_port_by_system_path[discovered_port.system_path] = discovered_port
        ports_upserted.append(discovered_port.system_path)

    # ---------------------------------------------------------------- drives
    discovered_ids = {d.device_identifier for d in topology.drives}
    drives_inserted: List[str] = []
    drives_updated: List[str] = []
    drives_removed: List[str] = []
    observed_drive_metadata: List[dict] = []
    removed_drive_metadata: List[dict] = []

    # Build set of enabled port IDs for port-enablement filtering.
    enabled_port_ids: set[int] = {
        row[0] for row in db.query(UsbPort.id).filter(UsbPort.enabled.is_(True)).all()
    }

    def _port_is_enabled(pid: Optional[int]) -> bool:
        """Return True only when the port is known and enabled."""
        return pid is not None and pid in enabled_port_ids

    # Upsert each discovered drive.
    for discovered_drive in topology.drives:
        discovered_port = discovered_port_by_system_path.get(discovered_drive.port_system_path)
        existing: Optional[UsbDrive] = (
            db.query(UsbDrive)
            .filter(UsbDrive.device_identifier == discovered_drive.device_identifier)
            .one_or_none()
        )

        discovered_serial_number = _serial_number_from_identifier(
            discovered_drive.device_identifier,
            discovered_drive.port_system_path,
        )

        if existing is None and discovered_serial_number:
            legacy_by_serial = (
                db.query(UsbDrive)
                .filter(UsbDrive.device_identifier == discovered_serial_number)
                .one_or_none()
            )
            if legacy_by_serial is not None and not is_persistent_device_identifier(legacy_by_serial.device_identifier):
                existing = legacy_by_serial

        if existing is None and discovered_drive.port_system_path:
            legacy_by_port = (
                db.query(UsbDrive)
                .filter(UsbDrive.device_identifier == discovered_drive.port_system_path)
                .one_or_none()
            )
            if legacy_by_port is not None and not is_persistent_device_identifier(legacy_by_port.device_identifier):
                existing = legacy_by_port

        port_id: Optional[int] = None
        if discovered_drive.port_system_path:
            port_id = port_id_by_system_path.get(discovered_drive.port_system_path)

        if existing is None:
            # New drive — physically present drives on disabled ports are
            # DISABLED, enabled ports yield AVAILABLE/IN_USE, and only absent
            # hardware is DISCONNECTED.
            port_enabled = _port_is_enabled(port_id)
            if port_enabled and discovered_drive.mount_path:
                initial_state = DriveState.IN_USE
            elif port_enabled:
                initial_state = DriveState.AVAILABLE
            else:
                initial_state = DriveState.DISABLED
            drive = UsbDrive(
                device_identifier=discovered_drive.device_identifier,
                manufacturer=discovered_drive.manufacturer,
                product_name=discovered_drive.product_name,
                port_id=port_id,
                filesystem_path=discovered_drive.filesystem_path,
                capacity_bytes=discovered_drive.capacity_bytes,
                current_state=initial_state,
                mount_path=discovered_drive.mount_path,
            )
            # Detect filesystem type for newly discovered drives.
            if discovered_drive.filesystem_path:
                try:
                    drive.filesystem_type = filesystem_detector.detect(
                        discovered_drive.filesystem_path
                    )
                except Exception:
                    logger.exception(
                        "Filesystem detection failed for new drive %s",
                        discovered_drive.device_identifier,
                    )
                    drive.filesystem_type = "unknown"
            db.add(drive)
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception(
                    "DB commit failed inserting discovered drive %s",
                    discovered_drive.device_identifier,
                )
                continue
            db.refresh(drive)
            drives_inserted.append(discovered_drive.device_identifier)
            metadata = _build_discovered_drive_metadata(discovered_drive, discovered_port, drive_id=drive.id)
            observed_drive_metadata.append({"action": "inserted", **metadata})
            logger.info("USB discovery inserted drive", extra=metadata)
            try:
                audit_repo.add(
                    action="DRIVE_DISCOVERED",
                    user=actor,
                    drive_id=drive.id,
                    details=_build_drive_discovered_audit_details(drive, actor=actor),
                    client_ip=client_ip,
                )
            except Exception:
                logger.exception("Failed to write audit log for DRIVE_DISCOVERED")

        else:
            # Existing drive — update mutable fields.
            changed = False
            if existing.device_identifier != discovered_drive.device_identifier:
                existing.device_identifier = discovered_drive.device_identifier
                changed = True
            if port_id is not None and existing.port_id != port_id:
                existing.port_id = port_id
                changed = True
            if existing.filesystem_path != discovered_drive.filesystem_path:
                existing.filesystem_path = discovered_drive.filesystem_path
                changed = True
            if discovered_drive.capacity_bytes is not None and existing.capacity_bytes != discovered_drive.capacity_bytes:
                existing.capacity_bytes = discovered_drive.capacity_bytes
                changed = True
            if discovered_drive.manufacturer is not None and existing.manufacturer != discovered_drive.manufacturer:
                existing.manufacturer = discovered_drive.manufacturer
                changed = True
            if discovered_drive.product_name is not None and existing.product_name != discovered_drive.product_name:
                existing.product_name = discovered_drive.product_name
                changed = True
            if existing.mount_path != discovered_drive.mount_path:
                existing.mount_path = discovered_drive.mount_path
                changed = True

            # Detect filesystem type on every refresh cycle.
            if discovered_drive.filesystem_path:
                try:
                    detected_fs = filesystem_detector.detect(
                        discovered_drive.filesystem_path
                    )
                except Exception:
                    logger.exception(
                        "Filesystem detection failed for drive %s",
                        discovered_drive.device_identifier,
                    )
                    detected_fs = "unknown"
                if existing.filesystem_type != detected_fs:
                    existing.filesystem_type = detected_fs
                    changed = True

            port_enabled = _port_is_enabled(port_id or existing.port_id)

            has_project_binding = bool(normalize_project_id(existing.current_project_id))

            # Mounted drives become IN_USE on rediscovery only when they are
            # still bound to a project. Mounted but uninitialized drives must
            # remain AVAILABLE so discovery does not manufacture project ownership.
            if (
                port_enabled
                and existing.mount_path
                and has_project_binding
                and existing.current_state != DriveState.IN_USE
            ):
                existing.current_state = DriveState.IN_USE
                changed = True
            # Re-activate physically present drives when the port becomes enabled.
            # Legacy UNMOUNTED rows from pre-DISABLED releases should also
            # reconcile forward instead of remaining stranded.
            elif existing.current_state in (DriveState.DISCONNECTED, DriveState.DISABLED, DriveState.UNMOUNTED) and port_enabled:
                if existing.mount_path and has_project_binding:
                    existing.current_state = DriveState.IN_USE
                else:
                    existing.current_state = DriveState.AVAILABLE
                changed = True

            # Physically present drives on disabled ports are not disconnected;
            # they remain visible as DISABLED until the hardware disappears.
            if existing.current_state == DriveState.DISCONNECTED and not port_enabled:
                existing.current_state = DriveState.DISABLED
                changed = True

            # Demote reachable drives to DISABLED when the port is disabled.
            # IN_USE drives are left untouched to preserve project isolation.
            if existing.current_state in (DriveState.AVAILABLE, DriveState.UNMOUNTED) and not port_enabled:
                existing.current_state = DriveState.DISABLED
                existing.mount_path = None
                changed = True

            if changed:
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "DB commit failed updating discovered drive %s",
                        discovered_drive.device_identifier,
                    )
                    continue
                db.refresh(existing)
                drives_updated.append(discovered_drive.device_identifier)
                metadata = _build_persisted_drive_metadata(existing)
                observed_drive_metadata.append({"action": "updated", **metadata})
                logger.info("USB discovery updated drive", extra=metadata)
            else:
                observed_drive_metadata.append({
                    "action": "observed",
                    **_build_discovered_drive_metadata(discovered_drive, discovered_port, drive_id=existing.id),
                })

    # Mark drives absent from hardware as DISCONNECTED (unless IN_USE — project
    # isolation must not be broken). Also clear stale device-path evidence and
    # stale port bindings so historical rows do not continue to occupy the same
    # USB port after the device has been removed.
    all_db_drives: List[UsbDrive] = drive_repo.list_all()
    for drive in all_db_drives:
        if drive.device_identifier not in discovered_ids:
            if drive.current_state == DriveState.IN_USE:
                continue

            was_available = drive.current_state == DriveState.AVAILABLE
            had_stale_presence = drive.filesystem_path is not None or drive.mount_path is not None
            had_stale_port_binding = drive.port_id is not None

            if was_available or had_stale_presence or had_stale_port_binding:
                drive.current_state = DriveState.DISCONNECTED
                drive.filesystem_path = None
                drive.mount_path = None
                drive.port_id = None
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "DB commit failed marking drive %s as DISCONNECTED",
                        drive.device_identifier,
                    )
                    continue
                db.refresh(drive)
                if was_available:
                    drives_removed.append(drive.device_identifier)
                    removed_metadata = _build_persisted_drive_metadata(drive)
                    removed_drive_metadata.append(removed_metadata)
                    logger.info("USB discovery removed drive", extra=removed_metadata)
                    try:
                        audit_repo.add(
                            action="DRIVE_REMOVED",
                            user=actor,
                            details={
                                "drive_id": drive.id,
                                "device_identifier": drive.device_identifier,
                            },
                            client_ip=client_ip,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to write audit log for DRIVE_REMOVED: %s",
                            drive.device_identifier,
                        )

    summary = {
        "hubs_upserted": len(hubs_upserted),
        "ports_upserted": len(ports_upserted),
        "drives_inserted": len(drives_inserted),
        "drives_updated": len(drives_updated),
        "drives_removed": len(drives_removed),
        "observed_drives": observed_drive_metadata,
        "removed_drives": removed_drive_metadata,
    }

    try:
        audit_repo.add(
            action="USB_DISCOVERY_SYNC",
            user=actor,
            details=summary,
            client_ip=client_ip,
        )
    except Exception:
        logger.exception("Failed to write audit log for USB_DISCOVERY_SYNC")

    logger.info(
        "USB discovery sync completed",
        extra={
            "actor": actor or "system",
            "hubs_upserted": summary["hubs_upserted"],
            "ports_upserted": summary["ports_upserted"],
            "drives_inserted": summary["drives_inserted"],
            "drives_updated": summary["drives_updated"],
            "drives_removed": summary["drives_removed"],
        },
    )

    return summary
