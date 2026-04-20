import hashlib
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.jobs import ExportFile
from app.repositories.audit_repository import AuditRepository
from app.repositories.job_repository import FileRepository, JobRepository
from app.schemas.jobs import FileCompareItem, FileCompareRequest, FileCompareResponse, FileHashesResponse


def _path_accessible(path: Path) -> bool:
    """Return True if *path* exists and is accessible.

    Suppresses any ``OSError`` (including ``PermissionError``,
    ``FileNotFoundError``, and I/O errors from broken symlinks or
    unreadable filesystems) and returns False instead.
    """
    try:
        return path.exists()
    except OSError:
        return False


def _compute_hashes(file_path: Path) -> tuple[Optional[str], Optional[str]]:
    """Return (md5_hex, sha256_hex) for *file_path*, or (None, None) on error."""
    try:
        md5 = hashlib.md5(usedforsecurity=False)
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as fh:
            while chunk := fh.read(1024 * 1024):
                md5.update(chunk)
                sha256.update(chunk)
        return md5.hexdigest(), sha256.hexdigest()
    except Exception:
        return None, None


def _resolve_source_file_path(ef: ExportFile, db: Session) -> Optional[Path]:
    """Return the source-side on-disk path for *ef*."""
    job = JobRepository(db).get(ef.job_id)
    if job is None or not job.source_path:
        return None
    return Path(job.source_path) / ef.relative_path


def _resolve_destination_file_path(ef: ExportFile, db: Session) -> Optional[Path]:
    """Return the destination-side on-disk path for *ef*."""
    job = JobRepository(db).get(ef.job_id)
    if job is None or not job.target_mount_path:
        return None
    return Path(job.target_mount_path) / ef.relative_path


def _resolve_file_path(ef: ExportFile, db: Session) -> Optional[Path]:
    """Return the most relevant on-disk path for *ef*.

    Prefer the copied destination file when present; fall back to the source
    path for older or partially populated jobs.
    """
    return _resolve_destination_file_path(ef, db) or _resolve_source_file_path(ef, db)


def _file_to_item_from_path(
    ef: ExportFile,
    file_path: Optional[Path],
    *,
    checksum_fallback: Optional[str] = None,
) -> FileCompareItem:
    """Build a :class:`FileCompareItem` for a specific source or destination path."""
    md5: Optional[str] = None
    sha256: Optional[str] = checksum_fallback
    size_bytes: Optional[int] = ef.size_bytes

    if file_path is not None and _path_accessible(file_path):
        try:
            size_bytes = file_path.stat().st_size
        except OSError:
            pass
        md5, sha256_live = _compute_hashes(file_path)
        if sha256_live is not None:
            sha256 = sha256_live

    return FileCompareItem(
        file_id=ef.id,
        relative_path=ef.relative_path,
        md5=md5,
        sha256=sha256,
        size_bytes=size_bytes,
    )


def _file_to_item(ef: ExportFile, db: Session) -> FileCompareItem:
    """Build a :class:`FileCompareItem` from an ExportFile, computing hashes live."""
    return _file_to_item_from_path(
        ef,
        _resolve_file_path(ef, db),
        checksum_fallback=ef.checksum,
    )


def get_file_hashes(
    file_id: int, db: Session, actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> FileHashesResponse:
    """Return MD5/SHA-256 hashes for the file identified by *file_id*.

    If the file exists on disk the hashes are computed live; otherwise the
    stored SHA-256 checksum is returned and MD5 is omitted.
    """
    file_repo = FileRepository(db)
    audit_repo = AuditRepository(db)

    ef = file_repo.get(file_id)
    if ef is None:
        raise HTTPException(status_code=404, detail="File not found")

    md5: Optional[str] = None
    sha256: Optional[str] = ef.checksum

    file_path = _resolve_file_path(ef, db)
    file_on_disk = file_path is not None and _path_accessible(file_path)
    if file_path is not None and file_on_disk:
        md5, sha256_live = _compute_hashes(file_path)
        if sha256_live is not None:
            sha256 = sha256_live

    audit_repo.add(
        action="FILE_HASHES_RETRIEVED",
        user=actor,
        job_id=ef.job_id,
        details={
            "file_id": file_id,
            "relative_path": ef.relative_path,
            "live_computed": file_on_disk,
        },
        client_ip=client_ip,
    )

    return FileHashesResponse(
        file_id=ef.id,
        relative_path=ef.relative_path,
        md5=md5,
        sha256=sha256,
        size_bytes=ef.size_bytes,
    )


def compare_files(
    body: FileCompareRequest, db: Session, actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> FileCompareResponse:
    """Compare two files by hash, size, and relative path.

    Looks up both files, computes/retrieves their hashes, and returns a
    structured comparison result.
    """
    file_repo = FileRepository(db)
    audit_repo = AuditRepository(db)

    ef_a = file_repo.get(body.file_id_a)
    if ef_a is None:
        raise HTTPException(status_code=404, detail=f"File {body.file_id_a} not found")

    ef_b = file_repo.get(body.file_id_b)
    if ef_b is None:
        raise HTTPException(status_code=404, detail=f"File {body.file_id_b} not found")

    compare_mode = "generic"
    if body.file_id_a == body.file_id_b:
        source_path = _resolve_source_file_path(ef_a, db)
        if source_path is None or not _path_accessible(source_path):
            raise HTTPException(status_code=409, detail="Source file is unavailable for comparison")

        destination_path = _resolve_destination_file_path(ef_a, db)
        if destination_path is None or not _path_accessible(destination_path):
            raise HTTPException(status_code=409, detail="Destination file is unavailable for comparison")

        item_a = _file_to_item_from_path(ef_a, source_path)
        item_b = _file_to_item_from_path(ef_a, destination_path, checksum_fallback=ef_a.checksum)
        compare_mode = "source_destination"
    else:
        item_a = _file_to_item(ef_a, db)
        item_b = _file_to_item(ef_b, db)

    # Compare each dimension, treating None as "unknown" (not a mismatch).
    if item_a.sha256 is not None and item_b.sha256 is not None:
        hash_match: Optional[bool] = item_a.sha256 == item_b.sha256
    elif item_a.md5 is not None and item_b.md5 is not None:
        hash_match = item_a.md5 == item_b.md5
    else:
        hash_match = None

    if item_a.size_bytes is not None and item_b.size_bytes is not None:
        size_match: Optional[bool] = item_a.size_bytes == item_b.size_bytes
    else:
        size_match = None

    path_match: bool = item_a.relative_path == item_b.relative_path

    # Hash must be explicitly confirmed equal for a positive match; if it is
    # unknown (None) or False the overall result is not a match.
    # Size is a secondary check: an explicit mismatch (False) prevents a match,
    # but an unknown size (None) is tolerated.
    match = (hash_match is True) and (size_match is not False) and path_match

    audit_repo.add(
        action="FILE_COMPARE",
        user=actor,
        details={
            "file_id_a": body.file_id_a,
            "file_id_b": body.file_id_b,
            "compare_mode": compare_mode,
            "match": match,
            "hash_match": hash_match,
            "size_match": size_match,
            "path_match": path_match,
        },
        client_ip=client_ip,
    )

    return FileCompareResponse(
        match=match,
        hash_match=hash_match,
        size_match=size_match,
        path_match=path_match,
        file_a=item_a,
        file_b=item_b,
    )
