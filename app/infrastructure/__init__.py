"""Infrastructure factory functions.

Returns concrete implementations of infrastructure protocols based on the
current platform.  Services and routers should depend on the Protocol types,
never import concrete classes directly.
"""
from app.config import settings
from app.infrastructure.device_path import validate_device_path
from app.infrastructure.filesystem_detection import (
    FilesystemDetector,
    LinuxFilesystemDetector,
)
from app.infrastructure.drive_format import (
    DriveFormatter,
    LinuxDriveFormatter,
)
from app.infrastructure.usb_discovery import (
    DriveDiscoveryProvider,
    LinuxDriveDiscovery,
)
from app.infrastructure.drive_eject import (
    DriveEjectProvider,
    LinuxDriveEject,
)
from app.services.os_user_service import (
    OsUserProvider,
    LinuxOsUserProvider,
)

__all__ = [
    "FilesystemDetector",
    "DriveFormatter",
    "DriveDiscoveryProvider",
    "DriveEjectProvider",
    "OsUserProvider",
    "get_filesystem_detector",
    "get_drive_formatter",
    "get_drive_discovery",
    "get_drive_eject",
    "get_os_user_provider",
    "validate_device_path",
]

_FILESYSTEM_DETECTOR_REGISTRY: dict[str, type[FilesystemDetector]] = {
    "linux": LinuxFilesystemDetector,
}

_DRIVE_FORMATTER_REGISTRY: dict[str, type[DriveFormatter]] = {
    "linux": LinuxDriveFormatter,
}

_DRIVE_DISCOVERY_REGISTRY: dict[str, type[DriveDiscoveryProvider]] = {
    "linux": LinuxDriveDiscovery,
}

_DRIVE_EJECT_REGISTRY: dict[str, type[DriveEjectProvider]] = {
    "linux": LinuxDriveEject,
}

_OS_USER_PROVIDER_REGISTRY: dict[str, type[OsUserProvider]] = {
    "linux": LinuxOsUserProvider,
}


def get_filesystem_detector() -> FilesystemDetector:
    """Return the platform-appropriate :class:`FilesystemDetector`."""
    cls = _FILESYSTEM_DETECTOR_REGISTRY.get(settings.platform)
    if cls is None:
        raise ValueError(f"Unsupported platform: {settings.platform!r}")
    return cls()


def get_drive_formatter() -> DriveFormatter:
    """Return the platform-appropriate :class:`DriveFormatter`."""
    cls = _DRIVE_FORMATTER_REGISTRY.get(settings.platform)
    if cls is None:
        raise ValueError(f"Unsupported platform: {settings.platform!r}")
    return cls()


def get_drive_discovery() -> DriveDiscoveryProvider:
    """Return the platform-appropriate :class:`DriveDiscoveryProvider`."""
    cls = _DRIVE_DISCOVERY_REGISTRY.get(settings.platform)
    if cls is None:
        raise ValueError(f"Unsupported platform: {settings.platform!r}")
    return cls()


def get_drive_eject() -> DriveEjectProvider:
    """Return the platform-appropriate :class:`DriveEjectProvider`."""
    cls = _DRIVE_EJECT_REGISTRY.get(settings.platform)
    if cls is None:
        raise ValueError(f"Unsupported platform: {settings.platform!r}")
    return cls()


def get_os_user_provider() -> OsUserProvider:
    """Return the platform-appropriate :class:`OsUserProvider`."""
    cls = _OS_USER_PROVIDER_REGISTRY.get(settings.platform)
    if cls is None:
        raise ValueError(f"Unsupported platform: {settings.platform!r}")
    return cls()
