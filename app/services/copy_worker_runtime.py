"""Track active ECUBE copy workers for operator diagnostics."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

_active_copy_workers: dict[int, dict[str, Any]] = {}
_active_copy_workers_lock = threading.Lock()


def register_active_copy_worker(*, job_id: int) -> dict[str, Any]:
    """Record the current worker thread as active for the given job."""

    current_thread = threading.current_thread()
    worker_key = int(current_thread.ident or id(current_thread))
    snapshot = {
        "worker_key": worker_key,
        "job_id": int(job_id),
        "worker_label": current_thread.name,
        "native_thread_id": getattr(current_thread, "native_id", None),
        "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "started_monotonic": time.monotonic(),
    }

    with _active_copy_workers_lock:
        _active_copy_workers[worker_key] = snapshot

    return snapshot


def unregister_active_copy_worker(snapshot: dict[str, Any] | None) -> None:
    """Remove a worker snapshot when the copy task finishes."""

    if not snapshot:
        return

    worker_key = snapshot.get("worker_key")
    if not isinstance(worker_key, int):
        return

    with _active_copy_workers_lock:
        current = _active_copy_workers.get(worker_key)
        if current is snapshot:
            _active_copy_workers.pop(worker_key, None)


def list_active_copy_workers() -> list[dict[str, Any]]:
    """Return a shallow snapshot of all currently active copy workers."""

    with _active_copy_workers_lock:
        return [dict(item) for item in _active_copy_workers.values()]