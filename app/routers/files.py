import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.jobs import FileCompareRequest, FileCompareResponse, FileHashesResponse
from app.schemas.errors import R_401, R_403, R_404, R_422
from app.services import file_service
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])

_ADMIN_AUDITOR = require_roles("admin", "auditor")


@router.get("/{file_id}/hashes", response_model=FileHashesResponse, responses={**R_401, **R_403, **R_404, **R_422})
def get_file_hashes(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_AUDITOR),
):
    """Return MD5 and SHA-256 hashes for a single export file.

    **Roles:** ``admin``, ``auditor``
    """
    return file_service.get_file_hashes(file_id, db, actor=current_user.username, client_ip=get_client_ip(request))


@router.post("/compare", response_model=FileCompareResponse, responses={**R_401, **R_403, **R_404, **R_422})
def compare_files(
    body: FileCompareRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_AUDITOR),
):
    """Compare two export files by hash, size, and relative path.

    **Roles:** ``admin``, ``auditor``
    """
    return file_service.compare_files(body, db, actor=current_user.username, client_ip=get_client_ip(request))
