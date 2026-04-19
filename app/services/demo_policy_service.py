"""Trusted demo-mode policy helpers for ECUBE administrative actions."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import AuthorizationError
from app.repositories.audit_repository import best_effort_audit

DEMO_USER_MANAGEMENT_LOCK_MESSAGE = (
    "Creating users and modifying user roles is disabled in demo mode."
)


def is_demo_user_management_locked() -> bool:
    """Return whether demo mode should make user-management writes read-only."""
    return bool(settings.is_demo_mode_enabled())


def enforce_user_management_write_allowed(
    *,
    db: Session,
    actor: str,
    user_roles: list[str],
    path: str,
    method: str,
    attempted_action: str,
    client_ip: str | None = None,
    target_user: str | None = None,
) -> None:
    """Block user-creation and role-mutation writes while demo mode is enabled."""
    if not is_demo_user_management_locked():
        return

    details = {
        "path": path,
        "method": method,
        "required_roles": ["admin"],
        "user_roles": list(user_roles or []),
        "attempted_action": attempted_action,
        "reason": DEMO_USER_MANAGEMENT_LOCK_MESSAGE,
    }
    if target_user:
        details["target_user"] = target_user

    best_effort_audit(
        db,
        "AUTHORIZATION_DENIED",
        actor,
        details,
        client_ip=client_ip,
    )
    raise AuthorizationError(DEMO_USER_MANAGEMENT_LOCK_MESSAGE)
