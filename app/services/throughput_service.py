from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import service_exception
from app.infrastructure.throughput_benchmark import ThroughputBenchmarkProvider
from app.models.hardware import DriveFormatStatus, DriveState, UsbDrive
from app.models.network import MountStatus, NetworkShare
from app.repositories.drive_repository import DriveRepository
from app.repositories.share_repository import ShareRepository
from app.services.audit_service import log_and_audit
from app.services.copy_engine import THROUGHPUT_BENCHMARK_SAMPLE_BUCKETS, _build_throughput_benchmark_sample_plan, scan_source_files

logger = logging.getLogger(__name__)

_MANUAL_DRIVE_THROUGHPUT_STATES = {DriveState.AVAILABLE, DriveState.IN_USE}


def _build_drive_write_sample_plan(sample_bytes: int) -> list[tuple[Path, int]]:
    if sample_bytes <= 0:
        return []

    remaining = sample_bytes
    sample_plan: list[tuple[Path, int]] = []
    for sample_index, (lower_bound, _upper_bound) in enumerate(THROUGHPUT_BENCHMARK_SAMPLE_BUCKETS):
        if remaining <= 0:
            break
        if lower_bound <= 0:
            continue
        if remaining < lower_bound:
            sample_plan.append((Path(f"manual-drive-throughput-{sample_index}.bin"), remaining))
            remaining = 0
            break
        sample_plan.append((Path(f"manual-drive-throughput-{sample_index}.bin"), lower_bound))
        remaining -= lower_bound

    if remaining > 0:
        sample_plan.append((Path(f"manual-drive-throughput-{len(sample_plan)}.bin"), remaining))

    return sample_plan


def _log_throughput_debug_failure(
    message: str,
    *,
    target_type: str,
    target_id: int,
    raw_error: BaseException,
) -> None:
    logger.debug(
        message,
        extra={
            "target_type": target_type,
            "target_id": target_id,
            "raw_error": str(raw_error),
        },
        exc_info=True,
    )


def _redacted_mount_label(_local_mount_point: Optional[str]) -> str:
    return "[redacted]"


