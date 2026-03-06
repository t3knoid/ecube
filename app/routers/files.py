from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.jobs import FileCompareRequest, FileCompareResponse, FileHashesResponse
from app.services import file_service

router = APIRouter(prefix="/files", tags=["files"])

_ADMIN_AUDITOR = require_roles("admin", "auditor")


@router.get("/{file_id}/hashes", response_model=FileHashesResponse)
def get_file_hashes(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_AUDITOR),
):
    """Return MD5 and SHA-256 hashes for a single export file.

    **Roles:** ``admin``, ``auditor``
    """
    return file_service.get_file_hashes(file_id, db, actor=current_user.username)


@router.post("/compare", response_model=FileCompareResponse)
def compare_files(
    body: FileCompareRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_AUDITOR),
):
    """Compare two export files by hash, size, and relative path.

    **Roles:** ``admin``, ``auditor``
    """
    return file_service.compare_files(body, db, actor=current_user.username)
