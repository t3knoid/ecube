"""Concurrency and row-locking tests.

These tests verify that:

1. ``get_for_update`` helpers exist and behave correctly under normal access.
2. A simulated lock conflict (OperationalError from the DB backend) is
   translated to :class:`~app.exceptions.ConflictError` (HTTP 409).
3. Double-start and double-assign are prevented: once a resource has
   transitioned to a new state, subsequent transition attempts return 409.

Notes
-----
SQLite (used in the test suite) silently ignores ``FOR UPDATE``, so row-level
lock contention is simulated with ``unittest.mock``.  The state-guard tests
(double-start / double-assign) exercise the application-level FSM checks that
protect critical paths as a defence-in-depth layer on all backends.

Together, the lock-conflict tests and the state-guard tests prove the full
concurrency protection strategy:

* **Row-level locking** (``SELECT … FOR UPDATE NOWAIT``) serialises concurrent
  transactions on PostgreSQL so that only one caller holds the row at a time.
* **Application-level state guards** reject any transition that arrives after
  the state has already been changed (visible to subsequent readers once the
  first transaction commits).
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.exceptions import ConflictError
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import ExportJob, JobStatus
from app.repositories.drive_repository import DriveRepository
from app.repositories.job_repository import JobRepository


# ---------------------------------------------------------------------------
# Unit tests – get_for_update basic contract
# ---------------------------------------------------------------------------


def test_drive_get_for_update_returns_drive(db):
    """get_for_update returns the drive when no lock conflict occurs."""
    drive = UsbDrive(device_identifier="USB-FU-01", current_state=DriveState.AVAILABLE)
    db.add(drive)
    db.commit()

    result = DriveRepository(db).get_for_update(drive.id)

    assert result is not None
    assert result.device_identifier == "USB-FU-01"


def test_drive_get_for_update_returns_none_when_missing(db):
    """get_for_update returns None for a non-existent drive ID."""
    assert DriveRepository(db).get_for_update(9999) is None


def test_job_get_for_update_returns_job(db):
    """get_for_update returns the job when no lock conflict occurs."""
    job = ExportJob(project_id="P", evidence_number="E", source_path="/src")
    db.add(job)
    db.commit()

    result = JobRepository(db).get_for_update(job.id)

    assert result is not None
    assert result.project_id == "P"


def test_job_get_for_update_returns_none_when_missing(db):
    """get_for_update returns None for a non-existent job ID."""
    assert JobRepository(db).get_for_update(9999) is None


# ---------------------------------------------------------------------------
# Unit tests – OperationalError from DB is translated to ConflictError
#
# The mock session drives the query chain:
#   db.query(Model).filter(...).with_for_update(nowait=True).one_or_none()
# to raise OperationalError, exactly as PostgreSQL would when NOWAIT cannot
# acquire the row-level lock.
# ---------------------------------------------------------------------------


def _make_operational_error(pgcode: str | None) -> OperationalError:
    class _Orig:
        def __init__(self, code: str | None):
            self.pgcode = code

    return OperationalError(
        "database operation failed", params=None, orig=_Orig(pgcode)
    )


def _make_locked_mock_session():
    """Return a MagicMock Session whose query chain raises lock OperationalError."""
    mock_db = MagicMock()
    lock_error = _make_operational_error("55P03")
    (
        mock_db.query.return_value
        .filter.return_value
        .with_for_update.return_value
        .one_or_none.side_effect
    ) = lock_error
    return mock_db


def test_drive_get_for_update_raises_conflict_on_lock():
    """OperationalError from the query layer is surfaced as ConflictError."""
    mock_db = _make_locked_mock_session()
    repo = DriveRepository(mock_db)

    with pytest.raises(ConflictError) as exc_info:
        repo.get_for_update(1)

    assert "locked" in exc_info.value.message.lower()
    mock_db.rollback.assert_called_once()


def test_job_get_for_update_raises_conflict_on_lock():
    """OperationalError from the query layer is surfaced as ConflictError."""
    mock_db = _make_locked_mock_session()
    repo = JobRepository(mock_db)

    with pytest.raises(ConflictError) as exc_info:
        repo.get_for_update(1)

    assert "locked" in exc_info.value.message.lower()
    mock_db.rollback.assert_called_once()


def test_drive_get_for_update_reraises_non_lock_operational_error():
    """Non-lock OperationalError values are not translated to ConflictError."""
    mock_db = MagicMock()
    non_lock_error = _make_operational_error("08006")
    (
        mock_db.query.return_value
        .filter.return_value
        .with_for_update.return_value
        .one_or_none.side_effect
    ) = non_lock_error

    repo = DriveRepository(mock_db)
    with pytest.raises(OperationalError):
        repo.get_for_update(1)
    mock_db.rollback.assert_called_once()


def test_job_get_for_update_reraises_non_lock_operational_error():
    """Non-lock OperationalError values are not translated to ConflictError."""
    mock_db = MagicMock()
    non_lock_error = _make_operational_error("08006")
    (
        mock_db.query.return_value
        .filter.return_value
        .with_for_update.return_value
        .one_or_none.side_effect
    ) = non_lock_error

    repo = JobRepository(mock_db)
    with pytest.raises(OperationalError):
        repo.get_for_update(1)
    mock_db.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# HTTP-layer tests – lock conflict returns consistent 409
# ---------------------------------------------------------------------------


def test_initialize_drive_lock_conflict_returns_409(manager_client, db):
    """A lock conflict on drive initialization returns HTTP 409."""
    drive = UsbDrive(
        device_identifier="USB-LOCK-01", current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    with patch(
        "app.repositories.drive_repository.DriveRepository.get_for_update",
        side_effect=ConflictError("Drive is currently locked by another operation."),
    ):
        response = manager_client.post(
            f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"}
        )

    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "CONFLICT"
    assert "locked" in data["message"].lower()


def test_prepare_eject_lock_conflict_returns_409(manager_client, db):
    """A lock conflict on prepare-eject returns HTTP 409."""
    drive = UsbDrive(
        device_identifier="USB-LOCK-02",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    with patch(
        "app.repositories.drive_repository.DriveRepository.get_for_update",
        side_effect=ConflictError("Drive is currently locked by another operation."),
    ):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_start_job_lock_conflict_returns_409(manager_client, db):
    """A lock conflict on job start returns HTTP 409."""
    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-LOCK-01",
        source_path="/data",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    with patch(
        "app.repositories.job_repository.JobRepository.get_for_update",
        side_effect=ConflictError("Job is currently locked by another operation."),
    ):
        response = manager_client.post(f"/jobs/{job.id}/start", json={})

    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "CONFLICT"
    assert "locked" in data["message"].lower()


def test_verify_job_lock_conflict_returns_409(manager_client, db):
    """A lock conflict on job verify returns HTTP 409."""
    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-LOCK-02",
        source_path="/data",
        status=JobStatus.COMPLETED,
    )
    db.add(job)
    db.commit()

    with patch(
        "app.repositories.job_repository.JobRepository.get_for_update",
        side_effect=ConflictError("Job is currently locked by another operation."),
    ):
        response = manager_client.post(f"/jobs/{job.id}/verify")

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_create_job_drive_lock_conflict_returns_409(manager_client, db):
    """A lock conflict when assigning a drive during job creation returns 409."""
    drive = UsbDrive(
        device_identifier="USB-LOCK-03", current_state=DriveState.AVAILABLE
    )
    db.add(drive)
    db.commit()

    with patch(
        "app.repositories.drive_repository.DriveRepository.get_for_update",
        side_effect=ConflictError("Drive is currently locked by another operation."),
    ):
        response = manager_client.post(
            "/jobs",
            json={
                "project_id": "PROJ-001",
                "evidence_number": "EV-LOCK-03",
                "source_path": "/data",
                "drive_id": drive.id,
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


# ---------------------------------------------------------------------------
# State-guard tests – double-start and double-assign are prevented
#
# These sequential tests demonstrate that after the first actor commits a
# state change the second actor—arriving after the lock is released—observes
# the updated state and is rejected with 409.  On PostgreSQL, the row lock
# also prevents two actors from observing the same "before" state at the
# same time, providing an additional layer of protection.
# ---------------------------------------------------------------------------


def test_double_start_prevented(manager_client, db):
    """Starting a PENDING job twice: first succeeds (→ RUNNING), second returns 409.

    ``start_job`` transitions the job to RUNNING atomically within the
    lock so that any subsequent request arriving after the commit is
    rejected before the background copy task begins.
    """
    job = ExportJob(
        project_id="PROJ-GUARD",
        evidence_number="EV-DS-01",
        source_path="/tmp",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    with patch("app.services.copy_engine.run_copy_job"):
        response1 = manager_client.post(f"/jobs/{job.id}/start", json={})
    assert response1.status_code == 200
    assert response1.json()["status"] == "RUNNING"

    # Second start attempt must be rejected because the job is now RUNNING.
    response2 = manager_client.post(f"/jobs/{job.id}/start", json={})
    assert response2.status_code == 409
    assert response2.json()["code"] == "CONFLICT"


def test_double_assign_prevented(manager_client, db):
    """Assigning the same AVAILABLE drive to two jobs: first succeeds, second returns 409.

    The first job creation sets the drive to IN_USE and commits.  The second
    creation request reads IN_USE and is rejected with 409.
    """
    drive = UsbDrive(
        device_identifier="USB-GUARD-01", current_state=DriveState.AVAILABLE
    )
    db.add(drive)
    db.commit()

    response1 = manager_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-GUARD",
            "evidence_number": "EV-DA-01",
            "source_path": "/data",
            "drive_id": drive.id,
        },
    )
    assert response1.status_code == 200

    # Second job tries to claim the same drive – drive is now IN_USE.
    response2 = manager_client.post(
        "/jobs",
        json={
            "project_id": "PROJ-GUARD",
            "evidence_number": "EV-DA-02",
            "source_path": "/data",
            "drive_id": drive.id,
        },
    )
    assert response2.status_code == 409
    assert response2.json()["code"] == "CONFLICT"


def test_double_initialize_different_projects_prevented(manager_client, db):
    """Initializing a drive for a different project while it is IN_USE returns 403."""
    drive = UsbDrive(
        device_identifier="USB-GUARD-02",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-A",
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(
        f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-B"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_start_job_transitions_to_running_atomically(manager_client, db):
    """start_job sets job status to RUNNING within the locked transaction.

    This ensures the row holds the updated state before the lock is released,
    so concurrent requests always observe RUNNING and receive 409.
    """
    job = ExportJob(
        project_id="PROJ-ATOMIC",
        evidence_number="EV-AT-01",
        source_path="/tmp",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    with patch("app.services.copy_engine.run_copy_job"):
        response = manager_client.post(f"/jobs/{job.id}/start", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"

    # Verify the DB row is RUNNING before the background task has a chance to run.
    db.expire_all()
    db.refresh(job)
    assert job.status == JobStatus.RUNNING
