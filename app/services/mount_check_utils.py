from typing import Optional

from app.config import settings
from app.infrastructure.mount_protocol import MountProvider


def check_mounted_with_configured_timeout(provider: MountProvider, local_mount_point: str) -> Optional[bool]:
    """Invoke mount checks with configured timeout and support legacy provider signatures."""
    try:
        return provider.check_mounted(
            local_mount_point,
            timeout_seconds=settings.subprocess_timeout_seconds,
        )
    except TypeError as exc:
        if "timeout_seconds" not in str(exc):
            raise
        return provider.check_mounted(local_mount_point)