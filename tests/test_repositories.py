"""Unit tests for repository layer.

Each test directly exercises the repository classes against an in-memory
SQLite database, without going through the HTTP layer.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus, Manifest
from app.models.network import MountStatus, MountType, NetworkMount
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.repositories.hardware_repository import PortRepository
from app.repositories.job_repository import (
    DriveAssignmentRepository,
    FileRepository,
    JobRepository,
    ManifestRepository,
)
from app.repositories.mount_repository import MountRepository


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SQLALCHEMY_DATABASE_URL = "sqlite://"

_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=_engine)
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


# ---------------------------------------------------------------------------
# DriveRepository
# ---------------------------------------------------------------------------


def test_drive_repo_list_all_empty(db):
    repo = DriveRepository(db)
    assert repo.list_all() == []


def test_drive_repo_add_and_get(db):
    repo = DriveRepository(db)
    drive = UsbDrive(device_identifier="USB-REPO-01", current_state=DriveState.AVAILABLE)
    saved = repo.add(drive)

    assert saved.id is not None
    fetched = repo.get(saved.id)
    assert fetched is not None
    assert fetched.device_identifier == "USB-REPO-01"


def test_drive_repo_get_missing(db):
    repo = DriveRepository(db)
    assert repo.get(9999) is None


def test_drive_repo_list_all_returns_all(db):
    repo = DriveRepository(db)
    repo.add(UsbDrive(device_identifier="USB-A", current_state=DriveState.AVAILABLE))
    repo.add(UsbDrive(device_identifier="USB-B", current_state=DriveState.EMPTY))

    all_drives = repo.list_all()
    assert len(all_drives) == 2
    identifiers = {d.device_identifier for d in all_drives}
    assert identifiers == {"USB-A", "USB-B"}


def test_drive_repo_save_updates_state(db):
    repo = DriveRepository(db)
    drive = repo.add(UsbDrive(device_identifier="USB-C", current_state=DriveState.AVAILABLE))

    drive.current_state = DriveState.IN_USE
    updated = repo.save(drive)

    assert updated.current_state == DriveState.IN_USE
    assert repo.get(drive.id).current_state == DriveState.IN_USE


# ---------------------------------------------------------------------------
# JobRepository
# ---------------------------------------------------------------------------


def test_job_repo_add_and_get(db):
    repo = JobRepository(db)
    job = ExportJob(
        project_id="PROJ-REPO",
        evidence_number="EV-REPO",
        source_path="/data",
    )
    saved = repo.add(job)

    assert saved.id is not None
    assert saved.status == JobStatus.PENDING

    fetched = repo.get(saved.id)
    assert fetched is not None
    assert fetched.project_id == "PROJ-REPO"


def test_job_repo_get_missing(db):
    repo = JobRepository(db)
    assert repo.get(9999) is None


def test_job_repo_save_updates_status(db):
    repo = JobRepository(db)
    job = repo.add(
        ExportJob(project_id="P", evidence_number="E", source_path="/src")
    )

    job.status = JobStatus.RUNNING
    repo.save(job)

    assert repo.get(job.id).status == JobStatus.RUNNING


def test_job_repo_count_active(db):
    repo = JobRepository(db)
    repo.add(ExportJob(project_id="P", evidence_number="E1", source_path="/src", status=JobStatus.RUNNING))
    repo.add(ExportJob(project_id="P", evidence_number="E2", source_path="/src", status=JobStatus.PENDING))
    repo.add(ExportJob(project_id="P", evidence_number="E3", source_path="/src", status=JobStatus.RUNNING))

    assert repo.count_active() == 2


# ---------------------------------------------------------------------------
# FileRepository
# ---------------------------------------------------------------------------


def _make_job(db) -> ExportJob:
    job = ExportJob(project_id="P", evidence_number="E", source_path="/src")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_file_repo_list_by_job_empty(db):
    job = _make_job(db)
    repo = FileRepository(db)
    assert repo.list_by_job(job.id) == []


def test_file_repo_add_bulk_and_list(db):
    job = _make_job(db)
    repo = FileRepository(db)

    files = [
        ExportFile(job_id=job.id, relative_path="a.txt", status=FileStatus.PENDING),
        ExportFile(job_id=job.id, relative_path="b.txt", status=FileStatus.PENDING),
    ]
    repo.add_bulk(files)

    result = repo.list_by_job(job.id)
    assert len(result) == 2
    paths = {f.relative_path for f in result}
    assert paths == {"a.txt", "b.txt"}


def test_file_repo_get_and_save(db):
    job = _make_job(db)
    repo = FileRepository(db)

    ef = ExportFile(job_id=job.id, relative_path="c.txt", status=FileStatus.PENDING)
    repo.add_bulk([ef])

    fetched = repo.get(ef.id)
    assert fetched is not None

    fetched.status = FileStatus.DONE
    repo.save(fetched)

    assert repo.get(ef.id).status == FileStatus.DONE


def test_file_repo_list_done_by_job(db):
    job = _make_job(db)
    repo = FileRepository(db)

    repo.add_bulk([
        ExportFile(job_id=job.id, relative_path="done.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="pending.txt", status=FileStatus.PENDING),
        ExportFile(job_id=job.id, relative_path="error.txt", status=FileStatus.ERROR),
    ])

    done = repo.list_done_by_job(job.id)
    assert len(done) == 1
    assert done[0].relative_path == "done.txt"


def test_file_repo_count_errors(db):
    job = _make_job(db)
    repo = FileRepository(db)

    repo.add_bulk([
        ExportFile(job_id=job.id, relative_path="ok.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="err1.txt", status=FileStatus.ERROR),
        ExportFile(job_id=job.id, relative_path="err2.txt", status=FileStatus.ERROR),
    ])

    assert repo.count_errors(job.id) == 2


def test_file_repo_count_done(db):
    job = _make_job(db)
    repo = FileRepository(db)

    repo.add_bulk([
        ExportFile(job_id=job.id, relative_path="a.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="b.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="c.txt", status=FileStatus.ERROR),
        ExportFile(job_id=job.id, relative_path="d.txt", status=FileStatus.PENDING),
    ])

    assert repo.count_done(job.id) == 2


def test_file_repo_list_error_messages(db):
    job = _make_job(db)
    repo = FileRepository(db)

    repo.add_bulk([
        ExportFile(job_id=job.id, relative_path="ok.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="e1.txt", status=FileStatus.ERROR, error_message="disk full"),
        ExportFile(job_id=job.id, relative_path="e2.txt", status=FileStatus.ERROR, error_message="perm denied"),
        ExportFile(job_id=job.id, relative_path="e3.txt", status=FileStatus.ERROR, error_message=None),
    ])

    rows = repo.list_error_messages(job.id, limit=10)
    assert len(rows) == 2  # e3.txt excluded (null error_message)
    messages = {msg for msg, _ in rows}
    assert "disk full" in messages
    assert "perm denied" in messages

    # Verify limit works
    rows_limited = repo.list_error_messages(job.id, limit=1)
    assert len(rows_limited) == 1


def test_file_repo_count_done_and_errors(db):
    job = _make_job(db)
    repo = FileRepository(db)

    repo.add_bulk([
        ExportFile(job_id=job.id, relative_path="a.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="b.txt", status=FileStatus.DONE),
        ExportFile(job_id=job.id, relative_path="c.txt", status=FileStatus.ERROR),
        ExportFile(job_id=job.id, relative_path="d.txt", status=FileStatus.PENDING),
    ])

    done, errors = repo.count_done_and_errors(job.id)
    assert done == 2
    assert errors == 1

    # Empty job returns zeros
    empty_job = _make_job(db)
    done_e, errors_e = repo.count_done_and_errors(empty_job.id)
    assert done_e == 0
    assert errors_e == 0


def test_file_repo_delete_by_job(db):
    job = _make_job(db)
    repo = FileRepository(db)

    repo.add_bulk([
        ExportFile(job_id=job.id, relative_path="x.txt", status=FileStatus.PENDING),
        ExportFile(job_id=job.id, relative_path="y.txt", status=FileStatus.PENDING),
    ])
    assert len(repo.list_by_job(job.id)) == 2

    repo.delete_by_job(job.id)
    assert repo.list_by_job(job.id) == []


def test_file_repo_increment_job_bytes(db):
    job = _make_job(db)
    file_repo = FileRepository(db)
    job_repo = JobRepository(db)

    # Initial copied_bytes should be 0 (default)
    assert job.copied_bytes == 0

    file_repo.increment_job_bytes(job.id, 1024)
    db.expire_all()
    updated_job = job_repo.get(job.id)
    assert updated_job.copied_bytes == 1024

    file_repo.increment_job_bytes(job.id, 512)
    db.expire_all()
    updated_job = job_repo.get(job.id)
    assert updated_job.copied_bytes == 1536


# ---------------------------------------------------------------------------
# DriveAssignmentRepository
# ---------------------------------------------------------------------------


def test_drive_assignment_repo_add(db):
    drive = UsbDrive(device_identifier="USB-DA-01", current_state=DriveState.AVAILABLE)
    db.add(drive)
    job = ExportJob(project_id="P", evidence_number="E", source_path="/src")
    db.add(job)
    db.commit()

    repo = DriveAssignmentRepository(db)
    assignment = repo.add(DriveAssignment(drive_id=drive.id, job_id=job.id))

    assert assignment.id is not None
    assert assignment.drive_id == drive.id
    assert assignment.job_id == job.id


def test_drive_assignment_repo_get_active_for_job(db):
    from datetime import datetime, timezone

    drive1 = UsbDrive(device_identifier="USB-ACT-01", current_state=DriveState.AVAILABLE)
    drive2 = UsbDrive(device_identifier="USB-ACT-02", current_state=DriveState.IN_USE)
    job = ExportJob(project_id="P", evidence_number="E", source_path="/src")
    db.add_all([drive1, drive2, job])
    db.commit()

    repo = DriveAssignmentRepository(db)

    # First assignment, now released
    a1 = repo.add(DriveAssignment(
        drive_id=drive1.id, job_id=job.id,
        released_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ))
    # Second assignment, still active
    a2 = repo.add(DriveAssignment(drive_id=drive2.id, job_id=job.id))

    active = repo.get_active_for_job(job.id)
    assert active is not None
    assert active.id == a2.id
    assert active.drive_id == drive2.id

    # No active assignment for a non-existent job
    assert repo.get_active_for_job(99999) is None


# ---------------------------------------------------------------------------
# ManifestRepository
# ---------------------------------------------------------------------------


def test_manifest_repo_add(db):
    job = _make_job(db)
    repo = ManifestRepository(db)

    manifest = repo.add(Manifest(job_id=job.id, manifest_path="/tmp/manifest.json", format="JSON"))

    assert manifest.id is not None
    assert manifest.job_id == job.id
    assert manifest.format == "JSON"


# ---------------------------------------------------------------------------
# MountRepository
# ---------------------------------------------------------------------------


def test_mount_repo_list_all_empty(db):
    repo = MountRepository(db)
    assert repo.list_all() == []


def test_mount_repo_add_and_get(db):
    repo = MountRepository(db)
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/exports",
        local_mount_point="/mnt/nfs",
        status=MountStatus.UNMOUNTED,
    )
    saved = repo.add(mount)

    assert saved.id is not None
    fetched = repo.get(saved.id)
    assert fetched is not None
    assert fetched.local_mount_point == "/mnt/nfs"


def test_mount_repo_get_missing(db):
    repo = MountRepository(db)
    assert repo.get(9999) is None


def test_mount_repo_list_all(db):
    repo = MountRepository(db)
    repo.add(NetworkMount(type=MountType.NFS, remote_path="1:/a", local_mount_point="/mnt/a"))
    repo.add(NetworkMount(type=MountType.SMB, remote_path="//2/b", local_mount_point="/mnt/b"))

    all_mounts = repo.list_all()
    assert len(all_mounts) == 2


def test_mount_repo_save_updates_status(db):
    repo = MountRepository(db)
    mount = repo.add(
        NetworkMount(type=MountType.NFS, remote_path="1:/c", local_mount_point="/mnt/c")
    )

    mount.status = MountStatus.MOUNTED
    updated = repo.save(mount)

    assert updated.status == MountStatus.MOUNTED
    assert repo.get(mount.id).status == MountStatus.MOUNTED


def test_mount_repo_delete(db):
    repo = MountRepository(db)
    mount = repo.add(
        NetworkMount(type=MountType.NFS, remote_path="1:/d", local_mount_point="/mnt/d")
    )
    mount_id = mount.id

    repo.delete(mount)
    assert repo.get(mount_id) is None


# ---------------------------------------------------------------------------
# AuditRepository
# ---------------------------------------------------------------------------


def test_audit_repo_add_minimal(db):
    repo = AuditRepository(db)
    entry = repo.add(action="TEST_EVENT")

    assert entry.id is not None
    assert entry.action == "TEST_EVENT"
    assert entry.user is None
    assert entry.job_id is None
    assert entry.details == {}


def test_audit_repo_add_full(db):
    job = _make_job(db)
    repo = AuditRepository(db)

    entry = repo.add(
        action="JOB_STARTED",
        user="investigator",
        job_id=job.id,
        details={"source": "/data"},
    )

    assert entry.action == "JOB_STARTED"
    assert entry.user == "investigator"
    assert entry.job_id == job.id
    assert entry.details == {"source": "/data"}


def test_audit_repo_add_multiple(db):
    repo = AuditRepository(db)
    repo.add(action="EVENT_ONE")
    repo.add(action="EVENT_TWO")
    repo.add(action="EVENT_THREE")

    from app.models.audit import AuditLog

    count = db.query(AuditLog).count()
    assert count == 3


# ---------------------------------------------------------------------------
# PortRepository
# ---------------------------------------------------------------------------


def _make_hub(db) -> UsbHub:
    hub = UsbHub(name="Test Hub", system_identifier="usb-test-1")
    db.add(hub)
    db.commit()
    db.refresh(hub)
    return hub


def test_port_enabled_defaults_to_false(db):
    hub = _make_hub(db)
    port = UsbPort(hub_id=hub.id, port_number=1, system_path="1-1")
    db.add(port)
    db.commit()
    db.refresh(port)

    assert port.enabled is False


def test_port_repo_set_enabled_toggles_state(db):
    hub = _make_hub(db)
    repo = PortRepository(db)
    port = repo.upsert(hub_id=hub.id, port_number=1, system_path="1-1")

    assert port.enabled is False

    updated = repo.set_enabled(port.id, True)
    assert updated is not None
    assert updated.enabled is True

    updated2 = repo.set_enabled(port.id, False)
    assert updated2 is not None
    assert updated2.enabled is False


def test_port_repo_set_enabled_returns_none_for_missing(db):
    repo = PortRepository(db)
    assert repo.set_enabled(9999, True) is None


def test_port_repo_list_enabled(db):
    hub = _make_hub(db)
    repo = PortRepository(db)
    p1 = repo.upsert(hub_id=hub.id, port_number=1, system_path="1-1")
    p2 = repo.upsert(hub_id=hub.id, port_number=2, system_path="1-2")
    p3 = repo.upsert(hub_id=hub.id, port_number=3, system_path="1-3")

    # None enabled initially
    assert repo.list_enabled() == []

    repo.set_enabled(p1.id, True)
    repo.set_enabled(p3.id, True)

    enabled = repo.list_enabled()
    assert len(enabled) == 2
    enabled_ids = {p.id for p in enabled}
    assert enabled_ids == {p1.id, p3.id}
