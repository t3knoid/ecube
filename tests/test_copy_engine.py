"""Tests for retry/resume semantics in the copy engine."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus, StartupAnalysisStatus
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


def _assign_drive(db, job: ExportJob) -> DriveAssignment:
    drive = UsbDrive(device_identifier=f"USB-COPY-{job.id}", current_state=DriveState.IN_USE)
    db.add(drive)
    db.commit()
    db.refresh(drive)

    assignment = DriveAssignment(drive_id=drive.id, job_id=job.id)
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


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


def test_copy_file_reports_chunk_progress(tmp_path):
    """copy_file reports incremental byte progress as chunks are written."""
    src = tmp_path / "chunked.bin"
    dst = tmp_path / "chunked-copy.bin"
    src.write_bytes(b"abcdefghij")

    seen = []

    with patch.object(copy_engine.settings, "copy_chunk_size_bytes", 4):
        success, checksum, err = copy_engine.copy_file(
            src,
            dst,
            progress_callback=seen.append,
        )

    assert success is True
    assert checksum is not None
    assert err is None
    assert seen == [4, 4, 2]


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

    def _flaky_copy(
        src,
        dst,
        checksum_algorithm="sha256",
        progress_callback=None,
        timeout_seconds=0,
    ):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            return False, None, "transient I/O error"
        return original_copy_file(
            src,
            dst,
            checksum_algorithm,
            progress_callback=progress_callback,
            timeout_seconds=timeout_seconds,
        )

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
    assert ef.error_message == "I/O failure"


def test_process_file_persists_safe_failure_message_and_audit_details(db, tmp_path):
    """_process_file stores safe failure details for UI and audit consumers."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    test_file = source_dir / "fail.txt"
    test_file.write_bytes(b"data")

    job = _make_job(db, str(source_dir), max_file_retries=0, retry_delay_seconds=0)

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

    raw_error = "Permission denied: /mnt/ecube/private/fail.txt"

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.copy_file",
            return_value=(False, None, raw_error),
        ):
            copy_engine._process_file(ef.id, test_file, tmp_path / "target", max_retries=0, retry_delay=0)

    db.expire_all()
    db.refresh(ef)

    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "FILE_COPY_FAILURE", AuditLog.job_id == job.id)
        .order_by(AuditLog.id.desc())
        .first()
    )

    assert ef.status == FileStatus.ERROR
    assert ef.error_message == "Permission or authentication failure"
    assert audit is not None
    assert audit.details["error_code"] == "permission_failure"
    assert audit.details["error_detail"] == "Permission or authentication failure"
    assert "/mnt/ecube/private" not in json.dumps(audit.details)


