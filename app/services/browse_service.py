"""Browse service — directory listing with path-traversal protection.

Security model:
1. ``path`` must match a registered mount root from the DB (USB ``mount_path``
   or network ``local_mount_point``).  Arbitrary filesystem paths are rejected
   with 403.
2. The resolved ``realpath(mount_root / subdir)`` must start with
   ``realpath(mount_root)``.  Path-traversal via ``../`` or symlinks is
   rejected with 400.
3. The resolved path must start with one of the configured
   ``settings.browse_allowed_prefixes`` as a secondary defence layer.
4. Symlinks are *not* followed — they are reported as ``type: "symlink"`` but
   never dereferenced.
5. An ``BROWSE_DIRECTORY`` audit record is written on every call.
"""

import logging
import os
import stat
from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.hardware import UsbDrive
from app.models.network import NetworkMount
from app.schemas.browse import BrowseEntry, BrowseResponse
from app.services.audit_service import log_and_audit

logger = logging.getLogger(__name__)


def _lookup_mount_root(path: str, db: Session) -> Optional[str]:
    """Return the DB-stored mount root that matches *path*, or ``None``.

    Matching is done by normalising both sides (strip trailing slash).  Returns
    the **DB-stored** value so that subsequent filesystem operations are derived
    from a trusted source rather than from the raw user-provided string.
    """
    normalised = path.rstrip("/")

    usb_paths = (
        db.query(UsbDrive.mount_path)
        .filter(UsbDrive.mount_path.isnot(None))
        .all()
    )
    for (p,) in usb_paths:
        if p and p.rstrip("/") == normalised:
            return p.rstrip("/")

    net_paths = db.query(NetworkMount.local_mount_point).all()
    for (p,) in net_paths:
        if p and p.rstrip("/") == normalised:
            return p.rstrip("/")

    return None


def _resolve_and_validate(
    db_mount_root: str,
    subdir: str,
) -> Tuple[str, str]:
    """Return ``(real_root, real_target)`` after safety checks.

    Both values are derived from *db_mount_root* (a DB-stored trusted value)
    combined with the user-supplied *subdir* after strict containment
    verification.

    Raises:
        HTTPException(400): path-traversal detected.
        HTTPException(403): resolved path not under an allowed prefix.
    """
    real_root = os.path.realpath(db_mount_root)

    # Build target path; strip leading slashes so subdir is always relative
    if subdir:
        relative = subdir.lstrip("/")
        target = os.path.join(real_root, relative)
    else:
        target = real_root

    real_target = os.path.realpath(target)

    # Containment check — real_target must be real_root or a descendant
    safe_root_prefix = real_root.rstrip("/") + "/"
    if real_target != real_root and not real_target.startswith(safe_root_prefix):
        raise HTTPException(
            status_code=400,
            detail="Path traversal detected: subdir resolves outside mount root.",
        )

    # Allowlist check (secondary defence)
    allowed = settings.browse_allowed_prefixes
    if allowed and not any(real_root.startswith(p) for p in allowed):
        raise HTTPException(
            status_code=403,
            detail="Mount root is not in the configured allowed-prefix list.",
        )

    return real_root, real_target


def _stat_entry(dirpath: str, name: str) -> Optional[BrowseEntry]:
    """Build a :class:`BrowseEntry` for ``name`` inside ``dirpath``.

    Uses ``lstat`` so that symlinks are reported as-is without following them.
    Returns ``None`` when the entry cannot be stat'd (e.g. race condition).

    Security: ``dirpath`` is the validated ``real_target`` (contained within the
    DB-registered mount root).  ``name`` comes from ``os.listdir()`` — it is a
    filesystem-provided entry name, not user input.  The join of two safe values
    is therefore safe; the ``os.lstat`` call below is intentional (false-positive
    path-injection: path is validated by the caller via realpath containment check).
    """
    # Limit name to a bare filename component (no directory separators).
    # This is a defence-in-depth measure against unexpected os.listdir results.
    safe_name = os.path.basename(name)
    full_path = os.path.join(dirpath, safe_name)
    try:
        entry_stat = os.lstat(full_path)
    except OSError:
        return None

    mode = entry_stat.st_mode
    if stat.S_ISLNK(mode):
        entry_type = "symlink"
        size_bytes = None
    elif stat.S_ISDIR(mode):
        entry_type = "directory"
        size_bytes = None
    else:
        entry_type = "file"
        size_bytes = entry_stat.st_size

    modified_at = datetime.fromtimestamp(entry_stat.st_mtime, tz=timezone.utc)

    return BrowseEntry(
        name=safe_name,
        type=entry_type,
        size_bytes=size_bytes,
        modified_at=modified_at,
    )


