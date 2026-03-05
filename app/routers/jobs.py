from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.auth import CurrentUser, require_roles
from app.database import get_db
from app.schemas.jobs import ExportJobSchema, JobCreate, JobStart
from app.services import job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

_ALL_ROLES = require_roles("admin", "manager", "processor", "auditor")
_ADMIN_MANAGER_PROCESSOR = require_roles("admin", "manager", "processor")


@router.post("", response_model=ExportJobSchema)
def create_job(
    body: JobCreate,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    return job_service.create_job(body, db)


@router.get("/{job_id}", response_model=ExportJobSchema)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ALL_ROLES),
):
    return job_service.get_job(job_id, db)


@router.post("/{job_id}/start", response_model=ExportJobSchema)
def start_job(
    job_id: int,
    body: JobStart,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    return job_service.start_job(job_id, body, background_tasks, db)


@router.post("/{job_id}/verify", response_model=ExportJobSchema)
def verify_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    return job_service.verify_job(job_id, background_tasks, db)


@router.post("/{job_id}/manifest", response_model=ExportJobSchema)
def create_manifest(
    job_id: int,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(_ADMIN_MANAGER_PROCESSOR),
):
    return job_service.create_manifest(job_id, db)