def test_process_file_persists_safe_timeout_message(db, tmp_path):
    """_process_file stores a sanitized timeout message for retryable TIMEOUT rows."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    test_file = source_dir / "slow.txt"
    test_file.write_bytes(b"data")

    job = _make_job(db, str(source_dir), max_file_retries=0, retry_delay_seconds=0)

    ef = ExportFile(
        job_id=job.id,
        relative_path="slow.txt",
        size_bytes=4,
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    raw_error = TimeoutError("File copy timed out after 1s while writing /mnt/ecube/private/slow.txt")

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.copy_file",
            side_effect=raw_error,
        ):
            copy_engine._process_file(ef.id, test_file, tmp_path / "target", max_retries=0, retry_delay=0)

    db.expire_all()
    db.refresh(ef)

    assert ef.status == FileStatus.TIMEOUT
    assert ef.error_message == "Operation timed out"
    assert "/mnt/ecube/private" not in (ef.error_message or "")


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


def test_process_file_updates_copied_bytes_for_completed_copy(db, tmp_path):
    """_process_file should advance the parent job byte counter when a file is copied."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    payload = b"abcdefghij"
    test_file = source_dir / "progress.txt"
    test_file.write_bytes(payload)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), max_file_retries=0, retry_delay_seconds=0, target_mount_path=str(target_dir))
    assignment = _assign_drive(db, job)

    ef = ExportFile(
        job_id=job.id,
        relative_path="progress.txt",
        size_bytes=len(payload),
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine._process_file(ef.id, test_file, target_dir, max_retries=0, retry_delay=0)

    db.expire_all()
    refreshed_job = db.get(ExportJob, job.id)
    refreshed_assignment = db.get(DriveAssignment, assignment.id)
    assert refreshed_job.copied_bytes == len(payload)
    assert refreshed_assignment is not None
    assert refreshed_assignment.copied_bytes == len(payload)
    assert refreshed_assignment.file_count == 1


def test_process_file_batches_copied_bytes_updates(db, tmp_path):
    """_process_file should batch copied_bytes updates instead of committing once per chunk."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    payload = b"abcdefghijkl"
    test_file = source_dir / "batched-progress.txt"
    test_file.write_bytes(payload)

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), max_file_retries=0, retry_delay_seconds=0, target_mount_path=str(target_dir))

    ef = ExportFile(
        job_id=job.id,
        relative_path="batched-progress.txt",
        size_bytes=len(payload),
        status=FileStatus.PENDING,
        retry_attempts=0,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    progress_updates: list[int] = []
    original_increment = copy_engine.FileRepository.increment_job_bytes

    def _record_increment(self, job_id, size_bytes):
        progress_updates.append(size_bytes)
        return original_increment(self, job_id, size_bytes)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch.object(copy_engine.settings, "copy_chunk_size_bytes", 4), patch.object(
            copy_engine.settings,
            "copy_progress_flush_bytes",
            8,
        ), patch.object(copy_engine.FileRepository, "increment_job_bytes", autospec=True, side_effect=_record_increment):
            copy_engine._process_file(ef.id, test_file, target_dir, max_retries=0, retry_delay=0)

    db.expire_all()
    refreshed_job = db.get(ExportJob, job.id)
    assert refreshed_job.copied_bytes == len(payload)
    assert progress_updates == [8, 4]


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

    def _fail_twice(
        src,
        dst,
        checksum_algorithm="sha256",
        progress_callback=None,
        timeout_seconds=0,
    ):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return False, None, "fail"
        return original_copy_file(
            src,
            dst,
            checksum_algorithm,
            progress_callback=progress_callback,
            timeout_seconds=timeout_seconds,
        )

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

    def _tracking_copy(
        src,
        dst,
        checksum_algorithm="sha256",
        progress_callback=None,
        timeout_seconds=0,
    ):
        copy_call_paths.append(str(src))
        return original_copy_file(
            src,
            dst,
            checksum_algorithm,
            progress_callback=progress_callback,
            timeout_seconds=timeout_seconds,
        )

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


def test_stale_paused_run_does_not_override_resumed_job(db, tmp_path):
    """An older paused worker must not reset a newer resumed run back to PAUSED."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "resume.txt").write_bytes(b"resume data")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    original_started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    resumed_started_at = original_started_at + timedelta(seconds=30)
    job.status = JobStatus.RUNNING
    job.started_at = original_started_at
    db.commit()

    class _FakeFuture:
        def result(self):
            return None

        def done(self):
            return False

        def cancel(self):
            return None

    class _FakeExecutor:
        def __init__(self, *args, **kwargs):
            self.futures = []

        def submit(self, fn, *args, **kwargs):
            future = _FakeFuture()
            self.futures.append(future)
            return future

        def shutdown(self, wait=True, cancel_futures=True):
            resumed_job = db.get(ExportJob, job.id)
            resumed_job.status = JobStatus.RUNNING
            resumed_job.started_at = resumed_started_at
            resumed_job.completed_at = None
            db.commit()

    def _fake_as_completed(futures):
        paused_job = db.get(ExportJob, job.id)
        paused_job.status = JobStatus.PAUSED
        db.commit()
        for future in list(futures):
            yield future

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.ThreadPoolExecutor", _FakeExecutor):
            with patch("app.services.copy_engine.as_completed", side_effect=_fake_as_completed):
                copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.RUNNING
    assert job.started_at == resumed_started_at.replace(tzinfo=None)


def test_run_copy_job_with_file_errors_still_completes(db, tmp_path):
    """run_copy_job completes when files fail but all file outcomes are recorded."""
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

    assert job.status == JobStatus.COMPLETED


def test_run_copy_job_marks_job_failed_when_source_scan_disappears(db, tmp_path):
    """run_copy_job fails gracefully when the source path vanishes during scan."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "volatile.txt").write_bytes(b"data")

    job = _make_job(db, str(source_dir), max_file_retries=0)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.scan_source_files",
            side_effect=FileNotFoundError("/proc/12345 disappeared"),
        ):
            copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.FAILED
    assert job.completed_at is not None


def test_run_copy_job_marks_job_failed_when_source_scan_permission_denied(db, tmp_path):
    """run_copy_job fails when the source path cannot be read during scan."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    job = _make_job(db, str(source_dir), max_file_retries=0)

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.scan_source_files",
            side_effect=PermissionError(f"[Errno 13] Permission denied: '{source_dir}'"),
        ):
            copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.FAILED
    assert job.completed_at is not None
    assert job.failure_reason is not None
    assert job.failure_reason == "Permission or authentication failure"


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
    """A later rerun can recover files even after an earlier partial completion."""
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
    assert job.status == JobStatus.COMPLETED

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


def test_run_copy_job_reuses_cached_startup_analysis_without_rescan(db, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"content")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    job.startup_analysis_file_count = 1
    job.startup_analysis_total_bytes = len(b"content")
    job.startup_analysis_entries = [
        {"relative_path": "file.txt", "size_bytes": len(b"content")},
        {"entry_type": "directory", "relative_path": "", "mtime_ns": source_dir.stat().st_mtime_ns},
    ]
    db.commit()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.scan_source_files") as scan_source_files:
            with patch("app.services.copy_engine._persist_startup_analysis_cache", wraps=copy_engine._persist_startup_analysis_cache) as persist_cache:
                copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert scan_source_files.call_count == 0
    assert persist_cache.call_count == 0

    reuse_audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_STARTUP_ANALYSIS_REUSED", AuditLog.job_id == job.id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert reuse_audit is not None


def test_build_startup_analysis_sample_plan_spans_file_sizes(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()

    small = source_dir / "small.bin"
    medium = source_dir / "medium.bin"
    large = source_dir / "large.bin"
    extra_large = source_dir / "extra-large.bin"
    small.write_bytes(b"a" * 128)
    medium.write_bytes(b"b" * 512)
    large.write_bytes(b"c" * 2048)
    extra_large.write_bytes(b"d" * 4096)

    sample_plan = copy_engine._build_startup_analysis_sample_plan(
        [small, medium, large, extra_large],
        2304,
    )

    sampled_names = [path.name for path, _sample_size in sample_plan]
    assert "small.bin" in sampled_names
    assert "large.bin" in sampled_names or "extra-large.bin" in sampled_names
    assert sum(sample_size for _path, sample_size in sample_plan) == 2304


def test_estimate_startup_analysis_duration_accounts_for_per_file_overhead():
    estimated_seconds = copy_engine._estimate_startup_analysis_duration_seconds(
        total_bytes=24 * 1024 * 1024,
        effective_copy_rate_mbps=12.0,
        per_file_overhead_seconds=0.5,
        file_count=4,
    )

    assert estimated_seconds == 4


def test_measure_startup_analysis_transfer_rates_reports_speeds_and_estimated_duration(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_files = []
    for name, size in (("small.bin", 128), ("medium.bin", 512), ("large.bin", 4096)):
        file_path = source_dir / name
        file_path.write_bytes(b"a" * size)
        source_files.append(file_path)

    target_dir = tmp_path / "target"
    target_dir.mkdir()
    job = SimpleNamespace(id=9, target_mount_path=str(target_dir))

    with patch.object(copy_engine.settings, "startup_analysis_benchmark_bytes", 1024):
        with patch.object(copy_engine.settings, "copy_chunk_size_bytes", 256):
            details = copy_engine._measure_startup_analysis_transfer_rates(job, source_files, 4736)

    assert details["benchmark_bytes"] == 1024
    assert details["share_read_mbps"] is not None
    assert details["share_read_mbps"] > 0
    assert details["drive_write_mbps"] is not None
    assert details["drive_write_mbps"] > 0
    assert details["estimated_duration_seconds"] is not None
    assert details["estimated_duration_seconds"] >= 1
    assert list(target_dir.glob(".startup-analysis-benchmark-*")) == []


def test_prepare_job_startup_analysis_persists_ready_state_and_file_rows(db, tmp_path, caplog):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.txt").write_bytes(b"alpha")
    (source_dir / "b.txt").write_bytes(b"bravo")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    job.status = JobStatus.PAUSED
    db.commit()

    benchmark_result = {
        "share_read_mbps": 120.5,
        "drive_write_mbps": 96.25,
        "estimated_duration_seconds": 1,
        "benchmark_bytes": 10,
    }

    with patch("app.services.copy_engine._measure_startup_analysis_transfer_rates", return_value=benchmark_result) as measure_benchmark:
        with caplog.at_level(logging.INFO):
            copy_engine.prepare_job_startup_analysis(job.id, actor="analyst", manual=True)

    db.expire_all()
    db.refresh(job)
    file_rows = db.query(ExportFile).filter(ExportFile.job_id == job.id).order_by(ExportFile.relative_path).all()
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_STARTUP_ANALYSIS_COMPLETED", AuditLog.job_id == job.id)
        .order_by(AuditLog.id.desc())
        .first()
    )

    assert job.status == JobStatus.PAUSED
    assert job.startup_analysis_status == StartupAnalysisStatus.READY
    assert job.startup_analysis_last_analyzed_at is not None
    assert job.startup_analysis_failure_reason is None
    assert job.startup_analysis_cached is True
    assert job.startup_analysis_share_read_mbps == benchmark_result["share_read_mbps"]
    assert job.startup_analysis_drive_write_mbps == benchmark_result["drive_write_mbps"]
    assert job.startup_analysis_estimated_duration_seconds == benchmark_result["estimated_duration_seconds"]
    assert job.file_count == 2
    assert job.total_bytes == len(b"alpha") + len(b"bravo")
    assert job.copied_bytes == 0
    assert [row.relative_path for row in file_rows] == ["a.txt", "b.txt"]
    assert all(row.status == FileStatus.PENDING for row in file_rows)
    assert audit is not None
    assert audit.details["ready_to_start"] is True
    assert audit.details["share_read_mbps"] == benchmark_result["share_read_mbps"]
    assert audit.details["drive_write_mbps"] == benchmark_result["drive_write_mbps"]
    assert audit.details["estimated_duration_seconds"] == benchmark_result["estimated_duration_seconds"]
    assert audit.details["benchmark_bytes"] == benchmark_result["benchmark_bytes"]
    measure_benchmark.assert_called_once()

    messages = [record.getMessage() for record in caplog.records]
    completed_messages = [message for message in messages if f"JOB_STARTUP_ANALYSIS_COMPLETED job_id={job.id}" in message]

    assert completed_messages
    assert any("project_id=PROJ-001" in message for message in completed_messages)
    assert any("status=READY" in message for message in completed_messages)
    assert any("file_count=2" in message for message in completed_messages)
    assert any("share_read_mbps=120.5" in message for message in completed_messages)
    assert any("drive_write_mbps=96.25" in message for message in completed_messages)
    assert any("estimated_duration_seconds=1" in message for message in completed_messages)
    assert all("source_path=" not in message for message in completed_messages)
    assert all("target_mount_path=" not in message for message in completed_messages)


def test_prepare_job_startup_analysis_uses_specific_failure_fallback_for_unknown_errors(db, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.scan_source_files", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                copy_engine.prepare_job_startup_analysis(job.id, actor="analyst", manual=True)

    db.expire_all()
    db.refresh(job)

    assert job.startup_analysis_status == StartupAnalysisStatus.FAILED
    assert job.startup_analysis_failure_reason == "Unable to prepare startup analysis"


def test_run_startup_analysis_logs_sanitized_failure_at_info_level(db, tmp_path, caplog):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.scan_source_files", side_effect=RuntimeError("boom /secret/path")):
            with caplog.at_level(logging.INFO):
                copy_engine.run_startup_analysis(job.id, actor="analyst")

    info_records = [record for record in caplog.records if record.levelno == logging.INFO]
    debug_records = [record for record in caplog.records if record.levelno == logging.DEBUG]

    assert any(record.getMessage() == "Unexpected startup analysis failure" for record in info_records)
    assert any(getattr(record, "reason", None) == "Startup analysis failed" for record in info_records)
    assert all("boom /secret/path" not in record.getMessage() for record in info_records)
    assert all("/secret/path" not in record.getMessage() for record in info_records)
    assert debug_records == []


def test_prepare_job_startup_analysis_completion_audit_failure_logs_sanitized_reason(db, tmp_path, caplog):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "a.txt").write_bytes(b"alpha")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    benchmark_result = {
        "share_read_mbps": 120.5,
        "drive_write_mbps": 96.25,
        "estimated_duration_seconds": 1,
        "benchmark_bytes": 5,
    }

    with patch("app.services.copy_engine._measure_startup_analysis_transfer_rates", return_value=benchmark_result):
        with patch("app.services.copy_engine.AuditRepository.add", side_effect=RuntimeError("boom /secret/path")):
            with caplog.at_level(logging.INFO):
                copy_engine.prepare_job_startup_analysis(job.id, actor="analyst", manual=True)

    info_records = [record for record in caplog.records if record.levelno == logging.INFO]
    debug_records = [record for record in caplog.records if record.levelno == logging.DEBUG]

    assert any(record.getMessage() == "Failed to write audit log for JOB_STARTUP_ANALYSIS_COMPLETED" for record in info_records)
    assert any(getattr(record, "reason", None) == "Audit log write failed after startup analysis completion" for record in info_records)
    assert all("boom /secret/path" not in record.getMessage() for record in info_records)
    assert all("/secret/path" not in record.getMessage() for record in info_records)
    assert debug_records == []


def test_run_copy_job_refreshes_stale_startup_analysis_cache_on_completed_run_with_file_errors(db, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"content")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), max_file_retries=0, target_mount_path=str(target_dir))
    job.startup_analysis_file_count = 1
    job.startup_analysis_total_bytes = len(b"content")
    initial_directory_mtime = source_dir.stat().st_mtime_ns
    job.startup_analysis_entries = [
        {"relative_path": "file.txt", "size_bytes": len(b"content")},
        {"entry_type": "directory", "relative_path": "", "mtime_ns": initial_directory_mtime},
    ]
    db.commit()

    (source_dir / "extra.txt").write_bytes(b"more")

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.scan_source_files",
            return_value=[source_dir / "file.txt", source_dir / "extra.txt"],
        ):
            with patch("app.services.copy_engine.copy_file", return_value=(False, None, "disk full")):
                with patch("app.services.copy_engine._checksum_only", return_value=(False, None, "disk full")):
                    copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert job.startup_analysis_cached is True
    assert job.startup_analysis_file_count == 2
    assert job.startup_analysis_total_bytes == len(b"content") + len(b"more")
    file_entries = sorted(
        [entry for entry in job.startup_analysis_entries if entry.get("entry_type", "file") == "file"],
        key=lambda entry: entry["relative_path"],
    )
    directory_entries = [entry for entry in job.startup_analysis_entries if entry.get("entry_type") == "directory"]

    assert file_entries == [
        {"relative_path": "extra.txt", "size_bytes": len(b"more")},
        {"relative_path": "file.txt", "size_bytes": len(b"content")},
    ]
    assert directory_entries == [
        {"entry_type": "directory", "relative_path": "", "mtime_ns": source_dir.stat().st_mtime_ns},
    ]


