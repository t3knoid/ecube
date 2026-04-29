import hashlib
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, Protocol, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.jobs import ExportFile, FileStatus, JobStatus, StartupAnalysisStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.job_repository import DriveAssignmentRepository, FileRepository, JobRepository
from app.services.callback_service import deliver_callback
from app.services.copy_worker_runtime import (
    register_active_copy_worker,
    unregister_active_copy_worker,
)
from app.utils.sanitize import describe_relative_paths, sanitize_error_message, validate_source_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CopyEngine Protocol
# ---------------------------------------------------------------------------

class CopyEngine(Protocol):
    """Platform-agnostic interface for low-level file copy operations."""

    def scan_source_files(self, source_path: str) -> List[Path]: ...

    def copy_file(
        self,
        src: Path,
        dst: Path,
        checksum_algorithm: str = "sha256",
        progress_callback: Optional[Callable[[int], None]] = None,
        timeout_seconds: int = 0,
    ) -> Tuple[bool, Optional[str], Optional[str]]: ...

    def checksum_only(
        self,
        src: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
        timeout_seconds: int = 0,
    ) -> Tuple[bool, Optional[str], Optional[str]]: ...


class NativeCopyEngine:
    """Reference implementation using Python standard library I/O."""

    def scan_source_files(self, source_path: str) -> List[Path]:
        return scan_source_files(source_path)

    def copy_file(
        self,
        src: Path,
        dst: Path,
        checksum_algorithm: str = "sha256",
        progress_callback: Optional[Callable[[int], None]] = None,
        timeout_seconds: int = 0,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        return copy_file(
            src,
            dst,
            checksum_algorithm,
            progress_callback=progress_callback,
            timeout_seconds=timeout_seconds,
        )

    def checksum_only(
        self,
        src: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
        timeout_seconds: int = 0,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        return _checksum_only(src, progress_callback=progress_callback, timeout_seconds=timeout_seconds)


def scan_source_files(source_path: str) -> List[Path]:
    """Recursively scan source_path and return a list of file Paths."""
    source = Path(validate_source_path(source_path, usb_mount_base_path=settings.usb_mount_base_path))
    try:
        if not source.exists():
            raise FileNotFoundError(source_path)
        if source.is_file():
            return [source]
        if not source.is_dir():
            raise FileNotFoundError(source_path)
    except OSError as exc:
        raise FileNotFoundError(source_path) from exc

    files: List[Path] = []
    scan_errors: list[OSError] = []

    def _record_scan_error(exc: OSError) -> None:
        scan_errors.append(exc)
        logger.debug("Source scan entry became unavailable under %s: %s", source, exc)

    for root, _dirs, filenames in os.walk(source, onerror=_record_scan_error):
        root_path = Path(root)
        for filename in filenames:
            candidate = root_path / filename
            try:
                if candidate.is_file():
                    files.append(candidate)
            except OSError as exc:
                _record_scan_error(exc)

    try:
        source_still_exists = source.exists()
    except OSError as exc:
        _record_scan_error(exc)
        source_still_exists = False

    if scan_errors:
        if not source_still_exists:
            raise FileNotFoundError(source_path) from scan_errors[0]
        raise scan_errors[0]

    return files


def copy_file(
    src: Path,
    dst: Path,
    checksum_algorithm: str = "sha256",
    progress_callback: Optional[Callable[[int], None]] = None,
    timeout_seconds: int = 0,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Copy *src* to *dst* and compute a checksum.

    Returns (success, checksum_hex, error_message).
    On failure, any partially written *dst* file is removed.
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.new(checksum_algorithm)
        chunk_size = settings.copy_chunk_size_bytes
        start_time = time.monotonic()
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while True:
                if timeout_seconds > 0 and (time.monotonic() - start_time) > timeout_seconds:
                    raise TimeoutError(f"File copy timed out after {timeout_seconds}s")
                chunk = fsrc.read(chunk_size)
                if not chunk:
                    break
                if timeout_seconds > 0 and (time.monotonic() - start_time) > timeout_seconds:
                    raise TimeoutError(f"File copy timed out after {timeout_seconds}s")
                h.update(chunk)
                fdst.write(chunk)
                if progress_callback is not None:
                    progress_callback(len(chunk))
            fdst.flush()
            os.fsync(fdst.fileno())
        return True, h.hexdigest(), None
    except TimeoutError:
        raise
    except Exception as exc:
        # Remove partial file so the target drive is not left with corrupt data.
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            logger.debug("Could not remove partial file %s", dst)
        return False, None, str(exc)


def _checksum_only(
    src: Path,
    progress_callback: Optional[Callable[[int], None]] = None,
    timeout_seconds: int = 0,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Compute a SHA-256 checksum without copying."""
    try:
        h = hashlib.sha256()
        chunk_size = settings.copy_chunk_size_bytes
        start_time = time.monotonic()
        with open(src, "rb") as f:
            while True:
                if timeout_seconds > 0 and (time.monotonic() - start_time) > timeout_seconds:
                    raise TimeoutError(f"File checksum timed out after {timeout_seconds}s")
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                if timeout_seconds > 0 and (time.monotonic() - start_time) > timeout_seconds:
                    raise TimeoutError(f"File checksum timed out after {timeout_seconds}s")
                h.update(chunk)
                if progress_callback is not None:
                    progress_callback(len(chunk))
        return True, h.hexdigest(), None
    except TimeoutError:
        raise
    except Exception as exc:
        return False, None, str(exc)


def _calculate_copy_rate_mb_s(copied_bytes: int, elapsed_seconds: float) -> float:
    """Return the average completed copy rate in MB/s."""
    if copied_bytes <= 0 or elapsed_seconds <= 0:
        return 0.0
    return round((copied_bytes / (1024 * 1024)) / elapsed_seconds, 2)


def _progress_flush_threshold_bytes() -> int:
    configured = int(getattr(settings, "copy_progress_flush_bytes", 0) or 0)
    chunk_size = int(getattr(settings, "copy_chunk_size_bytes", 0) or 0)
    return max(1, configured, chunk_size)


def _sanitize_job_failure_reason(
    reason: str,
    *,
    fallback: str,
    source_path: Optional[str] = None,
    target_mount_path: Optional[str] = None,
) -> str:
    """Return a sanitized, bounded job-level failure reason."""
    sanitized = sanitize_error_message(reason, fallback).strip()
    relative_paths = describe_relative_paths(
        reason,
        source_path=source_path,
        target_mount_path=target_mount_path,
    )
    if relative_paths:
        sanitized = f"{sanitized} ({', '.join(relative_paths)})"
    if len(sanitized) > 1024:
        sanitized = sanitized[:1021] + "..."
    return sanitized


def _classify_file_failure(reason: object) -> tuple[str, str]:
    """Return a safe ``(error_code, message)`` pair for file-level failures."""
    raw = str(reason or "").strip()
    lowered = raw.lower()

    if any(token in lowered for token in ("permission denied", "access denied", "auth", "not authorized")):
        return "permission_failure", "Permission or authentication failure"
    if any(token in lowered for token in ("disk full", "no space left", "not enough space")):
        return "target_full", "Target storage is full"
    if any(token in lowered for token in ("i/o error", "io error", "input/output error")):
        return "io_failure", "I/O failure"
    if "checksum" in lowered:
        return "checksum_failure", "Checksum verification failed"
    if "timed out" in lowered or "timeout" in lowered:
        return "copy_timeout", "Operation timed out"
    if "no such file" in lowered or "not found" in lowered:
        return "source_not_found", "Source file was not found"
    return "copy_failed", "File copy failed"


def _log_job_path_context(job_id: int, source_path: str, target_mount_path: Optional[str], phase: str) -> None:
    """Emit detailed path information at debug level only."""
    logger.debug(
        "Copy job path context",
        {
            "job_id": job_id,
            "phase": phase,
            "source_path": source_path,
            "target_mount_path": target_mount_path,
        },
    )


def _normalize_started_at(value: Optional[datetime]) -> Optional[datetime]:
    """Return a timezone-stable value for comparing job run ownership."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def _calculate_total_active_seconds(
    existing_seconds: Optional[int],
    started_at: Optional[datetime],
    ended_at: Optional[datetime] = None,
) -> float:
    """Return cumulative active run time across pause/resume cycles."""
    total = float(existing_seconds or 0)
    start = _normalize_started_at(started_at)
    end = _normalize_started_at(ended_at or datetime.now(timezone.utc))
    if start is None or end is None:
        return max(0.0, total)
    return max(0.0, total + max(0.0, (end - start).total_seconds()))


def _relative_path(f: Path, source: Path) -> Path:
    """Return *f* relative to *source* if *source* is a directory, else just the filename."""
    return f.relative_to(source) if source.is_dir() else Path(f.name)


def _clear_startup_analysis_cache(job: Any) -> None:
    job.startup_analysis_status = StartupAnalysisStatus.NOT_ANALYZED
    job.startup_analysis_last_analyzed_at = None
    job.startup_analysis_failure_reason = None
    job.startup_analysis_file_count = None
    job.startup_analysis_total_bytes = None
    job.startup_analysis_share_read_mbps = None
    job.startup_analysis_drive_write_mbps = None
    job.startup_analysis_estimated_duration_seconds = None
    job.startup_analysis_entries = None


def _clear_startup_analysis_entries(job: Any) -> None:
    job.startup_analysis_entries = None


def _startup_analysis_cache_details(job: Any) -> dict[str, int]:
    return {
        "cached_file_count": int(job.startup_analysis_file_count or 0),
        "cached_total_bytes": int(job.startup_analysis_total_bytes or 0),
    }


def _clear_startup_analysis_benchmark(job: Any) -> None:
    job.startup_analysis_share_read_mbps = None
    job.startup_analysis_drive_write_mbps = None
    job.startup_analysis_estimated_duration_seconds = None


def _set_startup_analysis_failed(job: Any, reason: str) -> None:
    job.startup_analysis_status = StartupAnalysisStatus.FAILED
    job.startup_analysis_failure_reason = reason
    _clear_startup_analysis_benchmark(job)


def _set_startup_analysis_ready(job: Any, *, analyzed_at: Optional[datetime] = None) -> None:
    job.startup_analysis_status = StartupAnalysisStatus.READY
    job.startup_analysis_last_analyzed_at = analyzed_at or datetime.now(timezone.utc)
    job.startup_analysis_failure_reason = None


def _log_startup_analysis_failure(
    message: str,
    *,
    job_id: int,
    reason: str,
    exc: Optional[BaseException] = None,
) -> None:
    logger.info(message, extra={"job_id": job_id, "reason": reason})
    if exc is not None:
        logger.debug(message, extra={"job_id": job_id, "reason": reason, "raw_error": str(exc)}, exc_info=True)


def _calculate_transfer_rate_mbps(transferred_bytes: int, elapsed_seconds: float) -> Optional[float]:
    if transferred_bytes <= 0 or elapsed_seconds <= 0:
        return None
    return round((transferred_bytes / (1024 * 1024)) / elapsed_seconds, 2)


def _estimate_startup_analysis_duration_seconds(
    total_bytes: int,
    effective_copy_rate_mbps: Optional[float],
    per_file_overhead_seconds: float,
    file_count: int,
) -> Optional[int]:
    if total_bytes <= 0:
        return 0
    if effective_copy_rate_mbps is None:
        return None
    if effective_copy_rate_mbps <= 0:
        return None
    transfer_seconds = (total_bytes / (1024 * 1024)) / effective_copy_rate_mbps
    fixed_overhead_seconds = max(0.0, per_file_overhead_seconds) * max(0, file_count)
    return max(1, math.ceil(transfer_seconds + fixed_overhead_seconds))


def _calculate_effective_copy_rate_mbps(
    benchmark_bytes: int,
    read_stream_seconds: float,
    write_stream_seconds: float,
) -> Optional[float]:
    combined_stream_seconds = max(0.0, read_stream_seconds) + max(0.0, write_stream_seconds)
    return _calculate_transfer_rate_mbps(benchmark_bytes, combined_stream_seconds)


def _calculate_per_file_overhead_seconds(
    sample_file_count: int,
    read_total_seconds: float,
    read_stream_seconds: float,
    write_total_seconds: float,
    write_stream_seconds: float,
) -> float:
    if sample_file_count <= 0:
        return 0.0
    overhead_seconds = max(0.0, (read_total_seconds - read_stream_seconds) + (write_total_seconds - write_stream_seconds))
    return overhead_seconds / sample_file_count


def _build_startup_analysis_sample_plan(files: list[Path], sample_bytes: int) -> list[tuple[Path, int]]:
    if sample_bytes <= 0:
        return []

    file_infos: list[tuple[Path, int]] = []
    for file_path in files:
        try:
            size_bytes = max(0, file_path.stat().st_size)
        except OSError:
            continue
        if size_bytes <= 0:
            continue
        file_infos.append((file_path, size_bytes))

    if not file_infos:
        return []

    sorted_infos = sorted(file_infos, key=lambda item: item[1])
    bucket_count = min(3, len(sorted_infos))
    buckets: list[list[tuple[Path, int]]] = []
    for bucket_index in range(bucket_count):
        start = (bucket_index * len(sorted_infos)) // bucket_count
        end = ((bucket_index + 1) * len(sorted_infos)) // bucket_count
        bucket = sorted_infos[start:end]
        if bucket:
            buckets.append(bucket)

    ordered_buckets: list[list[tuple[Path, int]]] = []
    for bucket in buckets:
        preferred_indexes = [len(bucket) // 2, 0, len(bucket) - 1]
        ordered_bucket: list[tuple[Path, int]] = []
        seen_indexes: set[int] = set()
        for index in preferred_indexes:
            if index in seen_indexes:
                continue
            ordered_bucket.append(bucket[index])
            seen_indexes.add(index)
        for index, item in enumerate(bucket):
            if index in seen_indexes:
                continue
            ordered_bucket.append(item)
        ordered_buckets.append(ordered_bucket)

    remaining = sample_bytes
    selected: list[tuple[Path, int]] = []
    bucket_positions = [0 for _ in ordered_buckets]

    while remaining > 0:
        progressed = False
        for bucket_index, bucket in enumerate(ordered_buckets):
            position = bucket_positions[bucket_index]
            if position >= len(bucket):
                continue
            file_path, size_bytes = bucket[position]
            bucket_positions[bucket_index] += 1
            progressed = True

            selected_bytes = min(size_bytes, remaining)
            selected.append((file_path, selected_bytes))
            remaining -= selected_bytes

            if remaining <= 0:
                break
        if not progressed:
            break

    return selected


def _measure_share_read_mbps(sample_plan: list[tuple[Path, int]]) -> tuple[Optional[float], int, float, float]:
    if not sample_plan:
        return None, 0, 0.0, 0.0

    bytes_read = 0
    checksum = hashlib.sha256()
    total_started_at = time.perf_counter()
    stream_elapsed_seconds = 0.0

    for file_path, planned_bytes in sample_plan:
        remaining = planned_bytes
        with open(file_path, "rb") as handle:
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

    elapsed_seconds = time.perf_counter() - total_started_at
    checksum.digest()
    return _calculate_transfer_rate_mbps(bytes_read, elapsed_seconds), bytes_read, elapsed_seconds, stream_elapsed_seconds


def _measure_drive_write_mbps(target_mount_path: Optional[str], sample_plan: list[tuple[Path, int]], *, job_id: int) -> tuple[Optional[float], float, float]:
    if not sample_plan:
        return None, 0.0, 0.0
    target_root = Path(str(target_mount_path or "").strip())
    if not str(target_mount_path or "").strip() or not target_root.exists() or not target_root.is_dir():
        raise RuntimeError("Assigned target drive is unavailable for startup analysis benchmark")

    bytes_written = 0
    total_started_at = time.perf_counter()
    stream_elapsed_seconds = 0.0

    try:
        for sample_index, (_source_file, planned_bytes) in enumerate(sample_plan):
            chunk_size = max(1, min(settings.copy_chunk_size_bytes, planned_bytes))
            chunk = b"\0" * chunk_size
            benchmark_path = target_root / f".startup-analysis-benchmark-{job_id}-{sample_index}-{time.time_ns()}.tmp"

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
            finally:
                try:
                    if benchmark_path.exists():
                        benchmark_path.unlink()
                except OSError:
                    logger.debug("Could not remove startup analysis benchmark file", extra={"job_id": job_id})
    finally:
        pass

    elapsed_seconds = time.perf_counter() - total_started_at
    return _calculate_transfer_rate_mbps(bytes_written, elapsed_seconds), elapsed_seconds, stream_elapsed_seconds


def _measure_startup_analysis_transfer_rates(
    job: Any,
    source_files: list[Path],
    total_bytes: int,
) -> dict[str, Optional[float] | Optional[int] | int]:
    if total_bytes <= 0:
        return {
            "share_read_mbps": None,
            "drive_write_mbps": None,
            "estimated_duration_seconds": 0,
            "benchmark_bytes": 0,
        }

    sample_bytes = min(int(settings.startup_analysis_benchmark_bytes), total_bytes)
    sample_plan = _build_startup_analysis_sample_plan(source_files, sample_bytes)
    share_read_mbps, actual_read_bytes, read_total_seconds, read_stream_seconds = _measure_share_read_mbps(sample_plan)
    benchmark_bytes = actual_read_bytes or sum(sample_size for _file_path, sample_size in sample_plan) or sample_bytes
    drive_write_mbps, write_total_seconds, write_stream_seconds = _measure_drive_write_mbps(job.target_mount_path, sample_plan, job_id=int(job.id))
    effective_copy_rate_mbps = _calculate_effective_copy_rate_mbps(
        benchmark_bytes,
        read_stream_seconds,
        write_stream_seconds,
    )
    per_file_overhead_seconds = _calculate_per_file_overhead_seconds(
        len(sample_plan),
        read_total_seconds,
        read_stream_seconds,
        write_total_seconds,
        write_stream_seconds,
    )
    estimated_duration_seconds = _estimate_startup_analysis_duration_seconds(
        total_bytes,
        effective_copy_rate_mbps,
        per_file_overhead_seconds,
        len(source_files),
    )
    return {
        "share_read_mbps": share_read_mbps,
        "drive_write_mbps": drive_write_mbps,
        "estimated_duration_seconds": estimated_duration_seconds,
        "benchmark_bytes": benchmark_bytes,
    }


def _relative_directory_markers(source: Path, relative_paths: list[str]) -> dict[str, int]:
    directories: set[str] = set()

    if source.is_dir():
        directories.add("")

    for rel in relative_paths:
        rel_parent = Path(rel).parent
        if str(rel_parent) == ".":
            if source.is_dir():
                directories.add("")
            continue

        current = rel_parent
        while str(current) not in ("", "."):
            directories.add(str(current))
            current = current.parent
        if source.is_dir():
            directories.add("")

    markers: dict[str, int] = {}
    for rel_dir in directories:
        directory_path = source if rel_dir == "" else source / rel_dir
        markers[rel_dir] = directory_path.stat().st_mtime_ns
    return markers


def _analyze_source_files(source: Path, files: list[Path]) -> tuple[dict[str, Path], dict[str, int], int, int, dict[str, int]]:
    src_by_rel: dict[str, Path] = {}
    size_by_rel: dict[str, int] = {}

    for file_path in files:
        rel = str(_relative_path(file_path, source))
        size_bytes = file_path.stat().st_size if file_path.exists() else 0
        src_by_rel[rel] = file_path
        size_by_rel[rel] = size_bytes

    file_count = len(src_by_rel)
    total_bytes = sum(size_by_rel.values())
    directory_mtime_by_rel = _relative_directory_markers(source, list(src_by_rel.keys()))
    return src_by_rel, size_by_rel, file_count, total_bytes, directory_mtime_by_rel


def _persist_startup_analysis_cache(job: Any, source: Path, files: list[Path]) -> tuple[dict[str, Path], dict[str, int], int, int]:
    src_by_rel, size_by_rel, file_count, total_bytes, directory_mtime_by_rel = _analyze_source_files(source, files)

    job.startup_analysis_file_count = file_count
    job.startup_analysis_total_bytes = total_bytes
    file_entries = [
        {"relative_path": rel, "size_bytes": size_bytes}
        for rel, size_bytes in size_by_rel.items()
    ]
    directory_entries = [
        {
            "entry_type": "directory",
            "relative_path": rel_dir,
            "mtime_ns": mtime_ns,
        }
        for rel_dir, mtime_ns in sorted(directory_mtime_by_rel.items())
    ]
    job.startup_analysis_entries = file_entries + directory_entries

    return src_by_rel, size_by_rel, int(job.startup_analysis_file_count or 0), int(job.startup_analysis_total_bytes or 0)


def _load_startup_analysis_cache(job: Any, source: Path) -> Optional[tuple[dict[str, Path], dict[str, int], int, int, dict[str, int]]]:
    entries = job.startup_analysis_entries
    file_count = job.startup_analysis_file_count
    total_bytes = job.startup_analysis_total_bytes

    if entries is None or file_count is None or total_bytes is None:
        return None
    if not isinstance(entries, list):
        return None

    src_by_rel: dict[str, Path] = {}
    size_by_rel: dict[str, int] = {}
    directory_mtime_by_rel: dict[str, int] = {}
    computed_total_bytes = 0

    for entry in entries:
        if not isinstance(entry, dict):
            return None
        entry_type = entry.get("entry_type", "file")
        rel = entry.get("relative_path")
        if not isinstance(rel, str) or not rel:
            if entry_type == "directory" and rel == "":
                pass
            else:
                return None
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            return None
        if entry_type == "directory":
            mtime_ns = entry.get("mtime_ns")
            if not isinstance(mtime_ns, int) or mtime_ns < 0:
                return None
            directory_mtime_by_rel[rel] = mtime_ns
            continue

        size_bytes = entry.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes < 0:
            return None
        src_by_rel[rel] = source / rel_path
        size_by_rel[rel] = size_bytes
        computed_total_bytes += size_bytes

    if len(src_by_rel) != int(file_count):
        return None
    if computed_total_bytes != int(total_bytes):
        return None

    return src_by_rel, size_by_rel, int(file_count), int(total_bytes), directory_mtime_by_rel


def _cached_startup_analysis_is_current(
    cached: tuple[dict[str, Path], dict[str, int], int, int, dict[str, int]],
    source: Path,
) -> bool:
    src_by_rel, size_by_rel, file_count, total_bytes, directory_mtime_by_rel = cached

    if source.is_dir() and "" not in directory_mtime_by_rel:
        return False

    if len(src_by_rel) != file_count:
        return False
    if sum(size_by_rel.values()) != total_bytes:
        return False

    for rel, expected_size in size_by_rel.items():
        file_path = src_by_rel[rel]
        try:
            if not file_path.is_file():
                return False
            if file_path.stat().st_size != expected_size:
                return False
        except OSError:
            return False

    for rel_dir, expected_mtime_ns in directory_mtime_by_rel.items():
        directory_path = source if rel_dir == "" else source / rel_dir
        try:
            if not directory_path.is_dir():
                return False
            if directory_path.stat().st_mtime_ns != expected_mtime_ns:
                return False
        except OSError:
            return False

    return True


def prepare_job_startup_analysis(
    job_id: int,
    *,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
    manual: bool = False,
) -> dict[str, object]:
    db: Session = SessionLocal()
    try:
        job_repo = JobRepository(db)
        file_repo = FileRepository(db)
        audit_repo = AuditRepository(db)

        job = job_repo.get(job_id)
        if not job:
            raise FileNotFoundError(f"Job {job_id} not found")

        source = Path(job.source_path)
        cached_startup_analysis = _load_startup_analysis_cache(job, source)
        reused_cached_analysis = False

        if cached_startup_analysis is None:
            files = scan_source_files(job.source_path)
            src_by_rel, size_by_rel, cached_file_count, cached_total_bytes = _persist_startup_analysis_cache(job, source, files)
        elif _cached_startup_analysis_is_current(cached_startup_analysis, source):
            reused_cached_analysis = True
            src_by_rel, size_by_rel, cached_file_count, cached_total_bytes, _directory_mtime_by_rel = cached_startup_analysis
        else:
            job.startup_analysis_status = StartupAnalysisStatus.STALE
            try:
                job_repo.save(job)
            except Exception:
                logger.exception("DB commit failed while marking startup analysis stale", extra={"job_id": job_id})
            files = scan_source_files(job.source_path)
            logger.info(
                "Refreshing stale startup analysis cache",
                extra={
                    "job_id": job_id,
                    "cached_file_count": cached_startup_analysis[2],
                    "current_file_count": len(files),
                },
            )
            src_by_rel, size_by_rel, cached_file_count, cached_total_bytes = _persist_startup_analysis_cache(job, source, files)

        benchmark_details: dict[str, Optional[float] | Optional[int] | int] = {
            "share_read_mbps": None,
            "drive_write_mbps": None,
            "estimated_duration_seconds": None,
            "benchmark_bytes": 0,
        }
        if manual:
            benchmark_details = _measure_startup_analysis_transfer_rates(
                job,
                [src_by_rel[rel] for rel in sorted(src_by_rel.keys())],
                cached_total_bytes,
            )
            job.startup_analysis_share_read_mbps = benchmark_details["share_read_mbps"]
            job.startup_analysis_drive_write_mbps = benchmark_details["drive_write_mbps"]
            job.startup_analysis_estimated_duration_seconds = benchmark_details["estimated_duration_seconds"]
        elif not reused_cached_analysis:
            _clear_startup_analysis_benchmark(job)

        existing_files = file_repo.list_by_job(job_id)
        existing_by_rel = {ef.relative_path: ef for ef in existing_files}

        for ef in existing_files:
            if ef.status != FileStatus.DONE:
                ef.status = FileStatus.PENDING
                ef.retry_attempts = 0
                ef.error_message = None
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        new_files = [
            ExportFile(
                job_id=job_id,
                relative_path=rel,
                size_bytes=size_by_rel[rel],
                status=FileStatus.PENDING,
                retry_attempts=0,
            )
            for rel in src_by_rel
            if rel not in existing_by_rel
        ]
        if new_files:
            file_repo.add_bulk(new_files)

        job.file_count = cached_file_count
        job.total_bytes = cached_total_bytes
        committed_files = file_repo.list_by_job(job_id)
        job.copied_bytes = sum(
            ef.size_bytes or 0
            for ef in committed_files
            if ef.status == FileStatus.DONE
        )
        _set_startup_analysis_ready(job)
        job_repo.save(job)

        details = {
            "cached_file_count": cached_file_count,
            "cached_total_bytes": cached_total_bytes,
            "reused_cached_analysis": reused_cached_analysis,
            "ready_to_start": True,
            "benchmark_bytes": int(benchmark_details["benchmark_bytes"] or 0),
            "share_read_mbps": benchmark_details["share_read_mbps"],
            "drive_write_mbps": benchmark_details["drive_write_mbps"],
            "estimated_duration_seconds": benchmark_details["estimated_duration_seconds"],
        }
        if manual:
            logger.info(
                f"JOB_STARTUP_ANALYSIS_COMPLETED job_id={job_id} project_id={job.project_id} "
                f"status={job.startup_analysis_status.value} file_count={cached_file_count} "
                f"total_bytes={cached_total_bytes} share_read_mbps={job.startup_analysis_share_read_mbps} "
                f"drive_write_mbps={job.startup_analysis_drive_write_mbps} "
                f"estimated_duration_seconds={job.startup_analysis_estimated_duration_seconds} "
                f"actor={actor or 'system'}",
                extra={
                    "job_id": job_id,
                    "project_id": job.project_id,
                    "status": job.startup_analysis_status.value,
                    "file_count": cached_file_count,
                    "total_bytes": cached_total_bytes,
                    "share_read_mbps": job.startup_analysis_share_read_mbps,
                    "drive_write_mbps": job.startup_analysis_drive_write_mbps,
                    "estimated_duration_seconds": job.startup_analysis_estimated_duration_seconds,
                    "actor": actor or "system",
                },
            )
            try:
                audit_repo.add(
                    action="JOB_STARTUP_ANALYSIS_COMPLETED",
                    user=actor,
                    project_id=job.project_id,
                    job_id=job_id,
                    details=details,
                    client_ip=client_ip,
                )
            except Exception as audit_exc:
                _log_startup_analysis_failure(
                    "Failed to write audit log for JOB_STARTUP_ANALYSIS_COMPLETED",
                    job_id=job_id,
                    reason="Audit log write failed after startup analysis completion",
                    exc=audit_exc,
                )
        return {
            "src_by_rel": src_by_rel,
            "size_by_rel": size_by_rel,
            "file_count": cached_file_count,
            "total_bytes": cached_total_bytes,
            "reused_cached_analysis": reused_cached_analysis,
        }
    except Exception as exc:
        db.rollback()
        job = JobRepository(db).get(job_id)
        safe_reason = _sanitize_job_failure_reason(
            str(exc),
            fallback="Unable to prepare startup analysis",
            source_path=job.source_path if job else None,
        )
        if job is not None:
            _set_startup_analysis_failed(job, safe_reason)
            try:
                JobRepository(db).save(job)
            except Exception as save_exc:
                _log_startup_analysis_failure(
                    "DB commit failed while saving startup analysis failure",
                    job_id=job_id,
                    reason="Database error while persisting startup analysis failure",
                    exc=save_exc,
                )
            if manual:
                try:
                    AuditRepository(db).add(
                        action="JOB_STARTUP_ANALYSIS_FAILED",
                        user=actor,
                        project_id=job.project_id,
                        job_id=job_id,
                        details={"reason": safe_reason},
                        client_ip=client_ip,
                    )
                except Exception as audit_exc:
                    _log_startup_analysis_failure(
                        "Failed to write audit log for JOB_STARTUP_ANALYSIS_FAILED",
                        job_id=job_id,
                        reason="Audit log write failed after startup analysis failure",
                        exc=audit_exc,
                    )
        raise
    finally:
        db.close()


def run_startup_analysis(
    job_id: int,
    *,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> None:
    try:
        prepare_job_startup_analysis(job_id, actor=actor, client_ip=client_ip, manual=True)
    except Exception as exc:
        safe_reason = sanitize_error_message(exc, "Startup analysis failed")
        _log_startup_analysis_failure(
            "Unexpected startup analysis failure",
            job_id=job_id,
            reason=safe_reason,
            exc=exc,
        )


def _process_file(
    export_file_id: int,
    src_file: Path,
    target: Optional[Path],
    max_retries: int = 0,
    retry_delay: float = 1.0,
) -> None:
    """Worker executed inside the thread pool.

    Each worker opens its own DB session to avoid cross-thread SQLAlchemy issues.
    Retries the copy up to *max_retries* additional times on failure, using
    exponential backoff seeded by *retry_delay* seconds.
    
    Files that timeout are marked TIMEOUT (not ERROR) and are skipped; the job
    continues copying remaining files. Timeout events are audited with elapsed time
    and file path.
    """
    db: Session = SessionLocal()
    worker_snapshot: Optional[dict[str, object]] = None
    try:
        file_repo = FileRepository(db)
        audit_repo = AuditRepository(db)

        ef = file_repo.get(export_file_id)
        if ef is None:
            return

        job_repo = JobRepository(db)
        job = job_repo.get(ef.job_id)
        if job is None:
            return
        assignment_repo = DriveAssignmentRepository(db)
        active_assignment = assignment_repo.get_active_for_job(ef.job_id)
        active_assignment_id = int(active_assignment.id) if active_assignment is not None else None
        if job.status in (JobStatus.PAUSING, JobStatus.PAUSED):
            ef.status = FileStatus.PENDING
            try:
                file_repo.save(ef)
            except Exception:
                logger.exception("DB commit failed restoring PENDING status for file %s", export_file_id)
            return

        worker_snapshot = register_active_copy_worker(job_id=ef.job_id)

        ef.status = FileStatus.COPYING
        try:
            file_repo.save(ef)
        except Exception:
            logger.exception("DB commit failed setting file %s to COPYING", export_file_id)
            return

        try:
            audit_repo.add(
                action="FILE_COPY_START",
                job_id=ef.job_id,
                details={"file_id": ef.id, "relative_path": ef.relative_path},
            )
        except Exception:
            logger.exception("Failed to write audit log for FILE_COPY_START")

        last_err: Optional[str] = None
        success = False
        checksum: Optional[str] = None
        bytes_reported = 0
        progress_flush_threshold = _progress_flush_threshold_bytes()
        timed_out = False
        timeout_elapsed_seconds = 0.0

        for attempt in range(max_retries + 1):
            attempt_bytes_reported = 0
            pending_progress_bytes = 0

            def _flush_progress(*, force: bool = False) -> None:
                nonlocal attempt_bytes_reported, bytes_reported, pending_progress_bytes
                if pending_progress_bytes <= 0:
                    return
                if not force and pending_progress_bytes < progress_flush_threshold:
                    return
                flushed_bytes = pending_progress_bytes
                try:
                    file_repo.increment_job_bytes(ef.job_id, flushed_bytes)
                    if active_assignment_id is not None:
                        file_repo.increment_assignment_bytes(active_assignment_id, flushed_bytes)
                    attempt_bytes_reported += flushed_bytes
                    bytes_reported += flushed_bytes
                    pending_progress_bytes = 0
                except Exception:
                    logger.exception("DB commit failed incrementing copied_bytes for file %s", export_file_id)

            def _report_progress(delta: int) -> None:
                nonlocal pending_progress_bytes
                if delta <= 0:
                    return
                pending_progress_bytes += delta
                _flush_progress()

            if attempt > 0:
                # Exponential backoff: retry_delay * 2^(attempt-1)
                delay = retry_delay * (2 ** (attempt - 1))
                ef.status = FileStatus.RETRYING
                ef.retry_attempts = attempt
                try:
                    file_repo.save(ef)
                except Exception:
                    logger.exception("DB commit failed setting file %s to RETRYING", export_file_id)
                try:
                    audit_repo.add(
                        action="FILE_COPY_RETRY",
                        job_id=ef.job_id,
                        details={
                            "file_id": ef.id,
                            "relative_path": ef.relative_path,
                            "attempt": attempt,
                            "delay_seconds": delay,
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for FILE_COPY_RETRY")
                time.sleep(delay)
                ef.status = FileStatus.COPYING
                try:
                    file_repo.save(ef)
                except Exception:
                    logger.exception("DB commit failed setting file %s to COPYING on retry", export_file_id)

            if target is not None:
                dst = target / ef.relative_path
                file_timeout_seconds = int(getattr(settings, "copy_job_timeout", 0) or 0)
                timeout_start = time.monotonic()
                try:
                    success, checksum, err = copy_file(
                        src_file,
                        dst,
                        progress_callback=_report_progress,
                        timeout_seconds=file_timeout_seconds,
                    )
                except TimeoutError as timeout_exc:
                    timeout_elapsed_seconds = time.monotonic() - timeout_start
                    timed_out = True
                    success = False
                    err = str(timeout_exc)
            else:
                file_timeout_seconds = int(getattr(settings, "copy_job_timeout", 0) or 0)
                timeout_start = time.monotonic()
                try:
                    success, checksum, err = _checksum_only(
                        src_file,
                        progress_callback=_report_progress,
                        timeout_seconds=file_timeout_seconds,
                    )
                except TimeoutError as timeout_exc:
                    timeout_elapsed_seconds = time.monotonic() - timeout_start
                    timed_out = True
                    success = False
                    err = str(timeout_exc)

            _flush_progress(force=True)

            if success:
                break

            if timed_out:
                # Timeout: skip this file, do not retry, let job continue with other files.
                # Audit the timeout with elapsed time and file path.
                last_err = err
                try:
                    AuditRepository(db).add(
                        action="FILE_COPY_TIMEOUT",
                        job_id=ef.job_id,
                        details={
                            "file_id": ef.id,
                            "relative_path": ef.relative_path,
                            "timeout_seconds": file_timeout_seconds,
                            "elapsed_seconds": round(timeout_elapsed_seconds, 2),
                            "error_code": "copy_timeout",
                            "error_detail": f"timed_out_after_{file_timeout_seconds}s",
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for FILE_COPY_TIMEOUT")
                break  # Exit retry loop; file will be marked TIMEOUT below

            if attempt_bytes_reported:
                try:
                    file_repo.decrement_job_bytes(ef.job_id, attempt_bytes_reported)
                    if active_assignment_id is not None:
                        file_repo.decrement_assignment_bytes(active_assignment_id, attempt_bytes_reported)
                    bytes_reported = max(0, bytes_reported - attempt_bytes_reported)
                except Exception:
                    logger.exception("DB commit failed rolling back copied_bytes for file %s", export_file_id)

            last_err = err
            error_code, safe_error_message = _classify_file_failure(last_err)
            logger.info(
                "File copy failure recorded",
                extra={
                    "job_id": ef.job_id,
                    "file_id": ef.id,
                    "relative_path": ef.relative_path,
                    "attempt": attempt,
                    "error_code": error_code,
                },
            )
            logger.debug(
                "File copy failure detail",
                extra={
                    "job_id": ef.job_id,
                    "file_id": ef.id,
                    "relative_path": ef.relative_path,
                    "attempt": attempt,
                    "error_code": error_code,
                    "raw_error": str(last_err or "unknown error"),
                },
            )
            try:
                audit_repo.add(
                    action="FILE_COPY_FAILURE",
                    job_id=ef.job_id,
                    details={
                        "file_id": ef.id,
                        "relative_path": ef.relative_path,
                        "attempt": attempt,
                        "error_code": error_code,
                        "error_detail": safe_error_message,
                    },
                )
            except Exception:
                logger.exception("Failed to write audit log for FILE_COPY_FAILURE")

        ef.checksum = checksum
        if success:
            ef.status = FileStatus.DONE
            try:
                file_repo.save(ef)
                if active_assignment_id is not None:
                    file_repo.increment_assignment_file_count(active_assignment_id)
            except Exception:
                logger.exception("DB commit failed saving DONE status for file %s", export_file_id)
                if bytes_reported:
                    try:
                        file_repo.decrement_job_bytes(ef.job_id, bytes_reported)
                        if active_assignment_id is not None:
                            file_repo.decrement_assignment_bytes(active_assignment_id, bytes_reported)
                    except Exception:
                        logger.exception("DB commit failed restoring copied_bytes for file %s", export_file_id)
            try:
                audit_repo.add(
                    action="FILE_COPY_SUCCESS",
                    job_id=ef.job_id,
                    details={"file_id": ef.id, "relative_path": ef.relative_path},
                )
            except Exception:
                logger.exception("Failed to write audit log for FILE_COPY_SUCCESS")
        elif timed_out:
            # Mark file as TIMEOUT (not ERROR) so job continues; timeout can be retried later.
            ef.status = FileStatus.TIMEOUT
            _error_code, safe_error_message = _classify_file_failure(last_err)
            ef.error_message = safe_error_message
            try:
                file_repo.save(ef)
            except Exception:
                logger.exception("DB commit failed saving TIMEOUT status for file", {"file_id": export_file_id})
                if bytes_reported:
                    try:
                        file_repo.decrement_job_bytes(ef.job_id, bytes_reported)
                    except Exception:
                        logger.exception("DB commit failed restoring copied_bytes for file", {"file_id": export_file_id})
        else:
            ef.status = FileStatus.ERROR
            _error_code, safe_error_message = _classify_file_failure(last_err)
            ef.error_message = safe_error_message
            try:
                file_repo.save(ef)
            except Exception:
                logger.exception("DB commit failed saving ERROR status for file %s", export_file_id)
    finally:
        unregister_active_copy_worker(worker_snapshot)
        db.close()


def run_copy_job(job_id: int) -> None:
    """Execute the copy job using a thread pool.

    Opens its own DB session so it is safe to run as a FastAPI background task
    after the originating request's session has been closed.

    **Resume semantics**: if the job already has ``DONE`` export-file records
    (e.g. from a previous partial run), those files are skipped.  Files in
    ``ERROR``, ``RETRYING``, ``COPYING``, or ``PENDING`` state are reset to
    ``PENDING`` so they will be re-processed.  Any source files not yet
    tracked receive fresh ``PENDING`` records.
    """
    db: Session = SessionLocal()
    try:
        job_repo = JobRepository(db)
        file_repo = FileRepository(db)

        job = job_repo.get(job_id)
        if not job:
            return
        if job.status == JobStatus.PAUSED:
            return

        job.status = JobStatus.RUNNING
        if not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        run_started_at = job.started_at
        run_started_at_key = _normalize_started_at(run_started_at)
        job.active_duration_seconds = int(job.active_duration_seconds or 0)
        job.completed_at = None
        job.failure_reason = None
        try:
            job_repo.save(job)
        except Exception:
            logger.error("DB commit failed setting job %s to RUNNING", job_id)
            return

        done_count = 0
        error_count = 0

        try:
            source = Path(job.source_path)
            target = Path(job.target_mount_path) if job.target_mount_path else None

            preparation = prepare_job_startup_analysis(job_id)
            src_by_rel = preparation["src_by_rel"]

            job = job_repo.get(job_id)
            if preparation["reused_cached_analysis"]:
                try:
                    AuditRepository(db).add(
                        action="JOB_STARTUP_ANALYSIS_REUSED",
                        job_id=job_id,
                        details={
                            "cached_file_count": int(preparation["file_count"]),
                            "cached_total_bytes": int(preparation["total_bytes"]),
                        },
                    )
                except Exception:
                    logger.error("Failed to write audit log for JOB_STARTUP_ANALYSIS_REUSED")

            committed_files = file_repo.list_by_job(job_id)

            # Re-query to get stable IDs; only submit PENDING (non-DONE) files.
            pending_files = [ef for ef in committed_files if ef.status == FileStatus.PENDING]
            file_pairs = [
                (src_by_rel[ef.relative_path], ef.id)
                for ef in pending_files
                if ef.relative_path in src_by_rel
            ]

            max_retries = job.max_file_retries if job.max_file_retries is not None else settings.copy_default_max_retries
            retry_delay = float(job.retry_delay_seconds) if job.retry_delay_seconds is not None else settings.copy_default_retry_delay_seconds

            pause_requested = False

            executor = ThreadPoolExecutor(
                max_workers=job.thread_count or settings.copy_default_thread_count,
                thread_name_prefix=f"copy-job-{job_id}",
            )
            try:
                futures = {
                    executor.submit(_process_file, ef_id, src, target, max_retries, retry_delay): ef_id
                    for src, ef_id in file_pairs
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        # Worker already recorded FileStatus.ERROR in its own session;
                        # unexpected exceptions are caught here to let other workers finish.
                        pass

                    db.expire_all()
                    latest_job = job_repo.get(job_id)
                    latest_started_at_key = _normalize_started_at(
                        latest_job.started_at if latest_job else None
                    )
                    if latest_job and latest_started_at_key and latest_started_at_key != run_started_at_key:
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        logger.info(
                            "Skipping stale copy worker after newer resume",
                            extra={"job_id": job_id, "started_at": str(run_started_at)},
                        )
                        return
                    if latest_job and latest_job.status in (JobStatus.PAUSING, JobStatus.PAUSED):
                        pause_requested = True
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        break

            finally:
                # Always wait for running workers to finish so the DB session is
                # idle before the main thread uses it.  cancel_futures=True
                # prevents queued (not-yet-started) tasks from running.
                executor.shutdown(wait=True, cancel_futures=True)

            # Determine final job status.
            db.expire_all()
            done_count, error_count = file_repo.count_done_and_errors(job_id)
            timeout_count = db.query(ExportFile).filter(
                ExportFile.job_id == job_id,
                ExportFile.status == FileStatus.TIMEOUT,
            ).count()

            job = job_repo.get(job_id)
            if job:
                if _normalize_started_at(job.started_at) != run_started_at_key:
                    logger.info(
                        "Skipping stale finalization for resumed copy job",
                        extra={"job_id": job_id, "started_at": str(run_started_at)},
                    )
                    return
                run_finished_at = datetime.now(timezone.utc)
                total_active_seconds = _calculate_total_active_seconds(
                    job.active_duration_seconds,
                    run_started_at,
                    run_finished_at,
                )
                job.active_duration_seconds = int(round(total_active_seconds))
                all_files_finished = (done_count + error_count + timeout_count) >= int(job.file_count or 0)
                if (pause_requested or job.status in (JobStatus.PAUSING, JobStatus.PAUSED)) and not all_files_finished:
                    job.status = JobStatus.PAUSED
                    job.completed_at = None
                    try:
                        job_repo.save(job)
                    except Exception:
                        logger.error("DB commit failed setting job %s to PAUSED", job_id)
                else:
                    # File-level ERROR/TIMEOUT outcomes are preserved for recall/retry,
                    # but they do not make the whole job FAILED once all files finish.
                    job.status = JobStatus.COMPLETED if all_files_finished else JobStatus.FAILED
                    job.completed_at = datetime.now(timezone.utc)
                    cache_cleared = False
                    cache_clear_details: dict[str, int] = {}
                    if (
                        job.status == JobStatus.COMPLETED
                        and error_count == 0
                        and timeout_count == 0
                        and job.startup_analysis_cached
                    ):
                        cache_clear_details = _startup_analysis_cache_details(job)
                        _clear_startup_analysis_entries(job)
                        cache_cleared = True
                    try:
                        job_repo.save(job)
                    except Exception:
                        logger.error("DB commit failed setting final status for job %s", job_id)
                        try:
                            AuditRepository(db).add(
                                action="JOB_STATUS_PERSIST_FAILED",
                                job_id=job_id,
                                details={
                                    "intended_status": job.status.value,
                                    "file_count": job.file_count,
                                    "error_count": error_count,
                                    "timeout_count": timeout_count,
                                    "elapsed_seconds": round(total_active_seconds, 2),
                                },
                            )
                        except Exception:
                            logger.error("Failed to write audit log for JOB_STATUS_PERSIST_FAILED")
                    else:
                        audit_action = "JOB_COMPLETED" if job.status == JobStatus.COMPLETED else "JOB_FAILED"
                        elapsed_seconds = round(total_active_seconds, 2)
                        copy_rate_mb_s = _calculate_copy_rate_mb_s(job.copied_bytes or 0, elapsed_seconds)
                        _log_job_path_context(job_id, job.source_path, job.target_mount_path, "copy-finished")
                        if job.status == JobStatus.FAILED:
                            logger.error(
                                f"JOB_FAILED job_id={job_id} project_id={job.project_id} "
                                f"status={job.status.value} started_at={job.started_at.isoformat() if job.started_at else None} failed_at={job.completed_at.isoformat() if job.completed_at else None} "
                                f"thread_count={job.thread_count} files_copied={done_count} file_count={job.file_count} error_count={error_count} timeout_count={timeout_count} copied_bytes={job.copied_bytes or 0} total_bytes={job.total_bytes or 0} elapsed_seconds={elapsed_seconds} copy_rate_mb_s={copy_rate_mb_s}",
                                extra={
                                    "job_id": job_id,
                                    "project_id": job.project_id,
                                    "status": job.status.value,
                                    "started_at": job.started_at.isoformat() if job.started_at else None,
                                    "thread_count": job.thread_count,
                                    "files_copied": done_count,
                                    "file_count": job.file_count,
                                    "error_count": error_count,
                                    "timeout_count": timeout_count,
                                    "copied_bytes": job.copied_bytes or 0,
                                    "total_bytes": job.total_bytes or 0,
                                    "elapsed_seconds": elapsed_seconds,
                                    "copy_rate_mb_s": copy_rate_mb_s,
                                },
                            )
                        else:
                            logger.info(
                                f"JOB_COMPLETED job_id={job_id} project_id={job.project_id} "
                                f"status={job.status.value} started_at={job.started_at.isoformat() if job.started_at else None} completed_at={job.completed_at.isoformat() if job.completed_at else None} "
                                f"thread_count={job.thread_count} files_copied={done_count} file_count={job.file_count} error_count={error_count} timeout_count={timeout_count} copied_bytes={job.copied_bytes or 0} total_bytes={job.total_bytes or 0} elapsed_seconds={elapsed_seconds} copy_rate_mb_s={copy_rate_mb_s}",
                                extra={
                                    "job_id": job_id,
                                    "project_id": job.project_id,
                                    "status": job.status.value,
                                    "started_at": job.started_at.isoformat() if job.started_at else None,
                                    "thread_count": job.thread_count,
                                    "files_copied": done_count,
                                    "file_count": job.file_count,
                                    "error_count": error_count,
                                    "timeout_count": timeout_count,
                                    "copied_bytes": job.copied_bytes or 0,
                                    "total_bytes": job.total_bytes or 0,
                                    "elapsed_seconds": elapsed_seconds,
                                    "copy_rate_mb_s": copy_rate_mb_s,
                                },
                            )
                        try:
                            AuditRepository(db).add(
                                action=audit_action,
                                job_id=job_id,
                                details={
                                    "status": job.status.value,
                                    "started_at": job.started_at.isoformat() if job.started_at else None,
                                    "thread_count": job.thread_count,
                                    "files_copied": done_count,
                                    "file_count": job.file_count,
                                    "error_count": error_count,
                                    "timeout_count": timeout_count,
                                    "copied_bytes": job.copied_bytes or 0,
                                    "total_bytes": job.total_bytes or 0,
                                    "elapsed_seconds": elapsed_seconds,
                                    "copy_rate_mb_s": copy_rate_mb_s,
                                },
                            )
                        except Exception:
                            logger.error("Failed to write audit log for %s", audit_action)
                        if cache_cleared:
                            try:
                                AuditRepository(db).add(
                                    action="JOB_STARTUP_ANALYSIS_CACHE_CLEARED",
                                    job_id=job_id,
                                    details={
                                        "reason": "job_completed",
                                        **cache_clear_details,
                                    },
                                )
                            except Exception:
                                logger.error("Failed to write audit log for JOB_STARTUP_ANALYSIS_CACHE_CLEARED")
                        try:
                            deliver_callback(job)
                        except Exception:
                            logger.error("Callback delivery failed for job %s (copy)", job_id)
        except Exception as exc:
            db.rollback()
            safe_reason = _sanitize_job_failure_reason(
                str(exc),
                fallback="Unexpected copy failure",
                source_path=job.source_path if job else None,
                target_mount_path=job.target_mount_path if job else None,
            )
            logger.debug(
                "Copy job raw failure detail",
                {"job_id": job_id, "phase": "copy", "raw_error": str(exc)},
            )

            job = job_repo.get(job_id)
            if job:
                run_finished_at = datetime.now(timezone.utc)
                job.status = JobStatus.FAILED
                job.completed_at = run_finished_at
                job.failure_reason = safe_reason
                job.active_duration_seconds = int(round(
                    _calculate_total_active_seconds(job.active_duration_seconds, run_started_at, run_finished_at)
                ))
                try:
                    job_repo.save(job)
                except Exception:
                    logger.error("DB commit failed setting final failure status for job %s", job_id)
                    try:
                        AuditRepository(db).add(
                            action="JOB_STATUS_PERSIST_FAILED",
                            job_id=job_id,
                            details={
                                "intended_status": "FAILED",
                                "reason": safe_reason,
                                "phase": "copy",
                                "elapsed_seconds": round(job.active_duration_seconds or 0, 2),
                            },
                        )
                    except Exception:
                        logger.error("Failed to write audit log for JOB_STATUS_PERSIST_FAILED")
                else:
                    elapsed_seconds = round(job.active_duration_seconds or 0, 2)
                    copy_rate_mb_s = _calculate_copy_rate_mb_s(job.copied_bytes or 0, elapsed_seconds)
                    _log_job_path_context(job_id, job.source_path, job.target_mount_path, "copy-exception")
                    logger.error(
                        f"JOB_FAILED job_id={job_id} project_id={job.project_id} "
                        f"status={JobStatus.FAILED.value} started_at={job.started_at.isoformat() if job.started_at else None} failed_at={job.completed_at.isoformat() if job.completed_at else None} "
                        f"thread_count={job.thread_count} files_copied={done_count} file_count={job.file_count} copied_bytes={job.copied_bytes or 0} total_bytes={job.total_bytes or 0} "
                        f"reason={safe_reason} elapsed_seconds={elapsed_seconds} copy_rate_mb_s={copy_rate_mb_s}",
                        extra={
                            "job_id": job_id,
                            "project_id": job.project_id,
                            "status": JobStatus.FAILED.value,
                            "started_at": job.started_at.isoformat() if job.started_at else None,
                            "thread_count": job.thread_count,
                            "files_copied": done_count,
                            "file_count": job.file_count,
                            "copied_bytes": job.copied_bytes or 0,
                            "total_bytes": job.total_bytes or 0,
                            "reason": safe_reason,
                            "phase": "copy",
                            "elapsed_seconds": elapsed_seconds,
                            "copy_rate_mb_s": copy_rate_mb_s,
                        },
                    )
                    try:
                        AuditRepository(db).add(
                            action="JOB_FAILED",
                            job_id=job_id,
                            details={
                                "status": JobStatus.FAILED.value,
                                "started_at": job.started_at.isoformat() if job.started_at else None,
                                "thread_count": job.thread_count,
                                "files_copied": done_count,
                                "file_count": job.file_count,
                                "copied_bytes": job.copied_bytes or 0,
                                "total_bytes": job.total_bytes or 0,
                                "reason": safe_reason,
                                "phase": "copy",
                                "elapsed_seconds": elapsed_seconds,
                                "copy_rate_mb_s": copy_rate_mb_s,
                            },
                        )
                    except Exception:
                        logger.error("Failed to write audit log for JOB_FAILED")
                    try:
                        deliver_callback(job)
                    except Exception:
                        logger.error("Callback delivery failed for job %s (copy-exception)", job_id)

            logger.exception("Unexpected copy job failure for job %s", job_id)
    finally:
        db.close()


def run_verify_job(job_id: int) -> None:
    """Re-compute checksums for all completed files and compare against stored values.

    Opens its own DB session so it is safe to run as a FastAPI background task.
    """
    db: Session = SessionLocal()
    try:
        job_repo = JobRepository(db)
        file_repo = FileRepository(db)

        job = job_repo.get(job_id)
        if not job:
            return

        target = Path(job.target_mount_path) if job.target_mount_path else None

        files = file_repo.list_done_by_job(job_id)

        any_mismatch = False
        for ef in files:
            if target is not None:
                dst = target / ef.relative_path
                success, checksum, err = _checksum_only(dst)
            else:
                # No target path — re-verify the source file checksum.
                src = Path(job.source_path)
                src_file = src / ef.relative_path if src.is_dir() else src
                success, checksum, err = _checksum_only(src_file)

            if not success:
                ef.status = FileStatus.ERROR
                _error_code, safe_error_message = _classify_file_failure(err or "Checksum computation failed")
                ef.error_message = safe_error_message
                any_mismatch = True
            elif checksum != ef.checksum:
                ef.status = FileStatus.ERROR
                ef.error_message = "Checksum verification failed"
                any_mismatch = True

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB commit failed during verification for job %s", job_id)
            return

        job = job_repo.get(job_id)
        if job:
            job.status = JobStatus.FAILED if any_mismatch else JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            try:
                job_repo.save(job)
            except Exception:
                logger.error("DB commit failed setting verification result for job %s", job_id)
                try:
                    AuditRepository(db).add(
                        action="JOB_STATUS_PERSIST_FAILED",
                        job_id=job_id,
                        details={
                            "intended_status": job.status.value,
                            "phase": "verification",
                            "files_verified": len(files),
                            "mismatches": any_mismatch,
                        },
                    )
                except Exception:
                    logger.error("Failed to write audit log for JOB_STATUS_PERSIST_FAILED")
            else:
                audit_action = "JOB_VERIFICATION_COMPLETED" if not any_mismatch else "JOB_VERIFICATION_FAILED"
                try:
                    AuditRepository(db).add(
                        action=audit_action,
                        job_id=job_id,
                        details={
                            "status": job.status.value,
                            "files_verified": len(files),
                            "mismatches": any_mismatch,
                        },
                    )
                except Exception:
                    logger.error("Failed to write audit log for %s", audit_action)
                try:
                    deliver_callback(job)
                except Exception:
                    logger.error("Callback delivery failed for job %s (verify)", job_id)
    finally:
        db.close()
