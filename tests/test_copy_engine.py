"""Tests for retry/resume semantics in the copy engine."""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.audit import AuditLog
from app.models.jobs import ExportFile, ExportJob, FileStatus, JobStatus
from app.services import copy_engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    db,
    source_path: str,
    max_file_retries: int = 0,
    retry_delay_seconds: int = 0,
    target_mount_path: str | None = None,
) -> ExportJob:
    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path=source_path,
        target_mount_path=target_mount_path,
        thread_count=1,
        max_file_retries=max_file_retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _session_factory(db):
    """Return a non-closing wrapper around *db* for use as SessionLocal mock."""

    class _NonClosing:
        """Proxy that delegates everything to *db* but ignores ``close()``."""

        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass  # keep the test session alive

    return lambda: _NonClosing()


# ---------------------------------------------------------------------------
# copy_file / retry unit tests
# ---------------------------------------------------------------------------


def test_copy_file_success(tmp_path):
    """copy_file copies the file and returns a valid checksum."""
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_bytes(b"hello world")

    success, checksum, err = copy_engine.copy_file(src, dst)

    assert success is True
    assert checksum is not None and len(checksum) == 64  # sha256 hex
    assert err is None
    assert dst.read_bytes() == b"hello world"


def test_copy_file_failure(tmp_path):
    """copy_file returns failure when source is missing."""
    src = tmp_path / "nonexistent.txt"
    dst = tmp_path / "dst.txt"

    success, checksum, err = copy_engine.copy_file(src, dst)

    assert success is False
    assert checksum is None
    assert err is not None


# ---------------------------------------------------------------------------
# _process_file retry tests
# ---------------------------------------------------------------------------


def test_process_file_succeeds_after_transient_failure(db, tmp_path):
    """_process_file retries on failure and marks the file DONE on success."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    test_file = source_dir / "data.txt"
    test_file.write_bytes(b"evidence data")

    job = _make_job(db, str(source_dir), max_file_retries=2, retry_delay_seconds=0)

    ef = ExportFile(
        job_id=job.id,
        relative_path="data.txt",
        size_bytes=len(b"evidence data"),
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    attempt_count = 0
    original_copy_file = copy_engine.copy_file

    def _flaky_copy(src, dst, checksum_algorithm="sha256"):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            return False, None, "transient I/O error"
        return original_copy_file(src, dst, checksum_algorithm)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.copy_file", side_effect=_flaky_copy):
            copy_engine._process_file(ef.id, test_file, target_dir, max_retries=2, retry_delay=0)

    db.expire_all()
    db.refresh(ef)

    assert ef.status == FileStatus.DONE
    assert ef.retry_attempts == 2
    assert ef.checksum is not None


def test_process_file_exhausts_retries_marks_error(db, tmp_path):
    """_process_file marks the file ERROR when all retries are exhausted."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    test_file = source_dir / "fail.txt"
    test_file.write_bytes(b"data")

    job = _make_job(db, str(source_dir), max_file_retries=2, retry_delay_seconds=0)

    ef = ExportFile(
        job_id=job.id,
        relative_path="fail.txt",
        size_bytes=4,
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.copy_file",
            return_value=(False, None, "persistent I/O error"),
        ):
            copy_engine._process_file(ef.id, test_file, tmp_path / "target", max_retries=2, retry_delay=0)

    db.expire_all()
    db.refresh(ef)

    assert ef.status == FileStatus.ERROR
    assert ef.error_message == "persistent I/O error"


