from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class ResolvedJobCopyTuning:
    thread_count_override: int | None
    effective_thread_count: int
    thread_count_source: str
    copy_chunk_size_bytes_override: int | None
    effective_copy_chunk_size_bytes: int
    copy_chunk_size_source: str
    copy_progress_flush_bytes_override: int | None
    effective_copy_progress_flush_bytes: int
    copy_progress_flush_source: str
    copy_file_fsync_enabled_override: bool | None
    effective_copy_file_fsync_enabled: bool
    copy_file_fsync_source: str


def resolve_job_copy_tuning(job: object) -> ResolvedJobCopyTuning:
    thread_count_override = _optional_int(getattr(job, "thread_count", None))
    copy_chunk_size_bytes_override = _optional_int(getattr(job, "copy_chunk_size_bytes", None))
    copy_progress_flush_bytes_override = _optional_int(getattr(job, "copy_progress_flush_bytes", None))
    copy_file_fsync_enabled_override = _optional_bool(getattr(job, "copy_file_fsync_enabled", None))

    effective_thread_count = thread_count_override or int(settings.copy_default_thread_count)
    effective_copy_chunk_size_bytes = copy_chunk_size_bytes_override or int(settings.copy_chunk_size_bytes)
    effective_copy_progress_flush_bytes = copy_progress_flush_bytes_override or int(settings.copy_progress_flush_bytes)
    effective_copy_file_fsync_enabled = (
        copy_file_fsync_enabled_override
        if copy_file_fsync_enabled_override is not None
        else bool(settings.copy_file_fsync_enabled)
    )

    return ResolvedJobCopyTuning(
        thread_count_override=thread_count_override,
        effective_thread_count=effective_thread_count,
        thread_count_source="job" if thread_count_override is not None else "default",
        copy_chunk_size_bytes_override=copy_chunk_size_bytes_override,
        effective_copy_chunk_size_bytes=effective_copy_chunk_size_bytes,
        copy_chunk_size_source="job" if copy_chunk_size_bytes_override is not None else "default",
        copy_progress_flush_bytes_override=copy_progress_flush_bytes_override,
        effective_copy_progress_flush_bytes=effective_copy_progress_flush_bytes,
        copy_progress_flush_source="job" if copy_progress_flush_bytes_override is not None else "default",
        copy_file_fsync_enabled_override=copy_file_fsync_enabled_override,
        effective_copy_file_fsync_enabled=effective_copy_file_fsync_enabled,
        copy_file_fsync_source="job" if copy_file_fsync_enabled_override is not None else "default",
    )


def resolve_progress_flush_threshold_bytes(job: object) -> int:
    tuning = resolve_job_copy_tuning(job)
    return max(1, tuning.effective_copy_progress_flush_bytes, tuning.effective_copy_chunk_size_bytes)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return bool(value)