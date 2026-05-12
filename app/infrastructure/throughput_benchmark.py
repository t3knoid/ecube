from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional, Protocol

from app.config import settings

logger = logging.getLogger(__name__)


def _calculate_transfer_rate_mbps(transferred_bytes: int, elapsed_seconds: float) -> Optional[float]:
    if transferred_bytes <= 0 or elapsed_seconds <= 0:
        return None
    rate_mbps = (transferred_bytes / (1024 * 1024)) / elapsed_seconds
    if rate_mbps <= 0:
        return None
    return max(0.01, round(rate_mbps, 2))


def _best_effort_posix_fadvise(file_descriptor: int, advice: int) -> None:
    if not hasattr(os, "posix_fadvise"):
        return

    try:
        os.posix_fadvise(file_descriptor, 0, 0, advice)
    except (AttributeError, OSError, ValueError):
        return


class ThroughputBenchmarkProvider(Protocol):
    def measure_share_read_mbps(self, sample_plan: list[tuple[Path, int]]) -> tuple[Optional[float], int, float, float]: ...

    def measure_drive_write_mbps(
        self,
        target_mount_path: str,
        sample_plan: list[tuple[Path, int]],
        *,
        benchmark_id: str,
    ) -> tuple[Optional[float], float, float]: ...


class LinuxThroughputBenchmarkProvider:
    def measure_share_read_mbps(self, sample_plan: list[tuple[Path, int]]) -> tuple[Optional[float], int, float, float]:
        if not sample_plan:
            return None, 0, 0.0, 0.0

        bytes_read = 0
        checksum = hashlib.sha256()
        total_started_at = time.perf_counter()
        stream_elapsed_seconds = 0.0

        for file_path, planned_bytes in sample_plan:
            remaining = planned_bytes
            with open(file_path, "rb") as handle:
                sequential_advice = getattr(os, "POSIX_FADV_SEQUENTIAL", None)
                if sequential_advice is not None:
                    _best_effort_posix_fadvise(handle.fileno(), sequential_advice)

                dontneed_advice = getattr(os, "POSIX_FADV_DONTNEED", None)
                if dontneed_advice is not None:
                    _best_effort_posix_fadvise(handle.fileno(), dontneed_advice)

                while remaining > 0:
                    chunk_started_at = time.perf_counter()
                    chunk = handle.read(min(settings.copy_chunk_size_bytes, remaining))
                    if not chunk:
                        stream_elapsed_seconds += time.perf_counter() - chunk_started_at
                        break
                    chunk_len = len(chunk)
                    checksum.update(chunk)
                    bytes_read += chunk_len
                    remaining -= chunk_len
                    stream_elapsed_seconds += time.perf_counter() - chunk_started_at

                if dontneed_advice is not None:
                    _best_effort_posix_fadvise(handle.fileno(), dontneed_advice)

        elapsed_seconds = time.perf_counter() - total_started_at
        checksum.digest()
        return _calculate_transfer_rate_mbps(bytes_read, elapsed_seconds), bytes_read, elapsed_seconds, stream_elapsed_seconds

    def measure_drive_write_mbps(
        self,
        target_mount_path: str,
        sample_plan: list[tuple[Path, int]],
        *,
        benchmark_id: str,
    ) -> tuple[Optional[float], float, float]:
        if not sample_plan:
            return None, 0.0, 0.0

        target_root = Path(str(target_mount_path or "").strip())
        if not str(target_mount_path or "").strip() or not target_root.exists() or not target_root.is_dir():
            raise RuntimeError("Target drive is unavailable for throughput testing")

        planned_bytes = sum(max(0, planned_size) for _sample_path, planned_size in sample_plan)
        if planned_bytes <= 0:
            return None, 0.0, 0.0

        bytes_written = 0
        total_started_at = time.perf_counter()
        stream_elapsed_seconds = 0.0
        elapsed_seconds = 0.0
        chunk_size = max(1, min(settings.copy_chunk_size_bytes, planned_bytes))
        chunk = b"\0" * chunk_size
        benchmark_path = target_root / f".throughput-benchmark-{benchmark_id}-{time.time_ns()}.tmp"

        try:
            with open(benchmark_path, "wb") as handle:
                remaining = planned_bytes
                while remaining > 0:
                    chunk_started_at = time.perf_counter()
                    write_size = min(chunk_size, remaining)
                    handle.write(chunk[:write_size])
                    bytes_written += write_size
                    remaining -= write_size
                    stream_elapsed_seconds += time.perf_counter() - chunk_started_at
                handle.flush()
                os.fsync(handle.fileno())
            elapsed_seconds = time.perf_counter() - total_started_at
        finally:
            try:
                if benchmark_path.exists():
                    benchmark_path.unlink()
            except OSError:
                logger.debug(
                    "Could not remove throughput benchmark file",
                    extra={"benchmark_id": benchmark_id},
                )

        return _calculate_transfer_rate_mbps(bytes_written, elapsed_seconds), elapsed_seconds, stream_elapsed_seconds