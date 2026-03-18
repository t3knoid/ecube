"""Centralised block-device path validation.

Every infrastructure module that needs to validate a ``/dev/…`` path
imports from here so the pattern is defined exactly once.
"""
from __future__ import annotations

import re

# Allowed block-device path pattern: /dev/<name>, e.g. /dev/sdb, /dev/sdc1.
_DEVICE_PATH_RE = re.compile(r"^/dev/[a-zA-Z][a-zA-Z0-9]*$")


def validate_device_path(path: str) -> bool:
    """Return ``True`` if *path* matches the expected block-device pattern."""
    return bool(_DEVICE_PATH_RE.match(path))