def test_run_copy_job_persists_startup_analysis_cache_on_completed_run_with_file_errors(db, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"content")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), max_file_retries=0, target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.copy_file", return_value=(False, None, "disk full")):
            with patch("app.services.copy_engine._checksum_only", return_value=(False, None, "disk full")):
                copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert job.startup_analysis_cached is True
    assert job.startup_analysis_file_count == 1
    assert job.startup_analysis_total_bytes == len(b"content")


def test_run_copy_job_clears_startup_analysis_cache_after_success(db, tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"content")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    analyzed_at = datetime(2026, 4, 24, tzinfo=timezone.utc)
    job.startup_analysis_status = StartupAnalysisStatus.READY
    job.startup_analysis_last_analyzed_at = analyzed_at
    job.startup_analysis_file_count = 1
    job.startup_analysis_total_bytes = len(b"content")
    job.startup_analysis_share_read_mbps = 120.5
    job.startup_analysis_drive_write_mbps = 96.25
    job.startup_analysis_estimated_duration_seconds = 1
    job.startup_analysis_entries = [
        {"relative_path": "file.txt", "size_bytes": len(b"content")},
        {"entry_type": "directory", "relative_path": "", "mtime_ns": source_dir.stat().st_mtime_ns},
    ]
    db.commit()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_STARTUP_ANALYSIS_CACHE_CLEARED", AuditLog.job_id == job.id)
        .order_by(AuditLog.id.desc())
        .first()
    )

    assert job.status == JobStatus.COMPLETED
    assert job.startup_analysis_cached is False
    assert job.startup_analysis_status == StartupAnalysisStatus.READY
    assert job.startup_analysis_last_analyzed_at is not None
    assert job.startup_analysis_file_count == 1
    assert job.startup_analysis_total_bytes == len(b"content")
    assert job.startup_analysis_share_read_mbps == 120.5
    assert job.startup_analysis_drive_write_mbps == 96.25
    assert job.startup_analysis_estimated_duration_seconds == 1
    assert audit is not None
    assert audit.details["reason"] == "job_completed"


