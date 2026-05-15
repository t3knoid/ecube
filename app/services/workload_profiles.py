from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SMALL_FILE_MAX_BYTES = 64 * 1024
LARGE_FILE_MIN_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class WorkloadProfile:
    key: str
    copy_chunk_size_bytes: int
    copy_progress_flush_bytes: int
    copy_default_thread_count: int
    copy_file_fsync_enabled: bool


WORKLOAD_PROFILES: dict[str, WorkloadProfile] = {
    "small_files": WorkloadProfile(
        key="small_files",
        copy_chunk_size_bytes=1_048_576,
        copy_progress_flush_bytes=33_554_432,
        copy_default_thread_count=12,
        copy_file_fsync_enabled=False,
    ),
    "mixed": WorkloadProfile(
        key="mixed",
        copy_chunk_size_bytes=4_194_304,
        copy_progress_flush_bytes=67_108_864,
        copy_default_thread_count=12,
        copy_file_fsync_enabled=False,
    ),
    "large_files": WorkloadProfile(
        key="large_files",
        copy_chunk_size_bytes=8_388_608,
        copy_progress_flush_bytes=134_217_728,
        copy_default_thread_count=6,
        copy_file_fsync_enabled=False,
    ),
    "greedy": WorkloadProfile(
        key="greedy",
        copy_chunk_size_bytes=16_777_216,
        copy_progress_flush_bytes=268_435_456,
        copy_default_thread_count=12,
        copy_file_fsync_enabled=False,
    ),
}


def build_size_distribution_summary(*, total_files: int, total_bytes: int, small_files: int, medium_files: int, large_files: int) -> dict[str, int | float]:
    safe_total_files = max(0, int(total_files))
    safe_total_bytes = max(0, int(total_bytes))
    small_count = max(0, int(small_files))
    medium_count = max(0, int(medium_files))
    large_count = max(0, int(large_files))

    if safe_total_files <= 0:
        return {
            "small_files": 0,
            "medium_files": 0,
            "large_files": 0,
            "small_files_percent": 0.0,
            "medium_files_percent": 0.0,
            "large_files_percent": 0.0,
            "average_file_size_bytes": 0,
            "total_files": 0,
            "total_bytes": safe_total_bytes,
        }

    return {
        "small_files": small_count,
        "medium_files": medium_count,
        "large_files": large_count,
        "small_files_percent": round((small_count / safe_total_files) * 100, 1),
        "medium_files_percent": round((medium_count / safe_total_files) * 100, 1),
        "large_files_percent": round((large_count / safe_total_files) * 100, 1),
        "average_file_size_bytes": int(safe_total_bytes / safe_total_files),
        "total_files": safe_total_files,
        "total_bytes": safe_total_bytes,
    }


def recommend_workload_profile(summary: dict[str, int | float]) -> Optional[str]:
    total_files = int(summary.get("total_files") or 0)
    if total_files <= 0:
        return None

    small_ratio = float(summary.get("small_files_percent") or 0.0) / 100.0
    large_ratio = float(summary.get("large_files_percent") or 0.0) / 100.0
    average_size = int(summary.get("average_file_size_bytes") or 0)

    if small_ratio >= 0.60:
        return "small_files"
    if large_ratio >= 0.60:
        return "large_files"
    if large_ratio >= 0.25 and small_ratio <= 0.20 and average_size >= 16 * 1024 * 1024:
        return "greedy"
    return "mixed"


def apply_workload_profile(job: object, profile_key: str) -> bool:
    profile = WORKLOAD_PROFILES.get(profile_key)
    if profile is None:
        return False

    changed = False
    if getattr(job, "copy_chunk_size_bytes", None) != profile.copy_chunk_size_bytes:
        setattr(job, "copy_chunk_size_bytes", profile.copy_chunk_size_bytes)
        changed = True
    if getattr(job, "copy_progress_flush_bytes", None) != profile.copy_progress_flush_bytes:
        setattr(job, "copy_progress_flush_bytes", profile.copy_progress_flush_bytes)
        changed = True
    if getattr(job, "thread_count", None) != profile.copy_default_thread_count:
        setattr(job, "thread_count", profile.copy_default_thread_count)
        changed = True
    if getattr(job, "copy_file_fsync_enabled", None) != profile.copy_file_fsync_enabled:
        setattr(job, "copy_file_fsync_enabled", profile.copy_file_fsync_enabled)
        changed = True

    return changed