def test_process_file_no_retries_on_first_success(db, tmp_path):
    """_process_file does not retry when the first attempt succeeds."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    test_file = source_dir / "ok.txt"
    test_file.write_bytes(b"ok")

    job = _make_job(db, str(source_dir), max_file_retries=3, retry_delay_seconds=0)

    ef = ExportFile(
        job_id=job.id,
        relative_path="ok.txt",
        size_bytes=2,
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine._process_file(ef.id, test_file, target_dir, max_retries=3, retry_delay=0)

    db.expire_all()
    db.refresh(ef)

    assert ef.status == FileStatus.DONE
    assert ef.retry_attempts == 0  # no retries needed


def test_process_file_retry_audit_entries_created(db, tmp_path):
    """FILE_COPY_RETRY audit entries are written for each retry attempt."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    test_file = source_dir / "audit.txt"
    test_file.write_bytes(b"audit data")

    job = _make_job(db, str(source_dir), max_file_retries=2, retry_delay_seconds=0)

    ef = ExportFile(
        job_id=job.id,
        relative_path="audit.txt",
        size_bytes=10,
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    original_copy_file = copy_engine.copy_file
    call_count = 0

    def _fail_twice(src, dst, checksum_algorithm="sha256"):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return False, None, "fail"
        return original_copy_file(src, dst, checksum_algorithm)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.copy_file", side_effect=_fail_twice):
            copy_engine._process_file(ef.id, test_file, target_dir, max_retries=2, retry_delay=0)

    retry_entries = (
        db.query(AuditLog).filter(AuditLog.action == "FILE_COPY_RETRY").all()
    )
    assert len(retry_entries) == 2
    attempts = sorted(e.details["attempt"] for e in retry_entries)
    assert attempts == [1, 2]


# ---------------------------------------------------------------------------
# run_copy_job integration tests
# ---------------------------------------------------------------------------


def test_run_copy_job_fresh_run(db, tmp_path):
    """run_copy_job completes successfully on a fresh job."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file_a.txt").write_bytes(b"aaa")
    (source_dir / "file_b.txt").write_bytes(b"bbb")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert job.file_count == 2
    files = db.query(ExportFile).filter(ExportFile.job_id == job.id).all()
    assert all(f.status == FileStatus.DONE for f in files)


def test_run_copy_job_resume_skips_done_files(db, tmp_path):
    """On resume, DONE files are preserved and not re-processed."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "done.txt").write_bytes(b"already done")
    (source_dir / "failed.txt").write_bytes(b"failed previously")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(
        db,
        str(source_dir),
        max_file_retries=0,
        retry_delay_seconds=0,
        target_mount_path=str(target_dir),
    )

    # Pre-populate as if a previous run completed partially.
    done_ef = ExportFile(
        job_id=job.id,
        relative_path="done.txt",
        size_bytes=12,
        checksum="a" * 64,
        status=FileStatus.DONE,
        retry_attempts=0,
    )
    error_ef = ExportFile(
        job_id=job.id,
        relative_path="failed.txt",
        size_bytes=15,
        status=FileStatus.ERROR,
        error_message="previous error",
        retry_attempts=0,
    )
    db.add_all([done_ef, error_ef])
    db.commit()
    db.refresh(done_ef)
    db.refresh(error_ef)

    # Copy the already-done file to the target so checksum can be verified.
    (target_dir / "done.txt").write_bytes(b"already done")

    copy_call_paths: list[str] = []
    original_copy_file = copy_engine.copy_file

    def _tracking_copy(src, dst, checksum_algorithm="sha256"):
        copy_call_paths.append(str(src))
        return original_copy_file(src, dst, checksum_algorithm)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.copy_file", side_effect=_tracking_copy):
            copy_engine.run_copy_job(job.id)

    # Only the previously-failed file should have been re-copied.
    assert all("failed.txt" in p for p in copy_call_paths), (
        f"Expected only 'failed.txt' to be copied; got: {copy_call_paths}"
    )

    db.expire_all()
    db.refresh(done_ef)
    db.refresh(error_ef)

    assert done_ef.status == FileStatus.DONE
    assert done_ef.checksum == "a" * 64  # unchanged
    assert error_ef.status == FileStatus.DONE  # successfully re-processed


def test_run_copy_job_resume_adds_new_source_files(db, tmp_path):
    """On resume, source files not yet tracked receive fresh PENDING records."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "existing.txt").write_bytes(b"existing")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    # Pre-populate only 'existing.txt' as DONE.
    existing_ef = ExportFile(
        job_id=job.id,
        relative_path="existing.txt",
        size_bytes=8,
        checksum="b" * 64,
        status=FileStatus.DONE,
        retry_attempts=0,
    )
    db.add(existing_ef)
    db.commit()

    # Add a new source file that was not part of the original run.
    (source_dir / "new_file.txt").write_bytes(b"new data")
    (target_dir / "existing.txt").write_bytes(b"existing")

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert job.file_count == 2

    files = {f.relative_path: f for f in db.query(ExportFile).filter(ExportFile.job_id == job.id).all()}
    assert files["existing.txt"].status == FileStatus.DONE
    assert files["new_file.txt"].status == FileStatus.DONE


def test_run_copy_job_failed_job_is_failed_status(db, tmp_path):
    """run_copy_job marks the job FAILED when any file errors out."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "bad.txt").write_bytes(b"data")

    job = _make_job(db, str(source_dir), max_file_retries=0)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.copy_file",
            return_value=(False, None, "disk full"),
        ):
            with patch(
                "app.services.copy_engine._checksum_only",
                return_value=(False, None, "disk full"),
            ):
                copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.FAILED


