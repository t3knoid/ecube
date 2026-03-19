from fastapi import Request

from app.config import settings


def get_client_ip(request: Request) -> str:
    """Extract the client IP address from a request.

    When :pydata:`~app.config.Settings.trust_proxy_headers` is ``True``,
    ``X-Forwarded-For`` (first entry) and ``X-Real-IP`` are honoured.
    Otherwise only the direct connection address is returned, preventing
    header-spoofing attacks.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
    return request.client.host if request.client else "unknown"
