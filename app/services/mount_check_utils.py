import inspect
from typing import Optional

from app.config import settings
from app.infrastructure.mount_protocol import MountProvider

# Cache attribute name for provider capability; avoids repeated expensive signature inspection
_SUPPORTS_TIMEOUT_SECONDS_ATTR = "_mount_check_supports_timeout_seconds"


def _check_accepts_timeout_seconds(provider: MountProvider) -> bool:
    """Check if provider.check_mounted accepts timeout_seconds keyword (inspects signature).
    
    Returns False (conservative fallback) if signature inspection fails,
    so mount check failures are not incorrectly attributed to introspection errors.
    """
    try:
        signature = inspect.signature(provider.check_mounted)
    except (ValueError, TypeError):
        # If signature inspection fails, treat provider as not supporting timeout_seconds
        # to avoid incorrectly marking mount state as ERROR due to introspection failure.
        return False

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


def _provider_supports_timeout_seconds(provider: MountProvider) -> bool:
    """Return cached capability or inspect once and cache the result on the provider."""
    cached = getattr(provider, _SUPPORTS_TIMEOUT_SECONDS_ATTR, None)
    if cached is not None:
        return cached
    
    supports = _check_accepts_timeout_seconds(provider)
    try:
        setattr(provider, _SUPPORTS_TIMEOUT_SECONDS_ATTR, supports)
    except (AttributeError, TypeError):
        # If we can't cache on the provider (e.g., frozen/slotted classes), just return
        pass
    
    return supports


def check_mounted_with_configured_timeout(provider: MountProvider, local_mount_point: str) -> Optional[bool]:
    """Invoke mount checks with configured timeout and support legacy provider signatures.
    
    Capability is cached per provider instance to avoid repeated expensive signature inspection.
    If signature inspection fails, provider is conservatively treated as not supporting timeout_seconds.
    """
    if _provider_supports_timeout_seconds(provider):
        return provider.check_mounted(
            local_mount_point,
            timeout_seconds=settings.subprocess_timeout_seconds,
        )
    return provider.check_mounted(local_mount_point)