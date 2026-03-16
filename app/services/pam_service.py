"""PAM-based local authentication and group enumeration (Linux only).

This module provides OS-level credential validation via PAM and reads
group memberships from the system group database. It is used by the
``POST /auth/token`` endpoint whenever system/PAM-backed authentication
is enabled (for example, when ``role_resolver`` is set to ``"local"`` or
``"ldap"`` with LDAP provided via PAM/SSSD).
"""

from __future__ import annotations

import grp
import logging
import pwd
from typing import List, Protocol

logger = logging.getLogger(__name__)


class PamAuthenticator(Protocol):
    """Protocol for PAM authentication backends (allows test mocking)."""

    def authenticate(self, username: str, password: str) -> bool: ...


class LinuxPamAuthenticator:
    """Authenticate credentials against Linux PAM.

    Requires the ``python-pam`` package (``pam.authenticate``).
    """

    def authenticate(self, username: str, password: str) -> bool:
        import pam as _pam  # type: ignore[import-untyped]

        p = _pam.pam()
        return bool(p.authenticate(username, password))


def get_user_groups(username: str) -> List[str]:
    """Return the list of OS group names *username* belongs to.

    Includes the user's primary group and all supplementary groups.
    """
    groups: set[str] = set()

    # Primary group
    try:
        pw = pwd.getpwnam(username)
        primary = grp.getgrgid(pw.pw_gid)
        groups.add(primary.gr_name)
    except KeyError:
        pass

    # Supplementary groups
    for g in grp.getgrall():
        if username in g.gr_mem:
            groups.add(g.gr_name)

    return sorted(groups)
