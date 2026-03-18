"""Platform-neutral PAM authentication protocol.

This module contains only the :class:`PamAuthenticator` typing Protocol so
that any module can ``from app.infrastructure.pam_protocol import
PamAuthenticator`` without pulling in Linux-only stdlib modules (``grp``,
``pwd``).  The concrete Linux implementation lives in
:mod:`app.services.pam_service`.
"""

from __future__ import annotations

from typing import List, Protocol


class PamAuthenticator(Protocol):
    """Protocol for PAM authentication backends (allows test mocking)."""

    def authenticate(self, username: str, password: str) -> bool: ...

    def get_user_groups(self, username: str) -> List[str]: ...
