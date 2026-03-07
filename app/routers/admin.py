"""Administrative endpoints for log file access.

These endpoints allow authenticated users to list and download application log
files.  All access is recorded in the audit trail for compliance.

Security considerations
-----------------------
* **Path traversal protection**: the ``{filename}`` parameter is validated
  against ``os.path.basename`` and must match a real file inside the
  configured log directory.  Attempts to escape the directory (e.g.
  ``../../etc/passwd``) are rejected with ``400 Bad Request``.
* **Authentication required**: both endpoints require a valid JWT bearer
  token (enforced at the router level via ``get_current_user``).  No
  additional role restriction is applied — all authenticated users may
  access log files.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import CurrentUser, get_current_user
from app.config import settings
from app.database import get_db
from app.repositories.audit_repository import AuditRepository
from app.schemas.admin import LogFileInfo, LogFilesResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _log_directory() -> Optional[str]:
    """Return the configured log directory, or ``None`` if logging to file is
    not enabled."""
    if not settings.log_file:
        return None
    return os.path.dirname(os.path.abspath(settings.log_file))


def _safe_filename(filename: str) -> str:
    """Validate *filename* to prevent path traversal.

    Returns the sanitised basename if valid; raises ``HTTPException(400)``
    otherwise.
    """
    safe = os.path.basename(filename)
    if not safe or safe != filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid filename: path traversal is not allowed",
        )
    return safe


@router.get("/logs", response_model=LogFilesResponse)
def list_log_files(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List available log files with metadata (size, timestamps).

    Requires authentication (all authenticated users have access; no role
    restriction).

    Returns ``200`` with file list, or ``404`` if file-based logging is not
    configured.
    """
    log_dir = _log_directory()
    if not log_dir or not os.path.isdir(log_dir):
        raise HTTPException(
            status_code=404,
            detail="File-based logging is not configured or log directory does not exist",
        )

    files: List[LogFileInfo] = []
    base_name = os.path.basename(settings.log_file)  # type: ignore[arg-type]
    for entry in sorted(os.listdir(log_dir)):
        # Only expose log files that share the base name prefix (e.g.
        # "app.log", "app.log.1", "app.log.2").
        if not entry.startswith(base_name):
            continue
        full = os.path.join(log_dir, entry)
        if not os.path.isfile(full):
            continue
        stat = os.stat(full)
        files.append(
            LogFileInfo(
                name=entry,
                size=stat.st_size,
                created=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )

    total_size = sum(f.size for f in files)

    # Record access in audit trail.
    try:
        AuditRepository(db).add(
            action="LOG_FILES_LISTED",
            user=current_user.username,
            details={"file_count": len(files), "total_size": total_size},
        )
    except Exception:
        logger.debug("Failed to record log file list access in audit trail", exc_info=True)

    return LogFilesResponse(
        log_files=files,
        total_size=total_size,
        log_directory=log_dir,
    )


@router.get("/logs/{filename}")
def download_log_file(
    filename: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Download a specific log file.

    Requires authentication (all authenticated users have access; no role
    restriction).

    The ``{filename}`` parameter is validated to prevent path traversal.
    """
    log_dir = _log_directory()
    if not log_dir or not os.path.isdir(log_dir):
        raise HTTPException(
            status_code=404,
            detail="File-based logging is not configured or log directory does not exist",
        )

    safe = _safe_filename(filename)
    full_path = os.path.join(log_dir, safe)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="Log file not found")

    # Record access in audit trail.
    try:
        AuditRepository(db).add(
            action="LOG_FILE_DOWNLOADED",
            user=current_user.username,
            details={"filename": safe},
        )
    except Exception:
        logger.debug("Failed to record log file download in audit trail", exc_info=True)

    return FileResponse(
        path=full_path,
        filename=safe,
        media_type="text/plain",
    )
