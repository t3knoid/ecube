import hashlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Protocol, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.jobs import ExportFile, FileStatus, JobStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.job_repository import FileRepository, JobRepository
from app.services.callback_service import deliver_callback
from app.utils.sanitize import sanitize_error_message, validate_source_path

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
    ) -> Tuple[bool, Optional[str], Optional[str]]: ...

    def checksum_only(
        self,
        src: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
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
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        return copy_file(src, dst, checksum_algorithm, progress_callback=progress_callback)

    def checksum_only(
        self,
        src: Path,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        return _checksum_only(src, progress_callback=progress_callback)


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

    if scan_errors and not source_still_exists:
        raise FileNotFoundError(source_path) from scan_errors[0]

    return files


def copy_file(
    src: Path,
    dst: Path,
    checksum_algorithm: str = "sha256",
    progress_callback: Optional[Callable[[int], None]] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Copy *src* to *dst* and compute a checksum.

    Returns (success, checksum_hex, error_message).
    On failure, any partially written *dst* file is removed.
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.new(checksum_algorithm)
        chunk_size = settings.copy_chunk_size_bytes
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while chunk := fsrc.read(chunk_size):
                h.update(chunk)
                fdst.write(chunk)
                if progress_callback is not None:
                    progress_callback(len(chunk))
            fdst.flush()
            os.fsync(fdst.fileno())
        return True, h.hexdigest(), None
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
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Compute a SHA-256 checksum without copying."""
    try:
        h = hashlib.sha256()
        chunk_size = settings.copy_chunk_size_bytes
        with open(src, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
                if progress_callback is not None:
                    progress_callback(len(chunk))
        return True, h.hexdigest(), None
    except Exception as exc:
        return False, None, str(exc)


def _calculate_copy_rate_mb_s(copied_bytes: int, elapsed_seconds: float) -> float:
    """Return the average completed copy rate in MB/s."""
    if copied_bytes <= 0 or elapsed_seconds <= 0:
        return 0.0
    return round((copied_bytes / (1024 * 1024)) / elapsed_seconds, 2)


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


def _relative_path(f: Path, source: Path) -> Path:
    """Return *f* relative to *source* if *source* is a directory, else just the filename."""
    return f.relative_to(source) if source.is_dir() else Path(f.name)


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
    """
    db: Session = SessionLocal()
    try:
        file_repo = FileRepository(db)
        audit_repo = AuditRepository(db)

        ef = file_repo.get(export_file_id)
        if ef is None:
            return

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

        for attempt in range(max_retries + 1):
            attempt_bytes_reported = 0

            def _report_progress(delta: int) -> None:
                nonlocal attempt_bytes_reported, bytes_reported
                if delta <= 0:
                    return
                try:
                    file_repo.increment_job_bytes(ef.job_id, delta)
                    attempt_bytes_reported += delta
                    bytes_reported += delta
                except Exception:
                    logger.exception("DB commit failed incrementing copied_bytes for file %s", export_file_id)
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
                success, checksum, err = copy_file(
                    src_file,
                    dst,
                    progress_callback=_report_progress,
                )
            else:
                success, checksum, err = _checksum_only(
                    src_file,
                    progress_callback=_report_progress,
                )

            if success:
                break

            if attempt_bytes_reported:
                try:
                    file_repo.decrement_job_bytes(ef.job_id, attempt_bytes_reported)
                    bytes_reported = max(0, bytes_reported - attempt_bytes_reported)
                except Exception:
                    logger.exception("DB commit failed rolling back copied_bytes for file %s", export_file_id)

            last_err = err
            logger.error(
                "FILE_COPY_FAILURE job_id=%s file_id=%s relative_path=%s attempt=%s reason=%s",
                ef.job_id,
                ef.id,
                ef.relative_path,
                attempt,
                err or "unknown error",
            )
            try:
                audit_repo.add(
                    action="FILE_COPY_FAILURE",
                    job_id=ef.job_id,
                    details={
                        "file_id": ef.id,
                        "relative_path": ef.relative_path,
                        "attempt": attempt,
                        "error": err,
                    },
                )
            except Exception:
                logger.exception("Failed to write audit log for FILE_COPY_FAILURE")

        ef.checksum = checksum
        if success:
            ef.status = FileStatus.DONE
            try:
                file_repo.save(ef)
            except Exception:
                logger.exception("DB commit failed saving DONE status for file %s", export_file_id)
                if bytes_reported:
                    try:
                        file_repo.decrement_job_bytes(ef.job_id, bytes_reported)
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
        else:
            ef.status = FileStatus.ERROR
            ef.error_message = last_err
            try:
                file_repo.save(ef)
            except Exception:
                logger.exception("DB commit failed saving ERROR status for file %s", export_file_id)
    finally:
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

        job.status = JobStatus.RUNNING
        if not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        job.completed_at = None
        try:
            job_repo.save(job)
        except Exception:
            logger.error("DB commit failed setting job %s to RUNNING", job_id)
            return

        job_start = time.monotonic()
        done_count = 0
        error_count = 0

        try:
            source = Path(job.source_path)
            target = Path(job.target_mount_path) if job.target_mount_path else None

            files = scan_source_files(job.source_path)
            src_by_rel = {str(_relative_path(f, source)): f for f in files}

            # ------------------------------------------------------------------
            # Resume-aware file setup:
            # • Keep DONE records as-is (already copied successfully).
            # • Reset non-DONE records to PENDING so they will be retried.
            # • Add fresh PENDING records for source files not yet tracked.
            # ------------------------------------------------------------------
            existing_files = file_repo.list_by_job(job_id)
            existing_by_rel = {ef.relative_path: ef for ef in existing_files}

            # Reset any non-DONE existing records.
            for ef in existing_files:
                if ef.status != FileStatus.DONE:
                    ef.status = FileStatus.PENDING
                    ef.retry_attempts = 0
                    ef.error_message = None
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.error("DB commit failed resetting file statuses for job %s", job_id)
                return

            # Add records for source files not yet tracked.
            new_files = [
                ExportFile(
                    job_id=job_id,
                    relative_path=rel,
                    size_bytes=f.stat().st_size if f.exists() else 0,
                    status=FileStatus.PENDING,
                    retry_attempts=0,
                )
                for rel, f in src_by_rel.items()
                if rel not in existing_by_rel
            ]
            if new_files:
                file_repo.add_bulk(new_files)

            # Update job totals.
            job.file_count = len(files)
            job.total_bytes = sum(f.stat().st_size for f in files if f.exists())

            # Set copied_bytes to the sum of already-DONE files so incremental
            # progress accounting is correct on both fresh runs and resumes.
            committed_files = file_repo.list_by_job(job_id)
            job.copied_bytes = sum(
                ef.size_bytes or 0
                for ef in committed_files
                if ef.status == FileStatus.DONE
            )
            job_repo.save(job)

            # Re-query to get stable IDs; only submit PENDING (non-DONE) files.
            pending_files = [ef for ef in committed_files if ef.status == FileStatus.PENDING]
            file_pairs = [
                (src_by_rel[ef.relative_path], ef.id)
                for ef in pending_files
                if ef.relative_path in src_by_rel
            ]

            max_retries = job.max_file_retries if job.max_file_retries is not None else settings.copy_default_max_retries
            retry_delay = float(job.retry_delay_seconds) if job.retry_delay_seconds is not None else settings.copy_default_retry_delay_seconds

            timeout = settings.copy_job_timeout
            timed_out = False

            executor = ThreadPoolExecutor(max_workers=job.thread_count or settings.copy_default_thread_count)
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

                    # Check timeout after each file completes.
                    if timeout > 0 and (time.monotonic() - job_start) > timeout:
                        timed_out = True
                        # Cancel remaining pending futures so they are not started.
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

            job = job_repo.get(job_id)
            if job:
                if timed_out:
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now(timezone.utc)
                    try:
                        job_repo.save(job)
                    except Exception:
                        logger.error("DB commit failed setting job %s to FAILED (timeout)", job_id)
                        try:
                            AuditRepository(db).add(
                                action="JOB_STATUS_PERSIST_FAILED",
                                job_id=job_id,
                                details={
                                    "intended_status": "FAILED",
                                    "reason": "timeout",
                                    "timeout_seconds": timeout,
                                    "elapsed_seconds": round(time.monotonic() - job_start, 2),
                                },
                            )
                        except Exception:
                            logger.error("Failed to write audit log for JOB_STATUS_PERSIST_FAILED")
                    else:
                        elapsed_seconds = round(time.monotonic() - job_start, 2)
                        copy_rate_mb_s = _calculate_copy_rate_mb_s(job.copied_bytes or 0, elapsed_seconds)
                        _log_job_path_context(job_id, job.source_path, job.target_mount_path, "timeout")
                        logger.error(
                            f"JOB_FAILED job_id={job_id} project_id={job.project_id} "
                            f"status={job.status.value} failed_at={job.completed_at.isoformat() if job.completed_at else None} "
                            f"thread_count={job.thread_count} files_copied={done_count} file_count={job.file_count} copied_bytes={job.copied_bytes or 0} total_bytes={job.total_bytes or 0} "
                            f"reason=timeout elapsed_seconds={elapsed_seconds} copy_rate_mb_s={copy_rate_mb_s}",
                            extra={
                                "job_id": job_id,
                                "project_id": job.project_id,
                                "status": job.status.value,
                                "started_at": job.started_at.isoformat() if job.started_at else None,
                                "thread_count": job.thread_count,
                                "files_copied": done_count,
                                "file_count": job.file_count,
                                "copied_bytes": job.copied_bytes or 0,
                                "total_bytes": job.total_bytes or 0,
                                "reason": "timeout",
                                "elapsed_seconds": elapsed_seconds,
                                "copy_rate_mb_s": copy_rate_mb_s,
                            },
                        )
                        try:
                            AuditRepository(db).add(
                                action="JOB_TIMEOUT",
                                job_id=job_id,
                                details={
                                    "timeout_seconds": timeout,
                                    "started_at": job.started_at.isoformat() if job.started_at else None,
                                    "thread_count": job.thread_count,
                                    "files_copied": done_count,
                                    "file_count": job.file_count,
                                    "copied_bytes": job.copied_bytes or 0,
                                    "total_bytes": job.total_bytes or 0,
                                    "elapsed_seconds": elapsed_seconds,
                                    "copy_rate_mb_s": copy_rate_mb_s,
                                },
                            )
                        except Exception:
                            logger.error("Failed to write audit log for JOB_TIMEOUT")
                        try:
                            deliver_callback(job)
                        except Exception:
                            logger.error("Callback delivery failed for job %s (timeout)", job_id)
                else:
                    job.status = JobStatus.FAILED if error_count > 0 else JobStatus.COMPLETED
                    job.completed_at = datetime.now(timezone.utc)
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
                                    "elapsed_seconds": round(time.monotonic() - job_start, 2),
                                },
                            )
                        except Exception:
                            logger.error("Failed to write audit log for JOB_STATUS_PERSIST_FAILED")
                    else:
                        audit_action = "JOB_COMPLETED" if job.status == JobStatus.COMPLETED else "JOB_FAILED"
                        elapsed_seconds = round(time.monotonic() - job_start, 2)
                        copy_rate_mb_s = _calculate_copy_rate_mb_s(job.copied_bytes or 0, elapsed_seconds)
                        _log_job_path_context(job_id, job.source_path, job.target_mount_path, "copy-finished")
                        if job.status == JobStatus.FAILED:
                            logger.error(
                                f"JOB_FAILED job_id={job_id} project_id={job.project_id} "
                                f"status={job.status.value} started_at={job.started_at.isoformat() if job.started_at else None} failed_at={job.completed_at.isoformat() if job.completed_at else None} "
                                f"thread_count={job.thread_count} files_copied={done_count} file_count={job.file_count} error_count={error_count} copied_bytes={job.copied_bytes or 0} total_bytes={job.total_bytes or 0} elapsed_seconds={elapsed_seconds} copy_rate_mb_s={copy_rate_mb_s}",
                                extra={
                                    "job_id": job_id,
                                    "project_id": job.project_id,
                                    "status": job.status.value,
                                    "started_at": job.started_at.isoformat() if job.started_at else None,
                                    "thread_count": job.thread_count,
                                    "files_copied": done_count,
                                    "file_count": job.file_count,
                                    "error_count": error_count,
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
                                f"thread_count={job.thread_count} files_copied={done_count} file_count={job.file_count} error_count={error_count} copied_bytes={job.copied_bytes or 0} total_bytes={job.total_bytes or 0} elapsed_seconds={elapsed_seconds} copy_rate_mb_s={copy_rate_mb_s}",
                                extra={
                                    "job_id": job_id,
                                    "project_id": job.project_id,
                                    "status": job.status.value,
                                    "started_at": job.started_at.isoformat() if job.started_at else None,
                                    "thread_count": job.thread_count,
                                    "files_copied": done_count,
                                    "file_count": job.file_count,
                                    "error_count": error_count,
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
                                    "copied_bytes": job.copied_bytes or 0,
                                    "total_bytes": job.total_bytes or 0,
                                    "elapsed_seconds": elapsed_seconds,
                                    "copy_rate_mb_s": copy_rate_mb_s,
                                },
                            )
                        except Exception:
                            logger.error("Failed to write audit log for %s", audit_action)
                        try:
                            deliver_callback(job)
                        except Exception:
                            logger.error("Callback delivery failed for job %s (copy)", job_id)
        except Exception as exc:
            db.rollback()
            safe_reason = sanitize_error_message(exc, "Source path became unavailable during copy")
            logger.debug(
                "Copy job raw failure detail",
                {"job_id": job_id, "phase": "copy", "raw_error": str(exc)},
            )

            job = job_repo.get(job_id)
            if job:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(timezone.utc)
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
                                "elapsed_seconds": round(time.monotonic() - job_start, 2),
                            },
                        )
                    except Exception:
                        logger.error("Failed to write audit log for JOB_STATUS_PERSIST_FAILED")
                else:
                    elapsed_seconds = round(time.monotonic() - job_start, 2)
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
                ef.error_message = err or "Checksum computation failed"
                any_mismatch = True
            elif checksum != ef.checksum:
                ef.status = FileStatus.ERROR
                ef.error_message = f"Checksum mismatch: expected {ef.checksum}, got {checksum}"
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
