"""Infrastructure factory functions.

Returns concrete implementations of infrastructure protocols based on the
current platform.  Services and routers should depend on the Protocol types,
never import concrete classes directly.

Concrete Linux implementations are imported lazily inside each ``get_*()``
factory so that ``import app.infrastructure`` does not pull in Linux-only
modules (``pwd``, ``grp``, ``pam``) and crash on non-Linux platforms.
"""
from __future__ import annotations

from typing import Callable

from app.config import settings
from app.infrastructure.device_path import validate_device_path
from app.infrastructure.filesystem_detection import FilesystemDetector
from app.infrastructure.drive_format import DriveFormatter
from app.infrastructure.usb_discovery import DriveDiscoveryProvider
from app.infrastructure.drive_eject import (
    DriveEjectProvider,
    EjectError,
    EjectResult,
)
from app.services.mount_service import MountProvider
from app.services.os_user_service import OsUserProvider
from app.services.pam_service import PamAuthenticator

__all__ = [
    "FilesystemDetector",
    "DriveFormatter",
    "DriveDiscoveryProvider",
    "DriveEjectProvider",
    "EjectError",
    "EjectResult",
    "MountProvider",
    "OsUserProvider",
    "PamAuthenticator",
    "get_filesystem_detector",
    "get_drive_formatter",
    "get_drive_discovery",
    "get_drive_eject",
    "get_mount_provider",
    "get_os_user_provider",
    "get_authenticator",
    "validate_device_path",
]


# ---------------------------------------------------------------------------
# Lazy registries — callables that import + return the concrete class.
# This avoids pulling in Linux-only modules (pwd, grp, pam) at import time.
# ---------------------------------------------------------------------------

def _linux_filesystem_detector() -> type[FilesystemDetector]:
    from app.infrastructure.filesystem_detection import LinuxFilesystemDetector
    return LinuxFilesystemDetector

def _linux_drive_formatter() -> type[DriveFormatter]:
    from app.infrastructure.drive_format import LinuxDriveFormatter
    return LinuxDriveFormatter

def _linux_drive_discovery() -> type[DriveDiscoveryProvider]:
    from app.infrastructure.usb_discovery import LinuxDriveDiscovery
    return LinuxDriveDiscovery

def _linux_drive_eject() -> type[DriveEjectProvider]:
    from app.infrastructure.drive_eject import LinuxDriveEject
    return LinuxDriveEject

def _linux_mount_provider() -> type[MountProvider]:
    from app.services.mount_service import LinuxMountProvider
    return LinuxMountProvider

def _linux_os_user_provider() -> type[OsUserProvider]:
    from app.services.os_user_service import LinuxOsUserProvider
    return LinuxOsUserProvider

def _linux_pam_authenticator() -> type[PamAuthenticator]:
    from app.services.pam_service import LinuxPamAuthenticator
    return LinuxPamAuthenticator


_FILESYSTEM_DETECTOR_REGISTRY: dict[str, Callable[[], type[FilesystemDetector]]] = {
    "linux": _linux_filesystem_detector,
}

_DRIVE_FORMATTER_REGISTRY: dict[str, Callable[[], type[DriveFormatter]]] = {
    "linux": _linux_drive_formatter,
}

_DRIVE_DISCOVERY_REGISTRY: dict[str, Callable[[], type[DriveDiscoveryProvider]]] = {
    "linux": _linux_drive_discovery,
}

_DRIVE_EJECT_REGISTRY: dict[str, Callable[[], type[DriveEjectProvider]]] = {
    "linux": _linux_drive_eject,
}

_MOUNT_PROVIDER_REGISTRY: dict[str, Callable[[], type[MountProvider]]] = {
    "linux": _linux_mount_provider,
}

_OS_USER_PROVIDER_REGISTRY: dict[str, Callable[[], type[OsUserProvider]]] = {
    "linux": _linux_os_user_provider,
}

_PAM_AUTHENTICATOR_REGISTRY: dict[str, Callable[[], type[PamAuthenticator]]] = {
    "linux": _linux_pam_authenticator,
}


def _resolve(registry: dict, label: str):
    """Look up the platform loader and instantiate the concrete class."""
    loader = registry.get(settings.platform)
    if loader is None:
        raise ValueError(f"Unsupported platform for {label}: {settings.platform!r}")
    return loader()()


def get_filesystem_detector() -> FilesystemDetector:
    """Return the platform-appropriate :class:`FilesystemDetector`."""
    return _resolve(_FILESYSTEM_DETECTOR_REGISTRY, "FilesystemDetector")


def get_drive_formatter() -> DriveFormatter:
    """Return the platform-appropriate :class:`DriveFormatter`."""
    return _resolve(_DRIVE_FORMATTER_REGISTRY, "DriveFormatter")


def get_drive_discovery() -> DriveDiscoveryProvider:
    """Return the platform-appropriate :class:`DriveDiscoveryProvider`."""
    return _resolve(_DRIVE_DISCOVERY_REGISTRY, "DriveDiscoveryProvider")


def get_drive_eject() -> DriveEjectProvider:
    """Return the platform-appropriate :class:`DriveEjectProvider`."""
    return _resolve(_DRIVE_EJECT_REGISTRY, "DriveEjectProvider")


def get_mount_provider() -> MountProvider:
    """Return the platform-appropriate :class:`MountProvider`."""
    return _resolve(_MOUNT_PROVIDER_REGISTRY, "MountProvider")


def get_os_user_provider() -> OsUserProvider:
    """Return the platform-appropriate :class:`OsUserProvider`."""
    return _resolve(_OS_USER_PROVIDER_REGISTRY, "OsUserProvider")


def get_authenticator() -> PamAuthenticator:
    """Return the platform-appropriate :class:`PamAuthenticator`."""
    return _resolve(_PAM_AUTHENTICATOR_REGISTRY, "PamAuthenticator")
