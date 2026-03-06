"""Repository layer for USB hardware topology (hubs and ports).

Drives are managed by :class:`~app.repositories.drive_repository.DriveRepository`.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.hardware import UsbHub, UsbPort


class HubRepository:
    """Data-access layer for :class:`~app.models.hardware.UsbHub`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> List[UsbHub]:
        """Return all hubs."""
        return self.db.query(UsbHub).all()

    def get(self, hub_id: int) -> Optional[UsbHub]:
        """Return a hub by primary key, or ``None``."""
        return self.db.get(UsbHub, hub_id)

    def get_by_system_identifier(self, system_identifier: str) -> Optional[UsbHub]:
        """Return a hub by its unique system identifier, or ``None``."""
        return (
            self.db.query(UsbHub)
            .filter(UsbHub.system_identifier == system_identifier)
            .one_or_none()
        )

    def upsert(
        self,
        system_identifier: str,
        name: str,
        location_hint: Optional[str] = None,
    ) -> UsbHub:
        """Insert or update a hub identified by *system_identifier*.

        If a hub with the given *system_identifier* already exists its *name*
        and *location_hint* are refreshed.  Otherwise a new row is created.
        The resulting object (new or updated) is returned after committing.

        *location_hint* is only written when a non-``None`` value is supplied;
        passing ``None`` (the default) leaves any existing hint unchanged.
        """
        hub = self.get_by_system_identifier(system_identifier)
        if hub is None:
            hub = UsbHub(
                system_identifier=system_identifier,
                name=name,
                location_hint=location_hint,
            )
            self.db.add(hub)
        else:
            hub.name = name
            if location_hint is not None:
                hub.location_hint = location_hint
        self.db.commit()
        self.db.refresh(hub)
        return hub


class PortRepository:
    """Data-access layer for :class:`~app.models.hardware.UsbPort`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_all(self) -> List[UsbPort]:
        """Return all ports."""
        return self.db.query(UsbPort).all()

    def get(self, port_id: int) -> Optional[UsbPort]:
        """Return a port by primary key, or ``None``."""
        return self.db.get(UsbPort, port_id)

    def get_by_system_path(self, system_path: str) -> Optional[UsbPort]:
        """Return a port by its unique system path, or ``None``."""
        return (
            self.db.query(UsbPort)
            .filter(UsbPort.system_path == system_path)
            .one_or_none()
        )

    def upsert(
        self,
        hub_id: int,
        port_number: int,
        system_path: str,
        friendly_label: Optional[str] = None,
    ) -> UsbPort:
        """Insert or update a port identified by *system_path*.

        Updates *hub_id* and *port_number* when the port already exists.
        *friendly_label* is only written when a non-``None`` value is
        supplied; passing ``None`` (the default) leaves any existing label
        unchanged.  Returns the persisted port after committing.
        """
        port = self.get_by_system_path(system_path)
        if port is None:
            port = UsbPort(
                hub_id=hub_id,
                port_number=port_number,
                system_path=system_path,
                friendly_label=friendly_label,
            )
            self.db.add(port)
        else:
            port.hub_id = hub_id
            port.port_number = port_number
            if friendly_label is not None:
                port.friendly_label = friendly_label
        self.db.commit()
        self.db.refresh(port)
        return port
