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

#: Valid POSIX username pattern string (for Path() and OpenAPI).
USERNAME_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"

#: Valid POSIX username: lowercase letter or underscore start, up to 32 chars.
USERNAME_RE = re.compile(USERNAME_PATTERN)

#: Valid group-name pattern string (same rules as usernames on Linux).
GROUPNAME_PATTERN = r"^[a-z_][a-z0-9_-]{0,31}$"

#: Valid group name (same pattern as usernames on Linux).
GROUPNAME_RE = re.compile(GROUPNAME_PATTERN)

#: Usernames that cannot be created/deleted through the API.
RESERVED_USERNAMES: frozenset[str] = frozenset(
    {"root", "ecube", "nobody", "daemon", "bin", "sys"}
)
