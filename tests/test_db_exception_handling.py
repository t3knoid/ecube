"""Tests for database exception handling in service-layer db.commit() calls.

Covers the high-risk multi-step sequences identified in issue #82:
- Job creation with drive assignment (multi-step DB)
- Drive eject after OS operations
- Mount add after OS mount operation
- Audit log writes never aborting primary operations
"""

from unittest.mock import MagicMock, patch

import os
import tempfile
from pathlib import Path

import pytest

from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import ExportJob, JobStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_drive(db, *, state=DriveState.AVAILABLE, project_id=None, device_id="USB-TEST"):
    drive = UsbDrive(
        device_identifier=device_id,
        current_state=state,
        current_project_id=project_id,
    )
    db.add(drive)
    db.commit()
    return drive


# ---------------------------------------------------------------------------
# Job creation — multi-step DB sequence
# ---------------------------------------------------------------------------

class TestJobCreationDBFailures:
    """Job creation: add job → add assignment → update drive state."""

    def test_create_job_db_failure_returns_500(self, client, db):
        """If the transaction commit fails, return 500 not a raw traceback."""
        with patch.object(
            db, "commit",
            side_effect=Exception("simulated DB failure"),
        ):
            response = client.post(
                "/jobs",
                json={
                    "project_id": "PROJ-001",
                    "evidence_number": "EV-001",
                    "source_path": "/data/evidence",
                },
            )
        assert response.status_code == 500
        body = response.json()
        assert "database" in body.get("detail", body.get("message", "")).lower() or \
               "error" in body.get("detail", body.get("message", "")).lower()

    def test_create_job_drive_assignment_db_failure(self, client, db):
        """If the single-transaction commit fails, return 500 and leave no orphaned job."""
        drive = _make_drive(db)

        original_commit = db.commit

        def fail_on_second_commit(*a, **kw):
            """Allow setup commits but fail the create_job transaction commit."""
            fail_on_second_commit.calls += 1
            # The create_job transaction commit is inside the service;
            # simulate failure by raising after flush succeeds.
            raise Exception("simulated commit failure")
        fail_on_second_commit.calls = 0

        with patch.object(db, "commit", side_effect=fail_on_second_commit):
            response = client.post(
                "/jobs",
                json={
                    "project_id": "PROJ-001",
                    "evidence_number": "EV-001",
                    "source_path": "/data/evidence",
                    "drive_id": drive.id,
                },
            )
        assert response.status_code == 500

        # Verify no orphaned job was left behind — rollback should have
        # cleaned up both the job and the drive assignment.
        from app.models.jobs import ExportJob as EJ
        original_commit()  # ensure session is clean
        orphans = db.query(EJ).filter(EJ.project_id == "PROJ-001").all()
        assert len(orphans) == 0, "Orphaned job record found after commit failure"

    def test_create_job_audit_failure_does_not_abort(self, client, db):
        """Audit log failure after successful job creation must not abort."""
        with patch(
            "app.repositories.audit_repository.AuditRepository.add",
            side_effect=Exception("simulated audit DB failure"),
        ):
            response = client.post(
                "/jobs",
                json={
                    "project_id": "PROJ-001",
                    "evidence_number": "EV-001",
                    "source_path": "/data/evidence",
                },
            )
        assert response.status_code == 200
        assert response.json()["project_id"] == "PROJ-001"


# ---------------------------------------------------------------------------
# Drive eject — OS side-effect then DB commit
# ---------------------------------------------------------------------------

class TestDriveEjectDBFailures:
    """Drive eject: OS unmount succeeds → DB state-change must handle errors."""

    def test_eject_db_failure_after_os_unmount(self, manager_client, db):
        """If DB commit fails after OS eject, return 500 with actionable detail."""
        drive = _make_drive(db, state=DriveState.IN_USE, project_id="PROJ-001")

        with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)), \
             patch("app.repositories.drive_repository.DriveRepository.save",
                   side_effect=Exception("simulated DB failure")):
            response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

        assert response.status_code == 500
        detail = response.json().get("detail", response.json().get("message", ""))
        assert "database" in detail.lower() or "os level" in detail.lower()

    def test_eject_audit_failure_does_not_abort(self, manager_client, db):
        """Audit log failure after successful eject must not abort the operation."""
        drive = _make_drive(db, state=DriveState.IN_USE, project_id="PROJ-001")

        with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)), \
             patch("app.repositories.audit_repository.AuditRepository.add",
                   side_effect=Exception("simulated audit DB failure")):
            response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

        assert response.status_code == 200
        assert response.json()["current_state"] == "AVAILABLE"


# ---------------------------------------------------------------------------
# Drive initialization — audit failure on isolation violation
# ---------------------------------------------------------------------------

