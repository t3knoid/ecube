from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from sqlalchemy import case, func, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

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
            orig = getattr(exc, "orig", None)
            sqlstate = getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)
            if sqlstate == "55P03":
                raise ConflictError(
                    "Job is currently locked by another operation."
                ) from exc
            raise

    def add(self, job: ExportJob) -> ExportJob:
        """Persist a new job and flush it to obtain its ID."""
        self.db.add(job)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(job)
        return job

    def save(self, job: ExportJob) -> ExportJob:
        """Commit pending changes to an existing job and refresh it."""
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
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

    def list_recent(self, limit: int = 200) -> List[ExportJob]:
        """Return the most recent jobs ordered by creation time descending."""
        return (
            self.db.query(ExportJob)
            .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
            .limit(limit)
            .all()
        )


class FileRepository:
    """Data-access layer for :class:`~app.models.jobs.ExportFile`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, file_id: int) -> Optional[ExportFile]:
        """Return a single export file by primary key, or ``None``."""
        return self.db.get(ExportFile, file_id)

    def list_by_job(self, job_id: int, *, limit: int | None = None) -> List[ExportFile]:
        """Return files belonging to *job_id*, optionally capped by *limit*."""
        query = (
            self.db.query(ExportFile)
            .filter(ExportFile.job_id == job_id)
            .order_by(ExportFile.id)
        )
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def count_by_job(self, job_id: int) -> int:
        """Return the total number of files belonging to *job_id*."""
        return (
            self.db.query(func.count())
            .filter(ExportFile.job_id == job_id)
            .scalar()
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

    def list_incomplete_by_job(self, job_id: int) -> List[ExportFile]:
        """Return files that are not yet successfully completed for *job_id*.

        This includes files in ``PENDING``, ``COPYING``, ``RETRYING``, and
        ``ERROR`` states — everything except ``DONE``.
        """
        return (
            self.db.query(ExportFile)
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status != FileStatus.DONE,
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
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def save(self, export_file: ExportFile) -> None:
        """Commit pending changes to an existing export file."""
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def delete_by_job(self, job_id: int) -> None:
        """Delete all export file records for *job_id*."""
        self.db.query(ExportFile).filter(ExportFile.job_id == job_id).delete()
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def count_done_and_errors(self, job_id: int) -> Tuple[int, int]:
        """Return ``(done_count, error_count)`` for *job_id* in a single query."""
        row = (
            self.db.query(
                func.count(case((ExportFile.status == FileStatus.DONE, 1))),
                func.count(case((ExportFile.status == FileStatus.ERROR, 1))),
            )
            .filter(ExportFile.job_id == job_id)
            .one()
        )
        return row[0], row[1]

    def count_done(self, job_id: int) -> int:
        """Return the number of files in DONE state for *job_id*."""
        return (
            self.db.query(func.count())
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status == FileStatus.DONE,
            )
            .scalar()
        )

    def count_errors(self, job_id: int) -> int:
        """Return the number of files in ERROR state for *job_id*."""
        return (
            self.db.query(func.count())
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status == FileStatus.ERROR,
            )
            .scalar()
        )

    def list_error_messages(
        self, job_id: int, *, limit: int = 5
    ) -> List[Tuple[str, str]]:
        """Return ``(error_message, relative_path)`` for up to *limit* failed files."""
        rows = (
            self.db.query(ExportFile.error_message, ExportFile.relative_path)
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status == FileStatus.ERROR,
                ExportFile.error_message.isnot(None),
            )
            .order_by(ExportFile.id)
            .limit(limit)
            .all()
        )
        return [(r.error_message, r.relative_path) for r in rows]

    def bulk_count_done_and_errors(
        self, job_ids: List[int]
    ) -> Dict[int, Tuple[int, int]]:
        """Return ``{job_id: (done_count, error_count)}`` for all *job_ids* in one query."""
        if not job_ids:
            return {}
        rows = (
            self.db.query(
                ExportFile.job_id,
                func.count(case((ExportFile.status == FileStatus.DONE, 1))),
                func.count(case((ExportFile.status == FileStatus.ERROR, 1))),
            )
            .filter(ExportFile.job_id.in_(job_ids))
            .group_by(ExportFile.job_id)
            .all()
        )
        return {r[0]: (r[1], r[2]) for r in rows}

    def bulk_list_error_messages(
        self, job_ids: List[int], *, limit_per_job: int = 5
    ) -> Dict[int, List[Tuple[str, str]]]:
        """Return ``{job_id: [(error_message, relative_path), ...]}``.

        Uses a window function to fetch at most *limit_per_job* error rows
        per job in a single query.
        """
        if not job_ids:
            return {}
        row_num = (
            func.row_number()
            .over(
                partition_by=ExportFile.job_id,
                order_by=ExportFile.id,
            )
            .label("rn")
        )
        subq = (
            self.db.query(
                ExportFile.job_id,
                ExportFile.error_message,
                ExportFile.relative_path,
                row_num,
            )
            .filter(
                ExportFile.job_id.in_(job_ids),
                ExportFile.status == FileStatus.ERROR,
                ExportFile.error_message.isnot(None),
            )
            .subquery()
        )
        rows = (
            self.db.query(
                subq.c.job_id,
                subq.c.error_message,
                subq.c.relative_path,
            )
            .filter(subq.c.rn <= limit_per_job)
            .all()
        )
        result: Dict[int, List[Tuple[str, str]]] = defaultdict(list)
        for job_id, msg, path in rows:
            result[job_id].append((msg, path))
        return dict(result)

    def increment_job_bytes(self, job_id: int, size_bytes: int) -> None:
        """Atomically increment the ``copied_bytes`` counter on the parent job."""
        self.db.execute(
            update(ExportJob)
            .where(ExportJob.id == job_id)
            .values(copied_bytes=ExportJob.copied_bytes + size_bytes)
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def decrement_job_bytes(self, job_id: int, size_bytes: int) -> None:
        """Atomically subtract bytes from the parent job, clamping at zero."""
        self.db.execute(
            update(ExportJob)
            .where(ExportJob.id == job_id)
            .values(
                copied_bytes=case(
                    (ExportJob.copied_bytes > size_bytes, ExportJob.copied_bytes - size_bytes),
                    else_=0,
                )
            )
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class DriveAssignmentRepository:
    """Data-access layer for :class:`~app.models.jobs.DriveAssignment`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, assignment: DriveAssignment) -> DriveAssignment:
        """Persist a new drive assignment and flush it."""
        self.db.add(assignment)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(assignment)
        return assignment

    def get_active_for_job(self, job_id: int) -> Optional[DriveAssignment]:
        """Return the most recent unreleased assignment for *job_id*, or ``None``."""
        return (
            self.db.query(DriveAssignment)
            .filter(
                DriveAssignment.job_id == job_id,
                DriveAssignment.released_at.is_(None),
            )
            .order_by(DriveAssignment.assigned_at.desc(), DriveAssignment.id.desc())
            .first()
        )

    def bulk_get_active_for_jobs(
        self, job_ids: List[int]
    ) -> Dict[int, DriveAssignment]:
        """Return ``{job_id: DriveAssignment}`` for unreleased assignments.

        When a job has multiple unreleased rows (rare), the most recent is
        kept — matching the single-job ``get_active_for_job`` semantics.
        """
        if not job_ids:
            return {}
        rows = (
            self.db.query(DriveAssignment)
            .options(joinedload(DriveAssignment.drive))
            .filter(
                DriveAssignment.job_id.in_(job_ids),
                DriveAssignment.released_at.is_(None),
            )
            .order_by(
                DriveAssignment.job_id,
                DriveAssignment.assigned_at.desc(),
                DriveAssignment.id.desc(),
            )
            .all()
        )
        result: Dict[int, DriveAssignment] = {}
        for assignment in rows:
            # First seen per job_id wins (most recent due to ORDER BY)
            if assignment.job_id not in result:
                result[assignment.job_id] = assignment
        return result


class ManifestRepository:
    """Data-access layer for :class:`~app.models.jobs.Manifest`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, manifest: Manifest) -> Manifest:
        """Persist a new manifest record and flush it."""
        self.db.add(manifest)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(manifest)
        return manifest