def test_run_copy_job_copied_bytes_excludes_previously_done_on_resume(db, tmp_path):
    """copied_bytes is correctly seeded from pre-existing DONE files on resume."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "done.txt").write_bytes(b"x" * 100)
    (source_dir / "pending.txt").write_bytes(b"y" * 200)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    # Seed done_ef as DONE with size_bytes so copied_bytes is pre-seeded correctly.
    done_ef = ExportFile(
        job_id=job.id,
        relative_path="done.txt",
        size_bytes=100,
        checksum="c" * 64,
        status=FileStatus.DONE,
        retry_attempts=0,
    )
    db.add(done_ef)
    db.commit()

    (target_dir / "done.txt").write_bytes(b"x" * 100)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    # Total copied bytes should be 100 (done.txt) + 200 (pending.txt)
    assert job.copied_bytes == 300
    assert job.status == JobStatus.COMPLETED


def test_run_copy_job_with_retry_recovers_on_resume(db, tmp_path):
    """Full flow: first run fails some files; resume with retries recovers them."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"content")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    # First run: max_file_retries=0 so the file fails immediately.
    job = _make_job(
        db,
        str(source_dir),
        max_file_retries=0,
        retry_delay_seconds=0,
        target_mount_path=str(target_dir),
    )

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.copy_file",
            return_value=(False, None, "first-run error"),
        ):
            copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)
    assert job.status == JobStatus.FAILED

    # Simulate the operator increasing retries and restarting.
    job.max_file_retries = 1
    job.status = JobStatus.PENDING
    db.commit()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)
    assert job.status == JobStatus.COMPLETED

    files = db.query(ExportFile).filter(ExportFile.job_id == job.id).all()
    assert len(files) == 1
    assert files[0].status == FileStatus.DONE


# ---------------------------------------------------------------------------
# list_incomplete_by_job repository tests
# ---------------------------------------------------------------------------


def test_list_incomplete_by_job(db):
    """list_incomplete_by_job returns all non-DONE files."""
    from app.repositories.job_repository import FileRepository

    job = ExportJob(project_id="P", evidence_number="E", source_path="/src")
    db.add(job)
    db.commit()
    db.refresh(job)

    statuses = [FileStatus.PENDING, FileStatus.COPYING, FileStatus.RETRYING, FileStatus.ERROR, FileStatus.DONE]
    for i, st in enumerate(statuses):
        db.add(ExportFile(job_id=job.id, relative_path=f"file{i}.txt", status=st))
    db.commit()

    incomplete = FileRepository(db).list_incomplete_by_job(job.id)
    assert len(incomplete) == 4  # all except DONE
    result_statuses = {f.status for f in incomplete}
    assert FileStatus.DONE not in result_statuses
