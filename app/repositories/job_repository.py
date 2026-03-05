from typing import List, Optional

from sqlalchemy import update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.exceptions import ConflictError
from app.models.jobs import (
    DriveAssignment,
    ExportFile,
    ExportJob,
    FileStatus,
    Manifest,
)


class JobRepository:
    """Data-access layer for :class:`~app.models.jobs.ExportJob`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, job_id: int) -> Optional[ExportJob]:
        """Return a single job by primary key, or ``None``."""
        return self.db.get(ExportJob, job_id)

    def get_for_update(self, job_id: int) -> Optional[ExportJob]:
        """Return a single job locked for update, or ``None`` if not found.

        Issues a ``SELECT … FOR UPDATE NOWAIT`` so that concurrent transactions
        attempting to transition the same job are serialized.  If the row is
        already held by another transaction the database raises an
        ``OperationalError`` which is translated to
        :class:`~app.exceptions.ConflictError` (HTTP 409).

        On backends that do not enforce ``FOR UPDATE`` at the row level
        (e.g. SQLite used in tests) the clause is silently ignored and a
        normal ``SELECT`` is executed instead.
        """
        try:
            return (
                self.db.query(ExportJob)
                .filter(ExportJob.id == job_id)
                .with_for_update(nowait=True)
                .one_or_none()
            )
        except OperationalError as exc:
            self.db.rollback()
            raise ConflictError(
                "Job is currently locked by another operation."
            ) from exc

    def add(self, job: ExportJob) -> ExportJob:
        """Persist a new job and flush it to obtain its ID."""
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def save(self, job: ExportJob) -> ExportJob:
        """Commit pending changes to an existing job and refresh it."""
        self.db.commit()
        self.db.refresh(job)
        return job

    def count_active(self) -> int:
        """Return the number of currently running jobs."""
        from app.models.jobs import JobStatus

        return (
            self.db.query(ExportJob)
            .filter(ExportJob.status == JobStatus.RUNNING)
            .count()
        )


class FileRepository:
    """Data-access layer for :class:`~app.models.jobs.ExportFile`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, file_id: int) -> Optional[ExportFile]:
        """Return a single export file by primary key, or ``None``."""
        return self.db.get(ExportFile, file_id)

    def list_by_job(self, job_id: int) -> List[ExportFile]:
        """Return all files belonging to *job_id*."""
        return (
            self.db.query(ExportFile).filter(ExportFile.job_id == job_id).all()
        )

    def list_done_by_job(self, job_id: int) -> List[ExportFile]:
        """Return completed files belonging to *job_id*."""
        return (
            self.db.query(ExportFile)
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status == FileStatus.DONE,
            )
            .all()
        )

    def add(self, export_file: ExportFile) -> ExportFile:
        """Persist a new export file record."""
        self.db.add(export_file)
        return export_file

    def add_bulk(self, export_files: List[ExportFile]) -> None:
        """Persist multiple export file records in a single transaction."""
        self.db.add_all(export_files)
        self.db.commit()

    def save(self, export_file: ExportFile) -> None:
        """Commit pending changes to an existing export file."""
        self.db.commit()

    def delete_by_job(self, job_id: int) -> None:
        """Delete all export file records for *job_id*."""
        self.db.query(ExportFile).filter(ExportFile.job_id == job_id).delete()
        self.db.commit()

    def count_errors(self, job_id: int) -> int:
        """Return the number of files in ERROR state for *job_id*."""
        return (
            self.db.query(ExportFile)
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status == FileStatus.ERROR,
            )
            .count()
        )

    def increment_job_bytes(self, job_id: int, size_bytes: int) -> None:
        """Atomically increment the ``copied_bytes`` counter on the parent job."""
        self.db.execute(
            update(ExportJob)
            .where(ExportJob.id == job_id)
            .values(copied_bytes=ExportJob.copied_bytes + size_bytes)
        )
        self.db.commit()


class DriveAssignmentRepository:
    """Data-access layer for :class:`~app.models.jobs.DriveAssignment`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, assignment: DriveAssignment) -> DriveAssignment:
        """Persist a new drive assignment and flush it."""
        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment


class ManifestRepository:
    """Data-access layer for :class:`~app.models.jobs.Manifest`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, manifest: Manifest) -> Manifest:
        """Persist a new manifest record and flush it."""
        self.db.add(manifest)
        self.db.commit()
        self.db.refresh(manifest)
        return manifest