def test_run_copy_job_accumulates_active_duration_on_resume(db, tmp_path):
    """Completed jobs retain previously accrued active duration after resume."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"content")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    job.status = JobStatus.RUNNING
    job.active_duration_seconds = 5
    job.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine._calculate_total_active_seconds", return_value=12):
            copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert job.active_duration_seconds == 12


def test_pause_request_after_last_file_still_completes_job(db, tmp_path):
    """A late pause request must not leave an already-finished job stuck in PAUSED."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "done.txt").write_bytes(b"done")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    job.status = JobStatus.RUNNING
    job.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()

    class _FinishedFuture:
        def result(self):
            return None

        def done(self):
            return True

        def cancel(self):
            return None

    class _Executor:
        def __init__(self, *args, **kwargs):
            self.future = _FinishedFuture()

        def submit(self, fn, *args, **kwargs):
            return self.future

        def shutdown(self, wait=True, cancel_futures=True):
            return None

    def _late_pause(futures):
        export_file = db.query(ExportFile).filter(ExportFile.job_id == job.id).one()
        export_file.status = FileStatus.DONE
        paused_job = db.get(ExportJob, job.id)
        paused_job.copied_bytes = export_file.size_bytes or 0
        paused_job.status = JobStatus.PAUSING
        db.commit()
        for future in list(futures):
            yield future

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.ThreadPoolExecutor", _Executor):
            with patch("app.services.copy_engine.as_completed", side_effect=_late_pause):
                copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED


def test_pause_request_after_last_failed_file_still_completes_job(db, tmp_path):
    """A late pause request must not override a terminal completed result with file errors."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "failed.txt").write_bytes(b"failed")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    job.status = JobStatus.RUNNING
    job.started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.commit()

    class _FinishedFuture:
        def result(self):
            return None

        def done(self):
            return True

        def cancel(self):
            return None

    class _Executor:
        def __init__(self, *args, **kwargs):
            self.future = _FinishedFuture()

        def submit(self, fn, *args, **kwargs):
            return self.future

        def shutdown(self, wait=True, cancel_futures=True):
            return None

    def _late_pause_after_error(futures):
        export_file = db.query(ExportFile).filter(ExportFile.job_id == job.id).one()
        export_file.status = FileStatus.ERROR
        paused_job = db.get(ExportJob, job.id)
        paused_job.status = JobStatus.PAUSING
        db.commit()
        for future in list(futures):
            yield future

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch("app.services.copy_engine.ThreadPoolExecutor", _Executor):
            with patch("app.services.copy_engine.as_completed", side_effect=_late_pause_after_error):
                copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED


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

    statuses = [FileStatus.PENDING, FileStatus.COPYING, FileStatus.RETRYING, FileStatus.ERROR, FileStatus.TIMEOUT, FileStatus.DONE]
    for i, st in enumerate(statuses):
        db.add(ExportFile(job_id=job.id, relative_path=f"file{i}.txt", status=st))
    db.commit()

    incomplete = FileRepository(db).list_incomplete_by_job(job.id)
    assert len(incomplete) == 5  # all except DONE
    result_statuses = {f.status for f in incomplete}
    assert FileStatus.DONE not in result_statuses
    assert FileStatus.TIMEOUT in result_statuses


# ---------------------------------------------------------------------------
# Audit trail tests for job completion events
# ---------------------------------------------------------------------------


def test_run_copy_job_emits_job_completed_audit(db, tmp_path):
    """A successful copy job emits a JOB_COMPLETED audit entry."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"data")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_COMPLETED", AuditLog.job_id == job.id)
        .first()
    )
    assert log is not None
    assert log.details["status"] == "COMPLETED"
    assert log.details["thread_count"] == 1
    assert log.details["started_at"] is not None
    assert log.details["error_count"] == 0
    assert log.details["files_copied"] == 1
    assert log.details["copied_bytes"] == 4
    assert log.details["total_bytes"] == 4
    assert log.details["elapsed_seconds"] >= 0
    assert "copy_rate_mb_s" in log.details
    assert log.details["copy_rate_mb_s"] >= 0