def test_drive_write_throughput(
    drive_id: int,
    db: Session,
    *,
    benchmark_provider: ThroughputBenchmarkProvider,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> UsbDrive:
    drive_repo = DriveRepository(db)
    drive = drive_repo.get_for_update(drive_id)
    if drive is None:
        raise service_exception(status_code=404, detail="Drive not found")

    if drive.format_status == DriveFormatStatus.PENDING:
        raise service_exception(
            status_code=409,
            detail="Drive format is in progress; wait for formatting to complete before running throughput testing",
        )

    if drive.current_state not in _MANUAL_DRIVE_THROUGHPUT_STATES or not drive.mount_path:
        log_and_audit(
            db,
            "DRIVE_THROUGHPUT_TESTED",
            actor,
            drive_id=drive.id,
            project_id=drive.current_project_id,
            client_ip=client_ip,
            metadata={
                "outcome": "rejected",
                "reason": "drive_not_mounted",
                "current_state": drive.current_state.value if drive.current_state else None,
            },
        )
        raise service_exception(status_code=409, detail="Drive throughput test requires a mounted managed drive")

    sample_plan = _build_drive_write_sample_plan(int(settings.startup_analysis_benchmark_bytes))
    benchmark_bytes = sum(sample_size for _sample_path, sample_size in sample_plan)

    try:
        write_mbps, _elapsed_seconds, _stream_seconds = benchmark_provider.measure_drive_write_mbps(
            drive.mount_path,
            sample_plan,
            benchmark_id=f"drive-{drive.id}",
        )
    except RuntimeError as exc:
        log_and_audit(
            db,
            "DRIVE_THROUGHPUT_TESTED",
            actor,
            drive_id=drive.id,
            project_id=drive.current_project_id,
            client_ip=client_ip,
            metadata={
                "outcome": "rejected",
                "reason": "drive_unavailable",
                "benchmark_bytes": benchmark_bytes,
            },
        )
        _log_throughput_debug_failure(
            "Drive throughput test failed because the mounted drive is unavailable",
            target_type="drive",
            target_id=drive.id,
            raw_error=exc,
        )
        raise service_exception(status_code=409, detail="Mounted drive is unavailable for throughput testing; refresh drive status and retry") from exc
    except Exception as exc:
        log_and_audit(
            db,
            "DRIVE_THROUGHPUT_TESTED",
            actor,
            level=logging.WARNING,
            drive_id=drive.id,
            project_id=drive.current_project_id,
            client_ip=client_ip,
            metadata={
                "outcome": "failed",
                "reason": "benchmark_failed",
                "benchmark_bytes": benchmark_bytes,
            },
        )
        _log_throughput_debug_failure(
            "Drive throughput test failed unexpectedly",
            target_type="drive",
            target_id=drive.id,
            raw_error=exc,
        )
        raise service_exception(status_code=500, detail="Drive throughput test failed; verify the mounted drive is available and retry") from exc

    if write_mbps is None:
        log_and_audit(
            db,
            "DRIVE_THROUGHPUT_TESTED",
            actor,
            level=logging.WARNING,
            drive_id=drive.id,
            project_id=drive.current_project_id,
            client_ip=client_ip,
            metadata={
                "outcome": "failed",
                "reason": "no_measurement",
                "benchmark_bytes": benchmark_bytes,
            },
        )
        raise service_exception(status_code=500, detail="Drive throughput test did not produce a measurement; retry the test")

    drive.throughput_write_mbps = write_mbps
    drive.throughput_tested_at = datetime.now(timezone.utc)
    saved_drive = drive_repo.save(drive)
    log_and_audit(
        db,
        "DRIVE_THROUGHPUT_TESTED",
        actor,
        drive_id=saved_drive.id,
        project_id=saved_drive.current_project_id,
        client_ip=client_ip,
        metadata={
            "outcome": "success",
            "benchmark_bytes": benchmark_bytes,
            "write_mbps": write_mbps,
        },
    )
    return saved_drive


def test_mount_read_throughput(
    mount_id: int,
    db: Session,
    *,
    benchmark_provider: ThroughputBenchmarkProvider,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> NetworkShare:
    mount_repo = ShareRepository(db)
    mount = mount_repo.get(mount_id)
    if mount is None:
        raise service_exception(status_code=404, detail="Mount not found")

    if mount.status != MountStatus.MOUNTED or not mount.local_mount_point:
        log_and_audit(
            db,
            "MOUNT_THROUGHPUT_TESTED",
            actor,
            project_id=mount.project_id,
            client_ip=client_ip,
            metadata={
                "mount_id": mount.id,
                "mount_label": _redacted_mount_label(mount.local_mount_point),
                "outcome": "rejected",
                "reason": "mount_not_mounted",
                "status": mount.status.value if mount.status else None,
            },
        )
        raise service_exception(status_code=409, detail="Share throughput test requires a mounted share")

    try:
        source_files = scan_source_files(mount.local_mount_point)
    except FileNotFoundError as exc:
        log_and_audit(
            db,
            "MOUNT_THROUGHPUT_TESTED",
            actor,
            project_id=mount.project_id,
            client_ip=client_ip,
            metadata={
                "mount_id": mount.id,
                "mount_label": _redacted_mount_label(mount.local_mount_point),
                "outcome": "rejected",
                "reason": "mount_unavailable",
            },
        )
        _log_throughput_debug_failure(
            "Mount throughput test failed because the mounted share is unavailable",
            target_type="mount",
            target_id=mount.id,
            raw_error=exc,
        )
        raise service_exception(status_code=409, detail="Mounted share is unavailable for throughput testing; refresh the mount and retry") from exc

    sample_plan = _build_throughput_benchmark_sample_plan(source_files, int(settings.startup_analysis_benchmark_bytes))
    benchmark_bytes = sum(sample_size for _sample_path, sample_size in sample_plan)
    if not sample_plan or benchmark_bytes <= 0:
        log_and_audit(
            db,
            "MOUNT_THROUGHPUT_TESTED",
            actor,
            project_id=mount.project_id,
            client_ip=client_ip,
            metadata={
                "mount_id": mount.id,
                "mount_label": _redacted_mount_label(mount.local_mount_point),
                "outcome": "rejected",
                "reason": "no_readable_files",
            },
        )
        raise service_exception(status_code=409, detail="Mounted share has no readable files available for throughput testing")

    try:
        read_mbps, _actual_read_bytes, _elapsed_seconds, _stream_seconds = benchmark_provider.measure_share_read_mbps(sample_plan)
    except Exception as exc:
        log_and_audit(
            db,
            "MOUNT_THROUGHPUT_TESTED",
            actor,
            level=logging.WARNING,
            project_id=mount.project_id,
            client_ip=client_ip,
            metadata={
                "mount_id": mount.id,
                "mount_label": _redacted_mount_label(mount.local_mount_point),
                "outcome": "failed",
                "reason": "benchmark_failed",
                "benchmark_bytes": benchmark_bytes,
            },
        )
        _log_throughput_debug_failure(
            "Mount throughput test failed unexpectedly",
            target_type="mount",
            target_id=mount.id,
            raw_error=exc,
        )
        raise service_exception(status_code=500, detail="Share throughput test failed; verify the mounted share is available and retry") from exc

    if read_mbps is None:
        log_and_audit(
            db,
            "MOUNT_THROUGHPUT_TESTED",
            actor,
            level=logging.WARNING,
            project_id=mount.project_id,
            client_ip=client_ip,
            metadata={
                "mount_id": mount.id,
                "mount_label": _redacted_mount_label(mount.local_mount_point),
                "outcome": "failed",
                "reason": "no_measurement",
                "benchmark_bytes": benchmark_bytes,
            },
        )
        raise service_exception(status_code=500, detail="Share throughput test did not produce a measurement; retry the test")

    mount.throughput_read_mbps = read_mbps
    mount.throughput_tested_at = datetime.now(timezone.utc)
    saved_mount = mount_repo.save(mount)
    log_and_audit(
        db,
        "MOUNT_THROUGHPUT_TESTED",
        actor,
        project_id=saved_mount.project_id,
        client_ip=client_ip,
        metadata={
            "mount_id": saved_mount.id,
            "mount_label": _redacted_mount_label(saved_mount.local_mount_point),
            "outcome": "success",
            "benchmark_bytes": benchmark_bytes,
            "read_mbps": read_mbps,
        },
    )
    return saved_mount