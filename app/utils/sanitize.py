"""Unicode string sanitization for database-safe input handling.

Strips null bytes and surrogate code points (U+D800\u2013U+DFFF) that pass
Pydantic validation but cause PostgreSQL to reject the value at insert
time (issue #124).
"""

import re
from typing import Annotated, Optional

from pydantic import BeforeValidator

# Matches any surrogate code point (U+D800–U+DFFF), all of which are
# invalid in UTF-8 and rejected by PostgreSQL.
_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

# Substrings in DB exception messages that indicate encoding/character issues.
_ENCODING_ERROR_MARKERS = (
    "invalid byte sequence",
    "character with byte sequence",
    "unsupported unicode",
    "invalid unicode",
    "null character",
    "\\x00",
    "0x00",
)


def sanitize_string(value: object) -> object:
    """Strip null bytes and surrogate code points from a string value.

    Removes all code points in U+D800\u2013U+DFFF (not just unpaired
    surrogates) because they are invalid in UTF-8 and cannot be stored
    in PostgreSQL.  Non-string values are returned unchanged so this can
    be used safely as a Pydantic ``BeforeValidator`` on ``Optional``
    fields.
    """
    if not isinstance(value, str):
        return value
    value = value.replace("\x00", "")
    value = _SURROGATE_RE.sub("", value)
    return value


def strict_sanitize_string(value: object) -> object:
    """Reject strings that contain null bytes or surrogate code points.

    Unlike :func:`sanitize_string` (which silently strips), this raises
    ``ValueError`` so Pydantic returns a 422.  Use for path-like fields
    where silent modification could change the OS-level target.
    """
    if not isinstance(value, str):
        return value
    if "\x00" in value or _SURROGATE_RE.search(value):
        raise ValueError(
            "Value contains invalid characters (null bytes or surrogate code points) "
            "that are not allowed in path fields"
        )
    return value


def normalize_project_id(value: object) -> object:
    """Canonicalize project identifiers for storage and comparison.

    Project IDs are treated case-insensitively in ECUBE workflows. This keeps
    a stable representation by removing invalid Unicode, trimming surrounding
    whitespace, and uppercasing the remaining value.
    """
    value = sanitize_string(value)
    if not isinstance(value, str):
        return value
    return value.strip().upper()


_PATH_LIKE_RE = re.compile(r"(?<![A-Za-z0-9._-])/(?:[^\s'\"=:;,])+")


def redact_pathlike_substrings(value: object, placeholder: str = "[redacted-path]") -> str:
    """Replace path-like substrings in error text with a safe placeholder."""
    if value is None:
        return ""
    text = sanitize_string(str(value))
    return _PATH_LIKE_RE.sub(placeholder, text)


def sanitize_error_message(err: object, default_message: str = "Operation failed") -> str:
    """Return a filesystem-safe summary for provider and OS errors."""
    if err is None:
        return default_message

    redacted = redact_pathlike_substrings(err).strip()
    if not redacted:
        return default_message

    lowered = redacted.lower()
    if any(token in lowered for token in ("permission denied", "access denied", "auth")):
        return "Permission or authentication failure"
    if "timed out" in lowered or "timeout" in lowered:
        return "Operation timed out"
    if "not mounted" in lowered or "no mount point" in lowered:
        return "Target was already unmounted"
    if "busy" in lowered:
        return "Target is busy"
    if "invalid device path" in lowered:
        return "Invalid device path"
    if "unknown filesystem type" in lowered or "wrong fs type" in lowered or "bad superblock" in lowered:
        return "Filesystem type is not supported by the host"
    return default_message


_AUDIT_REDACTED = "[redacted]"
_AUDIT_SENSITIVE_KEYS = {
    "filesystem_path",
    "mount_path",
    "local_mount_point",
    "remote_path",
    "device_name",
    "device_identifier",
    "system_path",
    "mount_label",
    "mount_slot",
    "serial",
    "serial_number",
    "drive_sn",
    "dev",
}
_AUDIT_ERROR_TEXT_KEYS = {"error", "details", "raw_error", "reason", "message"}
_SYSTEM_PATH_PREFIXES = (
    "/dev/",
    "/mnt/",
    "/media/",
    "/run/",
    "/nfs/",
    "/smb/",
    "/proc/",
    "/sys/",
    "/tmp/",
    "/var/",
)


def sanitize_audit_details(details: object) -> object:
    """Recursively sanitize audit metadata before it is persisted.

    This provides a final repository-side safety net so raw paths, device
    identifiers, and provider error text are not written verbatim even if an
    individual caller forgets to sanitize them first.
    """
    return _sanitize_audit_value(details)


def _sanitize_audit_value(value: object, key: Optional[str] = None) -> object:
    key_lower = key.lower() if isinstance(key, str) else None

    if isinstance(value, dict):
        return {item_key: _sanitize_audit_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize_audit_value(item, key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_audit_value(item, key) for item in value]
    if not isinstance(value, str):
        return value

    if key_lower in _AUDIT_SENSITIVE_KEYS:
        return _AUDIT_REDACTED

    stripped = sanitize_string(value).strip()
    if key_lower == "path":
        return _AUDIT_REDACTED if any(stripped.startswith(prefix) for prefix in _SYSTEM_PATH_PREFIXES) else stripped

    redacted = redact_pathlike_substrings(value).strip()
    if key_lower in _AUDIT_ERROR_TEXT_KEYS:
        return redacted or "Operation failed"
    return redacted


def is_encoding_error(exc: BaseException) -> bool:
    """Return True if *exc* looks like a database character-encoding failure."""
    msg = str(exc).lower()
    return any(marker in msg for marker in _ENCODING_ERROR_MARKERS)


# Drop-in replacement for ``str`` in Pydantic schemas.
SafeStr = Annotated[str, BeforeValidator(sanitize_string)]

# Project identifier variant: trims and uppercases for stable comparisons.
ProjectIdStr = Annotated[str, BeforeValidator(normalize_project_id)]

# Strict variant for path-like fields: rejects rather than silently modifying.
StrictSafeStr = Annotated[str, BeforeValidator(strict_sanitize_string)]
