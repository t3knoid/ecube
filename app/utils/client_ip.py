import ipaddress

from fastapi import Request

from app.config import settings

#: Maximum length stored for a client IP string (covers IPv6 mapped addresses).
_MAX_IP_LENGTH = 45


def _validated_ip(value: str) -> str | None:
    """Return the normalised IP string if *value* is a valid address, else ``None``."""
    candidate = value.strip()[:_MAX_IP_LENGTH]
    try:
        return str(ipaddress.ip_address(candidate))
    except (ValueError, TypeError):
        return None


def get_client_ip(request: Request) -> str:
    """Extract the client IP address from a request.

    When :pydata:`~app.config.Settings.trust_proxy_headers` is ``True``,
    ``X-Forwarded-For`` (first entry) and ``X-Real-IP`` are honoured,
    but only if the extracted value is a syntactically valid IP address.
    Malformed values are silently ignored and the function falls through
    to ``request.client.host``.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = _validated_ip(forwarded.split(",")[0])
            if ip:
                return ip
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            ip = _validated_ip(real_ip)
            if ip:
                return ip
    if request.client:
        return _validated_ip(request.client.host) or "unknown"
    return "unknown"
