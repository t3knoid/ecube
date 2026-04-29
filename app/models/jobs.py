from itertools import chain

from sqlalchemy import Column, Integer, String, BigInteger, Enum, ForeignKey, DateTime, Text, JSON, Float, Index, event
from sqlalchemy.dialects.postgresql import JSONB, insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, relationship, validates
from sqlalchemy.sql import func
from app.database import Base
from app.models.projects import Project
from app.utils.sanitize import normalize_project_id
import enum


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSING = "PAUSING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    VERIFYING = "VERIFYING"
    ARCHIVED = "ARCHIVED"


class FileStatus(str, enum.Enum):
    PENDING = "PENDING"
    COPYING = "COPYING"
    DONE = "DONE"
    ERROR = "ERROR"
    RETRYING = "RETRYING"
    TIMEOUT = "TIMEOUT"


class StartupAnalysisStatus(str, enum.Enum):
    NOT_ANALYZED = "NOT_ANALYZED"
    ANALYZING = "ANALYZING"
    READY = "READY"
    STALE = "STALE"
    FAILED = "FAILED"


class ExportJob(Base):
    __tablename__ = "export_jobs"
    id = Column(Integer, primary_key=True)
    project_id = Column(String, ForeignKey("projects.normalized_project_id"), nullable=False, index=True)
    evidence_number = Column(String, nullable=False)
    source_path = Column(String, nullable=False)
    target_mount_path = Column(String)
    status = Column(Enum(JobStatus, native_enum=False), default=JobStatus.PENDING)
    total_bytes = Column(BigInteger, default=0)
    copied_bytes = Column(BigInteger, default=0)
    file_count = Column(Integer, default=0)
    thread_count = Column(Integer, default=4)
    max_file_retries = Column(Integer, default=3)
    retry_delay_seconds = Column(Integer, default=1)
    active_duration_seconds = Column(Integer, default=0, nullable=False)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_by = Column(String)
    started_by = Column(String)
    client_ip = Column(String(45), nullable=True)
    callback_url = Column(String, nullable=True)
    failure_reason = Column(Text, nullable=True)
    startup_analysis_status = Column(Enum(StartupAnalysisStatus, native_enum=False), default=StartupAnalysisStatus.NOT_ANALYZED, nullable=False)
    startup_analysis_last_analyzed_at = Column(DateTime(timezone=True), nullable=True)
    startup_analysis_failure_reason = Column(Text, nullable=True)
    startup_analysis_file_count = Column(Integer, nullable=True)
    startup_analysis_total_bytes = Column(BigInteger, nullable=True)
    startup_analysis_share_read_mbps = Column(Float, nullable=True)
    startup_analysis_drive_write_mbps = Column(Float, nullable=True)
    startup_analysis_estimated_duration_seconds = Column(Integer, nullable=True)
    startup_analysis_entries = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship(Project, back_populates="jobs")
    files = relationship("ExportFile", back_populates="job")
    manifests = relationship("Manifest", back_populates="job")
    assignments = relationship("DriveAssignment", back_populates="job")

    @validates("project_id")
    def _normalize_project_id(self, _key, value):
        normalized = normalize_project_id(value)
        return normalized if isinstance(normalized, str) else value

    @property
    def startup_analysis_cached(self) -> bool:
        return self.startup_analysis_entries is not None

    @property
    def startup_analysis_ready(self) -> bool:
        return self.startup_analysis_cached and self.startup_analysis_status == StartupAnalysisStatus.READY


class ExportFile(Base):
    __tablename__ = "export_files"
    __table_args__ = (
        Index("ix_export_files_project_status", "project_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("export_jobs.id"), nullable=False)
    project_id = Column(String, ForeignKey("projects.normalized_project_id"), nullable=False, index=True)
    relative_path = Column(String, nullable=False)
    size_bytes = Column(BigInteger)
    checksum = Column(String)
    status = Column(Enum(FileStatus, native_enum=False), default=FileStatus.PENDING)
    error_message = Column(Text)
    retry_attempts = Column(Integer, default=0)
    job = relationship("ExportJob", back_populates="files")
    project = relationship(Project, back_populates="files")


class Manifest(Base):
    __tablename__ = "manifests"
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("export_jobs.id"), nullable=False)
    manifest_path = Column(String)
    format = Column(String, default="JSON")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    job = relationship("ExportJob", back_populates="manifests")


class DriveAssignment(Base):
    __tablename__ = "drive_assignments"
    id = Column(Integer, primary_key=True)
    drive_id = Column(Integer, ForeignKey("usb_drives.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("export_jobs.id"), nullable=False)
    file_count = Column(Integer, default=0, nullable=False)
    copied_bytes = Column(BigInteger, default=0, nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    released_at = Column(DateTime(timezone=True))
    drive = relationship("UsbDrive", back_populates="assignments")
    job = relationship("ExportJob", back_populates="assignments")


@event.listens_for(Session, "before_flush")
def _ensure_projects_for_jobs(session, _flush_context, _instances):
    project_ids: set[str] = set()
    for obj in chain(session.new, session.dirty):
        if isinstance(obj, ExportJob):
            normalized = normalize_project_id(obj.project_id)
        elif isinstance(obj, ExportFile):
            normalized = _resolve_export_file_project_id(session, obj)
        else:
            continue
        if not isinstance(normalized, str) or not normalized:
            continue
        if obj.project_id != normalized:
            obj.project_id = normalized
        project_ids.add(normalized)

    if not project_ids:
        return

    pending_project_ids = {
        normalized
        for obj in session.new
        if isinstance(obj, Project)
        and isinstance((normalized := normalize_project_id(obj.normalized_project_id)), str)
        and normalized
    }

    for project_id in sorted(project_ids - pending_project_ids):
        _insert_project_if_missing(session, project_id)


def _insert_project_if_missing(session: Session, project_id: str) -> None:
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""

    if dialect_name == "postgresql":
        session.execute(
            postgresql_insert(Project)
            .values(normalized_project_id=project_id)
            .on_conflict_do_nothing(index_elements=["normalized_project_id"])
        )
        return

    if dialect_name == "sqlite":
        session.execute(
            sqlite_insert(Project)
            .values(normalized_project_id=project_id)
            .on_conflict_do_nothing(index_elements=["normalized_project_id"])
        )
        return

    existing_project = session.get(Project, {"normalized_project_id": project_id})
    if existing_project is None:
        session.add(Project(normalized_project_id=project_id))


def _resolve_export_file_project_id(session: Session, export_file: ExportFile) -> object:
    if export_file.job is not None:
        return normalize_project_id(export_file.job.project_id)

    if export_file.job_id is not None:
        job = session.get(ExportJob, export_file.job_id)
        if job is not None:
            return normalize_project_id(job.project_id)

    return normalize_project_id(export_file.project_id)
