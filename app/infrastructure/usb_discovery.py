"""USB topology discovery from Linux sysfs / procfs.

This module provides a thin adapter that reads the current USB hardware state
from the host operating system and returns plain Python data structures.  The
adapter is dependency-injected so unit tests can supply synthetic device data
without requiring physical hardware.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Protocol

from app.config import settings


@dataclass
class DiscoveredHub:
    """A USB hub visible on the system bus."""

    system_identifier: str
    """Sysfs device name, e.g. ``"usb1"`` or ``"1-0:1.0"``."""
    name: str
    """Human-readable product string (falls back to *system_identifier*)."""
    location_hint: Optional[str] = None
    """Optional physical-location annotation, e.g. ``"front-panel"``."""
    vendor_id: Optional[str] = None
    """USB vendor ID from sysfs ``idVendor`` (e.g. ``"8086"``)."""
    product_id: Optional[str] = None
    """USB product ID from sysfs ``idProduct`` (e.g. ``"a36d"``)."""


@dataclass
class DiscoveredPort:
    """A downstream port belonging to a USB hub."""

    hub_system_identifier: str
    """``system_identifier`` of the parent :class:`DiscoveredHub`."""
    port_number: int
    """1-based port index as reported by sysfs."""
    system_path: str
    """Sysfs path used as a stable identifier, e.g. ``"1-1"``."""
    vendor_id: Optional[str] = None
    """Vendor ID of the device currently at this port."""
    product_id: Optional[str] = None
    """Product ID of the device currently at this port."""
    speed: Optional[str] = None
    """Port speed in Mbps from sysfs ``speed`` attribute (e.g. ``"480"``, ``"5000"``)."""


@dataclass
class DiscoveredDrive:
    """A USB mass-storage drive attached to a port."""

    device_identifier: str
    """Stable identifier – serial number when available, otherwise the sysfs
    device path."""
    port_system_path: Optional[str] = None
    """``system_path`` of the parent :class:`DiscoveredPort`, if known."""
    filesystem_path: Optional[str] = None
    """Block device node, e.g. ``"/dev/sdb"``."""
    capacity_bytes: Optional[int] = None
    """Total capacity in bytes as reported by the kernel."""


@dataclass
class DiscoveredTopology:
    """Complete snapshot of the current USB hardware topology."""

    hubs: List[DiscoveredHub] = field(default_factory=list)
    ports: List[DiscoveredPort] = field(default_factory=list)
    drives: List[DiscoveredDrive] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DriveDiscoveryProvider Protocol
# ---------------------------------------------------------------------------

class DriveDiscoveryProvider(Protocol):
    """Platform-agnostic interface for USB topology discovery."""

    def discover_topology(self) -> DiscoveredTopology: ...


class LinuxDriveDiscovery:
    """Linux implementation that reads USB topology from sysfs."""

    def discover_topology(self) -> DiscoveredTopology:
        return discover_usb_topology()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _read_sysfs_attr(dev_path: str, attr: str) -> Optional[str]:
    """Return the stripped content of a sysfs attribute file, or ``None``.

    Returns ``None`` when the file does not exist **or** is empty so that
    empty-string values never overwrite previously stored data downstream.
    """
    attr_file = os.path.join(dev_path, attr)
    try:
        with open(attr_file) as fh:
            value = fh.read().strip()
            return value or None
    except OSError:
        return None


def _block_device_for_sysfs_path(sysfs_dev_path: str) -> Optional[str]:
    """Return the ``/dev/<name>`` node for a USB device, or ``None``.

    Walks the device's sysfs subtree looking for a block device directory
    (``block/<name>``).
    """
    try:
        for root, dirs, _ in os.walk(sysfs_dev_path):
            if "block" in dirs:
                block_root = os.path.join(root, "block")
                block_names = os.listdir(block_root)
                if block_names:
                    return f"/dev/{block_names[0]}"
    except OSError:
        pass
    return None


def _read_capacity_bytes(dev_path: str) -> Optional[int]:
    """Return capacity in bytes from ``size`` sysfs attribute (512-byte sectors)."""
    size_str = _read_sysfs_attr(dev_path, "size")
    if size_str is not None:
        try:
            return int(size_str) * 512
        except ValueError:
            pass
    return None


def discover_usb_topology() -> DiscoveredTopology:
    """Read the current USB topology from ``/sys/bus/usb/devices``.

    Returns a :class:`DiscoveredTopology` describing the hubs, ports, and
    mass-storage drives that are currently visible to the kernel.  When the
    sysfs tree is unavailable (e.g. non-Linux hosts or unit-test environments)
    an empty topology is returned without raising.
    """
    usb_path = settings.sysfs_usb_devices_path
    topology = DiscoveredTopology()

    try:
        entries = os.listdir(usb_path)
    except OSError:
        return topology

    for dev in sorted(entries):
        dev_path = os.path.join(usb_path, dev)
        if not os.path.isdir(dev_path):
            continue

        dev_class = _read_sysfs_attr(dev_path, "bDeviceClass") or ""
        # Root hubs: bDeviceClass == "09" and name starts with "usb"
        if dev_class == "09" or dev.startswith("usb"):
            product = (
                _read_sysfs_attr(dev_path, "product")
                or _read_sysfs_attr(dev_path, "manufacturer")
                or dev
            )
            vendor_id = _read_sysfs_attr(dev_path, "idVendor")
            product_id = _read_sysfs_attr(dev_path, "idProduct")
            topology.hubs.append(
                DiscoveredHub(
                    system_identifier=dev,
                    name=product,
                    vendor_id=vendor_id,
                    product_id=product_id,
                )
            )
            continue

        # Downstream ports: pattern like "1-1", "2-3" (no colon, contains dash)
        if ":" not in dev and "-" in dev:
            parts = dev.split("-")
            if len(parts) == 2 and parts[1].isdigit():
                hub_id = f"usb{parts[0]}"
                port_vendor_id = _read_sysfs_attr(dev_path, "idVendor")
                port_product_id = _read_sysfs_attr(dev_path, "idProduct")
                port_speed = _read_sysfs_attr(dev_path, "speed")
                topology.ports.append(
                    DiscoveredPort(
                        hub_system_identifier=hub_id,
                        port_number=int(parts[1]),
                        system_path=dev,
                        vendor_id=port_vendor_id,
                        product_id=port_product_id,
                        speed=port_speed,
                    )
                )

                # Check for a mass-storage drive at this port
                interface_class = _read_sysfs_attr(dev_path, "bDeviceClass") or ""
                serial = _read_sysfs_attr(dev_path, "serial")
                device_id = serial if serial else dev
                block_node = _block_device_for_sysfs_path(dev_path)
                if block_node or interface_class == "00":
                    capacity: Optional[int] = None
                    if block_node:
                        # Attempt to read capacity from /sys/block/<name>/size
                        block_name = os.path.basename(block_node)
                        cap = _read_capacity_bytes(
                            f"{settings.sysfs_block_path}/{block_name}"
                        )
                        capacity = cap
                    topology.drives.append(
                        DiscoveredDrive(
                            device_identifier=device_id,
                            port_system_path=dev,
                            filesystem_path=block_node,
                            capacity_bytes=capacity,
                        )
                    )

    return topology
