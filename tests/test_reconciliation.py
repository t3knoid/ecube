"""Tests for startup state reconciliation (issue #101).

Covers:
- Mount reconciliation: MOUNTED mounts checked against OS, corrected if stale
- Job reconciliation: RUNNING / VERIFYING jobs marked FAILED after restart
- USB drive reconciliation: discovery runs and reconciles drive state
- Orchestrator: all three passes wired together
- Idempotency: running reconciliation twice produces no additional changes
"""

from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort
from app.models.jobs import ExportJob, JobStatus
from app.models.network import MountStatus, MountType, NetworkMount
from app.infrastructure.usb_discovery import (
    DiscoveredDrive,
    DiscoveredHub,
    DiscoveredPort,
    DiscoveredTopology,
)
from app.services.reconciliation_service import (
    reconcile_drives,
    reconcile_jobs,
    reconcile_mounts,
    run_startup_reconciliation,
)


# -----------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------

def _make_mount(db: Session, status: MountStatus = MountStatus.MOUNTED,
                local_mount_point: str = "/mnt/evidence") -> NetworkMount:
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="server:/export",
        local_mount_point=local_mount_point,
        status=status,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)
    return mount


def _make_job(db: Session, status: JobStatus = JobStatus.RUNNING) -> ExportJob:
    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path="/data/source",
        status=status,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_drive(db: Session, device_identifier: str = "USB-001",
                state: DriveState = DriveState.AVAILABLE,
                port_id: Optional[int] = None) -> UsbDrive:
    drive = UsbDrive(
        device_identifier=device_identifier,
        current_state=state,
        port_id=port_id,
        filesystem_path=f"/dev/{device_identifier}",
    )
    db.add(drive)
    db.commit()
    db.refresh(drive)
    return drive


def _make_hub_and_port(db: Session, enabled: bool = True) -> Tuple[UsbHub, UsbPort]:
    hub = UsbHub(name="Hub-1", system_identifier="hub-1")
    db.add(hub)
    db.commit()
    db.refresh(hub)
    port = UsbPort(hub_id=hub.id, port_number=1, system_path="/sys/bus/usb/1-1",
                   enabled=enabled)
    db.add(port)
    db.commit()
    db.refresh(port)
    return hub, port


class FakeMountProvider:
    """Configurable mount provider for testing."""

    def __init__(self, mounted_paths: Optional[set] = None):
        self._mounted = mounted_paths or set()

    def check_mounted(self, local_mount_point: str) -> Optional[bool]:
        if local_mount_point in self._mounted:
            return True
        return False

    def os_mount(self, *args, **kwargs) -> Tuple[bool, Optional[str]]:
        return False, "not implemented in test"

    def os_unmount(self, *args, **kwargs) -> Tuple[bool, Optional[str]]:
        return True, None


class FakeFilesystemDetector:
    def detect(self, path: str) -> str:
        return "ext4"


def _empty_topology() -> DiscoveredTopology:
    return DiscoveredTopology(hubs=[], ports=[], drives=[])


# =======================================================================
# Mount reconciliation tests
# =======================================================================

