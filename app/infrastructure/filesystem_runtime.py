"""Trusted host filesystem-runtime diagnostics."""
from __future__ import annotations

import os
from typing import Protocol

from app.config import settings


class FilesystemRuntimeInspector(Protocol):
    """Inspect host runtime support for selected filesystems."""

    def exfat_formatting_available(self) -> bool:
        """Return True when the host can format exFAT media."""
        ...

    def exfat_mount_runtime_available(self) -> bool | None:
        """Return True when exFAT mount support is available.

        Returns False when the kernel filesystem registry is readable and
        exFAT support is absent, or None when the check cannot complete
        reliably.
        """
        ...


class LinuxFilesystemRuntimeInspector:
    """Linux implementation using trusted host file probes."""

    def exfat_formatting_available(self) -> bool:
        path = str(getattr(settings, "mkfs_exfat_path", "") or "").strip()
        return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)

    def exfat_mount_runtime_available(self) -> bool | None:
        procfs_path = str(getattr(settings, "procfs_filesystems_path", "/proc/filesystems") or "").strip()
        if not procfs_path:
            return None

        try:
            with open(procfs_path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    entry = line.strip().split()
                    if entry and entry[-1] == "exfat":
                        return True
        except OSError:
            return None

        return False