def test_run_copy_job_emits_job_completed_audit_for_partial_success(db, tmp_path):
    """A job with file errors still emits JOB_COMPLETED with error counts."""
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

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_COMPLETED", AuditLog.job_id == job.id)
        .first()
    )
    assert log is not None
    assert log.details["status"] == "COMPLETED"
    assert log.details["error_count"] > 0


def test_run_copy_job_logs_job_id_on_partial_success_completion(db, tmp_path, caplog):
    """A partial-success completion writes an application log entry with the job ID."""
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
                with caplog.at_level("INFO"):
                    copy_engine.run_copy_job(job.id)

    messages = [record.getMessage() for record in caplog.records]
    assert any(f"job_id={job.id}" in message for message in messages)


def test_run_copy_job_persists_sanitized_job_failure_reason_for_unexpected_exception(db, tmp_path):
    """Unexpected copy exceptions persist a sanitized job-level failure reason."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "bad.txt").write_bytes(b"data")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))
    source_file = source_dir / "bad.txt"
    target_file = target_dir / "bad.txt"

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine.scan_source_files",
            side_effect=RuntimeError(f"provider exploded while copying {source_file} to {target_file}"),
        ):
            copy_engine.run_copy_job(job.id)

    db.expire_all()
    db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert job.failure_reason == (
        "Unexpected copy failure "
        "(source: bad.txt, destination: bad.txt)"
    )
    assert str(source_file) not in job.failure_reason
    assert str(target_file) not in job.failure_reason


def test_run_copy_job_logs_job_completed_with_job_id(db, tmp_path, caplog):
    """A successful copy job writes a completion log entry with the job ID."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "done.txt").write_bytes(b"completed")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with caplog.at_level("INFO"):
            copy_engine.run_copy_job(job.id)

    messages = [record.getMessage() for record in caplog.records]
    assert any(f"JOB_COMPLETED job_id={job.id}" in message for message in messages)
    completed_messages = [message for message in messages if f"JOB_COMPLETED job_id={job.id}" in message]
    assert completed_messages
    assert any(
        "thread_count=1" in message
        and "started_at=" in message
        and "file_count=1" in message
        and "files_copied=1" in message
        and "copied_bytes=9" in message
        and "total_bytes=9" in message
        and "elapsed_seconds=" in message
        and "copy_rate_mb_s=" in message
        for message in completed_messages
    )
    assert all("source_path=" not in message for message in completed_messages)
    assert all("target_mount_path=" not in message for message in completed_messages)


def test_run_verify_job_emits_verification_completed_audit(db, tmp_path):
    """A successful verification emits a JOB_VERIFICATION_COMPLETED audit entry."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    src_file = source_dir / "file.txt"
    src_file.write_bytes(b"data")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    # Run the copy first to get files in DONE state with checksums
    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()

    # Now run verification
    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_verify_job(job.id)

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_VERIFICATION_COMPLETED", AuditLog.job_id == job.id)
        .first()
    )
    assert log is not None
    assert log.details["status"] == "COMPLETED"
    assert log.details["mismatches"] is False


def test_run_verify_job_emits_verification_failed_audit(db, tmp_path):
    """A failed verification emits a JOB_VERIFICATION_FAILED audit entry."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"data")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    # Run copy first
    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()

    # Corrupt a checksum to trigger mismatch
    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine._checksum_only",
            return_value=(True, "badhash", None),
        ):
            copy_engine.run_verify_job(job.id)

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "JOB_VERIFICATION_FAILED", AuditLog.job_id == job.id)
        .first()
    )
    assert log is not None
    assert log.details["status"] == "FAILED"
    assert log.details["mismatches"] is True


def test_run_verify_job_sanitizes_persisted_checksum_errors(db, tmp_path):
    """Verification failures persist only sanitized checksum detail for operator-facing rows."""
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file.txt").write_bytes(b"data")

    target_dir = tmp_path / "target"
    target_dir.mkdir()

    job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        copy_engine.run_copy_job(job.id)

    db.expire_all()

    with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
        with patch(
            "app.services.copy_engine._checksum_only",
            return_value=(False, None, "checksum failed for /mnt/ecube/private/file.txt"),
        ):
            copy_engine.run_verify_job(job.id)

    file_row = db.query(ExportFile).filter(ExportFile.job_id == job.id).one()
    assert file_row.status == FileStatus.ERROR
    assert file_row.error_message == "Checksum verification failed"
    assert "/mnt/ecube/private" not in (file_row.error_message or "")
