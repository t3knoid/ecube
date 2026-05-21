"""Shared callback URL validation helpers."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse


def validate_callback_url_value(
    *,
    field_name: str,
    value: Optional[str],
    allow_insecure_http: bool,
    confirmation_field_name: str,
) -> Optional[str]:
    """Normalize and validate callback URLs.

    HTTPS remains the default transport. Plain HTTP is accepted only when the
    caller explicitly confirms insecure/test-only use through the paired
    confirmation field.
    """

    if value is None:
        return value

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")

    try:
        parsed = urlparse(normalized)
    except Exception as exc:
        raise ValueError(f"{field_name} is not a valid URL") from exc

    scheme = parsed.scheme.lower()
    if scheme == "https":
        pass
    elif scheme == "http":
        if not allow_insecure_http:
            raise ValueError(
                f"{field_name} must use HTTPS unless {confirmation_field_name} is true"
            )
    else:
        raise ValueError(f"{field_name} must use HTTPS")

    if not parsed.hostname:
        raise ValueError(f"{field_name} must include a hostname")
    if parsed.username or parsed.password:
        raise ValueError(f"{field_name} must not contain embedded credentials")

    return normalized