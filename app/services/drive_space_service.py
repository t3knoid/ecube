"""Async USB drive available-space refresh support."""
from __future__ import annotations

import atexit
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.database import SessionLocal, is_database_configured
from app.infrastructure import DriveSpaceProbe, get_drive_space_probe
from app.models.hardware import UsbDrive
from app.repositories.drive_repository import DriveRepository


logger = logging.getLogger(__name__)

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()
_pending_ids: set[int] = set()
_pending_lock = threading.Lock()
_MAX_WORKERS = 2


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="drive-space")
                atexit.register(_shutdown_executor)
    return _executor


def _shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


def _should_probe(drive: Optional[UsbDrive]) -> bool:
    if drive is None:
        return False
    return bool(drive.mount_path)


def request_available_space_refresh(drive_id: Optional[int], *, probe: Optional[DriveSpaceProbe] = None) -> None:
    if not isinstance(drive_id, int) or drive_id <= 0:
        return
    if not is_database_configured():
        return

    with _pending_lock:
        if drive_id in _pending_ids:
            return
        _pending_ids.add(drive_id)

    try:
        _get_executor().submit(_refresh_available_space_sync, drive_id, probe)
    except Exception as exc:
        with _pending_lock:
            _pending_ids.discard(drive_id)
        logger.info(
            "Drive available-space refresh could not be scheduled",
            extra={
                "drive_id": drive_id,
                "failure_class": "available_space_refresh_schedule_failed",
            },
        )
        logger.debug(
            "Drive available-space refresh scheduling diagnostics",
            extra={
                "drive_id": drive_id,
                "raw_error": str(exc),
            },
        )
        logger.exception("Drive available-space refresh scheduling raised an unexpected exception")


def request_available_space_refresh_for_drive(drive: Optional[UsbDrive], *, probe: Optional[DriveSpaceProbe] = None) -> None:
    if not _should_probe(drive):
        return
    request_available_space_refresh(getattr(drive, "id", None), probe=probe)


def _refresh_available_space_sync(drive_id: int, probe: Optional[DriveSpaceProbe] = None) -> None:
    try:
        space_probe = probe or get_drive_space_probe()
        db = SessionLocal()
        try:
            drive_repo = DriveRepository(db)
            drive = drive_repo.get_for_update(drive_id)
            if not _should_probe(drive):
                return

            available_bytes = space_probe.probe_available_bytes(drive.mount_path)
            if available_bytes is None:
                return
            if drive.available_bytes == available_bytes:
                return

            drive.available_bytes = available_bytes
            drive_repo.save(drive)
        finally:
            db.close()
    except Exception as exc:
        logger.info(
            "Drive available-space refresh failed",
            extra={"drive_id": drive_id, "failure_class": "available_space_refresh_failed"},
        )
        logger.debug(
            "Drive available-space refresh diagnostics",
            extra={"drive_id": drive_id, "raw_error": str(exc)},
        )
        logger.exception("Drive available-space refresh task raised an unexpected exception")
    finally:
        with _pending_lock:
            _pending_ids.discard(drive_id)