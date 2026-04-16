"""Browse router — ``GET /browse``.

Returns a paginated directory listing for an active USB drive mount path
or network share mount point.

Security is enforced by :mod:`app.services.browse_service` before any
filesystem call:

1. ``path`` must match a registered, ECUBE-managed mount root from the DB.
2. ``subdir`` containment is verified via ``realpath``.
3. The resolved path must start with one of the configured allowed prefixes.
4. Every call is written to ``audit_logs`` with action ``BROWSE_DIRECTORY``.
"""

import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.browse import BrowseResponse
from app.schemas.errors import R_400, R_401, R_403, R_404, R_422, R_500
from app.services import browse_service
from app.utils.client_ip import get_client_ip
from app.utils.sanitize import StrictSafeStr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/browse", tags=["browse"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")

_MAX_PAGE_SIZE = 500
_DEFAULT_PAGE_SIZE = 100


@router.get(
    "",
    response_model=BrowseResponse,
    responses={**R_400, **R_401, **R_403, **R_404, **R_422, **R_500},
)
def browse_directory(
    request: Request,
    path: StrictSafeStr = Query(
        ...,
        description=(
            "The mount root to browse. Must be an active USB drive mount path "
            "or network mount local mount point registered in the system."
        ),
    ),
    subdir: StrictSafeStr = Query(
        default="",
        description="Relative subdirectory within the mount root. Defaults to the root of the mount.",
    ),
    page: int = Query(
        default=1,
        ge=1,
        description="Page number (1-based).",
    ),
    page_size: int = Query(
        default=_DEFAULT_PAGE_SIZE,
        ge=1,
        le=_MAX_PAGE_SIZE,
        description=f"Number of entries per page. Maximum: {_MAX_PAGE_SIZE}.",
    ),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALL_ROLES),
):
    """List directory contents of an active USB drive or network share mount.

    The ``path`` parameter must be an active ECUBE-registered mount root —
    either a USB drive ``mount_path`` or a network mount ``local_mount_point``.
    Arbitrary filesystem paths are rejected with ``403``.

    The optional ``subdir`` parameter is a relative path within that root.
    Path-traversal attempts (e.g. ``../../etc``) are detected via ``realpath``
    containment check and rejected with ``400``.

    Symlinks within the directory are listed as ``type: "symlink"`` and are
    not followed or navigable.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return browse_service.list_directory(
        path=path,
        subdir=subdir,
        page=page,
        page_size=page_size,
        db=db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )
