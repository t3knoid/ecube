import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.jobs import ExportFile, ExportJob, FileStatus, JobStatus


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


def _process_file(export_file_id: int, src_file: Path, target: Optional[Path]) -> None:
    """Worker executed inside the thread pool.

    Each worker opens its own DB session to avoid cross-thread SQLAlchemy issues.
    """
    db: Session = SessionLocal()
    try:
        ef = db.get(ExportFile, export_file_id)
        if ef is None:
            return

        ef.status = FileStatus.COPYING
        db.commit()

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
        db.commit()

        # Update copied_bytes on the parent job atomically via a separate query.
        if success and ef.size_bytes:
            job = db.get(ExportJob, ef.job_id)
            if job:
                job.copied_bytes = (job.copied_bytes or 0) + ef.size_bytes
                db.commit()
    finally:
        db.close()


def run_copy_job(job_id: int, db: Session) -> None:
    """Execute the copy job using a thread pool.

    *db* is the caller's session and is used only for the initial job fetch and
    final status update.  Each worker thread opens its own session.
    """
    job = db.get(ExportJob, job_id)
    if not job:
        return

    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    source = Path(job.source_path)
    target = Path(job.target_mount_path) if job.target_mount_path else None

    files = scan_source_files(job.source_path)
    job.file_count = len(files)
    job.total_bytes = sum(f.stat().st_size for f in files if f.exists())
    db.commit()

    # Create ExportFile records and collect (src_path, export_file_id) pairs.
    file_pairs: List[Tuple[Path, int]] = []
    for f in files:
        rel = f.relative_to(source) if source.is_dir() else Path(f.name)
        ef = ExportFile(
            job_id=job_id,
            relative_path=str(rel),
            size_bytes=f.stat().st_size if f.exists() else 0,
            status=FileStatus.PENDING,
        )
        db.add(ef)
        db.flush()  # populate ef.id without full commit
        file_pairs.append((f, ef.id))
    db.commit()

    with ThreadPoolExecutor(max_workers=job.thread_count or 4) as executor:
        futures = {
            executor.submit(_process_file, ef_id, src, target): ef_id
            for src, ef_id in file_pairs
        }
        for future in as_completed(futures):
            future.result()  # re-raise any unexpected exception

    # Determine final job status.
    db.expire_all()
    error_count = (
        db.query(ExportFile)
        .filter(ExportFile.job_id == job_id, ExportFile.status == FileStatus.ERROR)
        .count()
    )

    job = db.get(ExportJob, job_id)
    if job:
        job.status = JobStatus.FAILED if error_count > 0 else JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
