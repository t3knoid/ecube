import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from typing import List

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.infrastructure import get_throughput_benchmark
from app.schemas.network import CandidateNetworkShareSchema, ShareCreate, MountShareDiscoveryRequest, MountShareDiscoveryResponse, ShareUpdate, NetworkShareSchema
from app.schemas.errors import R_400, R_401, R_403, R_404, R_409, R_422, R_500
from app.services import share_service, throughput_service
from app.utils.client_ip import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shares", tags=["shares"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER = require_roles("admin", "manager")


@router.post("", response_model=NetworkShareSchema, responses={**R_400, **R_401, **R_403, **R_409, **R_422, **R_500})
def add_share(
    body: ShareCreate,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Register a new network share (SMB, NFS, etc.) as a data source.

    Stores share credentials and configuration, and attempts to connect immediately,
    updating the share status based on the result of the system ``mount`` command.
    Connectivity can be explicitly re-tested via ``POST /shares/{share_id}/validate``.

    **Roles:** ``admin``, ``manager``
    """
    return share_service.add_share(body, db, actor=current_user.username, client_ip=get_client_ip(request))


@router.patch("/{share_id}", response_model=NetworkShareSchema, responses={**R_400, **R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def update_share(
    share_id: int,
    body: ShareUpdate,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Update an existing network share configuration.

    Reuses the same share validation flow as creation while preserving the
    generated local mount point and never returning credential values.

    **Roles:** ``admin``, ``manager``
    """
    return share_service.update_share(
        share_id,
        body,
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.get("", response_model=List[NetworkShareSchema], responses={**R_401, **R_403})
def list_shares(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ALL_ROLES),
):
    """List all registered network shares and their connectivity status.

    Returns share details without exposing credentials.

    **Roles:** ``admin``, ``manager``, ``processor``, ``auditor``
    """
    return share_service.list_shares(db, user_roles=current_user.roles)


@router.post("/validate", response_model=List[NetworkShareSchema], responses={**R_401, **R_403, **R_500})
def validate_all_shares(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Test connectivity and credentials for all registered network shares.

    Updates each share's connectivity status and ``last_checked_at`` timestamp; any
    errors encountered are reflected in the returned share status.

    **Roles:** ``admin``, ``manager``
    """
    return share_service.validate_all_shares(
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.post("/test", response_model=CandidateNetworkShareSchema, responses={**R_401, **R_403, **R_409, **R_422, **R_500})
def validate_share_candidate(
    body: ShareCreate,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Test connectivity and credentials for a candidate share before it is created.

    Attempts to connect using the submitted share settings, then restores the host
    to its pre-test state without persisting a new share record.

    **Roles:** ``admin``, ``manager``
    """
    return share_service.validate_share_candidate(
        body,
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.post("/discover", response_model=MountShareDiscoveryResponse, responses={**R_401, **R_403, **R_409, **R_422, **R_500})
def discover_shares(
    body: MountShareDiscoveryRequest,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Discover shares or exports from the Add Share flow.

    Uses the submitted share type plus any entered credentials to enumerate
    available NFS exports or SMB shares from the target server. Results are
    returned as sanitized remote paths suitable for the Add Share dialog.

    **Roles:** ``admin``, ``manager``
    """
    return share_service.discover_shares(
        body,
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )


@router.delete("/validate", status_code=405, responses={**R_401, **R_403}, include_in_schema=False)
def _delete_validate_not_allowed(
    _: CurrentUser = Depends(_ADMIN_MANAGER),
):
    """Reject DELETE on the /validate path with 405 Method Not Allowed."""
    from fastapi import HTTPException
    raise HTTPException(
        status_code=405,
        detail="Method Not Allowed",
        headers={"Allow": "POST"},
    )


@router.delete("/{share_id}", status_code=204, responses={**R_401, **R_403, **R_404, **R_422, **R_500})
def remove_share(
    share_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Remove a network share from the system.

    Deletes the share configuration and credentials. In-progress jobs using this share may fail.

    **Roles:** ``admin``, ``manager``
    """
    share_service.remove_share(
        share_id,
        db,
        actor=current_user.username,
        client_ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.post("/{share_id}/validate", response_model=NetworkShareSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def validate_share(
    share_id: int,
    body: ShareUpdate | None = None,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Test connectivity and credentials for a specific network share.

    Attempts to connect using stored credentials and reports success or error.

    **Roles:** ``admin``, ``manager``
    """
    return share_service.validate_share(
        share_id,
        db,
        mount_data=body,
        actor=current_user.username,
        client_ip=get_client_ip(request),
        trace_id=getattr(request.state, "trace_id", None),
    )


@router.post("/{share_id}/throughput-test", response_model=NetworkShareSchema, responses={**R_401, **R_403, **R_404, **R_409, **R_422, **R_500})
def test_share_throughput(
    share_id: int,
    *,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(_ADMIN_MANAGER),
    request: Request,
):
    """Measure mounted share read throughput and persist the latest result.

    **Roles:** ``admin``, ``manager``
    """
    return throughput_service.test_mount_read_throughput(
        share_id,
        db,
        benchmark_provider=get_throughput_benchmark(),
        actor=current_user.username,
        client_ip=get_client_ip(request),
    )