def list_directory(
    *,
    path: str,
    subdir: str,
    page: int,
    page_size: int,
    db: Session,
    actor: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> BrowseResponse:
    """Return a paginated directory listing for *path* / *subdir*.

    Parameters
    ----------
    path:
        The mount root to browse.  Must match an active USB drive mount path
        or network mount local mount point registered in the database.
    subdir:
        Relative subdirectory within the mount root.  Empty string for root.
    page:
        1-based page number.
    page_size:
        Number of entries per page (max enforced by caller).
    db:
        Active SQLAlchemy session.
    actor:
        Username of the requesting user (for audit logging).
    client_ip:
        Client IP address (for audit logging).

    Raises
    ------
    HTTPException(403):
        When *path* does not match any active mount root, or falls outside the
        configured allowed-prefix list.
    HTTPException(400):
        When *subdir* causes a path-traversal outside the mount root.
    HTTPException(500):
        When the target directory cannot be listed due to a filesystem error.
    """
    # 1. Validate mount root against DB — returns the DB-stored (trusted) value
    #    or None.  Using the DB-stored value means all subsequent filesystem
    #    operations are derived from a trusted source, not from user input.
    db_mount_root = _lookup_mount_root(path, db)
    if db_mount_root is None:
        log_and_audit(
            db,
            "BROWSE_DENIED",
            actor_id=actor,
            level=logging.WARNING,
            metadata={"path": path, "subdir": subdir, "reason": "unknown_mount_root"},
            client_ip=client_ip,
        )
        raise HTTPException(
            status_code=403,
            detail="The requested path is not a registered active mount root.",
        )

    # 2 & 3. Resolve path from the trusted DB root + user subdir; validate
    #         containment (anti-traversal) and allowlist (defence-in-depth).
    real_root, real_target = _resolve_and_validate(db_mount_root, subdir)

    # 4. List directory -- path is derived from the DB-stored trusted root after
    #    realpath containment validation above.
    try:
        names = sorted(os.listdir(real_target))  # noqa: S605 -- path validated above
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="Permission denied listing the requested directory.",
        )
    except NotADirectoryError:
        raise HTTPException(
            status_code=400,
            detail="The resolved path is not a directory.",
        )
    except OSError as exc:
        logger.error("Failed to list directory %s: %s", real_target, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to list the directory due to a filesystem error.",
        )

    total = len(names)
    start = (page - 1) * page_size
    page_names = names[start : start + page_size]

    entries = []
    for name in page_names:
        # name comes from os.listdir() (filesystem-provided), not from user input
        entry = _stat_entry(real_target, name)  # noqa: S605 -- path validated above
        if entry is not None:
            entries.append(entry)

    # 5. Audit log
    log_and_audit(
        db,
        "BROWSE_DIRECTORY",
        actor_id=actor,
        metadata={
            "path": path,
            "subdir": subdir,
            "page": page,
            "page_size": page_size,
            "total": total,
            "entry_count": len(entries),
        },
        client_ip=client_ip,
    )

    return BrowseResponse(
        path=db_mount_root,
        subdir=subdir,
        entries=entries,
        total=total,
        page=page,
        page_size=page_size,
    )
