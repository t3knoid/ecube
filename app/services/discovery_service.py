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

import logging
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from app.infrastructure.usb_discovery import DiscoveredTopology, discover_usb_topology
from app.infrastructure import FilesystemDetector
from app.models.hardware import DriveState, UsbDrive, UsbPort
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.hardware_repository import HubRepository, PortRepository

logger = logging.getLogger(__name__)


def _default_topology_source() -> DiscoveredTopology:
    """Lazy import to route through the platform-selected provider."""
    from app.infrastructure import get_drive_discovery
    return get_drive_discovery().discover_topology()


def run_discovery_sync(
    db: Session,
    actor: Optional[str] = None,
    *,
    topology_source: Callable[[], DiscoveredTopology] = _default_topology_source,
    filesystem_detector: FilesystemDetector,
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
        )
        hub_id_by_system_id[discovered_hub.system_identifier] = hub.id
        hubs_upserted.append(discovered_hub.system_identifier)

    # ----------------------------------------------------------------- ports
    ports_upserted: List[str] = []
    port_id_by_system_path: dict[str, int] = {}

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
        )
        port_id_by_system_path[discovered_port.system_path] = port.id
        ports_upserted.append(discovered_port.system_path)

    # ---------------------------------------------------------------- drives
    discovered_ids = {d.device_identifier for d in topology.drives}
    drives_inserted: List[str] = []
    drives_updated: List[str] = []
    drives_removed: List[str] = []

    # Build set of enabled port IDs for port-enablement filtering.
    enabled_port_ids: set[int] = {
        p.id for p in db.query(UsbPort).filter(UsbPort.enabled == True).all()  # noqa: E712
    }

    def _port_is_enabled(pid: Optional[int]) -> bool:
        """Return True only when the port is known and enabled."""
        return pid is not None and pid in enabled_port_ids

    # Upsert each discovered drive.
    for discovered_drive in topology.drives:
        existing: Optional[UsbDrive] = (
            db.query(UsbDrive)
            .filter(UsbDrive.device_identifier == discovered_drive.device_identifier)
            .one_or_none()
        )

        port_id: Optional[int] = None
        if discovered_drive.port_system_path:
            port_id = port_id_by_system_path.get(discovered_drive.port_system_path)

        if existing is None:
            # New drive — insert as AVAILABLE only if port is enabled.
            initial_state = DriveState.AVAILABLE if _port_is_enabled(port_id) else DriveState.EMPTY
            drive = UsbDrive(
                device_identifier=discovered_drive.device_identifier,
                port_id=port_id,
                filesystem_path=discovered_drive.filesystem_path,
                capacity_bytes=discovered_drive.capacity_bytes,
                current_state=initial_state,
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
        else:
            # Existing drive — update mutable fields.
            changed = False
            if port_id is not None and existing.port_id != port_id:
                existing.port_id = port_id
                changed = True
            if existing.filesystem_path != discovered_drive.filesystem_path:
                existing.filesystem_path = discovered_drive.filesystem_path
                changed = True
            if discovered_drive.capacity_bytes is not None and existing.capacity_bytes != discovered_drive.capacity_bytes:
                existing.capacity_bytes = discovered_drive.capacity_bytes
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

            # Re-activate a previously-emptied drive only if port is enabled.
            if existing.current_state == DriveState.EMPTY and _port_is_enabled(port_id or existing.port_id):
                existing.current_state = DriveState.AVAILABLE
                changed = True

            # Demote AVAILABLE → EMPTY when the port has been disabled.
            # IN_USE drives are left untouched to preserve project isolation.
            if existing.current_state == DriveState.AVAILABLE and not _port_is_enabled(port_id or existing.port_id):
                existing.current_state = DriveState.EMPTY
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

    # Mark drives absent from hardware as EMPTY (unless IN_USE — project
    # isolation must not be broken).
    all_db_drives: List[UsbDrive] = drive_repo.list_all()
    for drive in all_db_drives:
        if drive.device_identifier not in discovered_ids:
            if drive.current_state == DriveState.AVAILABLE:
                drive.current_state = DriveState.EMPTY
                try:
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "DB commit failed marking drive %s as EMPTY",
                        drive.device_identifier,
                    )
                    continue
                db.refresh(drive)
                drives_removed.append(drive.device_identifier)
                try:
                    audit_repo.add(
                        action="DRIVE_REMOVED",
                        user=actor,
                        details={
                            "drive_id": drive.id,
                            "device_identifier": drive.device_identifier,
                        },
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
    }

    try:
        audit_repo.add(
            action="USB_DISCOVERY_SYNC",
            user=actor,
            details=summary,
        )
    except Exception:
        logger.exception("Failed to write audit log for USB_DISCOVERY_SYNC")

    return summary
