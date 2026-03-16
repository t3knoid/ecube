"""OS-level user and group management service.

Wraps ``subprocess.run(["sudo", ...])`` calls to manage Linux users and groups
through the ECUBE API.  The ECUBE FastAPI service runs as a non-root ``ecube``
service account; narrowly scoped sudoers rules
(``deploy/ecube-sudoers``) grant access to the specific binaries used here.

Security notes:
- All arguments are validated at the schema/router layer before reaching here.
- Passwords are passed via stdin to ``chpasswd`` and never appear in logs,
  command lines, or return values.
- The ``ecube`` service account itself cannot be deleted through this layer.
"""

from __future__ import annotations

import grp
import logging
import pwd
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Groups considered ECUBE-relevant for listing/filtering.
ECUBE_GROUPS = {"ecube-admins", "ecube-managers", "ecube-processors", "ecube-auditors"}

# Reserved usernames that cannot be created/deleted through the API.
RESERVED_USERNAMES = {"root", "ecube", "nobody", "daemon", "bin", "sys"}

# Valid POSIX username pattern (matches the router-level check in users.py).
USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# Valid group name pattern.
GROUPNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# Default subprocess timeout (seconds).
_SUBPROCESS_TIMEOUT = settings.subprocess_timeout_seconds


class OSUserError(Exception):
    """Raised when an OS user/group operation fails."""

    def __init__(self, message: str, returncode: int | None = None) -> None:
        self.message = message
        self.returncode = returncode
        super().__init__(message)


@dataclass
class OSUser:
    """Representation of an OS user."""
    username: str
    uid: int
    gid: int
    home: str
    shell: str
    groups: List[str] = field(default_factory=list)


@dataclass
class OSGroup:
    """Representation of an OS group."""
    name: str
    gid: int
    members: List[str] = field(default_factory=list)