class TestDriveInitDBFailures:
    """Drive init: audit + state change must handle DB errors."""

    def test_initialize_audit_failure_does_not_abort(self, manager_client, db):
        """Audit failure during initialization must not abort the operation."""
        drive = _make_drive(db)

        with patch(
            "app.repositories.audit_repository.AuditRepository.add",
            side_effect=Exception("simulated audit DB failure"),
        ):
            response = manager_client.post(
                f"/drives/{drive.id}/initialize",
                json={"project_id": "PROJ-001"},
            )

        assert response.status_code == 200
        assert response.json()["current_project_id"] == "PROJ-001"

    def test_initialize_db_failure_returns_500(self, manager_client, db):
        """If DB commit fails during drive state change, return 500."""
        drive = _make_drive(db)

        with patch(
            "app.repositories.drive_repository.DriveRepository.save",
            side_effect=Exception("simulated DB failure"),
        ):
            response = manager_client.post(
                f"/drives/{drive.id}/initialize",
                json={"project_id": "PROJ-001"},
            )

        assert response.status_code == 500

    def test_isolation_violation_audit_failure_still_rejects(self, manager_client, db):
        """Even if audit log fails, project isolation violation must still be rejected."""
        drive = _make_drive(db, state=DriveState.IN_USE, project_id="PROJ-AAA")

        with patch(
            "app.repositories.audit_repository.AuditRepository.add",
            side_effect=Exception("simulated audit DB failure"),
        ):
            response = manager_client.post(
                f"/drives/{drive.id}/initialize",
                json={"project_id": "PROJ-BBB"},
            )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Mount add — OS side-effect then DB commit
# ---------------------------------------------------------------------------

class TestMountDBFailures:
    """Mount operations: OS mount → DB status update."""

    def test_add_mount_db_failure_on_initial_record(self, manager_client, db):
        """If initial mount record insert fails, return 500."""
        with patch(
            "app.repositories.mount_repository.MountRepository.add",
            side_effect=Exception("simulated DB failure"),
        ):
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "server:/share",
                    "local_mount_point": "/mnt/test",
                },
            )
        assert response.status_code == 500

    def test_add_mount_audit_failure_does_not_abort(self, manager_client, db):
        """Audit failure on mount add must not abort the operation."""
        with patch(
            "subprocess.run",
            return_value=MagicMock(returncode=0, stderr="", stdout=""),
        ), patch(
            "app.repositories.audit_repository.AuditRepository.add",
            side_effect=Exception("simulated audit DB failure"),
        ):
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "server:/share",
                    "local_mount_point": "/mnt/test",
                },
            )
        # Should succeed despite audit failure
        assert response.status_code == 200

    def test_remove_mount_audit_failure_does_not_abort(self, manager_client, db):
        """Audit failure on mount removal must not abort the delete."""
        from app.models.network import MountStatus, NetworkMount

        mount = NetworkMount(
            type="NFS",
            remote_path="server:/share",
            local_mount_point="/mnt/test",
            status=MountStatus.MOUNTED,
        )
        db.add(mount)
        db.commit()

        with patch("subprocess.run"), \
             patch(
                 "app.repositories.audit_repository.AuditRepository.add",
                 side_effect=Exception("simulated audit DB failure"),
             ):
            response = manager_client.delete(f"/mounts/{mount.id}")
        assert response.status_code == 204


# ---------------------------------------------------------------------------
# Repository layer — rollback on commit failure
# ---------------------------------------------------------------------------

class TestRepositoryRollback:
    """Repository-level commits must rollback on failure to keep session clean."""

    def test_drive_repo_add_rolls_back_on_failure(self, db):
        """DriveRepository.add() should rollback and re-raise on commit failure."""
        from app.repositories.drive_repository import DriveRepository

        repo = DriveRepository(db)
        drive = UsbDrive(device_identifier="USB-ROLLBACK", current_state=DriveState.AVAILABLE)

        with patch.object(db, "commit", side_effect=Exception("simulated")):
            with pytest.raises(Exception, match="simulated"):
                repo.add(drive)

        # Session should be usable after rollback
        drives = repo.list_all()
        assert isinstance(drives, list)

    def test_audit_repo_add_rolls_back_on_failure(self, db):
        """AuditRepository.add() should rollback and re-raise on commit failure."""
        from app.repositories.audit_repository import AuditRepository

        repo = AuditRepository(db)

        with patch.object(db, "commit", side_effect=Exception("simulated")):
            with pytest.raises(Exception, match="simulated"):
                repo.add(action="TEST_ACTION", user="tester")

        # Session should be usable after rollback
        logs = repo.query()
        assert isinstance(logs, list)

    def test_job_repo_save_rolls_back_on_failure(self, db):
        """JobRepository.save() should rollback and re-raise on commit failure."""
        from app.repositories.job_repository import JobRepository

        repo = JobRepository(db)
        job = ExportJob(
            project_id="PROJ-001",
            evidence_number="EV-001",
            source_path="/data",
        )
        db.add(job)
        db.commit()

        job.status = JobStatus.RUNNING
        with patch.object(db, "commit", side_effect=Exception("simulated")):
            with pytest.raises(Exception, match="simulated"):
                repo.save(job)

        # Session should be usable after rollback
        result = repo.get(job.id)
        assert result is not None


