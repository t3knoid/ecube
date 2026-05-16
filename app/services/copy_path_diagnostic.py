from __future__ import annotations

import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Literal, Optional
from uuid import uuid4

from app.config import settings
from app.infrastructure import ThroughputBenchmarkProvider, get_throughput_benchmark
from app.services.copy_engine import (
    _build_startup_analysis_sample_plan,
    _calculate_effective_copy_rate_mbps,
    _measure_drive_write_mbps,
    _measure_share_read_mbps,
    _relative_path,
    copy_file,
    scan_source_files,
)
from app.utils.sanitize import validate_source_path


CopyPathDiagnosticMode = Literal["balanced", "small-file-stress"]

DEFAULT_SMALL_FILE_STRESS_SAMPLE_FILE_COUNT = 2000


@dataclass(frozen=True)
class CopyPathDiagnosticResult:
    source_path: str
    target_path: str
    sample_mode: CopyPathDiagnosticMode
    source_file_count: int
    source_total_bytes: int
    benchmark_requested_bytes: int
    benchmark_measured_bytes: int
    sample_file_count: int
    sample_copied_bytes: int
    sample_median_file_size_bytes: int
    sample_small_file_count: int
    share_read_mbps: Optional[float]
    drive_write_mbps: Optional[float]
    benchmark_effective_copy_mbps: Optional[float]
    end_to_end_copy_mbps: Optional[float]
    sample_copy_elapsed_seconds: float
    sample_copy_files_per_second: Optional[float]
    copy_chunk_size_bytes: int
    copy_file_fsync_enabled: bool
    notes: list[str]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _dedupe_sample_paths(sample_plan: list[tuple[Path, int]]) -> list[Path]:
    selected: list[Path] = []
    seen: set[Path] = set()
    for file_path, _planned_bytes in sample_plan:
        if file_path in seen:
            continue
        selected.append(file_path)
        seen.add(file_path)
    return selected


def _count_small_files(file_sizes: list[int], threshold_bytes: int = 1024 * 1024) -> int:
    return sum(1 for size_bytes in file_sizes if size_bytes <= threshold_bytes)


def _build_small_file_stress_sample_plan(
    files: list[Path],
    *,
    max_sample_file_count: int,
) -> list[tuple[Path, int]]:
    if max_sample_file_count <= 0:
        return []

    file_infos: list[tuple[Path, int]] = []
    for file_path in files:
        try:
            size_bytes = file_path.stat().st_size
        except OSError:
            continue
        if size_bytes <= 0:
            continue
        file_infos.append((file_path, size_bytes))

    if not file_infos:
        return []

    return sorted(file_infos, key=lambda item: (item[1], str(item[0])))[:max_sample_file_count]


def _build_copy_path_sample_plan(
    files: list[Path],
    *,
    sample_mode: CopyPathDiagnosticMode,
    sample_bytes: int,
    small_file_stress_sample_file_count: int,
) -> list[tuple[Path, int]]:
    if sample_mode == "small-file-stress":
        return _build_small_file_stress_sample_plan(
            files,
            max_sample_file_count=small_file_stress_sample_file_count,
        )
    return _build_startup_analysis_sample_plan(files, sample_bytes)


