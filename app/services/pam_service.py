"""PAM-based local authentication and group enumeration (Linux only).

This module provides OS-level credential validation via PAM and reads
group memberships from the system group database. It is used by the
``POST /auth/token`` endpoint whenever system/PAM-backed authentication
is enabled (for example, when ``role_resolver`` is set to ``"local"`` or
``"ldap"`` with LDAP provided via PAM/SSSD).
"""

from __future__ import annotations

import logging
import os

try:
    import grp
    import pwd
except ImportError:  # pragma: no cover – Linux-only stdlib modules
    grp = None  # type: ignore[assignment]
    pwd = None  # type: ignore[assignment]
from typing import List

# Re-export so existing ``from app.services.pam_service import PamAuthenticator``
# keeps working.
from app.infrastructure.pam_protocol import PamAuthenticator  # noqa: F401 – re-export

logger = logging.getLogger(__name__)


def _require_posix() -> None:
    """Raise a clear error when POSIX modules are unavailable."""
    if pwd is None or grp is None:
        raise RuntimeError(
            "This function requires the 'pwd' and 'grp' modules "
            "which are only available on POSIX/Linux systems."
        )


class LinuxPamAuthenticator:
    """Authenticate credentials against Linux PAM.

    Requires the ``python-pam`` package (``pam.authenticate``).
    """

    def __init__(self) -> None:
        _require_posix()

    def authenticate(self, username: str, password: str) -> bool:
        import pam as _pam  # type: ignore[import-untyped]
                            # lazy import avoids import-time failure on non-Linux platforms

        p = _pam.pam()
        return bool(p.authenticate(username, password))

    def get_user_groups(self, username: str) -> List[str]:
        return get_user_groups(username)


def get_user_groups(username: str) -> List[str]:
    """Return the list of OS group names *username* belongs to.

    Includes the user's primary group and all supplementary groups.
    """
    _require_posix()
    groups: set[str] = set()

    try:
        pw = pwd.getpwnam(username)
    except KeyError:
        logger.warning(
            "OS user %s not found in passwd database",
            username,
        )
        return sorted(groups)

    # All groups (primary + supplementary) via getgrouplist(3),
    # avoids the O(total-groups) scan of grp.getgrall().
    for gid in os.getgrouplist(username, pw.pw_gid):
        try:
            groups.add(grp.getgrgid(gid).gr_name)
        except KeyError:
            logger.debug("GID %s has no group database entry", gid)

    return sorted(groups)