# ---------------------------------------------------------------------------
# Copy engine — background task DB failures
# ---------------------------------------------------------------------------

class TestCopyEngineDBFailures:
    """Copy engine: worker and main function DB error handling."""

    def test_run_copy_job_db_failure_on_status_update(self, db):
        """If setting job to RUNNING fails, copy job should exit gracefully."""
        from app.services.copy_engine import run_copy_job

        job = ExportJob(
            project_id="PROJ-001",
            evidence_number="EV-001",
            source_path="/tmp",
            status=JobStatus.PENDING,
        )
        db.add(job)
        db.commit()
        job_id = job.id

        with patch(
            "app.repositories.job_repository.JobRepository.save",
            side_effect=Exception("simulated DB failure"),
        ):
            # Should not raise — background tasks should handle errors internally
            run_copy_job(job_id)

    def test_process_file_audit_failure_does_not_abort_copy(self, db):
        """Audit failure during file copy must not prevent the copy from completing."""
        from app.models.jobs import ExportFile, FileStatus
        from app.services.copy_engine import _process_file

        # Create job and file records
        job = ExportJob(
            project_id="PROJ-001",
            evidence_number="EV-001",
            source_path="/tmp",
            status=JobStatus.RUNNING,
        )
        db.add(job)
        db.commit()

        ef = ExportFile(
            job_id=job.id,
            relative_path="test.txt",
            size_bytes=5,
            status=FileStatus.PENDING,
        )
        db.add(ef)
        db.commit()
        ef_id = ef.id

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello")
            src_path = f.name

        try:
            with patch(
                "app.repositories.audit_repository.AuditRepository.add",
                side_effect=Exception("simulated audit DB failure"),
            ):
                _process_file(ef_id, Path(src_path), None)

            # File should still be processed successfully despite audit failure
            db.expire_all()
            ef = db.get(ExportFile, ef_id)
            assert ef.status == FileStatus.DONE
        finally:
            os.unlink(src_path)

    def test_process_file_skips_increment_when_done_save_fails(self, db):
        """If saving DONE status fails, copied_bytes must NOT be incremented."""
        from app.models.jobs import ExportFile, FileStatus
        from app.services.copy_engine import _process_file

        job = ExportJob(
            project_id="PROJ-001",
            evidence_number="EV-001",
            source_path="/tmp",
            status=JobStatus.RUNNING,
            copied_bytes=0,
        )
        db.add(job)
        db.commit()

        ef = ExportFile(
            job_id=job.id,
            relative_path="important.txt",
            size_bytes=100,
            status=FileStatus.PENDING,
        )
        db.add(ef)
        db.commit()
        ef_id = ef.id
        job_id = job.id

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("x" * 100)
            src_path = f.name

        try:
            original_save = db.commit

            call_count = 0

            def commit_fails_on_done_save(*a, **kw):
                """Fail the commit that persists DONE status (second commit),
                but allow others (COPYING status, audit, etc.)."""
                nonlocal call_count
                call_count += 1
                # The DONE-status save is the 2nd real commit in _process_file
                # (1st = COPYING status). Fail it to simulate DB error.
                if call_count == 2:
                    raise Exception("simulated DONE-save failure")
                return original_save()

            with patch(
                "app.repositories.audit_repository.AuditRepository.add",
                return_value=None,  # silence audit to simplify commit counting
            ), patch(
                "app.services.copy_engine.SessionLocal",
                return_value=db,
            ):
                # Patch commit on the session used by the worker
                with patch.object(db, "commit", side_effect=commit_fails_on_done_save):
                    _process_file(ef_id, Path(src_path), None)

            # copied_bytes on the job should remain 0 because the DONE save
            # failed — the increment must have been skipped.
            db.expire_all()
            refreshed_job = db.get(ExportJob, job_id)
            assert refreshed_job.copied_bytes == 0, (
                f"Expected copied_bytes=0 but got {refreshed_job.copied_bytes}; "
                "increment_job_bytes should be skipped when DONE save fails"
            )
        finally:
            os.unlink(src_path)
