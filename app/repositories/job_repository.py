from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, case, func, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload

from app.exceptions import ConflictError
from app.models.hardware import UsbDrive
from app.models.jobs import (
    DriveAssignment,
    ExportFile,
    ExportJob,
    FileStatus,
    JobStatus,
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

    def list_recent(
        self,
        limit: int = 200,
        *,
        offset: int = 0,
        drive_id: Optional[int] = None,
        statuses: Optional[Iterable[JobStatus]] = None,
        include_archived: bool = False,
    ) -> List[ExportJob]:
        """Return recent jobs ordered by creation time descending.

        Optional filters can scope the result to jobs currently assigned to a
        specific drive and/or to specific job statuses.
        """
        query = self.db.query(ExportJob)

        if drive_id is not None:
            query = query.filter(
                ExportJob.assignments.any(
                    and_(
                        DriveAssignment.drive_id == drive_id,
                        DriveAssignment.released_at.is_(None),
                    )
                )
            )

        effective_statuses = tuple(statuses) if statuses else None
        if effective_statuses and not include_archived:
            effective_statuses = tuple(
                status for status in effective_statuses if status != JobStatus.ARCHIVED
            )
            if not effective_statuses:
                return []

        if effective_statuses:
            query = query.filter(ExportJob.status.in_(effective_statuses))
        elif not include_archived:
            query = query.filter(ExportJob.status != JobStatus.ARCHIVED)

        return (
            query
            .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def list_assigned_jobs_for_drive(
        self,
        drive_id: int,
        *,
        statuses: tuple[JobStatus, ...],
    ) -> List[ExportJob]:
        """Return jobs currently assigned to *drive_id* with unreleased assignments."""
        return (
            self.db.query(ExportJob)
            .filter(
                ExportJob.assignments.any(
                    and_(
                        DriveAssignment.drive_id == drive_id,
                        DriveAssignment.released_at.is_(None),
                    )
                ),
                ExportJob.status.in_(statuses),
            )
            .order_by(ExportJob.created_at.desc(), ExportJob.id.desc())
            .all()
        )


class FileRepository:
    """Data-access layer for :class:`~app.models.jobs.ExportFile`."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, file_id: int) -> Optional[ExportFile]:
        """Return a single export file by primary key, or ``None``."""
        return self.db.get(ExportFile, file_id)

    def list_by_job(
        self,
        job_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> List[ExportFile]:
        """Return files belonging to *job_id*, optionally paged by *offset* and *limit*."""
        query = (
            self.db.query(ExportFile)
            .filter(ExportFile.job_id == job_id)
            .order_by(ExportFile.id)
        )
        if offset:
            query = query.offset(offset)
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

        This includes files in ``PENDING``, ``COPYING``, ``RETRYING``,
        ``ERROR``, and ``TIMEOUT`` states — everything except ``DONE``.
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

    def count_done_errors_and_timeouts(self, job_id: int) -> Tuple[int, int, int]:
        """Return ``(done_count, error_count, timeout_count)`` for *job_id* in one query."""
        row = (
            self.db.query(
                func.count(case((ExportFile.status == FileStatus.DONE, 1))),
                func.count(case((ExportFile.status == FileStatus.ERROR, 1))),
                func.count(case((ExportFile.status == FileStatus.TIMEOUT, 1))),
            )
            .filter(ExportFile.job_id == job_id)
            .one()
        )
        return row[0], row[1], row[2]

    def count_done_and_errors(self, job_id: int) -> Tuple[int, int]:
        """Return ``(done_count, error_count)`` for *job_id* in a single query."""
        done, errors, _timeouts = self.count_done_errors_and_timeouts(job_id)
        return done, errors

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

    def reset_failed_for_retry(self, job_id: int) -> int:
        """Reset retry-eligible failed files to ``PENDING`` for *job_id*."""
        updated = (
            self.db.query(ExportFile)
            .filter(
                ExportFile.job_id == job_id,
                ExportFile.status.in_((FileStatus.ERROR, FileStatus.TIMEOUT)),
            )
            .update(
                {
                    ExportFile.status: FileStatus.PENDING,
                    ExportFile.retry_attempts: 0,
                    ExportFile.error_message: None,
                },
                synchronize_session=False,
            )
        )
        return int(updated or 0)

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

    def bulk_count_done_errors_and_timeouts(
        self, job_ids: List[int]
    ) -> Dict[int, Tuple[int, int, int]]:
        """Return ``{job_id: (done_count, error_count, timeout_count)}`` in one query."""
        if not job_ids:
            return {}
        rows = (
            self.db.query(
                ExportFile.job_id,
                func.count(case((ExportFile.status == FileStatus.DONE, 1))),
                func.count(case((ExportFile.status == FileStatus.ERROR, 1))),
                func.count(case((ExportFile.status == FileStatus.TIMEOUT, 1))),
            )
            .filter(ExportFile.job_id.in_(job_ids))
            .group_by(ExportFile.job_id)
            .all()
        )
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    def bulk_count_done_and_errors(
        self, job_ids: List[int]
    ) -> Dict[int, Tuple[int, int]]:
        """Return ``{job_id: (done_count, error_count)}`` for all *job_ids* in one query."""
        result = self.bulk_count_done_errors_and_timeouts(job_ids)
        return {job_id: (done, errors) for job_id, (done, errors, _timeouts) in result.items()}

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

    def increment_assignment_bytes(self, assignment_id: int, size_bytes: int) -> None:
        """Atomically increment copied bytes for the active drive assignment."""
        self.db.execute(
            update(DriveAssignment)
            .where(DriveAssignment.id == assignment_id)
            .values(copied_bytes=DriveAssignment.copied_bytes + size_bytes)
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def decrement_assignment_bytes(self, assignment_id: int, size_bytes: int) -> None:
        """Atomically subtract copied bytes from the assignment, clamping at zero."""
        self.db.execute(
            update(DriveAssignment)
            .where(DriveAssignment.id == assignment_id)
            .values(
                copied_bytes=case(
                    (DriveAssignment.copied_bytes > size_bytes, DriveAssignment.copied_bytes - size_bytes),
                    else_=0,
                )
            )
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def increment_assignment_file_count(self, assignment_id: int) -> None:
        """Atomically increment completed-file count for the active assignment."""
        self.db.execute(
            update(DriveAssignment)
            .where(DriveAssignment.id == assignment_id)
            .values(file_count=DriveAssignment.file_count + 1)
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
            .options(joinedload(DriveAssignment.drive).joinedload(UsbDrive.port))
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
            .options(joinedload(DriveAssignment.drive).joinedload(UsbDrive.port))
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

    def list_active_jobs_for_drive(
        self,
        drive_id: int,
        *,
        statuses: tuple[JobStatus, ...],
    ) -> List[ExportJob]:
        """Return active jobs assigned to *drive_id* with unreleased assignments."""
        return JobRepository(self.db).list_assigned_jobs_for_drive(drive_id, statuses=statuses)


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

    def get_latest_for_job(self, job_id: int) -> Optional[Manifest]:
        """Return the newest manifest recorded for *job_id*, or ``None``."""
        return (
            self.db.query(Manifest)
            .filter(Manifest.job_id == job_id)
            .order_by(Manifest.id.desc())
            .first()
        )
