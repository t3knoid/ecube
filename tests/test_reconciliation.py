"""Tests for startup state reconciliation (issue #101).

Covers:
- Mount reconciliation: MOUNTED mounts checked against OS, corrected if stale
- Job reconciliation: RUNNING / VERIFYING jobs marked FAILED after restart
- USB drive reconciliation: discovery runs and reconciles drive state
- Orchestrator: all three passes wired together
- Idempotency: running reconciliation twice produces no additional changes
"""

import os
import logging
import pytest
from typing import Optional, Tuple
from unittest.mock import patch
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from app.config import settings
from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus, StartupAnalysisEntry, StartupAnalysisStatus
from app.models.network import MountStatus, MountType, NetworkMount
from app.models.system import ReconciliationLock
from app.models.users import UserRole
from app.infrastructure.os_user_protocol import OSUser
from app.infrastructure.usb_discovery import (
    DiscoveredDrive,
    DiscoveredHub,
    DiscoveredPort,
    DiscoveredTopology,
)
from app.services.reconciliation_service import (
    STALE_LOCK_SECONDS,
    _acquire_reconciliation_lock,
    _is_holder_alive,
    _refresh_reconciliation_lock,
    _release_reconciliation_lock,
    reconcile_identity_groups,
    reconcile_identity_users,
    reconcile_drives,
    reconcile_jobs,
    reconcile_mounts,
    run_manual_managed_mount_reconciliation,
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


def _make_job(
    db: Session,
    status: JobStatus = JobStatus.RUNNING,
    *,
    project_id: str = "PROJ-001",
    target_mount_path: str | None = None,
) -> ExportJob:
    job = ExportJob(
        project_id=project_id,
        evidence_number="EV-001",
        source_path="/data/source",
        target_mount_path=target_mount_path,
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

    def __init__(self, mounted_paths: Optional[set] = None, mounted_sources: Optional[dict[str, str]] = None):
        self._mounted = mounted_paths or set()
        self._mounted_sources = mounted_sources or {path: "server:/export" for path in self._mounted}
        self.mount_calls = []
        self.unmount_calls = []

    def check_mounted(self, local_mount_point: str) -> Optional[bool]:
        if local_mount_point in self._mounted or local_mount_point in self._mounted_sources:
            return True
        return False

    def os_mount(self, mount_type, remote_path, local_mount_point, **kwargs) -> Tuple[bool, Optional[str]]:
        self.mount_calls.append((mount_type, remote_path, local_mount_point))
        self._mounted.add(local_mount_point)
        self._mounted_sources[local_mount_point] = remote_path
        return True, None

    def os_unmount(self, local_mount_point, *args, **kwargs) -> Tuple[bool, Optional[str]]:
        self.unmount_calls.append(local_mount_point)
        self._mounted.discard(local_mount_point)
        self._mounted_sources.pop(local_mount_point, None)
        return True, None


class FakeDriveMountProvider:
    def __init__(self, mounted_paths: Optional[dict[str, str]] = None):
        self.mounted_paths = mounted_paths or {}
        self.mount_calls = []
        self.unmount_calls = []

    def mount_drive(self, device_path: str, mount_point: str) -> Tuple[bool, Optional[str]]:
        self.mount_calls.append((device_path, mount_point))
        self.mounted_paths[mount_point] = device_path
        return True, None

    def unmount_drive(self, mount_point: str) -> Tuple[bool, Optional[str]]:
        self.unmount_calls.append(mount_point)
        self.mounted_paths.pop(mount_point, None)
        return True, None


@pytest.fixture(autouse=True)
def _isolate_live_mount_table():
    with patch("app.services.reconciliation_service.read_mount_table", return_value={}):
        yield


@pytest.fixture(autouse=True)
def _allow_mount_validation_directory_checks():
    with (
        patch("app.services.mount_service._ensure_mount_directory", return_value=None),
        patch("app.services.mount_service._validate_mount_directory_owner", return_value=None),
    ):
        yield


class FakeFilesystemDetector:
    def detect(self, path: str) -> str:
        return "ext4"


class FakeOsUserProvider:
    def __init__(
        self,
        created_groups: Optional[list[str]] = None,
        should_fail_groups: bool = False,
        should_fail_users: bool = False,
        existing_users: Optional[dict[str, set[str]]] = None,
    ):
        self.created_groups = created_groups or []
        self.should_fail_groups = should_fail_groups
        self.should_fail_users = should_fail_users
        self.ensure_calls = 0
        self.list_users_calls = 0
        self.users = {u: set(gs) for u, gs in (existing_users or {}).items()}
        self.created_usernames: list[str] = []
        self.updated_group_usernames: list[str] = []

    def ensure_ecube_groups(self) -> list[str]:
        self.ensure_calls += 1
        if self.should_fail_groups:
            raise RuntimeError("group reconciliation failed")
        return list(self.created_groups)

    def list_users(self, ecube_only: bool = True):
        self.list_users_calls += 1
        result = []
        for username, groups in sorted(self.users.items()):
            if ecube_only and not any(g.startswith("ecube-") for g in groups):
                continue
            result.append(OSUser(
                username=username,
                uid=1000,
                gid=1000,
                home=f"/home/{username}",
                shell="/bin/bash",
                groups=sorted(groups),
            ))
        return result

    def user_exists(self, username: str) -> bool:
        return username in self.users

    def create_user(self, username: str, password: str, groups: Optional[list[str]] = None):
        if self.should_fail_users:
            raise RuntimeError("user reconciliation failed")
        self.created_usernames.append(username)
        self.users.setdefault(username, set()).update(groups or [])
        return OSUser(
            username=username,
            uid=1001,
            gid=1001,
            home=f"/home/{username}",
            shell="/bin/bash",
            groups=sorted(self.users[username]),
        )

    def add_user_to_groups(self, username: str, groups: list[str], _skip_managed_check: bool = False):
        if self.should_fail_users:
            raise RuntimeError("user reconciliation failed")
        self.updated_group_usernames.append(username)
        self.users.setdefault(username, set()).update(groups)
        return OSUser(
            username=username,
            uid=1001,
            gid=1001,
            home=f"/home/{username}",
            shell="/bin/bash",
            groups=sorted(self.users[username]),
        )


def _empty_topology() -> DiscoveredTopology:
    return DiscoveredTopology(hubs=[], ports=[], drives=[])


# =======================================================================
# Mount reconciliation tests
# =======================================================================

class TestReconcileMounts:
    """Mount reconciliation: persisted network mounts are restored on startup."""

    def test_mounted_mount_still_active_no_change(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/active")
        provider = FakeMountProvider(mounted_paths={"/mnt/active"})

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert result["mounts_corrected"] == 0

    def test_stale_mounted_is_remounted(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/stale")
        provider = FakeMountProvider(mounted_paths=set())

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_corrected"] == 1
        assert provider.mount_calls == [(MountType.NFS, "server:/export", "/mnt/stale")]

    def test_startup_reconciliation_uses_persisted_nfs_client_version(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/nfs-versioned")
        mount.nfs_client_version = "4.2"
        db.commit()

        class VersionAwareProvider(FakeMountProvider):
            def __init__(self):
                super().__init__(mounted_paths=set())
                self.seen_nfs_versions = []

            def os_mount(self, mount_type, remote_path, local_mount_point, **kwargs) -> Tuple[bool, Optional[str]]:
                self.seen_nfs_versions.append(kwargs.get("nfs_client_version"))
                return super().os_mount(mount_type, remote_path, local_mount_point, **kwargs)

        provider = VersionAwareProvider()

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_corrected"] == 1
        assert provider.seen_nfs_versions == ["4.2"]

    def test_unexpected_live_unmounted_mount_is_removed(self, db: Session):
        mount = _make_mount(db, MountStatus.UNMOUNTED, "/nfs/unexpected")
        provider = FakeMountProvider(mounted_sources={"/nfs/unexpected": "server:/wrong-export"})

        with patch("app.services.reconciliation_service.read_mount_table", return_value={"/nfs/unexpected": "server:/wrong-export"}):
            result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_corrected"] == 1
        assert provider.unmount_calls == ["/nfs/unexpected"]
        assert provider.mount_calls == [(MountType.NFS, "server:/export", "/nfs/unexpected")]

    def test_orphan_generated_network_mount_is_removed(self, db: Session):
        provider = FakeMountProvider(mounted_sources={"/nfs/orphan": "server:/orphan"})

        with patch("app.services.reconciliation_service.read_mount_table", return_value={"/nfs/orphan": "server:/orphan"}):
            result = reconcile_mounts(db, provider)

        assert result["mounts_corrected"] == 1
        assert provider.unmount_calls == ["/nfs/orphan"]

    def test_orphan_generated_network_mount_emits_audit_record(self, db: Session):
        provider = FakeMountProvider(mounted_sources={"/nfs/orphan": "server:/orphan"})

        with patch("app.services.reconciliation_service.read_mount_table", return_value={"/nfs/orphan": "server:/orphan"}):
            reconcile_mounts(db, provider)

        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "MOUNT_RECONCILED")
            .filter(AuditLog.details["reason"].as_string() == "orphan_managed_mount_removed")
            .first()
        )
        assert audit is not None
        assert audit.details["old_status"] == "MOUNTED"
        assert audit.details["new_status"] == "UNMOUNTED"
        assert audit.details["managed_area"] == "nfs"

    def test_persisted_usb_mount_is_remounted_to_expected_slot(self, db: Session):
        drive = _make_drive(db, "USB-STARTUP", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = "PROJ-STARTUP"
        drive.mount_path = "/mnt/ecube/stale"
        db.commit()
        drive_provider = FakeDriveMountProvider()

        with patch("app.services.reconciliation_service.find_device_mount_point", return_value=None):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive_provider.mount_calls == [(drive.filesystem_path, f"{settings.usb_mount_base_path}/{drive.id}")]

        db.refresh(drive)
        assert drive.mount_path == f"{settings.usb_mount_base_path}/{drive.id}"

    def test_in_use_usb_drive_with_cleared_mount_path_is_remounted(self, db: Session):
        drive = _make_drive(db, "USB-STARTUP-CLEARED", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = "PROJ-STARTUP"
        drive.mount_path = None
        db.commit()
        drive_provider = FakeDriveMountProvider()

        with patch("app.services.reconciliation_service.find_device_mount_point", return_value=None):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive_provider.mount_calls == [(drive.filesystem_path, f"{settings.usb_mount_base_path}/{drive.id}")]
        assert drive.mount_path == f"{settings.usb_mount_base_path}/{drive.id}"

    def test_persisted_usb_mount_outside_managed_root_is_unmounted_before_remount(self, db: Session):
        drive = _make_drive(db, "USB-STARTUP-EXTERNAL", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = "PROJ-STARTUP"
        drive.mount_path = "/mnt/ecube/stale"
        db.commit()
        drive_provider = FakeDriveMountProvider()

        with patch("app.services.reconciliation_service.find_device_mount_point", return_value="/media/operator/usb-startup"):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive_provider.unmount_calls == ["/media/operator/usb-startup"]
        assert drive_provider.mount_calls == [(drive.filesystem_path, f"{settings.usb_mount_base_path}/{drive.id}")]

    def test_persisted_usb_mount_cleanup_and_remount_counts_once(self, db: Session):
        drive = _make_drive(db, "USB-STARTUP-MANAGED", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = "PROJ-STARTUP"
        drive.mount_path = "/mnt/ecube/stale"
        db.commit()
        drive_provider = FakeDriveMountProvider()

        with patch("app.services.reconciliation_service.find_device_mount_point", return_value="/mnt/ecube/999"):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive_provider.unmount_calls == ["/mnt/ecube/999"]
        assert drive_provider.mount_calls == [(drive.filesystem_path, f"{settings.usb_mount_base_path}/{drive.id}")]

    def test_orphan_managed_usb_mount_is_removed(self, db: Session):
        drive_provider = FakeDriveMountProvider({"/mnt/ecube/999": "/dev/sdz1"})

        with patch("app.services.reconciliation_service.read_mount_table", return_value={"/mnt/ecube/999": "/dev/sdz1"}):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        assert result["usb_mounts_corrected"] == 1
        assert drive_provider.unmount_calls == ["/mnt/ecube/999"]

    def test_usb_mount_restores_missing_project_binding_from_matching_job(self, db: Session):
        drive = _make_drive(db, "USB-RECOVER", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        job = _make_job(
            db,
            project_id="PROJ-RECOVER",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
        db.commit()

        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive.current_state == DriveState.IN_USE
        assert drive.current_project_id == "PROJ-RECOVER"
        assert drive_provider.unmount_calls == []
        assert drive_provider.mount_calls == []

    def test_usb_mount_restores_missing_project_binding_when_multiple_jobs_share_one_project(self, db: Session):
        drive = _make_drive(db, "USB-SHARED-PROJECT", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        job_one = _make_job(
            db,
            project_id="PROJ-SAME",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        job_two = _make_job(
            db,
            project_id="PROJ-SAME",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        db.add_all([
            DriveAssignment(drive_id=drive.id, job_id=job_one.id),
            DriveAssignment(drive_id=drive.id, job_id=job_two.id),
        ])
        db.commit()

        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert drive.current_state == DriveState.IN_USE
        assert drive.current_project_id == "PROJ-SAME"
        assert drive_provider.unmount_calls == []

    def test_usb_mount_with_no_relevant_owner_is_released(self, db: Session):
        drive = _make_drive(db, "USB-ORPHANED", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        db.commit()

        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            result = reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive.current_state == DriveState.AVAILABLE
        assert drive.current_project_id is None
        assert drive.mount_path is None
        assert drive_provider.unmount_calls == [f"{settings.usb_mount_base_path}/{drive.id}"]
        assert drive_provider.mount_calls == []

    def test_usb_mount_with_conflicting_project_owners_is_released(self, db: Session):
        drive = _make_drive(db, "USB-CONFLICT", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        job_one = _make_job(
            db,
            project_id="PROJ-A",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        job_two = _make_job(
            db,
            project_id="PROJ-B",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        db.add_all([
            DriveAssignment(drive_id=drive.id, job_id=job_one.id),
            DriveAssignment(drive_id=drive.id, job_id=job_two.id),
        ])
        db.commit()

        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert drive.current_state == DriveState.AVAILABLE
        assert drive.current_project_id is None
        assert drive.mount_path is None
        assert drive_provider.unmount_calls == [f"{settings.usb_mount_base_path}/{drive.id}"]

    def test_released_assignments_do_not_restore_missing_project_binding(self, db: Session):
        drive = _make_drive(db, "USB-RELEASED-ONLY", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        job = _make_job(
            db,
            project_id="PROJ-OLD",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        db.add(
            DriveAssignment(
                drive_id=drive.id,
                job_id=job.id,
                released_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert drive.current_state == DriveState.AVAILABLE
        assert drive.current_project_id is None
        assert drive_provider.unmount_calls == [f"{settings.usb_mount_base_path}/{drive.id}"]

    def test_unreleased_assignment_with_different_target_does_not_restore_binding(self, db: Session):
        drive = _make_drive(db, "USB-STALE-ACTIVE", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        job = _make_job(
            db,
            project_id="PROJ-STALE",
            target_mount_path="/mnt/ecube/other-drive",
        )
        db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
        db.commit()

        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            reconcile_mounts(db, FakeMountProvider(), drive_provider)

        db.refresh(drive)
        assert drive.current_state == DriveState.AVAILABLE
        assert drive.current_project_id is None
        assert drive.mount_path is None
        assert drive_provider.unmount_calls == [f"{settings.usb_mount_base_path}/{drive.id}"]

    def test_stale_mount_emits_audit_record(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/audit-test")
        provider = FakeMountProvider(mounted_paths=set())

        reconcile_mounts(db, provider)

        audit = db.query(AuditLog).filter(AuditLog.action == "MOUNT_RECONCILED").first()
        assert audit is not None
        assert audit.details["mount_id"] == mount.id
        assert audit.details["old_status"] == "MOUNTED"
        assert audit.details["new_status"] == "MOUNTED"
        assert audit.details["reason"] == "startup reconciliation"

    def test_unmounted_mounts_are_remounted(self, db: Session):
        mount = _make_mount(db, MountStatus.UNMOUNTED, "/mnt/already-unmounted")
        provider = FakeMountProvider(mounted_paths=set())

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert provider.mount_calls == [(MountType.NFS, "server:/export", "/mnt/already-unmounted")]

    def test_error_status_mounts_are_remounted(self, db: Session):
        mount = _make_mount(db, MountStatus.ERROR, "/mnt/error")
        provider = FakeMountProvider(mounted_paths=set())

        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert provider.mount_calls == [(MountType.NFS, "server:/export", "/mnt/error")]

    def test_unmounted_live_expected_mount_is_marked_mounted(self, db: Session):
        mount = _make_mount(db, MountStatus.UNMOUNTED, "/nfs/expected-live")
        provider = FakeMountProvider(mounted_sources={"/nfs/expected-live": "server:/export"})

        with patch("app.services.reconciliation_service.read_mount_table", return_value={"/nfs/expected-live": "server:/export"}):
            result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_corrected"] == 1
        assert provider.mount_calls == []

    def test_check_mounted_returns_none_sets_error(self, db: Session):
        """When the OS check is inconclusive, startup still attempts a remount."""
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/os-error")

        class ErrorProvider(FakeMountProvider):
            def check_mounted(self, local_mount_point: str) -> Optional[bool]:
                return None

        result = reconcile_mounts(db, ErrorProvider())

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_corrected"] == 1

    def test_check_mounted_exception_treated_as_error(self, db: Session):
        """An exception from check_mounted is caught and treated as ERROR."""
        m1 = _make_mount(db, MountStatus.MOUNTED, "/mnt/broken")
        m2 = _make_mount(db, MountStatus.MOUNTED, "/mnt/ok")

        class PartialBrokenProvider(FakeMountProvider):
            def check_mounted(self, local_mount_point: str) -> Optional[bool]:
                if local_mount_point == "/mnt/broken":
                    raise RuntimeError("OS error")
                return True  # /mnt/ok is fine

        result = reconcile_mounts(db, PartialBrokenProvider())

        db.refresh(m1)
        db.refresh(m2)
        assert m1.status == MountStatus.ERROR
        assert m2.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 2
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
        assert m1.status == MountStatus.MOUNTED
        assert m2.status == MountStatus.MOUNTED
        assert m3.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 3
        assert result["mounts_corrected"] == 2

    def test_mismatched_live_network_mount_cleanup_and_remount_counts_once(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/nfs/project-a")
        provider = FakeMountProvider(mounted_sources={"/nfs/project-a": "server:/wrong-export"})

        with patch("app.services.reconciliation_service.read_mount_table", return_value={"/nfs/project-a": "server:/wrong-export"}):
            result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert result["mounts_corrected"] == 1
        assert provider.unmount_calls == ["/nfs/project-a"]
        assert provider.mount_calls == [(MountType.NFS, "server:/export", "/nfs/project-a")]

    def test_reconcile_mounts_passes_configured_timeout(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/timeout-aware")

        class TimeoutAwareProvider(FakeMountProvider):
            def __init__(self):
                super().__init__(mounted_paths={"/mnt/timeout-aware"})
                self.seen_timeouts = []

            def check_mounted(self, local_mount_point: str, *, timeout_seconds=None) -> Optional[bool]:
                self.seen_timeouts.append(timeout_seconds)
                return super().check_mounted(local_mount_point)

        provider = TimeoutAwareProvider()
        result = reconcile_mounts(db, provider)

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert provider.seen_timeouts == [settings.subprocess_timeout_seconds]

    def test_reconcile_mounts_legacy_provider_without_timeout_kw(self, db: Session):
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/legacy-provider")

        class LegacyProvider(FakeMountProvider):
            def check_mounted(self, local_mount_point: str) -> Optional[bool]:
                return super().check_mounted(local_mount_point)

        result = reconcile_mounts(db, LegacyProvider(mounted_paths={"/mnt/legacy-provider"}))

        db.refresh(mount)
        assert mount.status == MountStatus.MOUNTED
        assert result["mounts_checked"] == 1
        assert result["mounts_corrected"] == 0


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
        assert job.failure_reason == "Job interrupted by service restart before completion"
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

    def test_stale_startup_analysis_without_valid_cache_resets_to_not_analyzed(self, db: Session):
        job = ExportJob(
            project_id="PROJ-RECON-ANALYZE-001",
            evidence_number="EV-RECON-ANALYZE-001",
            source_path="/data/recon-analyze-001",
            status=JobStatus.PENDING,
            startup_analysis_status=StartupAnalysisStatus.ANALYZING,
            startup_analysis_failure_reason="stale state",
        )
        db.add(job)
        db.commit()

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.startup_analysis_status == StartupAnalysisStatus.NOT_ANALYZED
        assert job.startup_analysis_failure_reason is None
        assert result["jobs_checked"] == 1
        assert result["jobs_corrected"] == 1
        assert result["startup_analysis_checked"] == 1
        assert result["startup_analysis_corrected"] == 1

        audit = db.query(AuditLog).filter(AuditLog.action == "JOB_STARTUP_ANALYSIS_RECONCILED").first()
        assert audit is not None
        assert audit.job_id == job.id
        assert audit.details["old_status"] == "ANALYZING"
        assert audit.details["new_status"] == "NOT_ANALYZED"
        assert audit.details["reason"] == "analysis_interrupted_by_restart"

    def test_stale_startup_analysis_with_current_cache_restores_ready(self, db: Session, tmp_path):
        source_dir = tmp_path / "startup-analysis"
        source_dir.mkdir()
        sample_file = source_dir / "sample.txt"
        sample_file.write_text("abc")
        analyzed_at = datetime(2026, 5, 1, tzinfo=timezone.utc)

        job = ExportJob(
            project_id="PROJ-RECON-ANALYZE-002",
            evidence_number="EV-RECON-ANALYZE-002",
            source_path=str(source_dir),
            status=JobStatus.PENDING,
            startup_analysis_status=StartupAnalysisStatus.ANALYZING,
            startup_analysis_last_analyzed_at=analyzed_at,
            startup_analysis_cache_present=True,
            startup_analysis_revision=1,
            startup_analysis_file_count=1,
            startup_analysis_total_bytes=3,
        )
        db.add(job)
        db.flush()
        db.add(
            ExportFile(
                job_id=job.id,
                project_id=job.project_id,
                relative_path="sample.txt",
                size_bytes=3,
                status=FileStatus.PENDING,
                startup_analysis_revision=1,
            )
        )
        db.add(
            StartupAnalysisEntry(
                job_id=job.id,
                entry_type="directory",
                relative_path="",
                mtime_ns=source_dir.stat().st_mtime_ns,
            )
        )
        db.commit()

        result = reconcile_jobs(db)

        db.refresh(job)
        assert job.startup_analysis_status == StartupAnalysisStatus.READY
        restored_analyzed_at = job.startup_analysis_last_analyzed_at
        assert restored_analyzed_at is not None
        assert restored_analyzed_at.replace(tzinfo=timezone.utc) == analyzed_at
        assert job.file_count == 1
        assert job.total_bytes == 3
        assert result["jobs_checked"] == 1
        assert result["jobs_corrected"] == 1
        assert result["startup_analysis_checked"] == 1
        assert result["startup_analysis_corrected"] == 1

        audit = db.query(AuditLog).filter(AuditLog.action == "JOB_STARTUP_ANALYSIS_RECONCILED").first()
        assert audit is not None
        assert audit.job_id == job.id
        assert audit.details["new_status"] == "READY"
        assert audit.details["reason"] == "valid_cache_restored_after_restart"

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

    def test_mounted_discovered_drive_promoted_to_in_use(self, db: Session):
        hub, port = _make_hub_and_port(db, enabled=True)
        drive = _make_drive(db, "USB-MOUNTED", DriveState.AVAILABLE, port_id=port.id)
        drive.current_project_id = "PROJ-001"
        drive.mount_path = "/mnt/ecube/stale"
        db.commit()

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
                device_identifier="USB-MOUNTED",
                port_system_path="/sys/bus/usb/1-1",
                filesystem_path="/dev/sdb1",
                mount_path="/media/ecube/usb-mounted",
                capacity_bytes=1_000_000,
            )],
        )

        result = reconcile_drives(
            db,
            topology_source=lambda: topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        db.refresh(drive)
        assert result["drives_updated"] >= 1
        assert drive.current_state == DriveState.IN_USE
        assert drive.mount_path == "/media/ecube/usb-mounted"

    def test_absent_available_drive_marked_empty(self, db: Session):
        hub, port = _make_hub_and_port(db, enabled=True)
        drive = _make_drive(db, "USB-GONE", DriveState.AVAILABLE, port_id=port.id)

        result = reconcile_drives(
            db,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        db.refresh(drive)
        assert drive.current_state == DriveState.DISCONNECTED
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
# Identity reconciliation tests
# =======================================================================

class TestReconcileIdentityGroups:
    def test_creates_missing_default_groups(self):
        provider = FakeOsUserProvider(created_groups=["ecube-processors", "ecube-auditors"])

        result = reconcile_identity_groups(provider)

        assert provider.ensure_calls == 1
        assert result["groups_created"] == 2
        assert result["created_group_names"] == ["ecube-processors", "ecube-auditors"]

    def test_noop_when_groups_already_exist(self):
        provider = FakeOsUserProvider(created_groups=[])

        result = reconcile_identity_groups(provider)

        assert provider.ensure_calls == 1
        assert result["groups_created"] == 0
        assert result["created_group_names"] == []


class TestReconcileIdentityUsers:
    def test_reports_missing_os_user_from_db_roles_without_creating(self, db: Session):
        db.add(UserRole(username="frank", role="manager"))
        db.commit()

        provider = FakeOsUserProvider(existing_users={"admin": {"ecube-admins"}})
        result = reconcile_identity_users(db, provider)

        assert result["users_checked"] == 1
        assert result["users_created"] == 0
        assert result["users_missing_os_account"] == 1
        assert result["users_groups_updated"] == 0
        assert result["users_created_password_reset_required"] == 0
        assert provider.created_usernames == []
        assert "frank" not in provider.users

    def test_syncs_missing_groups_for_existing_os_user(self, db: Session):
        db.add(UserRole(username="frank", role="manager"))
        db.add(UserRole(username="frank", role="auditor"))
        db.commit()

        provider = FakeOsUserProvider(existing_users={"frank": {"ecube-managers"}})
        result = reconcile_identity_users(db, provider)

        assert result["users_created"] == 0
        assert result["users_missing_os_account"] == 0
        assert result["users_groups_updated"] == 1
        assert provider.updated_group_usernames == ["frank"]
        assert "ecube-auditors" in provider.users["frank"]

    def test_does_not_scan_all_os_users(self, db: Session):
        db.add(UserRole(username="frank", role="manager"))
        db.commit()

        provider = FakeOsUserProvider(existing_users={"frank": {"ecube-managers"}})
        result = reconcile_identity_users(db, provider)

        assert result["users_with_errors"] == 0
        assert provider.list_users_calls == 0

    def test_user_reconcile_failure_reported(self, db: Session):
        db.add(UserRole(username="frank", role="manager"))
        db.commit()

        provider = FakeOsUserProvider(
            should_fail_users=True,
            existing_users={"frank": set()},
        )
        result = reconcile_identity_users(db, provider)

        assert result["users_with_errors"] == 1
        assert result["errors"][0]["username"] == "frank"


# =======================================================================
# Manual managed-mount reconciliation tests
# =======================================================================

class TestRunManualManagedMountReconciliation:
    """Manual path runs only managed-mount convergence and records a safe summary."""

    def test_runs_mount_pass_only(self, db: Session):
        provider = FakeMountProvider(mounted_paths=set())
        drive_provider = FakeDriveMountProvider()

        with (
            patch("app.services.reconciliation_service.reconcile_mounts", return_value={
                "mounts_checked": 2,
                "mounts_corrected": 1,
                "mount_failures": 0,
                "usb_mounts_checked": 1,
                "usb_mounts_corrected": 0,
                "usb_mount_failures": 0,
            }) as reconcile_mounts_mock,
            patch("app.services.reconciliation_service.reconcile_jobs") as reconcile_jobs_mock,
            patch("app.services.reconciliation_service.reconcile_drives") as reconcile_drives_mock,
            patch("app.services.reconciliation_service.reconcile_identity_groups") as reconcile_groups_mock,
            patch("app.services.reconciliation_service.reconcile_identity_users") as reconcile_users_mock,
        ):
            result = run_manual_managed_mount_reconciliation(
                db,
                provider,
                drive_mount_provider=drive_provider,
                actor="manager-user",
            )

        reconcile_mounts_mock.assert_called_once_with(db, provider, drive_provider)
        reconcile_jobs_mock.assert_not_called()
        reconcile_drives_mock.assert_not_called()
        reconcile_groups_mock.assert_not_called()
        reconcile_users_mock.assert_not_called()

        assert result["status"] == "ok"
        assert result["scope"] == "managed_mounts_only"
        assert result["network_mounts_checked"] == 2
        assert result["network_mounts_corrected"] == 1
        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 0
        assert result["failure_count"] == 0

        audit = db.query(AuditLog).filter(AuditLog.action == "MANUAL_MOUNT_RECONCILIATION").first()
        assert audit is not None
        assert audit.details["status"] == "ok"
        assert audit.details["failure_count"] == 0

    def test_reports_partial_when_corrective_operations_fail(self, db: Session):
        provider = FakeMountProvider(mounted_paths=set())
        drive_provider = FakeDriveMountProvider()

        with patch("app.services.reconciliation_service.reconcile_mounts", return_value={
            "mounts_checked": 2,
            "mounts_corrected": 0,
            "mount_failures": 1,
            "usb_mounts_checked": 1,
            "usb_mounts_corrected": 0,
            "usb_mount_failures": 1,
        }):
            result = run_manual_managed_mount_reconciliation(
                db,
                provider,
                drive_mount_provider=drive_provider,
                actor="manager-user",
            )

        assert result["status"] == "partial"
        assert result["failure_count"] == 2

    def test_manual_reconciliation_reuses_usb_ownership_recovery_logic(self, db: Session):
        drive = _make_drive(db, "USB-MANUAL-RECOVER", DriveState.IN_USE)
        drive.filesystem_type = "ext4"
        drive.current_project_id = None
        drive.mount_path = f"{settings.usb_mount_base_path}/{drive.id}"
        job = _make_job(
            db,
            project_id="PROJ-MANUAL",
            target_mount_path=f"{settings.usb_mount_base_path}/{drive.id}",
        )
        db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
        db.commit()

        provider = FakeMountProvider(mounted_paths=set())
        drive_provider = FakeDriveMountProvider({f"{settings.usb_mount_base_path}/{drive.id}": drive.filesystem_path})

        with patch(
            "app.services.reconciliation_service.find_device_mount_point",
            return_value=f"{settings.usb_mount_base_path}/{drive.id}",
        ):
            result = run_manual_managed_mount_reconciliation(
                db,
                provider,
                drive_mount_provider=drive_provider,
                actor="manager-user",
            )

        db.refresh(drive)
        assert result["status"] == "ok"
        assert result["usb_mounts_checked"] == 1
        assert result["usb_mounts_corrected"] == 1
        assert drive.current_state == DriveState.IN_USE
        assert drive.current_project_id == "PROJ-MANUAL"

    def test_rejects_when_lock_already_held(self, db: Session):
        assert _acquire_reconciliation_lock(db) is True

        provider = FakeMountProvider(mounted_paths=set())
        drive_provider = FakeDriveMountProvider()

        with pytest.raises(Exception) as exc_info:
            run_manual_managed_mount_reconciliation(
                db,
                provider,
                drive_mount_provider=drive_provider,
                actor="manager-user",
            )

        assert getattr(exc_info.value, "status_code", None) == 409
        assert getattr(exc_info.value, "code", None) == "MANUAL_RECONCILIATION_IN_PROGRESS"
        _release_reconciliation_lock(db)


# =======================================================================
# Orchestrator tests
# =======================================================================

class TestRunStartupReconciliation:
    """Full orchestrator runs all three passes."""

    def test_all_passes_execute(self, db: Session):
        _make_mount(db, MountStatus.MOUNTED, "/mnt/stale")
        _make_job(db, JobStatus.RUNNING)

        provider = FakeMountProvider(mounted_paths=set())
        drive_provider = FakeDriveMountProvider()
        os_user_provider = FakeOsUserProvider(created_groups=["ecube-processors"])

        result = run_startup_reconciliation(
            db, provider,
            drive_mount_provider=drive_provider,
            os_user_provider=os_user_provider,
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert "identity" in result
        assert "groups" in result["identity"]
        assert "users" in result["identity"]
        assert "mounts" in result
        assert "jobs" in result
        assert "drives" in result
        assert result["identity"]["groups"]["groups_created"] == 1
        assert result["mounts"]["mounts_corrected"] == 1
        assert result["jobs"]["jobs_corrected"] == 1

    def test_jobs_pass_emits_immediate_result_log(self, db: Session, caplog):
        _make_job(db, JobStatus.RUNNING)

        provider = FakeMountProvider(mounted_paths=set())
        drive_provider = FakeDriveMountProvider()

        with caplog.at_level(logging.INFO):
            run_startup_reconciliation(
                db,
                provider,
                drive_mount_provider=drive_provider,
                topology_source=_empty_topology,
                filesystem_detector=FakeFilesystemDetector(),
            )

        matches = [
            record for record in caplog.records
            if record.getMessage() == "Startup reconciliation: jobs result"
        ]
        assert len(matches) == 1
        assert getattr(matches[0], "status", None) == "ok"
        assert getattr(matches[0], "jobs_checked", None) == 1
        assert getattr(matches[0], "jobs_corrected", None) == 1
        assert getattr(matches[0], "startup_analysis_checked", None) == 0
        assert getattr(matches[0], "startup_analysis_corrected", None) == 0

    def test_identity_failure_does_not_block_other_passes(self, db: Session):
        _make_mount(db, MountStatus.MOUNTED, "/mnt/stale")
        _make_job(db, JobStatus.RUNNING)

        result = run_startup_reconciliation(
            db,
            FakeMountProvider(mounted_paths=set()),
            drive_mount_provider=FakeDriveMountProvider(),
            os_user_provider=FakeOsUserProvider(should_fail_groups=True),
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert result["identity"]["groups"]["error"] == "identity group reconciliation failed"
        assert result["mounts"]["mounts_corrected"] == 1
        assert result["jobs"]["jobs_corrected"] == 1

    def test_one_pass_failure_does_not_block_others(self, db: Session):
        """A per-mount exception is caught; jobs and drives still run."""
        mount = _make_mount(db, MountStatus.MOUNTED, "/mnt/broken")
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
            drive_mount_provider=FakeDriveMountProvider(),
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        # Exception treated as None → mount transitions to ERROR
        db.refresh(mount)
        assert mount.status == MountStatus.ERROR
        assert result["mounts"]["mounts_corrected"] == 1
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
        assert r2["mounts_checked"] == 1
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


# =======================================================================
# Cross-process reconciliation lock tests
# =======================================================================

class TestReconciliationLock:
    """Tests for the single-row reconciliation lock guard."""

    def test_lock_acquired_and_released(self, db: Session):
        """Lock can be acquired and then released cleanly."""
        assert _acquire_reconciliation_lock(db) is True
        assert db.query(ReconciliationLock).count() == 1
        assert _release_reconciliation_lock(db) is True
        assert db.query(ReconciliationLock).count() == 0

    def test_second_acquire_blocked(self, db: Session):
        """A second acquire fails while the first lock is held."""
        assert _acquire_reconciliation_lock(db) is True
        assert _acquire_reconciliation_lock(db) is False
        # Cleanup
        _release_reconciliation_lock(db)

    def test_stale_lock_reclaimed(self, db: Session):
        """A lock older than STALE_LOCK_SECONDS with a dead PID is reclaimed."""
        stale_time = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_LOCK_SECONDS + 60,
        )
        db.add(ReconciliationLock(id=1, locked_by="pid-99999", locked_at=stale_time))
        db.commit()

        # Mock os.kill to raise ProcessLookupError (Linux behaviour);
        # on Windows os.kill raises a generic OSError for dead PIDs.
        with patch("app.services.reconciliation_service.os.kill",
                   side_effect=ProcessLookupError), \
             patch("app.services.reconciliation_service.os.name", "posix"):
            assert _acquire_reconciliation_lock(db) is True
        lock = db.query(ReconciliationLock).first()
        assert lock is not None
        assert lock.locked_by != "pid-99999"
        _release_reconciliation_lock(db)

    def test_stale_lock_not_reclaimed_when_holder_alive(self, db: Session):
        """A stale lock whose holder PID is still alive is NOT reclaimed."""
        stale_time = datetime.now(timezone.utc) - timedelta(
            seconds=STALE_LOCK_SECONDS + 60,
        )
        # Use our own PID — guaranteed to be alive
        alive_pid = f"pid-{os.getpid()}"
        db.add(ReconciliationLock(id=1, locked_by=alive_pid, locked_at=stale_time))
        db.commit()

        assert _acquire_reconciliation_lock(db) is False
        lock = db.query(ReconciliationLock).first()
        assert lock.locked_by == alive_pid
        _release_reconciliation_lock(db)

    def test_fresh_lock_not_reclaimed(self, db: Session):
        """A recently-acquired lock is not considered stale."""
        fresh_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        db.add(ReconciliationLock(id=1, locked_by="active-worker", locked_at=fresh_time))
        db.commit()

        assert _acquire_reconciliation_lock(db) is False
        lock = db.query(ReconciliationLock).first()
        assert lock.locked_by == "active-worker"
        _release_reconciliation_lock(db)

    def test_orchestrator_skips_when_locked(self, db: Session):
        """Orchestrator returns ``skipped`` when another worker holds the lock."""
        db.add(ReconciliationLock(
            id=1,
            locked_by="other-worker",
            locked_at=datetime.now(timezone.utc),
        ))
        db.commit()

        result = run_startup_reconciliation(
            db,
            FakeMountProvider(),
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert result == {"skipped": True}
        # Lock is untouched (still held by other-worker)
        lock = db.query(ReconciliationLock).first()
        assert lock.locked_by == "other-worker"

    def test_orchestrator_releases_lock_after_success(self, db: Session):
        """Lock is released after a successful orchestrator run."""
        result = run_startup_reconciliation(
            db,
            FakeMountProvider(),
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        assert "skipped" not in result
        assert db.query(ReconciliationLock).count() == 0

    def test_is_holder_alive_dead_pid(self):
        """_is_holder_alive returns False for a non-existent PID."""
        with patch("app.services.reconciliation_service.os.kill",
                   side_effect=ProcessLookupError), \
             patch("app.services.reconciliation_service.os.name", "posix"):
            assert _is_holder_alive("pid-99999") is False

    def test_is_holder_alive_current_pid(self):
        """_is_holder_alive returns True for the current process."""
        assert _is_holder_alive(f"pid-{os.getpid()}") is True

    def test_is_holder_alive_unknown_format(self):
        """_is_holder_alive assumes alive for unrecognised formats."""
        assert _is_holder_alive("unknown-format") is True
        assert _is_holder_alive("") is True

    def test_refresh_extends_lock_timestamp(self, db: Session):
        """_refresh_reconciliation_lock updates locked_at to a newer time."""
        old_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        db.add(ReconciliationLock(id=1, locked_by="pid-1", locked_at=old_time))
        db.commit()

        _refresh_reconciliation_lock(db)

        lock = db.query(ReconciliationLock).first()
        # locked_at should be much more recent than old_time
        refreshed = lock.locked_at.replace(tzinfo=None)
        original = old_time.replace(tzinfo=None)
        assert refreshed > original
        _release_reconciliation_lock(db)

    def test_orchestrator_releases_lock_after_failure(self, db: Session):
        """Lock is released even when a mount check raises an exception."""
        _make_mount(db, MountStatus.MOUNTED, "/mnt/broken")

        class BrokenMountProvider:
            def check_mounted(self, *args):
                raise RuntimeError("OS error")
            def os_mount(self, *args, **kwargs):
                return False, None
            def os_unmount(self, *args, **kwargs):
                return True, None

        result = run_startup_reconciliation(
            db,
            BrokenMountProvider(),
            topology_source=_empty_topology,
            filesystem_detector=FakeFilesystemDetector(),
        )

        # Exception caught per-mount, treated as ERROR — pass still succeeds
        assert result["mounts"]["mounts_corrected"] == 1
        assert db.query(ReconciliationLock).count() == 0
