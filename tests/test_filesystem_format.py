"""Tests for filesystem detection, drive formatting, and initialize guard.

Uses fake implementations of FilesystemDetector and DriveFormatter protocols
to avoid any real OS calls.  All tests use the in-memory SQLite database from
conftest.py.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from app.infrastructure.filesystem_detection import FilesystemDetector
from app.infrastructure.drive_format import DriveFormatter, LinuxDriveFormatter
from app.logging_config import TextFormatter
from app.infrastructure.usb_discovery import (
    DiscoveredDrive,
    DiscoveredHub,
    DiscoveredPort,
    DiscoveredTopology,
)
from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.network import MountStatus, MountType, NetworkMount
from app.services import discovery_service, drive_service
from app.utils.sanitize import sanitize_error_message


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeFilesystemDetector:
    """Fake that returns a pre-configured filesystem type."""

    def __init__(self, result: str = "ext4"):
        self.result = result
        self.calls: list[str] = []

    def detect(self, device_path: str) -> str:
        self.calls.append(device_path)
        return self.result


class FakeFormatter:
    """Fake formatter that records calls and optionally raises."""

    def __init__(
        self,
        *,
        fail: bool = False,
        mounted: bool = False,
        free_bytes_result: int | None = None,
        free_bytes_error: Exception | None = None,
    ):
        self._fail = fail
        self._mounted = mounted
        self._free_bytes_result = free_bytes_result
        self._free_bytes_error = free_bytes_error
        self.format_calls: list[tuple[str, str]] = []
        self.mounted_calls: list[str] = []
        self.free_bytes_calls: list[tuple[str, str]] = []

    def format(self, device_path: str, filesystem_type: str) -> None:
        self.format_calls.append((device_path, filesystem_type))
        if self._fail:
            raise RuntimeError("mkfs failed: simulated error")

    def is_mounted(self, device_path: str) -> bool:
        self.mounted_calls.append(device_path)
        return self._mounted

    def probe_free_bytes(self, device_path: str, filesystem_type: str) -> int | None:
        self.free_bytes_calls.append((device_path, filesystem_type))
        if self._free_bytes_error is not None:
            raise self._free_bytes_error
        return self._free_bytes_result


def test_linux_drive_formatter_uses_sudo_when_configured(monkeypatch):
    formatter = LinuxDriveFormatter()

    monkeypatch.setattr("app.infrastructure.drive_format.settings.use_sudo", True)
    monkeypatch.setattr("app.infrastructure.drive_format.os.geteuid", lambda: 1000)

    with patch("app.infrastructure.drive_format.subprocess.run") as mock_run:
        formatter.format("/dev/sdb", "ext4")

    cmd = mock_run.call_args.args[0]
    assert cmd[:2] == ["sudo", "-n"]
    assert cmd[-2:] == ["/sbin/mkfs.ext4", "/dev/sdb"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _topology_with_drive(
    device_id: str = "SN-001",
    fs_path: str = "/dev/sdb",
) -> DiscoveredTopology:
    hub = DiscoveredHub(system_identifier="usb1", name="Hub")
    port = DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")
    drive = DiscoveredDrive(
        device_identifier=device_id,
        port_system_path="1-1",
        filesystem_path=fs_path,
        capacity_bytes=32_000_000_000,
    )
    return DiscoveredTopology(hubs=[hub], ports=[port], drives=[drive])


def _make_drive(db, **kwargs) -> UsbDrive:
    defaults = {
        "device_identifier": "USB-TEST",
        "current_state": DriveState.AVAILABLE,
        "filesystem_path": "/dev/sdb",
        "filesystem_type": None,
    }
    defaults.update(kwargs)
    drive = UsbDrive(**defaults)
    db.add(drive)
    db.commit()
    db.refresh(drive)
    return drive


def _make_project_mount(db, project_id: str, local_mount_point: str) -> NetworkMount:
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path=f"10.0.0.1:/exports/{project_id.lower()}",
        project_id=project_id,
        local_mount_point=local_mount_point,
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)
    return mount


# ===========================================================================
# Part 0: LinuxFilesystemDetector._first_fstype helper
# ===========================================================================


class TestFirstFstype:
    """Unit tests for recursive child-node traversal in lsblk JSON parsing."""

    def test_fstype_on_root_device(self):
        """A whole-disk device with fstype set directly."""
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        nodes = [{"fstype": "ext4"}]
        assert LinuxFilesystemDetector._first_fstype(nodes) == "ext4"

    def test_fstype_on_child_partition(self):
        """Partitioned drive: root fstype is null, child has the filesystem."""
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        nodes = [
            {
                "fstype": None,
                "children": [{"fstype": "ext4"}],
            }
        ]
        assert LinuxFilesystemDetector._first_fstype(nodes) == "ext4"

    def test_fstype_on_nested_children(self):
        """Deeply nested children (e.g. LVM on partition)."""
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        nodes = [
            {
                "fstype": None,
                "children": [
                    {
                        "fstype": None,
                        "children": [{"fstype": "xfs"}],
                    }
                ],
            }
        ]
        assert LinuxFilesystemDetector._first_fstype(nodes) == "xfs"

    def test_multiple_partitions_returns_first(self):
        """Multiple children — returns the first non-empty fstype."""
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        nodes = [
            {
                "fstype": None,
                "children": [
                    {"fstype": None},
                    {"fstype": "ntfs"},
                    {"fstype": "ext4"},
                ],
            }
        ]
        assert LinuxFilesystemDetector._first_fstype(nodes) == "ntfs"

    def test_no_fstype_anywhere(self):
        """All nodes have null fstype — returns None."""
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        nodes = [{"fstype": None, "children": [{"fstype": None}]}]
        assert LinuxFilesystemDetector._first_fstype(nodes) is None

    def test_empty_nodes_list(self):
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        assert LinuxFilesystemDetector._first_fstype([]) is None


# ===========================================================================
# Part 0b: LinuxFilesystemDetector._try_blkid — returncode 2 disambiguation
# ===========================================================================


class TestTryBlkid:
    """Verify _try_blkid interprets returncode 2 correctly."""

    def test_rc2_no_stderr_is_unformatted(self):
        """rc==2 with empty stderr means no filesystem signature → unformatted."""
        from unittest.mock import patch, MagicMock
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        proc = MagicMock(returncode=2, stdout=b"", stderr=b"")
        detector = LinuxFilesystemDetector()
        with patch("app.infrastructure.filesystem_detection.subprocess.run", return_value=proc):
            assert detector._try_blkid("/dev/sdb") == "unformatted"

    def test_rc2_with_stderr_returns_none(self):
        """rc==2 with stderr (e.g. missing device) → None (fall through to lsblk)."""
        from unittest.mock import patch, MagicMock
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        proc = MagicMock(returncode=2, stdout=b"", stderr=b"/dev/sdz: No such file or directory\n")
        detector = LinuxFilesystemDetector()
        with patch("app.infrastructure.filesystem_detection.subprocess.run", return_value=proc):
            assert detector._try_blkid("/dev/sdz") is None

    def test_rc0_empty_stdout_is_unformatted(self):
        """rc==0 with no output means no TYPE field → unformatted."""
        from unittest.mock import patch, MagicMock
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        proc = MagicMock(returncode=0, stdout=b"", stderr=b"")
        detector = LinuxFilesystemDetector()
        with patch("app.infrastructure.filesystem_detection.subprocess.run", return_value=proc):
            assert detector._try_blkid("/dev/sdb") == "unformatted"

    def test_rc0_with_type_returns_fstype(self):
        """rc==0 with TYPE output → canonical lowercase label."""
        from unittest.mock import patch, MagicMock
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        proc = MagicMock(returncode=0, stdout=b"ext4\n", stderr=b"")
        detector = LinuxFilesystemDetector()
        with patch("app.infrastructure.filesystem_detection.subprocess.run", return_value=proc):
            assert detector._try_blkid("/dev/sdb") == "ext4"

    def test_detect_falls_back_to_lsblk_when_whole_disk_blkid_is_unformatted(self):
        """Partitioned drives should still resolve a child filesystem via lsblk."""
        from unittest.mock import patch
        from app.infrastructure.filesystem_detection import LinuxFilesystemDetector

        detector = LinuxFilesystemDetector()
        with patch("app.infrastructure.filesystem_detection.validate_device_path", return_value=True), \
             patch.object(detector, "_try_blkid", return_value="unformatted"), \
             patch.object(detector, "_try_lsblk", return_value="ext4"):
            assert detector.detect("/dev/sda") == "ext4"


# ===========================================================================
# Part 1: Filesystem detection mapping
# ===========================================================================


class TestFilesystemDetectionMapping:
    """Verify detection results are stored correctly during discovery."""

    def test_new_drive_gets_ext4(self, db):
        detector = FakeFilesystemDetector("ext4")
        topology = _topology_with_drive()
        discovery_service.run_discovery_sync(
            db, topology_source=lambda: topology, filesystem_detector=detector,
        )
        drive = db.query(UsbDrive).first()
        assert drive.filesystem_type == "ext4"
        assert detector.calls == ["/dev/sdb"]

    def test_new_drive_unformatted(self, db):
        detector = FakeFilesystemDetector("unformatted")
        topology = _topology_with_drive()
        discovery_service.run_discovery_sync(
            db, topology_source=lambda: topology, filesystem_detector=detector,
        )
        drive = db.query(UsbDrive).first()
        assert drive.filesystem_type == "unformatted"

    def test_new_drive_unknown_on_error(self, db):
        """When detection raises, the drive should get 'unknown'."""

        class FailingDetector:
            def detect(self, device_path: str) -> str:
                raise OSError("permission denied")

        topology = _topology_with_drive()
        discovery_service.run_discovery_sync(
            db, topology_source=lambda: topology, filesystem_detector=FailingDetector(),
        )
        drive = db.query(UsbDrive).first()
        assert drive.filesystem_type == "unknown"

    def test_existing_drive_fs_updated(self, db):
        """Filesystem type is re-detected on every refresh cycle."""
        detector = FakeFilesystemDetector("ext4")
        topology = _topology_with_drive()
        discovery_service.run_discovery_sync(
            db, topology_source=lambda: topology, filesystem_detector=detector,
        )
        drive = db.query(UsbDrive).first()
        assert drive.filesystem_type == "ext4"

        # Second refresh — filesystem changed
        detector2 = FakeFilesystemDetector("exfat")
        discovery_service.run_discovery_sync(
            db, topology_source=lambda: topology, filesystem_detector=detector2,
        )
        db.refresh(drive)
        assert drive.filesystem_type == "exfat"

    def test_no_detection_without_filesystem_path(self, db):
        """Drives without a filesystem_path should not trigger detection."""
        detector = FakeFilesystemDetector("ext4")
        topology = DiscoveredTopology(
            hubs=[DiscoveredHub(system_identifier="usb1", name="Hub")],
            ports=[DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")],
            drives=[DiscoveredDrive(device_identifier="SN-NOFS", port_system_path="1-1")],
        )
        discovery_service.run_discovery_sync(
            db, topology_source=lambda: topology, filesystem_detector=detector,
        )
        drive = db.query(UsbDrive).first()
        assert drive.filesystem_type is None
        assert detector.calls == []


# ===========================================================================
# Part 2: GET /drives returns filesystem_type
# ===========================================================================


class TestFilesystemTypeInResponse:

    def test_filesystem_type_in_drive_response(self, client, db):
        _make_drive(db, device_identifier="USB-FS", filesystem_type="ext4")
        resp = client.get("/drives")
        assert resp.status_code == 200
        data = resp.json()
        match = next(d for d in data if d["device_identifier"] == "USB-FS")
        assert match["filesystem_type"] == "ext4"

    def test_filesystem_type_null(self, client, db):
        _make_drive(db, device_identifier="USB-NULL")
        resp = client.get("/drives")
        assert resp.status_code == 200
        match = next(d for d in resp.json() if d["device_identifier"] == "USB-NULL")
        assert match["filesystem_type"] is None

    def test_all_roles_see_filesystem_type(self, admin_client, manager_client, auditor_client, client, db):
        _make_drive(db, device_identifier="USB-VIS", filesystem_type="exfat")
        for c in [admin_client, manager_client, auditor_client, client]:
            resp = c.get("/drives")
            assert resp.status_code == 200
            match = next(d for d in resp.json() if d["device_identifier"] == "USB-VIS")
            assert match["filesystem_type"] == "exfat"


# ===========================================================================
# Part 3: POST /drives/{id}/format
# ===========================================================================


class TestFormatDriveEndpoint:

    def test_format_success_ext4(self, admin_client, db):
        drive = _make_drive(db, filesystem_type="unformatted")
        fake = FakeFormatter(free_bytes_result=31_000_000_000)
        detector = FakeFilesystemDetector("ext4")
        with (
            patch("app.routers.drives.get_drive_formatter", return_value=fake),
            patch("app.routers.drives.get_filesystem_detector", return_value=detector),
        ):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filesystem_type"] == "ext4"
        assert fake.format_calls == [("/dev/sdb", "ext4")]

        log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_FORMATTED").first()
        assert log is not None
        assert log.drive_id == drive.id
        assert log.project_id is None
        assert log.details["drive_id"] == drive.id
        assert log.details["filesystem_type"] == "ext4"
        assert log.details["detected_filesystem_type"] == "ext4"
        assert log.details["free_bytes"] == 31_000_000_000
        assert log.details["capacity_bytes"] is None
        assert log.details["filesystem_path"] == "[redacted]"
        assert fake.free_bytes_calls == [("/dev/sdb", "ext4")]
        assert detector.calls == ["/dev/sdb"]

    def test_format_success_emits_application_log_event(self, admin_client, db, caplog):
        drive = _make_drive(db, filesystem_type="unformatted")
        fake = FakeFormatter(free_bytes_result=31_000_000_000)
        detector = FakeFilesystemDetector("ext4")
        caplog.set_level("INFO", logger="app.services.audit_service")

        with (
            patch("app.routers.drives.get_drive_formatter", return_value=fake),
            patch("app.routers.drives.get_filesystem_detector", return_value=detector),
        ):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )

        assert resp.status_code == 200
        log_record = next(
            record
            for record in caplog.records
            if record.name == "app.services.audit_service" and record.getMessage() == "DRIVE_FORMATTED"
        )
        assert log_record.drive_id == drive.id
        assert log_record.filesystem_type == "ext4"

    def test_format_success_text_formatter_includes_audit_context(self, admin_client, db):
        import io

        drive = _make_drive(db, filesystem_type="unformatted")
        fake = FakeFormatter(free_bytes_result=31_000_000_000)
        detector = FakeFilesystemDetector("ext4")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(TextFormatter())
        audit_logger = logging.getLogger("app.services.audit_service")
        previous_handlers = audit_logger.handlers[:]
        previous_propagate = audit_logger.propagate
        previous_level = audit_logger.level
        audit_logger.handlers = [handler]
        audit_logger.propagate = False
        audit_logger.setLevel(logging.INFO)

        try:
            with (
                patch("app.routers.drives.get_drive_formatter", return_value=fake),
                patch("app.routers.drives.get_filesystem_detector", return_value=detector),
            ):
                resp = admin_client.post(
                    f"/drives/{drive.id}/format",
                    json={"filesystem_type": "ext4"},
                )
        finally:
            handler.flush()
            audit_logger.handlers = previous_handlers
            audit_logger.propagate = previous_propagate
            audit_logger.setLevel(previous_level)

        assert resp.status_code == 200
        output = stream.getvalue()
        assert "DRIVE_FORMATTED" in output
        assert '"drive_id": ' in output
        assert '"filesystem_type": "ext4"' in output
        assert '"detected_filesystem_type": "ext4"' in output

    def test_format_success_exfat(self, manager_client, db):
        drive = _make_drive(db, filesystem_type="unformatted")
        fake = FakeFormatter()
        detector = FakeFilesystemDetector("exfat")
        with (
            patch("app.routers.drives.get_drive_formatter", return_value=fake),
            patch("app.routers.drives.get_filesystem_detector", return_value=detector),
        ):
            resp = manager_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "exfat"},
            )
        assert resp.status_code == 200
        assert resp.json()["filesystem_type"] == "exfat"

    def test_format_audit_enrichment_is_null_safe_when_probes_fail(self, admin_client, db):
        drive = _make_drive(db, filesystem_type="unformatted", capacity_bytes=64_000_000_000)
        fake = FakeFormatter(free_bytes_result=None, free_bytes_error=RuntimeError("probe failed"))

        class FailingDetector:
            def detect(self, device_path: str) -> str:
                raise RuntimeError("detect failed")

        with (
            patch("app.routers.drives.get_drive_formatter", return_value=fake),
            patch("app.routers.drives.get_filesystem_detector", return_value=FailingDetector()),
        ):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )

        assert resp.status_code == 200
        log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_FORMATTED").first()
        assert log is not None
        assert log.details["detected_filesystem_type"] is None
        assert log.details["free_bytes"] is None
        assert log.details["capacity_bytes"] == 64_000_000_000

    def test_format_unsupported_type_rejected(self, admin_client, db):
        drive = _make_drive(db)
        resp = admin_client.post(
            f"/drives/{drive.id}/format",
            json={"filesystem_type": "ntfs"},
        )
        # Pydantic Literal validation rejects this before the handler runs
        assert resp.status_code == 422

    def test_format_processor_forbidden(self, client, db):
        drive = _make_drive(db)
        resp = client.post(
            f"/drives/{drive.id}/format",
            json={"filesystem_type": "ext4"},
        )
        assert resp.status_code == 403

    def test_format_auditor_forbidden(self, auditor_client, db):
        drive = _make_drive(db)
        resp = auditor_client.post(
            f"/drives/{drive.id}/format",
            json={"filesystem_type": "ext4"},
        )
        assert resp.status_code == 403

    def test_format_not_found(self, admin_client, db):
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                "/drives/999/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 404

    def test_format_wrong_state(self, admin_client, db):
        drive = _make_drive(db, current_state=DriveState.IN_USE, current_project_id="P1", filesystem_type="ext4")
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 409
        assert "AVAILABLE" in resp.json()["message"]

    def test_format_mounted_rejected(self, admin_client, db):
        drive = _make_drive(db)
        fake = FakeFormatter(mounted=True)
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 409
        assert "mounted" in resp.json()["message"].lower()

    def test_format_no_filesystem_path(self, admin_client, db):
        drive = _make_drive(db, filesystem_path=None)
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 400
        assert "filesystem_path" in resp.json()["message"].lower()

    def test_format_invalid_device_path(self, admin_client, db):
        drive = _make_drive(db, filesystem_path="/tmp/evil")
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 400
        assert "invalid" in resp.json()["message"].lower()

    def test_format_failure_audit_log(self, admin_client, db):
        drive = _make_drive(db)
        fake = FakeFormatter(fail=True)
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 500

        log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_FORMAT_FAILED").first()
        assert log is not None
        assert log.drive_id == drive.id
        assert log.project_id is None
        assert log.details["drive_id"] == drive.id
        assert log.details["error"] == sanitize_error_message("mkfs failed: simulated error")

        # Filesystem type should NOT be updated on failure
        db.refresh(drive)
        assert drive.filesystem_type is None

    def test_format_db_save_failure_audit_log(self, admin_client, db):
        """Format succeeds at OS level but DB save fails — audit entry records divergence."""
        drive = _make_drive(db)
        fake = FakeFormatter()
        with (
            patch("app.routers.drives.get_drive_formatter", return_value=fake),
            patch(
                "app.services.drive_service.DriveRepository.save",
                side_effect=RuntimeError("DB commit failed"),
            ),
        ):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 500
        assert "database update failed" in resp.json()["message"].lower()

        # Formatter was called — OS-level format happened
        assert fake.format_calls == [("/dev/sdb", "ext4")]

        log = (
            db.query(AuditLog)
            .filter(AuditLog.action == "DRIVE_FORMAT_DB_UPDATE_FAILED")
            .first()
        )
        assert log is not None
        assert log.drive_id == drive.id
        assert log.project_id is None
        assert log.details["drive_id"] == drive.id
        assert log.details["filesystem_type"] == "ext4"


# ===========================================================================
# Part 4: Initialize guard — reject unformatted drives
# ===========================================================================


class TestInitializeFilesystemGuard:

    def test_initialize_rejects_null_filesystem(self, manager_client, db):
        drive = _make_drive(db, filesystem_type=None)
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 409
        assert "recognized filesystem" in resp.json()["message"].lower()
        assert "NULL" in resp.json()["message"]

        log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_FILESYSTEM").first()
        assert log is not None
        assert log.drive_id == drive.id
        assert log.project_id == "PROJ-001"
        assert log.details["drive_id"] == drive.id
        assert log.details["project_id"] == "PROJ-001"
        assert log.details["filesystem_type"] is None

    def test_initialize_rejects_unformatted(self, manager_client, db):
        drive = _make_drive(db, filesystem_type="unformatted")
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 409
        assert "unformatted" in resp.json()["message"]

        log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_FILESYSTEM").first()
        assert log is not None
        assert log.drive_id == drive.id
        assert log.project_id == "PROJ-001"
        assert log.details["drive_id"] == drive.id
        assert log.details["project_id"] == "PROJ-001"
        assert log.details["filesystem_type"] == "unformatted"

    def test_initialize_rejects_unknown(self, manager_client, db):
        drive = _make_drive(db, filesystem_type="unknown")
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 409
        assert "unknown" in resp.json()["message"]

        log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_FILESYSTEM").first()
        assert log is not None
        assert log.drive_id == drive.id
        assert log.project_id == "PROJ-001"
        assert log.details["drive_id"] == drive.id
        assert log.details["project_id"] == "PROJ-001"
        assert log.details["filesystem_type"] == "unknown"

    def test_initialize_accepts_ext4(self, manager_client, db):
        _make_project_mount(db, "PROJ-001", "/nfs/proj-001-init-ext4")
        drive = _make_drive(db, filesystem_type="ext4", mount_path="/mnt/ecube/init-ext4")
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "IN_USE"

    def test_initialize_accepts_exfat(self, manager_client, db):
        _make_project_mount(db, "PROJ-001", "/nfs/proj-001-init-exfat")
        drive = _make_drive(db, filesystem_type="exfat", mount_path="/mnt/ecube/init-exfat")
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "IN_USE"


class TestFormatClearsProjectBinding:
    """Formatting a drive must clear the project binding.

    This is the mechanism that allows a drive to be re-assigned to a different
    project after a wipe: eject → format (clears binding) → initialize for any project.
    """

    def test_format_clears_current_project_id(self, admin_client, db):
        drive = _make_drive(
            db,
            current_state=DriveState.AVAILABLE,
            current_project_id="PROJ-OLD",
            filesystem_type="exfat",
        )
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )
        assert resp.status_code == 200
        assert resp.json()["current_project_id"] is None
        db.refresh(drive)
        assert drive.current_project_id is None

    def test_format_then_initialize_for_new_project(self, admin_client, db):
        """After format, a drive previously used by PROJ-OLD can be initialized for PROJ-NEW."""
        _make_project_mount(db, "PROJ-NEW", "/nfs/proj-new-after-format")
        drive = _make_drive(
            db,
            current_state=DriveState.AVAILABLE,
            current_project_id="PROJ-OLD",
            filesystem_type="exfat",
            mount_path="/mnt/ecube/formatted-reassign",
        )
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            admin_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "ext4"},
            )

        resp = admin_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-NEW"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_project_id"] == "PROJ-NEW"

