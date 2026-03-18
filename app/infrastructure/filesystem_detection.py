"""Filesystem detection infrastructure.

Defines the :class:`FilesystemDetector` protocol and the Linux reference
implementation that shells out to ``blkid`` / ``lsblk``.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)

# Allowed block-device path pattern: /dev/<name>, e.g. /dev/sdb, /dev/sdc1.
_DEVICE_PATH_RE = re.compile(r"^/dev/[a-zA-Z][a-zA-Z0-9]*$")

# Absolute paths to system utilities so PATH manipulation cannot redirect them.
_BLKID_BIN = settings.blkid_binary_path
_LSBLK_BIN = settings.lsblk_binary_path


class FilesystemDetector(Protocol):
    """Detect the filesystem type on a block device."""

    def detect(self, device_path: str) -> str:
        """Return the canonical filesystem label for the given block device.

        Returns
        -------
        str
            One of: ``'ext4'``, ``'exfat'``, ``'ntfs'``, ``'fat32'``, ``'xfs'``,
            etc. for recognized filesystems; ``'unformatted'`` when no filesystem
            signature is found; ``'unknown'`` when detection fails.
        """
        ...


class LinuxFilesystemDetector:
    """Linux implementation using ``blkid`` and ``lsblk``."""

    def detect(self, device_path: str) -> str:
        if not _DEVICE_PATH_RE.match(device_path):
            logger.warning("Invalid device path for filesystem detection: %r", device_path)
            return "unknown"

        # Primary: blkid
        result = self._try_blkid(device_path)
        if result is not None:
            return result

        # Fallback: lsblk
        result = self._try_lsblk(device_path)
        if result is not None:
            return result

        return "unknown"

    def _try_blkid(self, device_path: str) -> str | None:
        """Try ``blkid -o value -s TYPE <device>``.

        Returns the canonical fs label, ``'unformatted'`` for empty output,
        or ``None`` if the command failed entirely (so the caller can fall back).
        """
        try:
            proc = subprocess.run(
                [_BLKID_BIN, "-o", "value", "-s", "TYPE", device_path],
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
            # blkid returns exit code 2 when no fs signature is found
            if proc.returncode == 2 or (proc.returncode == 0 and not proc.stdout.strip()):
                return "unformatted"
            if proc.returncode == 0:
                return proc.stdout.decode(errors="replace").strip().lower()
            # Non-zero exit code other than 2 — fall through to lsblk
            return None
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("blkid failed for %s: %s", device_path, exc)
            return None

    def _try_lsblk(self, device_path: str) -> str | None:
        """Try ``lsblk --json -o FSTYPE <device>``.

        Returns the canonical fs label, ``'unformatted'`` for empty/null, or
        ``None`` on failure.
        """
        try:
            proc = subprocess.run(
                [_LSBLK_BIN, "--json", "-o", "FSTYPE", device_path],
                capture_output=True,
                timeout=settings.subprocess_timeout_seconds,
            )
            if proc.returncode != 0:
                return None
            data = json.loads(proc.stdout)
            devices = data.get("blockdevices", [])
            if devices:
                fstype = devices[0].get("fstype")
                if fstype:
                    return fstype.strip().lower()
                return "unformatted"
            return "unformatted"
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, KeyError) as exc:
            logger.debug("lsblk failed for %s: %s", device_path, exc)
            return None
