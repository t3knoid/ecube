"""Browse service — directory listing with path-traversal protection.

Security model:
1. ``path`` must match a registered mount root from the DB (USB ``mount_path``
   or network ``local_mount_point``).  Arbitrary filesystem paths are rejected
   with 403.
2. The resolved ``realpath(mount_root / subdir)`` must start with
   ``realpath(mount_root)``.  Path-traversal via ``../`` is rejected with 400.
3. Each component of the user-supplied *subdir* is checked with ``islink``;
   symlink traversal is rejected with 400 even when the resolved path
   stays inside the mount root.
4. The resolved path must start with one of the configured
   ``settings.browse_allowed_prefixes`` as a secondary defence layer.
5. Symlinks are *not* followed — they are reported as ``type: "symlink"`` but
   never dereferenced.
6. A ``BROWSE_DIRECTORY`` audit record is written on success; a
   ``BROWSE_DENIED`` record is written when the request is rejected with 403.
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
from app.models.network import MountStatus, NetworkMount
from app.schemas.browse import BrowseEntry, BrowseResponse, EntryType
from app.services.audit_service import log_and_audit

logger = logging.getLogger(__name__)


def _lookup_mount_root(path: str, db: Session) -> Optional[str]:
    """Return the DB-stored mount root that matches *path*, or ``None``.

    Matching is done by normalising both sides (strip trailing slash).  Returns
    the **DB-stored** value so that subsequent filesystem operations are derived
    from a trusted source rather than from the raw user-provided string.
    """
    normalised = path.rstrip("/")
    candidates = [normalised]
    if normalised:
        candidates.append(f"{normalised}/")
    else:
        candidates.append("/")

    usb_path = (
        db.query(UsbDrive.mount_path)
        .filter(
            UsbDrive.mount_path.isnot(None),
            UsbDrive.mount_path.in_(candidates),
        )
        .first()
    )
    if usb_path and usb_path[0]:
        return usb_path[0].rstrip("/")

    net_path = (
        db.query(NetworkMount.local_mount_point)
        .filter(
            NetworkMount.status == MountStatus.MOUNTED,
            NetworkMount.local_mount_point.isnot(None),
            NetworkMount.local_mount_point != "",
            NetworkMount.local_mount_point.in_(candidates),
        )
        .first()
    )
    if net_path and net_path[0]:
        return net_path[0].rstrip("/")

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
        HTTPException(400): symlink encountered on the path from root to target.
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

    # Symlink check — walk each component of the *unresolved* subdir path
    # from real_root to ensure no intermediate or leaf component is a symlink.
    # This prevents API-level navigation through symlinked directories even
    # when the resolved target stays inside the mount root.
    if subdir:
        components = relative.split("/")
        current = real_root
        for component in components:
            if not component:
                continue
            current = os.path.join(current, component)
            if os.path.islink(current):
                raise HTTPException(
                    status_code=400,
                    detail="Symlink traversal denied: a path component is a symbolic link.",
                )

    # Allowlist check (secondary defence).  Normalize each configured prefix
    # and enforce a path-separator boundary so that prefix "/mnt/ecube" does
    # not accidentally match "/mnt/ecube2/...".
    allowed = settings.browse_allowed_prefixes
    if allowed:
        normalised_prefixes = [os.path.realpath(p).rstrip("/") + "/" for p in allowed]
        root_with_sep = real_root.rstrip("/") + "/"
        if not any(root_with_sep.startswith(np) or real_root == np.rstrip("/") for np in normalised_prefixes):
            raise HTTPException(
                status_code=403,
                detail="Mount root is not in the configured allowed-prefix list.",
            )

    return real_root, real_target


def _stat_entry(dir_entry: os.DirEntry) -> Optional[BrowseEntry]:
    """Build a :class:`BrowseEntry` from an :class:`os.DirEntry`.

    Accepts an ``os.DirEntry`` so the caller can sort by name before
    stat'ing only the page slice.  Note: ``DirEntry.stat()`` still
    performs a real ``lstat`` syscall on the first call (it is **not**
    served from the ``scandir`` d_type cache); however, the result is
    cached on the ``DirEntry`` for any subsequent ``.stat()`` calls.

    Returns ``None`` when the entry cannot be stat'd (e.g. race condition
    where the file was removed between ``scandir`` and ``stat``).
    """
    try:
        entry_stat = dir_entry.stat(follow_symlinks=False)
    except OSError:
        return None

    mode = entry_stat.st_mode
    if stat.S_ISLNK(mode):
        entry_type = EntryType.SYMLINK
        size_bytes = None
    elif stat.S_ISDIR(mode):
        entry_type = EntryType.DIRECTORY
        size_bytes = None
    else:
        entry_type = EntryType.FILE
        size_bytes = entry_stat.st_size

    modified_at = datetime.fromtimestamp(entry_stat.st_mtime, tz=timezone.utc)

    return BrowseEntry(
        name=dir_entry.name,
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
    try:
        if db_mount_root is None:
            raise HTTPException(
                status_code=403,
                detail="The requested path is not a registered active mount root.",
            )

        # 2 & 3. Resolve path from the trusted DB root + user subdir; validate
        #         containment (anti-traversal) and allowlist (defence-in-depth).
        real_root, real_target = _resolve_and_validate(db_mount_root, subdir)

        # 4. List directory -- use os.scandir() to collect DirEntry objects,
        #    sort by name, then stat only the requested page.  This avoids
        #    stat'ing entries outside the page window.
        try:
            with os.scandir(real_target) as it:  # noqa: S605 -- path validated above
                dir_entries = sorted(it, key=lambda e: e.name)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="The directory no longer exists — the drive or share may have been unmounted.",
            )
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

        total = len(dir_entries)
        start = (page - 1) * page_size
        page_slice = dir_entries[start : start + page_size]

        entries = []
        for de in page_slice:
            entry = _stat_entry(de)  # noqa: S605 -- path validated above
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
    except HTTPException as exc:
        if exc.status_code == 403:
            reason = str(exc.detail) if exc.detail else "browse_forbidden"

            log_and_audit(
                db,
                "BROWSE_DENIED",
                actor_id=actor,
                level=logging.WARNING,
                metadata={"path": path, "subdir": subdir, "reason": reason},
                client_ip=client_ip,
            )
        raise
