"""Tests for filesystem detection, drive formatting, and initialize guard.

Uses fake implementations of FilesystemDetector and DriveFormatter protocols
to avoid any real OS calls.  All tests use the in-memory SQLite database from
conftest.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.infrastructure.filesystem_detection import FilesystemDetector
from app.infrastructure.drive_format import DriveFormatter
from app.infrastructure.usb_discovery import (
    DiscoveredDrive,
    DiscoveredHub,
    DiscoveredPort,
    DiscoveredTopology,
)
from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.services import discovery_service, drive_service


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

    def __init__(self, *, fail: bool = False, mounted: bool = False):
        self._fail = fail
        self._mounted = mounted
        self.format_calls: list[tuple[str, str]] = []
        self.mounted_calls: list[str] = []

    def format(self, device_path: str, filesystem_type: str) -> None:
        self.format_calls.append((device_path, filesystem_type))
        if self._fail:
            raise RuntimeError("mkfs failed: simulated error")

    def is_mounted(self, device_path: str) -> bool:
        self.mounted_calls.append(device_path)
        return self._mounted


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
        assert len(data) == 1
        assert data[0]["filesystem_type"] == "ext4"

    def test_filesystem_type_null(self, client, db):
        _make_drive(db, device_identifier="USB-NULL")
        resp = client.get("/drives")
        assert resp.status_code == 200
        assert resp.json()[0]["filesystem_type"] is None

    def test_all_roles_see_filesystem_type(self, admin_client, manager_client, auditor_client, client, db):
        _make_drive(db, device_identifier="USB-VIS", filesystem_type="exfat")
        for c in [admin_client, manager_client, auditor_client, client]:
            resp = c.get("/drives")
            assert resp.status_code == 200
            assert resp.json()[0]["filesystem_type"] == "exfat"


# ===========================================================================
# Part 3: POST /drives/{id}/format
# ===========================================================================


class TestFormatDriveEndpoint:

    def test_format_success_ext4(self, admin_client, db):
        drive = _make_drive(db, filesystem_type="unformatted")
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
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
        assert log.details["drive_id"] == drive.id
        assert log.details["filesystem_type"] == "ext4"

    def test_format_success_exfat(self, manager_client, db):
        drive = _make_drive(db, filesystem_type="unformatted")
        fake = FakeFormatter()
        with patch("app.routers.drives.get_drive_formatter", return_value=fake):
            resp = manager_client.post(
                f"/drives/{drive.id}/format",
                json={"filesystem_type": "exfat"},
            )
        assert resp.status_code == 200
        assert resp.json()["filesystem_type"] == "exfat"

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
        assert log.details["drive_id"] == drive.id
        assert "simulated error" in log.details["error"]

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
        assert log.details["drive_id"] == drive.id
        assert log.details["project_id"] == "PROJ-001"
        assert log.details["filesystem_type"] == "unknown"

    def test_initialize_accepts_ext4(self, manager_client, db):
        drive = _make_drive(db, filesystem_type="ext4")
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "IN_USE"

    def test_initialize_accepts_exfat(self, manager_client, db):
        drive = _make_drive(db, filesystem_type="exfat")
        resp = manager_client.post(
            f"/drives/{drive.id}/initialize",
            json={"project_id": "PROJ-001"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_state"] == "IN_USE"
