import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.jobs import ExportFile, ExportJob, FileStatus, JobStatus
from app.repositories.job_repository import FileRepository, JobRepository


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
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            while chunk := fsrc.read(1024 * 1024):
                h.update(chunk)
                fdst.write(chunk)
        return True, h.hexdigest(), None
    except Exception as exc:
        return False, None, str(exc)


def _checksum_only(src: Path) -> Tuple[bool, Optional[str], Optional[str]]:
    """Compute a SHA-256 checksum without copying."""
    try:
        h = hashlib.sha256()
        with open(src, "rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return True, h.hexdigest(), None
    except Exception as exc:
        return False, None, str(exc)


def _relative_path(f: Path, source: Path) -> Path:
    """Return *f* relative to *source* if *source* is a directory, else just the filename."""
    return f.relative_to(source) if source.is_dir() else Path(f.name)


def _process_file(export_file_id: int, src_file: Path, target: Optional[Path]) -> None:
    """Worker executed inside the thread pool.

    Each worker opens its own DB session to avoid cross-thread SQLAlchemy issues.
    """
    db: Session = SessionLocal()
    try:
        file_repo = FileRepository(db)

        ef = file_repo.get(export_file_id)
        if ef is None:
            return

        ef.status = FileStatus.COPYING
        file_repo.save(ef)

        if target is not None:
            dst = target / ef.relative_path
            success, checksum, err = copy_file(src_file, dst)
        else:
            success, checksum, err = _checksum_only(src_file)

        ef.checksum = checksum
        if success:
            ef.status = FileStatus.DONE
        else:
            ef.status = FileStatus.ERROR
            ef.error_message = err
        file_repo.save(ef)

        # Atomically increment copied_bytes to avoid lost-update races between threads.
        if success and ef.size_bytes:
            file_repo.increment_job_bytes(ef.job_id, ef.size_bytes)
    finally:
        db.close()


def run_copy_job(job_id: int) -> None:
    """Execute the copy job using a thread pool.

    Opens its own DB session so it is safe to run as a FastAPI background task
    after the originating request's session has been closed.
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
        job_repo.save(job)

        source = Path(job.source_path)
        target = Path(job.target_mount_path) if job.target_mount_path else None

        files = scan_source_files(job.source_path)
        job.file_count = len(files)
        job.total_bytes = sum(f.stat().st_size for f in files if f.exists())
        job_repo.save(job)

        # Delete any existing ExportFile rows for this job (e.g. on a FAILED restart)
        # so we start clean and avoid duplicate records.
        file_repo.delete_by_job(job_id)

        # Insert fresh ExportFile records for this run.
        export_files = [
            ExportFile(
                job_id=job_id,
                relative_path=str(_relative_path(f, source)),
                size_bytes=f.stat().st_size if f.exists() else 0,
                status=FileStatus.PENDING,
            )
            for f in files
        ]
        file_repo.add_bulk(export_files)

        # Re-query to get stable IDs now that the transaction is committed.
        committed_files = file_repo.list_by_job(job_id)
        src_by_rel = {str(_relative_path(f, source)): f for f in files}
        file_pairs = [
            (src_by_rel[ef.relative_path], ef.id)
            for ef in committed_files
            if ef.relative_path in src_by_rel
        ]

        with ThreadPoolExecutor(max_workers=job.thread_count or 4) as executor:
            futures = {
                executor.submit(_process_file, ef_id, src, target): ef_id
                for src, ef_id in file_pairs
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    # Worker already recorded FileStatus.ERROR in its own session;
                    # unexpected exceptions are caught here to let other workers finish.
                    pass

        # Determine final job status.
        db.expire_all()
        error_count = file_repo.count_errors(job_id)

        job = job_repo.get(job_id)
        if job:
            job.status = JobStatus.FAILED if error_count > 0 else JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job_repo.save(job)
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

        db.commit()

        job = job_repo.get(job_id)
        if job:
            job.status = JobStatus.FAILED if any_mismatch else JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            job_repo.save(job)
    finally:
        db.close()
