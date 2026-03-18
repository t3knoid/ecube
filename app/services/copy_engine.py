import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.jobs import ExportFile, ExportJob, FileStatus, JobStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.job_repository import FileRepository, JobRepository

logger = logging.getLogger(__name__)


def scan_source_files(source_path: str) -> List[Path]:
    """Recursively scan source_path and return a list of file Paths."""
    source = Path(source_path)
    if not source.exists():
        return []
    if source.is_file():
        return [source]
    return [p for p in source.rglob("*") if p.is_file()]


def copy_file(
    src: Path, dst: Path, checksum_algorithm: str = "sha256"
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Copy *src* to *dst* and compute a checksum.

    Returns (success, checksum_hex, error_message).
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        h = hashlib.new(checksum_algorithm)
        chunk_size = settings.copy_chunk_size_bytes
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while chunk := fsrc.read(chunk_size):
                h.update(chunk)
                fdst.write(chunk)
        return True, h.hexdigest(), None
    except Exception as exc:
        return False, None, str(exc)


def _checksum_only(src: Path) -> Tuple[bool, Optional[str], Optional[str]]:
    """Compute a SHA-256 checksum without copying."""
    try:
        h = hashlib.sha256()
        chunk_size = settings.copy_chunk_size_bytes
        with open(src, "rb") as f:
            while chunk := f.read(chunk_size):
                h.update(chunk)
        return True, h.hexdigest(), None
    except Exception as exc:
        return False, None, str(exc)


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

        for attempt in range(max_retries + 1):
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
                success, checksum, err = copy_file(src_file, dst)
            else:
                success, checksum, err = _checksum_only(src_file)

            if success:
                break

            last_err = err
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
        done_saved = False
        if success:
            ef.status = FileStatus.DONE
            try:
                file_repo.save(ef)
                done_saved = True
            except Exception:
                logger.exception("DB commit failed saving DONE status for file %s", export_file_id)
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

        # Only increment copied_bytes when the DONE status was actually
        # persisted.  If the save failed the file will be re-processed on
        # resume, and incrementing here would cause double-counting.
        if done_saved and ef.size_bytes:
            try:
                file_repo.increment_job_bytes(ef.job_id, ef.size_bytes)
            except Exception:
                logger.exception("DB commit failed incrementing copied_bytes for file %s", export_file_id)
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
        job.started_at = datetime.now(timezone.utc)
        try:
            job_repo.save(job)
        except Exception:
            logger.exception("DB commit failed setting job %s to RUNNING", job_id)
            return

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
            logger.exception("DB commit failed resetting file statuses for job %s", job_id)
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
        job_start = time.monotonic()
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
                    # Cancel remaining pending futures and stop the executor without waiting.
                    for pending in futures:
                        if not pending.done():
                            pending.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
        finally:
            # On normal completion, wait for all tasks to finish; on timeout we already
            # performed a non-blocking shutdown above.
            if not timed_out:
                executor.shutdown(wait=True)

        # Determine final job status.
        db.expire_all()
        error_count = file_repo.count_errors(job_id)

        job = job_repo.get(job_id)
        if job:
            if timed_out:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(timezone.utc)
                try:
                    job_repo.save(job)
                except Exception:
                    logger.exception("DB commit failed setting job %s to FAILED (timeout)", job_id)

                try:
                    AuditRepository(db).add(
                        action="JOB_TIMEOUT",
                        job_id=job_id,
                        details={
                            "timeout_seconds": timeout,
                            "elapsed_seconds": round(time.monotonic() - job_start, 2),
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for JOB_TIMEOUT")
            else:
                job.status = JobStatus.FAILED if error_count > 0 else JobStatus.COMPLETED
                job.completed_at = datetime.now(timezone.utc)
                try:
                    job_repo.save(job)
                except Exception:
                    logger.exception("DB commit failed setting final status for job %s", job_id)

                audit_action = "JOB_COMPLETED" if job.status == JobStatus.COMPLETED else "JOB_FAILED"
                try:
                    AuditRepository(db).add(
                        action=audit_action,
                        job_id=job_id,
                        details={
                            "status": job.status.value,
                            "file_count": job.file_count,
                            "error_count": error_count,
                            "elapsed_seconds": round(time.monotonic() - job_start, 2),
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for %s", audit_action)
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
            logger.exception("DB commit failed during verification for job %s", job_id)
            return

        job = job_repo.get(job_id)
        if job:
            job.status = JobStatus.FAILED if any_mismatch else JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            try:
                job_repo.save(job)
            except Exception:
                logger.exception("DB commit failed setting verification result for job %s", job_id)

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
                logger.exception("Failed to write audit log for %s", audit_action)
    finally:
        db.close()
