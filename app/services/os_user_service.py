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
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from app.config import settings
from app.constants import (
    ECUBE_GROUP_PREFIX,
    ECUBE_GROUPS,
    GROUPNAME_RE,
    RESERVED_USERNAMES,
    USERNAME_RE,
)

logger = logging.getLogger(__name__)

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


_UNSAFE_PASSWORD_CHARS = frozenset("\n\r:")


def validate_password(password: str) -> None:
    """Raise :class:`ValueError` if *password* contains characters unsafe for chpasswd.

    ``chpasswd`` parses ``username:password`` lines delimited by newlines, so
    ``\\n``, ``\\r``, and ``:`` in the password could cause it to misinterpret
    the input and change passwords for unintended accounts.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    found = _UNSAFE_PASSWORD_CHARS.intersection(password)
    if found:
        # Describe offending characters without echoing the password itself.
        labels = sorted(
            "newline" if c == "\n" else "carriage-return" if c == "\r" else "colon"
            for c in found
        )
        raise ValueError(
            f"Password contains unsafe characters: {', '.join(labels)}. "
            "Newlines and colons are not permitted."
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


def _is_ecube_managed(username: str) -> bool:
    """Return True if *username* belongs to at least one ``ecube-*`` group."""
    # First, check the user's primary group.
    try:
        pw_entry = pwd.getpwnam(username)
    except KeyError:
        # User does not exist.
        return False

    try:
        primary_group = grp.getgrgid(pw_entry.pw_gid)
        if primary_group.gr_name.startswith(ECUBE_GROUP_PREFIX):
            return True
    except KeyError:
        # Primary group not found; fall back to supplementary groups.
        pass

    # Then, check any supplementary groups the user belongs to.
    try:
        for g in grp.getgrall():
            if username in g.gr_mem and g.gr_name.startswith(ECUBE_GROUP_PREFIX):
                return True
    except KeyError:
        # Defensive: some platforms may raise KeyError for invalid group entries.
        pass
    return False


def _require_ecube_managed_user(username: str) -> None:
    """Raise ``ValueError`` unless *username* is an ECUBE-managed account.

    The user must not be in :data:`RESERVED_USERNAMES` **and** must belong to
    at least one ``ecube-*`` group.  This prevents accidental mutation of
    system/service accounts (e.g. ``postgres``, ``www-data``) that happen to
    pass the POSIX username regex.
    """
    if _is_reserved_username(username):
        raise ValueError(f"Cannot modify reserved system account: {username}")
    if not _is_ecube_managed(username):
        raise ValueError(
            f"User '{username}' is not in any ecube-* group and cannot be "
            "managed through this API. Only ECUBE-managed accounts can be "
            "modified or deleted."
        )


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
    validate_password(password)

    # Validate all requested groups BEFORE creating the user so that
    # invalid input never leaves a partially-created account behind.
    ecube_groups_found = False
    if groups:
        for g in groups:
            validate_group_name(g)
            if not group_exists(g):
                raise OSUserError(f"Group '{g}' does not exist")
            if g.startswith(ECUBE_GROUP_PREFIX):
                ecube_groups_found = True

    if not ecube_groups_found:
        raise ValueError(
            "At least one group starting with '"
            f"{ECUBE_GROUP_PREFIX}' is required so the account "
            "remains manageable through the API."
        )

    # Create user with home directory.
    _run_sudo([settings.useradd_binary_path, "-m", username])

    # Set password via stdin (never on command line).
    _run_sudo([settings.chpasswd_binary_path], stdin_data=f"{username}:{password}")

    # Add to requested groups.  If usermod fails, delete the newly created
    # user so the caller never sees a partial account.
    if groups:
        try:
            _run_sudo([settings.usermod_binary_path, "-aG", ",".join(groups), username])
        except OSUserError:
            try:
                _run_sudo([settings.userdel_binary_path, "-r", username])
            except Exception:
                logger.exception(
                    "Failed to clean up OS user '%s' after usermod failure",
                    username,
                )
            raise

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
    # Build a username→groups mapping in one pass over grp.getgrall()
    # to avoid O(users×groups) repeated scans.
    all_groups = grp.getgrall()
    user_group_map: dict[str, list[str]] = {}
    for g in all_groups:
        for member in g.gr_mem:
            user_group_map.setdefault(member, []).append(g.gr_name)

    result: List[OSUser] = []
    for pw in pwd.getpwall():
        groups = list(user_group_map.get(pw.pw_name, []))
        # Include the primary group.
        try:
            primary = grp.getgrgid(pw.pw_gid).gr_name
            if primary not in groups:
                groups.append(primary)
        except KeyError:
            pass
        groups.sort()
        if ecube_only and not any(g.startswith(ECUBE_GROUP_PREFIX) for g in groups):
            continue
        result.append(
            OSUser(
                username=pw.pw_name,
                uid=pw.pw_uid,
                gid=pw.pw_gid,
                home=pw.pw_dir,
                shell=pw.pw_shell,
                groups=groups,
            )
        )
    result.sort(key=lambda u: u.username)
    return result


def delete_user(username: str, *, _skip_managed_check: bool = False) -> None:
    """Delete an OS user.

    Raises :class:`OSUserError` on failure, :class:`ValueError` for reserved
    or non-ECUBE-managed users.

    The private *_skip_managed_check* flag is used internally for compensation
    (e.g. cleaning up a just-created user whose group assignment failed before
    any ``ecube-*`` membership was established).
    """
    validate_username(username)
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")
    if not _skip_managed_check:
        _require_ecube_managed_user(username)

    _run_sudo([settings.userdel_binary_path, "-r", username])


def reset_password(username: str, password: str, *, _skip_managed_check: bool = False) -> None:
    """Reset an OS user's password.

    Raises :class:`OSUserError` on failure, :class:`ValueError` for bad input
    or non-ECUBE-managed users.

    The private *_skip_managed_check* flag is used by the setup wizard's
    recovery path where the user may not yet be in an ``ecube-*`` group.
    """
    validate_username(username)
    validate_password(password)
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")
    if not _skip_managed_check:
        _require_ecube_managed_user(username)

    _run_sudo([settings.chpasswd_binary_path], stdin_data=f"{username}:{password}")


def set_user_groups(username: str, groups: List[str]) -> OSUser:
    """Replace a user's ``ecube-*`` supplementary groups.

    Only group names starting with the ``ecube-`` prefix are accepted.
    Non-ECUBE supplementary groups are preserved automatically so that
    ``usermod -G`` never strips memberships the API does not manage.

    Raises :class:`ValueError` on bad input, :class:`OSUserError` on failure.
    Returns the updated :class:`OSUser`.
    """
    validate_username(username)

    if not groups:
        raise ValueError(
            "At least one group starting with '"
            f"{ECUBE_GROUP_PREFIX}' is required so the account "
            "remains manageable through the API."
        )

    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")
    _require_ecube_managed_user(username)

    for g in groups:
        validate_group_name(g)
        if not g.startswith(ECUBE_GROUP_PREFIX):
            raise ValueError(
                f"Group '{g}' does not start with '{ECUBE_GROUP_PREFIX}'. "
                "Use the append endpoint (POST) to add non-ECUBE groups."
            )
        if not group_exists(g):
            raise OSUserError(f"Group '{g}' does not exist")

    # Preserve existing non-ecube-* supplementary groups.
    current_groups = _get_user_groups(username)
    non_ecube = [g for g in current_groups if not g.startswith(ECUBE_GROUP_PREFIX)]
    final_groups = sorted(set(groups) | set(non_ecube))

    # -G replaces all supplementary groups.
    _run_sudo([settings.usermod_binary_path, "-G", ",".join(final_groups), username])

    pw = pwd.getpwnam(username)
    return OSUser(
        username=pw.pw_name,
        uid=pw.pw_uid,
        gid=pw.pw_gid,
        home=pw.pw_dir,
        shell=pw.pw_shell,
        groups=_get_user_groups(username),
    )


def add_user_to_groups(username: str, groups: List[str], *, _skip_managed_check: bool = False) -> OSUser:
    """Add a user to supplementary groups without removing existing memberships.

    Uses ``usermod -aG`` (append) instead of ``-G`` (replace).
    Returns the updated :class:`OSUser`.

    The private *_skip_managed_check* flag is used by the setup wizard's
    recovery path where the user may not yet be in an ``ecube-*`` group.
    """
    validate_username(username)
    if not user_exists(username):
        raise OSUserError(f"User '{username}' does not exist")
    if not _skip_managed_check:
        _require_ecube_managed_user(username)

    for g in groups:
        validate_group_name(g)
        if not group_exists(g):
            raise OSUserError(f"Group '{g}' does not exist")

    _run_sudo([settings.usermod_binary_path, "-aG", ",".join(groups), username])

    pw = pwd.getpwnam(username)
    return OSUser(
        username=pw.pw_name,
        uid=pw.pw_uid,
        gid=pw.pw_gid,
        home=pw.pw_dir,
        shell=pw.pw_shell,
        groups=_get_user_groups(username),
    )


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------

def create_group(name: str) -> OSGroup:
    """Create an OS group.

    Only groups with the ``ecube-`` prefix can be created through the API
    to prevent accidental interference with host-OS groups.

    Raises :class:`OSUserError` on failure, :class:`ValueError` on bad input.
    """
    validate_group_name(name)
    if not name.startswith(ECUBE_GROUP_PREFIX):
        raise ValueError(
            f"Group name must start with '{ECUBE_GROUP_PREFIX}'. "
            "Only ECUBE-managed groups can be created through the API."
        )
    if group_exists(name):
        raise OSUserError(f"Group '{name}' already exists")

    _run_sudo([settings.groupadd_binary_path, name])

    g = grp.getgrnam(name)
    return OSGroup(name=g.gr_name, gid=g.gr_gid, members=list(g.gr_mem))


def list_groups(ecube_only: bool = True) -> List[OSGroup]:
    """List OS groups, optionally filtered to ECUBE-relevant names."""
    result: List[OSGroup] = []
    for g in grp.getgrall():
        if ecube_only and not g.gr_name.startswith(ECUBE_GROUP_PREFIX):
            continue
        result.append(
            OSGroup(name=g.gr_name, gid=g.gr_gid, members=list(g.gr_mem))
        )
    result.sort(key=lambda x: x.name)
    return result


def delete_group(name: str) -> None:
    """Delete an OS group.

    Only groups with the ``ecube-`` prefix can be deleted through the API
    to prevent accidental interference with host-OS groups.

    Raises :class:`OSUserError` on failure, :class:`ValueError` for bad input.
    """
    validate_group_name(name)
    if not name.startswith(ECUBE_GROUP_PREFIX):
        raise ValueError(
            f"Group name must start with '{ECUBE_GROUP_PREFIX}'. "
            "Only ECUBE-managed groups can be deleted through the API."
        )
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
