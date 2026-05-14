"""Infrastructure helpers for host subprocess execution.

Services may assemble domain-specific command arguments, but the actual
subprocess invocation lives here so host execution flows through the
infrastructure layer rather than directly through service code.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

RunCallable = Callable[..., subprocess.CompletedProcess[Any]]
WhichCallable = Callable[[str], str | None]


def run_subprocess(
    cmd: Sequence[str],
    *,
    runner: RunCallable | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    active_runner = runner or subprocess.run
    return active_runner(list(cmd), **kwargs)


def open_subprocess(
    cmd: Sequence[str],
    *,
    popen_factory: Callable[..., subprocess.Popen[Any]] | None = None,
    **kwargs: Any,
) -> subprocess.Popen[Any]:
    active_factory = popen_factory or subprocess.Popen
    return active_factory(list(cmd), **kwargs)


def resolve_binary(
    candidates: Sequence[str],
    *,
    which: WhichCallable | None = None,
) -> str | None:
    active_which = which or shutil.which
    for candidate in candidates:
        resolved = active_which(candidate)
        if resolved:
            return resolved
    return None