"""Platform-neutral password policy protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PasswordPolicyError(Exception):
    """Raised when password policy operations fail."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class PasswordExpirationInfo:
    """Password expiration state returned for a user account."""

    days_until_expiration: int | None
    warning_days: int | None
    warning_active: bool


class PasswordPolicyProvider(Protocol):
    """Platform-agnostic interface for password policy and expiry inspection."""

    def get_policy_settings(self) -> dict[str, int]: ...

    def update_policy_settings(self, updates: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]: ...

    def get_password_expiration_info(self, username: str) -> PasswordExpirationInfo | None: ...