def _run_sudo(
    cmd: list[str],
    *,
    stdin_data: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a command with ``sudo`` and return the result.

    Raises :class:`OSUserError` on non-zero exit when *check* is True.
    """
    full_cmd = ["sudo"] + cmd
    # Never log stdin_data (may contain passwords).
    logger.debug("Running: %s", " ".join(full_cmd))
    try:
        result = subprocess.run(
            full_cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise OSUserError(f"Command timed out: {' '.join(cmd)}")

    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise OSUserError(
            f"Command failed (exit {result.returncode}): {stderr}",
            returncode=result.returncode,
        )
    return result


def validate_username(username: str) -> None:
    """Raise :class:`ValueError` if *username* is not a valid POSIX username."""
    if not USERNAME_RE.match(username):
        raise ValueError(
            "Invalid username. Must start with a lowercase letter or underscore, "
            "contain only lowercase letters, digits, hyphens, or underscores, "
            "and be 1-32 characters."
        )


def validate_group_name(name: str) -> None:
    """Raise :class:`ValueError` if *name* is not a valid POSIX group name."""
    if not GROUPNAME_RE.match(name):
        raise ValueError(
            "Invalid group name. Must start with a lowercase letter or underscore, "
            "contain only lowercase letters, digits, hyphens, or underscores, "
            "and be 1-32 characters."
        )


def _is_reserved_username(username: str) -> bool:
    return username in RESERVED_USERNAMES


def user_exists(username: str) -> bool:
    """Check if an OS user exists."""
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def group_exists(name: str) -> bool:
    """Check if an OS group exists."""
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def _get_user_groups(username: str) -> List[str]:
    """Return group names the user belongs to."""
    groups = []
    try:
        for g in grp.getgrall():
            if username in g.gr_mem:
                groups.append(g.gr_name)
        # Also include the user's primary group.
        pw = pwd.getpwnam(username)
        primary = grp.getgrgid(pw.pw_gid).gr_name
        if primary not in groups:
            groups.append(primary)
    except KeyError:
        pass
    return sorted(groups)


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

def create_user(
    username: str,
    password: str,
    groups: Optional[List[str]] = None,
) -> OSUser:
    """Create an OS user, set password, and add to groups.

    Raises :class:`OSUserError` on failure, :class:`ValueError` on bad input.
    """
    validate_username(username)
    if _is_reserved_username(username):
        raise ValueError(f"Cannot create reserved username: {username}")
    if user_exists(username):
        raise OSUserError(f"User '{username}' already exists")
    if not password:
        raise ValueError("Password cannot be empty")

    # Create user with home directory.
    _run_sudo([settings.useradd_binary_path, "-m", username])

    # Set password via stdin (never on command line).
    _run_sudo([settings.chpasswd_binary_path], stdin_data=f"{username}:{password}")

    # Add to requested groups.
    if groups:
        for g in groups:
            validate_group_name(g)
            if not group_exists(g):
                raise OSUserError(f"Group '{g}' does not exist")
        _run_sudo([settings.usermod_binary_path, "-aG", ",".join(groups), username])

    pw = pwd.getpwnam(username)
    return OSUser(
        username=username,
        uid=pw.pw_uid,
        gid=pw.pw_gid,
        home=pw.pw_dir,
        shell=pw.pw_shell,
        groups=_get_user_groups(username),
    )


def list_users(ecube_only: bool = True) -> List[OSUser]:
    """List OS users, optionally filtered to ECUBE-relevant groups."""
    result: List[OSUser] = []
    for pw in pwd.getpwall():
        user_groups = _get_user_groups(pw.pw_name)
        if ecube_only and not any(g in ECUBE_GROUPS for g in user_groups):
            continue
        result.append(
            OSUser(
                username=pw.pw_name,
                uid=pw.pw_uid,
                gid=pw.pw_gid,
                home=pw.pw_dir,
                shell=pw.pw_shell,
                groups=user_groups,
            )
        )
    result.sort(key=lambda u: u.username)
    return result


def delete_user(username: str) -> None:
    """Delete an OS user.

    Raises :class:`OSUserError` on failure, :class:`ValueError` for reserved names.
    """
    validate_username(username)
    if _is_reserved_username(username):
        raise ValueError(f"Cannot delete reserved username: {username}")
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")

    _run_sudo([settings.userdel_binary_path, "-r", username])


def reset_password(username: str, password: str) -> None:
    """Reset an OS user's password.

    Raises :class:`OSUserError` on failure, :class:`ValueError` for bad input.
    """
    validate_username(username)
    if not password:
        raise ValueError("Password cannot be empty")
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")

    _run_sudo([settings.chpasswd_binary_path], stdin_data=f"{username}:{password}")


def set_user_groups(username: str, groups: List[str]) -> OSUser:
    """Replace a user's supplementary group memberships.

    Returns the updated :class:`OSUser`.
    """
    validate_username(username)
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")

    for g in groups:
        validate_group_name(g)
        if not group_exists(g):
            raise OSUserError(f"Group '{g}' does not exist")

    # -G replaces all supplementary groups.
    _run_sudo([settings.usermod_binary_path, "-G", ",".join(groups), username])

    pw = pwd.getpwnam(username)
    return OSUser(
        username=pw.pw_name,
        uid=pw.pw_uid,
        gid=pw.pw_gid,
        home=pw.pw_dir,
        shell=pw.pw_shell,
        groups=_get_user_groups(username),
    )


def add_user_to_groups(username: str, groups: List[str]) -> List[str]:
    """Add a user to supplementary groups without removing existing memberships.

    Uses ``usermod -aG`` (append) instead of ``-G`` (replace).
    Returns the resulting group list.
    """
    validate_username(username)
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")

    for g in groups:
        validate_group_name(g)
        if not group_exists(g):
            raise OSUserError(f"Group '{g}' does not exist")

    _run_sudo([settings.usermod_binary_path, "-aG", ",".join(groups), username])
    return _get_user_groups(username)


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------

def create_group(name: str) -> OSGroup:
    """Create an OS group.

    Raises :class:`OSUserError` on failure, :class:`ValueError` on bad input.
    """
    validate_group_name(name)
    if group_exists(name):
        raise OSUserError(f"Group '{name}' already exists")

    _run_sudo([settings.groupadd_binary_path, name])

    g = grp.getgrnam(name)
    return OSGroup(name=g.gr_name, gid=g.gr_gid, members=list(g.gr_mem))


def list_groups(ecube_only: bool = True) -> List[OSGroup]:
    """List OS groups, optionally filtered to ECUBE-relevant names."""
    result: List[OSGroup] = []
    for g in grp.getgrall():
        if ecube_only and g.gr_name not in ECUBE_GROUPS:
            continue
        result.append(
            OSGroup(name=g.gr_name, gid=g.gr_gid, members=list(g.gr_mem))
        )
    result.sort(key=lambda x: x.name)
    return result


def delete_group(name: str) -> None:
    """Delete an OS group.

    Raises :class:`OSUserError` on failure, :class:`ValueError` for bad input.
    """
    validate_group_name(name)
    if not group_exists(name):
        raise OSUserError(f"Group '{name}' does not exist")

    _run_sudo([settings.groupdel_binary_path, name])


# ---------------------------------------------------------------------------
# First-run helpers
# ---------------------------------------------------------------------------

def ensure_ecube_groups() -> List[str]:
    """Create all ECUBE groups that don't already exist.

    Returns the list of groups that were created.
    """
    created = []
    for group_name in sorted(ECUBE_GROUPS):
        if not group_exists(group_name):
            _run_sudo([settings.groupadd_binary_path, group_name])
            created.append(group_name)
    return created
