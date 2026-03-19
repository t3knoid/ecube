"""Repository layer for USB hardware topology (hubs and ports).

Drives are managed by :class:`~app.repositories.drive_repository.DriveRepository`.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.exc import IntegrityError
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
        vendor_id: Optional[str] = None,
        product_id: Optional[str] = None,
    ) -> UsbHub:
        """Insert or update a hub identified by *system_identifier*.

        If a hub with the given *system_identifier* already exists its *name*
        is refreshed.  Otherwise a new row is created.
        The resulting object (new or updated) is returned after committing.

        *location_hint* is only written when a non-``None`` value is supplied;
        passing ``None`` (the default) leaves any existing hint unchanged.
        *vendor_id* and *product_id* are always updated when non-``None``.

        If a concurrent session inserts the same *system_identifier* between
        our read and write, the resulting ``IntegrityError`` is caught and
        the operation is retried as an update.
        """
        hub = self.get_by_system_identifier(system_identifier)
        if hub is None:
            hub = UsbHub(
                system_identifier=system_identifier,
                name=name,
                location_hint=location_hint,
                vendor_id=vendor_id,
                product_id=product_id,
            )
            self.db.add(hub)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                hub = self.get_by_system_identifier(system_identifier)
                if hub is None:
                    raise  # pragma: no cover — unexpected; re-raise
                hub.name = name
                if location_hint is not None:
                    hub.location_hint = location_hint
                if vendor_id is not None:
                    hub.vendor_id = vendor_id
                if product_id is not None:
                    hub.product_id = product_id
                try:
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
            except Exception:
                self.db.rollback()
                raise
        else:
            hub.name = name
            if location_hint is not None:
                hub.location_hint = location_hint
            if vendor_id is not None:
                hub.vendor_id = vendor_id
            if product_id is not None:
                hub.product_id = product_id
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        self.db.refresh(hub)
        return hub

    def update_location_hint(self, hub_id: int, location_hint: str) -> Optional[UsbHub]:
        """Set *location_hint* on a hub.  Returns ``None`` if not found."""
        hub = self.get(hub_id)
        if hub is None:
            return None
        hub.location_hint = location_hint
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
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
        vendor_id: Optional[str] = None,
        product_id: Optional[str] = None,
        speed: Optional[str] = None,
    ) -> UsbPort:
        """Insert or update a port identified by *system_path*.

        Updates *hub_id* and *port_number* when the port already exists.
        *friendly_label* is only written when a non-``None`` value is
        supplied; passing ``None`` (the default) leaves any existing label
        unchanged.  *vendor_id*, *product_id*, and *speed* are always updated
        when non-``None``.  Returns the persisted port after committing.

        If a concurrent session inserts the same *system_path* between our
        read and write, the resulting ``IntegrityError`` is caught and the
        operation is retried as an update.
        """
        port = self.get_by_system_path(system_path)
        if port is None:
            port = UsbPort(
                hub_id=hub_id,
                port_number=port_number,
                system_path=system_path,
                friendly_label=friendly_label,
                enabled=False,
                vendor_id=vendor_id,
                product_id=product_id,
                speed=speed,
            )
            self.db.add(port)
            try:
                self.db.commit()
            except IntegrityError:
                self.db.rollback()
                port = self.get_by_system_path(system_path)
                if port is None:
                    raise  # pragma: no cover — unexpected; re-raise
                port.hub_id = hub_id
                port.port_number = port_number
                if friendly_label is not None:
                    port.friendly_label = friendly_label
                if vendor_id is not None:
                    port.vendor_id = vendor_id
                if product_id is not None:
                    port.product_id = product_id
                if speed is not None:
                    port.speed = speed
                try:
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
            except Exception:
                self.db.rollback()
                raise
        else:
            port.hub_id = hub_id
            port.port_number = port_number
            if friendly_label is not None:
                port.friendly_label = friendly_label
            if vendor_id is not None:
                port.vendor_id = vendor_id
            if product_id is not None:
                port.product_id = product_id
            if speed is not None:
                port.speed = speed
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        self.db.refresh(port)
        return port

    def update_friendly_label(self, port_id: int, friendly_label: str) -> Optional[UsbPort]:
        """Set *friendly_label* on a port.  Returns ``None`` if not found."""
        port = self.get(port_id)
        if port is None:
            return None
        port.friendly_label = friendly_label
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(port)
        return port

    def set_enabled(self, port_id: int, enabled: bool) -> Optional[UsbPort]:
        """Set the *enabled* flag on a port.  Returns ``None`` if not found."""
        port = self.get(port_id)
        if port is None:
            return None
        port.enabled = enabled
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(port)
        return port

    def list_enabled(self) -> List[UsbPort]:
        """Return all ports where ``enabled`` is ``True``."""
        return self.db.query(UsbPort).filter(UsbPort.enabled.is_(True)).all()
