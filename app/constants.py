"""Shared constants used across the ECUBE application.

Centralises group/role mappings, username validation, and other values
that were previously duplicated in multiple modules.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Group ↔ role mapping
# ---------------------------------------------------------------------------

#: Canonical mapping from OS group name to ECUBE role.
ECUBE_GROUP_ROLE_MAP: dict[str, str] = {
    "ecube-admins": "admin",
    "ecube-managers": "manager",
    "ecube-processors": "processor",
    "ecube-auditors": "auditor",
}

#: Set of all ECUBE-managed group names (derived from the canonical map).
ECUBE_GROUPS: frozenset[str] = frozenset(ECUBE_GROUP_ROLE_MAP)

#: Set of valid ECUBE role strings (derived from the canonical map).
VALID_ROLES: frozenset[str] = frozenset(ECUBE_GROUP_ROLE_MAP.values())

#: Prefix shared by all ECUBE-managed groups.
ECUBE_GROUP_PREFIX: str = "ecube-"

# ---------------------------------------------------------------------------
# Username / group-name validation
# ---------------------------------------------------------------------------

#: Canonical POSIX name pattern (lowercase letter or underscore start,
#: then up to 31 alphanumeric/underscore/hyphen chars).  Used for both
#: usernames and group names, which follow the same rules on Linux.
_POSIX_NAME_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"

#: Valid POSIX username.
USERNAME_RE = re.compile(_POSIX_NAME_PATTERN)

#: Valid group name — intentionally the same pattern as usernames on Linux.
#: Aliased to a shared regex so the two cannot accidentally diverge.
GROUPNAME_RE = USERNAME_RE

#: Usernames that cannot be created/deleted through the API.
RESERVED_USERNAMES: frozenset[str] = frozenset(
    {"root", "ecube", "nobody", "daemon", "bin", "sys"}
)
