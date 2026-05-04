"""Shared mount-namespace detection helpers."""

from __future__ import annotations

from typing import Callable

import os


PROC_SELF_MOUNT_NAMESPACE_PATH = "/proc/self/ns/mnt"
PROC_HOST_MOUNT_NAMESPACE_PATH = "/proc/1/ns/mnt"


def shares_host_mount_namespace(
    *,
    on_self_read_error: bool = True,
    on_host_read_error: bool = True,
    on_host_read_error_callback: Callable[[OSError], None] | None = None,
) -> bool:
    """Return whether the current process shares PID 1's mount namespace.

    Callers can preserve their existing fallback policy by specifying the
    boolean value to use when either namespace symlink cannot be read.
    """
    try:
        current_ns = os.readlink(PROC_SELF_MOUNT_NAMESPACE_PATH)
    except OSError:
        return on_self_read_error

    try:
        host_ns = os.readlink(PROC_HOST_MOUNT_NAMESPACE_PATH)
    except OSError as exc:
        if on_host_read_error_callback is not None:
            on_host_read_error_callback(exc)
        return on_host_read_error

    return current_ns == host_ns