def _build_diagnostic_notes(
    *,
    share_read_mbps: Optional[float],
    drive_write_mbps: Optional[float],
    benchmark_effective_copy_mbps: Optional[float],
    end_to_end_copy_mbps: Optional[float],
    sample_file_count: int,
    sample_median_file_size_bytes: int,
    sample_small_file_count: int,
    copy_file_fsync_enabled: bool,
) -> list[str]:
    notes: list[str] = []

    if sample_file_count > 0 and sample_small_file_count >= max(4, sample_file_count // 2):
        notes.append(
            "Sample workload is small-file heavy; per-file open, metadata, hashing, and flush overhead can dominate throughput."
        )

    if copy_file_fsync_enabled and sample_median_file_size_bytes <= 8 * 1024 * 1024:
        notes.append(
            "copy_file_fsync_enabled is on; fsync after each file can collapse throughput on USB media, especially for small-file workloads."
        )

    if share_read_mbps and drive_write_mbps:
        slower_leg = min(share_read_mbps, drive_write_mbps)
        if end_to_end_copy_mbps and end_to_end_copy_mbps < slower_leg * 0.5:
            notes.append(
                "End-to-end sample copy is far below the isolated source and target measurements; look for per-file overhead, fsync cost, hashing cost, or contention outside the raw I/O legs."
            )
        if benchmark_effective_copy_mbps and end_to_end_copy_mbps and end_to_end_copy_mbps < benchmark_effective_copy_mbps * 0.6:
            notes.append(
                "Real sample copy is materially slower than the startup-analysis benchmark estimate, which usually points to workload shape differences such as directory depth or many small files."
            )
        if share_read_mbps < drive_write_mbps * 0.7:
            notes.append(
                "Mounted share read speed is substantially lower than mounted drive write speed; the source side or network path is the likely bottleneck."
            )
        elif drive_write_mbps < share_read_mbps * 0.7:
            notes.append(
                "Mounted drive write speed is substantially lower than mounted share read speed; the target drive or USB path is the likely bottleneck."
            )

    if not notes:
        notes.append("No dominant bottleneck was inferred from the sample; compare this result against the job runtime parameters and the actual workload file-size mix.")

    return notes


def run_copy_path_diagnostic(
    source_path: str,
    target_path: str,
    *,
    sample_mode: CopyPathDiagnosticMode = "balanced",
    benchmark_bytes: Optional[int] = None,
    small_file_stress_sample_file_count: int = DEFAULT_SMALL_FILE_STRESS_SAMPLE_FILE_COUNT,
    benchmark_provider: Optional[ThroughputBenchmarkProvider] = None,
    keep_sample: bool = False,
) -> CopyPathDiagnosticResult:
    source_root = Path(validate_source_path(source_path, usb_mount_base_path=settings.usb_mount_base_path))
    target_root = Path(target_path).expanduser()
    if not target_root.exists() or not target_root.is_dir():
        raise RuntimeError("Target path must exist and be a directory")

    source_files = scan_source_files(str(source_root))
    if not source_files:
        raise RuntimeError("Source path has no readable files available for diagnostics")

    file_sizes = [file_path.stat().st_size for file_path in source_files if file_path.is_file()]
    total_bytes = sum(file_sizes)
    if total_bytes <= 0:
        raise RuntimeError("Source path has no non-empty readable files available for diagnostics")

    provider = benchmark_provider or get_throughput_benchmark()
    requested_bytes = min(int(benchmark_bytes or settings.startup_analysis_benchmark_bytes), total_bytes)
    sample_plan = _build_copy_path_sample_plan(
        source_files,
        sample_mode=sample_mode,
        sample_bytes=requested_bytes,
        small_file_stress_sample_file_count=small_file_stress_sample_file_count,
    )
    if not sample_plan:
        raise RuntimeError("Could not build a diagnostic sample plan from the source path")

    share_read_mbps, actual_read_bytes, _read_total_seconds, read_stream_seconds = _measure_share_read_mbps(
        sample_plan,
        benchmark_provider=provider,
    )
    measured_bytes = actual_read_bytes or sum(planned_bytes for _sample_path, planned_bytes in sample_plan)
    drive_write_mbps, _write_total_seconds, write_stream_seconds = _measure_drive_write_mbps(
        str(target_root),
        sample_plan,
        job_id=0,
        benchmark_provider=provider,
    )
    benchmark_effective_copy_mbps = _calculate_effective_copy_rate_mbps(
        measured_bytes,
        read_stream_seconds,
        write_stream_seconds,
    )

    sample_files = _dedupe_sample_paths(sample_plan)
    sample_file_sizes = [file_path.stat().st_size for file_path in sample_files]
    sample_dir = target_root / f".copy-path-diagnostic-{uuid4().hex}"
    copied_bytes = 0
    copy_started_at = time.perf_counter()
    try:
        for file_path in sample_files:
            relative_path = _relative_path(file_path, source_root)
            destination_path = sample_dir / relative_path
            success, _checksum_hex, error_message = copy_file(file_path, destination_path)
            if not success:
                raise RuntimeError(error_message or f"Sample copy failed for {relative_path}")
            copied_bytes += file_path.stat().st_size
    finally:
        if sample_dir.exists() and not keep_sample:
            shutil.rmtree(sample_dir, ignore_errors=True)
    copy_elapsed_seconds = max(0.0, time.perf_counter() - copy_started_at)
    end_to_end_copy_mbps = None
    sample_copy_files_per_second = None
    if copied_bytes > 0 and copy_elapsed_seconds > 0:
        end_to_end_copy_mbps = round(((copied_bytes * 8) / (1024 * 1024)) / copy_elapsed_seconds, 2)
    if sample_files and copy_elapsed_seconds > 0:
        sample_copy_files_per_second = round(len(sample_files) / copy_elapsed_seconds, 2)

    sample_median_file_size_bytes = int(median(sample_file_sizes)) if sample_file_sizes else 0
    sample_small_file_count = _count_small_files(sample_file_sizes)
    notes = _build_diagnostic_notes(
        share_read_mbps=share_read_mbps,
        drive_write_mbps=drive_write_mbps,
        benchmark_effective_copy_mbps=benchmark_effective_copy_mbps,
        end_to_end_copy_mbps=end_to_end_copy_mbps,
        sample_file_count=len(sample_files),
        sample_median_file_size_bytes=sample_median_file_size_bytes,
        sample_small_file_count=sample_small_file_count,
        copy_file_fsync_enabled=settings.copy_file_fsync_enabled,
    )

    return CopyPathDiagnosticResult(
        source_path=str(source_root),
        target_path=str(target_root),
        sample_mode=sample_mode,
        source_file_count=len(source_files),
        source_total_bytes=total_bytes,
        benchmark_requested_bytes=requested_bytes,
        benchmark_measured_bytes=measured_bytes,
        sample_file_count=len(sample_files),
        sample_copied_bytes=copied_bytes,
        sample_median_file_size_bytes=sample_median_file_size_bytes,
        sample_small_file_count=sample_small_file_count,
        share_read_mbps=share_read_mbps,
        drive_write_mbps=drive_write_mbps,
        benchmark_effective_copy_mbps=benchmark_effective_copy_mbps,
        end_to_end_copy_mbps=end_to_end_copy_mbps,
        sample_copy_elapsed_seconds=round(copy_elapsed_seconds, 4),
        sample_copy_files_per_second=sample_copy_files_per_second,
        copy_chunk_size_bytes=settings.copy_chunk_size_bytes,
        copy_file_fsync_enabled=settings.copy_file_fsync_enabled,
        notes=notes,
    )