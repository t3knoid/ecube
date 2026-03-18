"""Platform-neutral OS user/group management protocol and shared types.

This module contains:

* :class:`OsUserProvider` — the typing Protocol for OS user operations.
* :class:`OSUser` / :class:`OSGroup` — pure dataclasses returned by the
  provider.
* :class:`OSUserError` — domain exception for OS user failures.

Importing this module has **no** platform-specific dependencies so it is safe
on any OS.  The concrete Linux implementation lives in
:mod:`app.services.os_user_service`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol


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


class OsUserProvider(Protocol):
    """Platform-agnostic interface for OS user and group management."""

    def user_exists(self, username: str) -> bool: ...
    def group_exists(self, name: str) -> bool: ...
    def create_user(self, username: str, password: str, groups: Optional[List[str]] = None) -> OSUser: ...
    def list_users(self, ecube_only: bool = True) -> List[OSUser]: ...
    def delete_user(self, username: str, *, _skip_managed_check: bool = False) -> None: ...
    def reset_password(self, username: str, password: str, *, _skip_managed_check: bool = False) -> None: ...
    def set_user_groups(self, username: str, groups: List[str]) -> OSUser: ...
    def add_user_to_groups(self, username: str, groups: List[str], *, _skip_managed_check: bool = False) -> OSUser: ...
    def create_group(self, name: str) -> OSGroup: ...
    def list_groups(self, ecube_only: bool = True) -> List[OSGroup]: ...
    def delete_group(self, name: str) -> None: ...
    def ensure_ecube_groups(self) -> List[str]: ...
