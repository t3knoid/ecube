from __future__ import annotations

import os

try:
    from app._generated_build_info import BUILD_TIMESTAMP as _GENERATED_BUILD_TIMESTAMP
except ImportError:
    _GENERATED_BUILD_TIMESTAMP = ""


def get_build_timestamp() -> str | None:
    env_timestamp = os.getenv("ECUBE_BUILD_TIMESTAMP", "").strip()
    generated_timestamp = str(_GENERATED_BUILD_TIMESTAMP or "").strip()
    return env_timestamp or generated_timestamp or None