class TestReconcileMounts:
    """Mount reconciliation: MOUNTED mounts verified against OS."""

    def test_mounted_mount_still_active_no_change(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/active")
        provider = FakeMountProvider(mounted_paths={"/mnt/active"})

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert result["mounts_corrected"] == 0

    def test_stale_mounted_corrected_to_unmounted(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/stale")
        provider = FakeMountProvider(mounted_paths=set())

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.UNMOUNTED
        assert result["mounts_corrected"] == 1

    def test_stale_mount_emits_audit_record(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/audit-test")
        provider = FakeMountProvider(mounted_paths=set())

        reconcile_mounts(db, provider)

        audit = db.query(AuditLog).filter(AuditLog.action == "MOUNT_RECONCILED").first()
        assert audit is not None
        assert audit.details["mount_id"] == mount.id
        assert audit.details["old_status"] == "MOUNTED"
        assert audit.details["new_status"] == "UNMOUNTED"
        assert audit.details["reason"] == "startup reconciliation"

    def test_unmounted_mounts_not_touched(self, db: Session):
        mount = _make_mount(db, MountStatus.UNMOUNTED, "/mnt/already-unmounted")
        provider = FakeMountProvider(mounted_paths=set())

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.UNMOUNTED
        assert result["mounts_checked"] == 0  # Only MOUNTED are checked

    def test_error_status_mounts_not_touched(self, db: Session):
        mount = _make_mount(db, MountStatus.ERROR, "/mnt/error")
        provider = FakeMountProvider(mounted_paths=set())

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.ERROR
        assert result["mounts_checked"] == 0

    def test_check_mounted_returns_none_sets_error(self, db: Session):
        """When check_mounted returns None (OS error), set status to ERROR."""
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/os-error")

        class ErrorProvider(FakeMountProvider):
            def check_mounted(self, local_mount_point: str) -> Optional[bool]:
                return None

        result = reconcile_mounts(db, ErrorProvider())

        db.refresh(mount)
        assert mount.status == MountStatus.ERROR
        assert result["mounts_corrected"] == 1

    def test_multiple_mounts_each_checked(self, db: Session):
        m1 = _make_mount(db, MountStatus.MOUNTED, "/mnt/a")
        m2 = _make_mount(db, MountStatus.MOUNTED, "/mnt/b")
        m3 = _make_mount(db, MountStatus.MOUNTED, "/mnt/c")
        provider = FakeMountProvider(mounted_paths={"/mnt/b"})

        result = reconcile_mounts(db, provider)

        db.refresh(m1)
        db.refresh(m2)
        db.refresh(m3)
        assert m1.status == MountStatus.UNMOUNTED
        assert m2.status == MountStatus.MOUNTED
        assert m3.status == MountStatus.UNMOUNTED
        assert result["mounts_checked"] == 3
        assert result["mounts_corrected"] == 2


# =======================================================================
# Job reconciliation tests
# =======================================================================

class TestReconcileJobs:
    """Job reconciliation: in-progress jobs failed after restart."""

    def test_running_job_marked_failed(self, db: Session):
        job = _make_job(db, JobStatus.RUNNING)

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.status == JobStatus.FAILED
        assert job.completed_at is not None
        assert result["jobs_checked"] == 1
        assert result["jobs_corrected"] == 1

    def test_verifying_job_marked_failed(self, db: Session):
        job = _make_job(db, JobStatus.VERIFYING)

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.status == JobStatus.FAILED
        assert result["jobs_corrected"] == 1

    def test_pending_job_not_touched(self, db: Session):
        job = _make_job(db, JobStatus.PENDING)

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.status == JobStatus.PENDING
        assert result["jobs_checked"] == 0

    def test_completed_job_not_touched(self, db: Session):
        job = _make_job(db, JobStatus.COMPLETED)

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.status == JobStatus.COMPLETED
        assert result["jobs_checked"] == 0

    def test_already_failed_job_not_touched(self, db: Session):
        job = _make_job(db, JobStatus.FAILED)

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.status == JobStatus.FAILED
        assert result["jobs_checked"] == 0

    def test_failed_job_emits_audit_record(self, db: Session):
        job = _make_job(db, JobStatus.RUNNING)

        reconcile_jobs(db)

        audit = db.query(AuditLog).filter(AuditLog.action == "JOB_RECONCILED").first()
        assert audit is not None
        assert audit.job_id == job.id
        assert audit.details["old_status"] == "RUNNING"
        assert audit.details["new_status"] == "FAILED"
        assert audit.details["reason"] == "interrupted by restart"

    def test_multiple_jobs_each_handled(self, db: Session):
        j1 = _make_job(db, JobStatus.RUNNING)
        j2 = _make_job(db, JobStatus.VERIFYING)
        j3 = _make_job(db, JobStatus.PENDING)
        j4 = _make_job(db, JobStatus.COMPLETED)

        result = reconcile_jobs(db)

        db.refresh(j1)
        db.refresh(j2)
        db.refresh(j3)
        db.refresh(j4)
        assert j1.status == JobStatus.FAILED
        assert j2.status == JobStatus.FAILED
        assert j3.status == JobStatus.PENDING
        assert j4.status == JobStatus.COMPLETED
        assert result["jobs_checked"] == 2
        assert result["jobs_corrected"] == 2


# =======================================================================
# USB drive reconciliation tests
# =======================================================================

class TestReconcileDrives:
    """Drive reconciliation delegates to discovery_service."""

    def test_discovery_runs_on_reconciliation(self, db: Session):
        hub, port = _make_hub_and_port(db, enabled=True)
        topology = DiscoveredTopology(
            hubs=[DiscoveredHub(
                system_identifier="hub-1", name="Hub-1",
                location_hint=None, vendor_id=None, product_id=None,
            )],
            ports=[DiscoveredPort(
                hub_system_identifier="hub-1", port_number=1,
                system_path="/sys/bus/usb/1-1",
                vendor_id=None, product_id=None, speed=None,
            )],
            drives=[DiscoveredDrive(
                device_identifier="USB-NEW",
                port_system_path="/sys/bus/usb/1-1",
                filesystem_path="/dev/sdb1",
                capacity_bytes=1_000_000,
            )],
        )

        result = reconcile_drives(
            db,
            topology_source=lambda: topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert result["drives_inserted"] >= 1
        drive = db.query(UsbDrive).filter(
            UsbDrive.device_identifier == "USB-NEW"
        ).first()
        assert drive is not None
        assert drive.current_state == DriveState.AVAILABLE

    def test_absent_available_drive_marked_empty(self, db: Session):
        hub, port = _make_hub_and_port(db, enabled=True)
        drive = _make_drive(db, "USB-GONE", DriveState.AVAILABLE, port_id=port.id)

        result = reconcile_drives(
            db,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        db.refresh(drive)
        assert drive.current_state == DriveState.EMPTY
        assert result["drives_removed"] >= 1

    def test_absent_in_use_drive_preserved(self, db: Session):
        """IN_USE drives retain state for project isolation."""
        hub, port = _make_hub_and_port(db, enabled=True)
        drive = _make_drive(db, "USB-INUSE", DriveState.IN_USE, port_id=port.id)
        drive.current_project_id = "PROJ-001"
        db.commit()

        reconcile_drives(
            db,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        db.refresh(drive)
        assert drive.current_state == DriveState.IN_USE
        assert drive.current_project_id == "PROJ-001"


# =======================================================================
# Orchestrator tests
# =======================================================================

class TestRunStartupReconciliation:
    """Full orchestrator runs all three passes."""

    def test_all_passes_execute(self, db: Session):
        _make_mount(db, MountStatus.MOUNTED, "/mnt/stale")
        _make_job(db, JobStatus.RUNNING)

        provider = FakeMountProvider(mounted_paths=set())

        result = run_startup_reconciliation(
            db, provider,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert "mounts" in result
        assert "jobs" in result
        assert "drives" in result
        assert result["mounts"]["mounts_corrected"] == 1
        assert result["jobs"]["jobs_corrected"] == 1

    def test_one_pass_failure_does_not_block_others(self, db: Session):
        """If mount reconciliation fails, jobs and drives still run."""
        _make_mount(db, MountStatus.MOUNTED, "/mnt/broken")
        _make_job(db, JobStatus.RUNNING)

        class BrokenMountProvider:
            def check_mounted(self, *args):
                raise RuntimeError("OS error")
            def os_mount(self, *args, **kwargs):
                return False, None
            def os_unmount(self, *args, **kwargs):
                return True, None

        result = run_startup_reconciliation(
            db, BrokenMountProvider(),
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        # Mounts errored but jobs still reconciled
        assert "error" in result["mounts"]
        assert result["jobs"]["jobs_corrected"] == 1


# =======================================================================
# Idempotency tests
# =======================================================================

class TestIdempotency:
    """Running reconciliation twice produces no additional changes."""

    def test_mount_reconciliation_idempotent(self, db: Session):
        _make_mount(db, MountStatus.MOUNTED, "/mnt/idem")
        provider = FakeMountProvider(mounted_paths=set())

        r1 = reconcile_mounts(db, provider)
        audit_after_first = db.query(AuditLog).filter(
            AuditLog.action == "MOUNT_RECONCILED"
        ).count()
        r2 = reconcile_mounts(db, provider)
        audit_after_second = db.query(AuditLog).filter(
            AuditLog.action == "MOUNT_RECONCILED"
        ).count()

        assert r1["mounts_corrected"] == 1
        assert r2["mounts_checked"] == 0  # Now UNMOUNTED, not rechecked
        assert r2["mounts_corrected"] == 0
        assert audit_after_first == 1
        assert audit_after_second == 1  # No duplicate audit rows

    def test_job_reconciliation_idempotent(self, db: Session):
        _make_job(db, JobStatus.RUNNING)

        r1 = reconcile_jobs(db)
        audit_after_first = db.query(AuditLog).filter(
            AuditLog.action == "JOB_RECONCILED"
        ).count()
        r2 = reconcile_jobs(db)
        audit_after_second = db.query(AuditLog).filter(
            AuditLog.action == "JOB_RECONCILED"
        ).count()

        assert r1["jobs_corrected"] == 1
        assert r2["jobs_checked"] == 0  # Now FAILED, not rechecked
        assert r2["jobs_corrected"] == 0
        assert audit_after_first == 1
        assert audit_after_second == 1  # No duplicate audit rows

    def test_drive_reconciliation_idempotent(self, db: Session):
        hub, port = _make_hub_and_port(db, enabled=True)
        _make_drive(db, "USB-IDEM", DriveState.AVAILABLE, port_id=port.id)

        r1 = reconcile_drives(
            db,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )
        r2 = reconcile_drives(
            db,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert r1["drives_removed"] >= 1
        assert r2["drives_removed"] == 0  # Already EMPTY
