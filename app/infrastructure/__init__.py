"""Infrastructure factory functions.

Returns concrete implementations of infrastructure protocols based on the
current platform.  Services and routers should depend on the Protocol types,
never import concrete classes directly.
"""
from app.config import settings
from app.infrastructure.filesystem_detection import (
    FilesystemDetector,
    LinuxFilesystemDetector,
)
from app.infrastructure.drive_format import (
    DriveFormatter,
    LinuxDriveFormatter,
)

__all__ = [
    "FilesystemDetector",
    "DriveFormatter",
    "get_filesystem_detector",
    "get_drive_formatter",
    "validate_device_path",
]

_FILESYSTEM_DETECTOR_REGISTRY: dict[str, type[FilesystemDetector]] = {
    "linux": LinuxFilesystemDetector,
}

_DRIVE_FORMATTER_REGISTRY: dict[str, type[DriveFormatter]] = {
    "linux": LinuxDriveFormatter,
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


import re

_DEVICE_PATH_RE = re.compile(r"^/dev/[a-zA-Z][a-zA-Z0-9]*$")


def validate_device_path(path: str) -> bool:
    """Return ``True`` if *path* matches the expected block-device pattern."""
    return bool(_DEVICE_PATH_RE.match(path))
