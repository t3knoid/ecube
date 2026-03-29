"""Runtime detection of Docker/container environments."""

from __future__ import annotations

import os


def is_running_in_docker() -> bool:
    """Return ``True`` when the process is running inside a Docker container.

    Two complementary checks are used:

    1. ``/.dockerenv`` — Docker creates this empty marker file in every
       container; it is absent on bare-metal and most VM hosts.
    2. ``/proc/self/cgroup`` — on cgroup v1 (Linux < 4.5 and most Docker
       images still using it) the cgroup paths contain "docker" or
       "containerd".  On cgroup v2, ``/.dockerenv`` is the reliable signal.

    Returns ``False`` on non-Linux platforms (e.g., macOS with Docker for
    Mac — the application runs *inside* the Linux VM, not the host).
    """
    if os.path.exists("/.dockerenv"):
        return True

    try:
        with open("/proc/self/cgroup", encoding="utf-8") as fh:
            contents = fh.read()
        if "docker" in contents or "containerd" in contents:
            return True
    except OSError:
        pass

    return False
