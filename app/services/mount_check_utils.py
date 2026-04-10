import inspect
from typing import Optional

from app.config import settings
from app.infrastructure.mount_protocol import MountProvider


def _accepts_timeout_seconds(provider: MountProvider) -> bool:
    """Return True when provider.check_mounted accepts timeout_seconds keyword."""
    signature = inspect.signature(provider.check_mounted)
    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    timeout_param = signature.parameters.get("timeout_seconds")
    if timeout_param is None:
        return False
    return timeout_param.kind in (
        inspect.Parameter.KEYWORD_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )


def check_mounted_with_configured_timeout(provider: MountProvider, local_mount_point: str) -> Optional[bool]:
    """Invoke mount checks with configured timeout and support legacy provider signatures."""
    if _accepts_timeout_seconds(provider):
        return provider.check_mounted(
            local_mount_point,
            timeout_seconds=settings.subprocess_timeout_seconds,
        )
    return provider.check_mounted(local_mount_point)