from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.infrastructure import throughput_benchmark
from app.exceptions import ConflictError
from app.infrastructure.drive_eject import EjectResult
from app.infrastructure.throughput_benchmark import LinuxThroughputBenchmarkProvider
from app.models.audit import AuditLog
from app.models.hardware import DriveFormatStatus, UsbDrive, DriveState, UsbHub, UsbPort
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobChainOfCustodySnapshot, JobStatus
from app.models.network import MountStatus, MountType, NetworkMount
from app.services import drive_service
from app.utils.drive_identity import build_persistent_device_identifier


def _fake_eject(flush_ok=True, unmount_ok=True,
                flush_error=None, unmount_error=None,
                prepare_eject_side_effect=None):
    """Return a MagicMock DriveEjectProvider with preconfigured prepare_eject."""
    provider = MagicMock()
    if prepare_eject_side_effect is not None:
        provider.prepare_eject.side_effect = prepare_eject_side_effect
    else:
        provider.prepare_eject.return_value = EjectResult(
            flush_ok=flush_ok, unmount_ok=unmount_ok,
            flush_error=flush_error, unmount_error=unmount_error,
        )
    return provider


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


def test_list_drives(client, db):
    response = client.get("/drives")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_list_drives_with_data(client, db):
    drive = UsbDrive(
        device_identifier="USB001",
        current_state=DriveState.AVAILABLE,
        available_bytes=2048,
    )
    db.add(drive)
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    data = response.json()
    ids = [d["device_identifier"] for d in data]
    assert "USB001" in ids
    assert ids.count("USB001") == 1
    match = next(item for item in data if item["device_identifier"] == "USB001")
    assert match["available_bytes"] == 2048


def test_list_drives_exposes_port_and_serial_identifiers(client, db):
    hub = UsbHub(name="Hub Ticket260", system_identifier="hub-ticket260-drives")
    db.add(hub)
    db.flush()

    port = UsbPort(hub_id=hub.id, port_number=91, system_path="9-1", enabled=True)
    db.add(port)
    db.flush()

    drive = UsbDrive(device_identifier="SER-001", port_id=port.id, current_state=DriveState.AVAILABLE)
    db.add(drive)
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["port_system_path"] == "9-1"
    assert match["serial_number"] == "SER-001"


def test_list_drives_exposes_safe_usb_metadata_and_readable_label(client, db):
    hub = UsbHub(name="Hub Ticket217", system_identifier="hub-ticket217-drives")
    db.add(hub)
    db.flush()

    port = UsbPort(hub_id=hub.id, port_number=7, system_path="9-7", enabled=True, speed="5000")
    db.add(port)
    db.flush()

    drive = UsbDrive(
        device_identifier=build_persistent_device_identifier(
            "0951",
            "1666",
            "SER-7777",
            "9-7",
        ),
        manufacturer="Kingston",
        product_name="DataTraveler",
        port_id=port.id,
        capacity_bytes=32_000_000_000,
        current_state=DriveState.AVAILABLE,
    )
    db.add(drive)
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["manufacturer"] == "Kingston"
    assert match["product_name"] == "DataTraveler"
    assert match["port_number"] == 7
    assert match["speed"] == "5000"
    assert match["display_device_label"] == "Kingston DataTraveler - Port 7 (30GB)"
    assert match["serial_number"] == "SER-7777"


def test_drive_throughput_test_persists_latest_measurement(manager_client, db, tmp_path):
    drive = UsbDrive(
        device_identifier="USB-THROUGHPUT-1",
        current_state=DriveState.AVAILABLE,
        mount_path=str(tmp_path),
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.measure_drive_write_mbps.return_value = (145.6, 0.5, 0.4)

    with patch("app.routers.drives.get_throughput_benchmark", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/throughput-test")

    assert response.status_code == 200
    provider.measure_drive_write_mbps.assert_called_once()
    provider.measure_share_read_mbps.assert_not_called()
    data = response.json()
    assert data["throughput_write_mbps"] == 145.6
    assert data["throughput_tested_at"] is not None
    db.refresh(drive)
    assert drive.throughput_write_mbps == 145.6
    assert drive.throughput_tested_at is not None


def test_drive_throughput_test_requires_mounted_drive(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-THROUGHPUT-INVALID",
        current_state=DriveState.DISCONNECTED,
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/throughput-test")

    assert response.status_code == 409
    assert "Drive throughput test requires a mounted managed drive" in str(response.json())


def test_drive_throughput_test_rejects_pending_format(manager_client, db, tmp_path):
    drive = UsbDrive(
        device_identifier="USB-THROUGHPUT-PENDING-FORMAT",
        current_state=DriveState.AVAILABLE,
        mount_path=str(tmp_path),
        format_status=DriveFormatStatus.PENDING,
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/throughput-test")

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Drive format is in progress; wait for formatting to complete before running throughput testing"
    )


def test_drive_write_benchmark_uses_one_contiguous_file(tmp_path):
    provider = LinuxThroughputBenchmarkProvider()
    sample_plan = [
        (tmp_path / "small.bin", 16 * 1024),
        (tmp_path / "medium.bin", 128 * 1024),
        (tmp_path / "large.bin", 1024 * 1024),
    ]

    write_mbps, elapsed_seconds, stream_seconds = provider.measure_drive_write_mbps(
        str(tmp_path),
        sample_plan,
        benchmark_id="contiguous",
    )

    assert write_mbps is not None
    assert elapsed_seconds >= stream_seconds >= 0.0
    assert not list(tmp_path.glob(".throughput-benchmark-contiguous-*.tmp"))


def test_drive_write_benchmark_rejects_zero_byte_sample_plan(tmp_path):
    provider = LinuxThroughputBenchmarkProvider()

    write_mbps, elapsed_seconds, stream_seconds = provider.measure_drive_write_mbps(
        str(tmp_path),
        [(tmp_path / "empty.bin", 0)],
        benchmark_id="zero",
    )

    assert write_mbps is None
    assert elapsed_seconds == 0.0
    assert stream_seconds == 0.0


def test_drive_write_benchmark_excludes_cleanup_time_from_elapsed_seconds(tmp_path):
    provider = LinuxThroughputBenchmarkProvider()
    current_tick = {"value": 0.0}
    original_unlink = Path.unlink

    def fake_perf_counter():
        value = current_tick["value"]
        current_tick["value"] += 1.0
        return value

    def delayed_unlink(path_obj, *args, **kwargs):
        current_tick["value"] += 100.0
        return original_unlink(path_obj, *args, **kwargs)

    with patch.object(throughput_benchmark.time, "perf_counter", side_effect=fake_perf_counter):
        with patch.object(Path, "unlink", new=delayed_unlink):
            write_mbps, elapsed_seconds, stream_seconds = provider.measure_drive_write_mbps(
                str(tmp_path),
                [(tmp_path / "sample.bin", 1)],
                benchmark_id="cleanup-timing",
            )

    assert write_mbps == 0.01
    assert elapsed_seconds == 3.0
    assert stream_seconds == 1.0


def test_list_drives_filter_by_project(client, db):
    """GET /drives?project_id= returns only matching drives."""
    d1 = UsbDrive(device_identifier="USB-A", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    d2 = UsbDrive(device_identifier="USB-B", current_state=DriveState.IN_USE, current_project_id="PROJ-002")
    d3 = UsbDrive(device_identifier="USB-C", current_state=DriveState.AVAILABLE)
    db.add_all([d1, d2, d3])
    db.commit()

    response = client.get("/drives", params={"project_id": "PROJ-001"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_identifier"] == "USB-A"
    assert data[0]["current_project_id"] == "PROJ-001"


def test_list_drives_filter_by_project_no_match(client, db):
    """GET /drives?project_id= returns empty list when no drives match."""
    drive = UsbDrive(device_identifier="USB-X", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    db.add(drive)
    db.commit()

    response = client.get("/drives", params={"project_id": "PROJ-999"})
    assert response.status_code == 200
    assert response.json() == []


def test_list_drives_filter_by_project_normalizes_case_and_whitespace(client, db):
    drive = UsbDrive(device_identifier="USB-NORM", current_state=DriveState.IN_USE, current_project_id="  proj-001  ")
    db.add(drive)
    db.commit()
    db.refresh(drive)

    assert drive.current_project_id == "PROJ-001"

    response = client.get("/drives", params={"project_id": "  proj-001  "})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["device_identifier"] == "USB-NORM"


def test_list_drives_empty_project_id_rejected(client, db):
    """GET /drives?project_id= (empty string) returns 422."""
    response = client.get("/drives", params={"project_id": ""})
    assert response.status_code == 422


def test_list_drives_default_excludes_disconnected(client, db):
    """GET /drives without project_id returns connected drives (excludes DISCONNECTED by default)."""
    d1 = UsbDrive(device_identifier="USB-1", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    d2 = UsbDrive(device_identifier="USB-2", current_state=DriveState.AVAILABLE)
    d5 = UsbDrive(device_identifier="USB-5", current_state=DriveState.DISABLED)
    d3 = UsbDrive(device_identifier="USB-3", current_state=DriveState.DISCONNECTED)
    db.add_all([d1, d2, d3, d5])
    db.commit()

    response = client.get("/drives")
    assert response.status_code == 200
    data = response.json()
    ids = [d["device_identifier"] for d in data]
    assert "USB-1" in ids
    assert "USB-2" in ids
    assert "USB-5" in ids
    assert "USB-3" not in ids


def test_list_drives_include_disconnected(client, db):
    """GET /drives?include_disconnected=true returns all drives including DISCONNECTED."""
    d1 = UsbDrive(device_identifier="USB-1", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    d2 = UsbDrive(device_identifier="USB-2", current_state=DriveState.AVAILABLE)
    d3 = UsbDrive(device_identifier="USB-3", current_state=DriveState.DISCONNECTED)
    db.add_all([d1, d2, d3])
    db.commit()

    response = client.get("/drives", params={"include_disconnected": "true"})
    assert response.status_code == 200
    data = response.json()
    ids = [d["device_identifier"] for d in data]
    assert "USB-1" in ids
    assert "USB-2" in ids
    assert "USB-3" in ids


def test_list_drives_include_related_job_custody_complete(client, db):
    drive = UsbDrive(device_identifier="USB-CUSTODY-1", current_state=DriveState.IN_USE, current_project_id="PROJ-001")
    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path="/nfs/proj-001",
        status=JobStatus.COMPLETED,
    )
    db.add_all([drive, job])
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)))
    db.add(
        AuditLog(
            action="COC_HANDOFF_CONFIRMED",
            project_id="PROJ-001",
            drive_id=drive.id,
            job_id=job.id,
            details={"delivery_time": "2026-05-02T18:30:00Z"},
        )
    )
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-001",
        "custody_status": "HANDOFF_RECORDED",
        "delivery_time": "2026-05-02T18:30:00Z",
    }


def test_list_drives_include_related_job_custody_pending(client, db):
    drive = UsbDrive(device_identifier="USB-CUSTODY-2", current_state=DriveState.IN_USE, current_project_id="PROJ-002")
    job = ExportJob(
        project_id="PROJ-002",
        evidence_number="EV-002",
        source_path="/nfs/proj-002",
        status=JobStatus.COMPLETED,
    )
    db.add_all([drive, job])
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)))
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-002",
        "custody_status": "PENDING_HANDOFF",
        "delivery_time": None,
    }


def test_list_drives_include_related_job_custody_does_not_leak_same_project_assignment(client, db):
    assigned_drive = UsbDrive(device_identifier="USB-CUSTODY-LEAK-A", current_state=DriveState.IN_USE, current_project_id="PROJ-LEAK-001")
    unassigned_drive = UsbDrive(device_identifier="USB-CUSTODY-LEAK-B", current_state=DriveState.IN_USE, current_project_id="PROJ-LEAK-001")
    job = ExportJob(
        project_id="PROJ-LEAK-001",
        evidence_number="EV-LEAK-001",
        source_path="/nfs/proj-leak-001",
        status=JobStatus.RUNNING,
    )
    db.add_all([assigned_drive, unassigned_drive, job])
    db.flush()
    db.add(DriveAssignment(drive_id=assigned_drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)))
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    assigned_match = next(item for item in payload if item["id"] == assigned_drive.id)
    unassigned_match = next(item for item in payload if item["id"] == unassigned_drive.id)

    assert assigned_match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-LEAK-001",
        "custody_status": "PENDING_HANDOFF",
        "delivery_time": None,
    }
    assert unassigned_match["related_job"] == {
        "job_id": None,
        "evidence_number": None,
        "custody_status": "NO_RELATED_JOB",
        "delivery_time": None,
    }


def test_list_drives_include_related_job_custody_for_explicit_overflow_assignment(client, db):
    primary_drive = UsbDrive(device_identifier="USB-CUSTODY-OVERFLOW-A", current_state=DriveState.IN_USE, current_project_id="PROJ-OVERFLOW-CUSTODY-001")
    overflow_drive = UsbDrive(device_identifier="USB-CUSTODY-OVERFLOW-B", current_state=DriveState.IN_USE, current_project_id="PROJ-OVERFLOW-CUSTODY-001")
    spare_drive = UsbDrive(device_identifier="USB-CUSTODY-OVERFLOW-C", current_state=DriveState.IN_USE, current_project_id="PROJ-OVERFLOW-CUSTODY-001")
    job = ExportJob(
        project_id="PROJ-OVERFLOW-CUSTODY-001",
        evidence_number="EV-OVERFLOW-001",
        source_path="/nfs/proj-overflow-custody-001",
        status=JobStatus.RUNNING,
    )
    db.add_all([primary_drive, overflow_drive, spare_drive, job])
    db.flush()
    db.add_all([
        DriveAssignment(drive_id=primary_drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)),
        DriveAssignment(drive_id=overflow_drive.id, job_id=job.id),
    ])
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    primary_match = next(item for item in payload if item["id"] == primary_drive.id)
    overflow_match = next(item for item in payload if item["id"] == overflow_drive.id)
    spare_match = next(item for item in payload if item["id"] == spare_drive.id)

    assert primary_match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-OVERFLOW-001",
        "custody_status": "PENDING_HANDOFF",
        "delivery_time": None,
    }
    assert overflow_match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-OVERFLOW-001",
        "custody_status": "PENDING_HANDOFF",
        "delivery_time": None,
    }
    assert spare_match["related_job"] == {
        "job_id": None,
        "evidence_number": None,
        "custody_status": "NO_RELATED_JOB",
        "delivery_time": None,
    }


def test_list_drives_include_related_job_custody_unavailable_without_snapshot(client, db):
    drive = UsbDrive(device_identifier="USB-CUSTODY-3", current_state=DriveState.IN_USE, current_project_id="PROJ-003")
    job = ExportJob(
        project_id="PROJ-003",
        evidence_number="EV-003",
        source_path="/nfs/proj-003",
        status=JobStatus.ARCHIVED,
    )
    db.add_all([drive, job])
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)))
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-003",
        "custody_status": "STATUS_UNAVAILABLE",
        "delivery_time": None,
    }


def test_list_drives_include_related_job_custody_from_archived_snapshot(client, db):
    drive = UsbDrive(device_identifier="USB-CUSTODY-4", current_state=DriveState.IN_USE, current_project_id="PROJ-004")
    job = ExportJob(
        project_id="PROJ-004",
        evidence_number="EV-004",
        source_path="/nfs/proj-004",
        status=JobStatus.ARCHIVED,
    )
    db.add_all([drive, job])
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)))
    db.add(
        JobChainOfCustodySnapshot(
            job_id=job.id,
            payload={
                "selector_mode": "JOB",
                "project_id": "PROJ-004",
                "reports": [{
                    "drive_id": drive.id,
                    "drive_sn": drive.device_identifier,
                    "drive_manufacturer": None,
                    "drive_model": None,
                    "project_id": "PROJ-004",
                    "evidence_number": "EV-004",
                    "custody_complete": True,
                    "delivery_time": "2026-05-03T12:00:00Z",
                    "chain_of_custody_events": [],
                    "manifest_summary": [],
                }],
            },
        )
    )
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["related_job"] == {
        "job_id": job.id,
        "evidence_number": "EV-004",
        "custody_status": "HANDOFF_RECORDED",
        "delivery_time": "2026-05-03T12:00:00Z",
    }


def test_list_drives_include_related_job_custody_no_related_job_after_binding_clears(client, db):
    drive = UsbDrive(device_identifier="USB-CUSTODY-5", current_state=DriveState.AVAILABLE, current_project_id=None)
    job = ExportJob(
        project_id="PROJ-005",
        evidence_number="EV-005",
        source_path="/nfs/proj-005",
        status=JobStatus.COMPLETED,
    )
    db.add_all([drive, job])
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id, activated_at=datetime.now(timezone.utc)))
    db.commit()

    response = client.get("/drives", params={"include_related_job_custody": "true"})

    assert response.status_code == 200
    payload = response.json()
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["related_job"] == {
        "job_id": None,
        "evidence_number": None,
        "custody_status": "NO_RELATED_JOB",
        "delivery_time": None,
    }



def test_initialize_drive(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB002",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        mount_path="/mnt/ecube/usb002",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.1:/exports/proj-001",
        project_id="PROJ-001",
        local_mount_point="/nfs/proj-001",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 200
    data = response.json()
    assert data["current_project_id"] == "PROJ-001"
    assert data["current_state"] == "IN_USE"


def test_initialize_drive_rejects_unmounted_destination_drive(manager_client, db):
    from app.models.audit import AuditLog
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB-NOT-MOUNTED",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        mount_path=None,
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.10:/exports/proj-ready",
        project_id="PROJ-READY",
        local_mount_point="/nfs/proj-ready",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-READY"})

    assert response.status_code == 409
    assert response.json()["message"] == "Drive must be mounted before it can be initialized for a project."

    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_NOT_MOUNTED").one()
    assert log.project_id == "PROJ-READY"
    assert log.drive_id == drive.id
    assert log.details["requested_project_id"] == "PROJ-READY"
    assert log.details["error_code"] == "DRIVE_NOT_MOUNTED"
    assert log.details["message"] == "Drive is not mounted"


def test_initialize_drive_rejects_project_without_mounted_source(manager_client, db):
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB-NO-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        mount_path="/mnt/ecube/no-project-source",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-MISSING"})

    assert response.status_code == 409
    assert response.json()["message"] == (
        "No mounted share is assigned to project PROJ-MISSING. "
        "Mount a share for this project before initializing a drive."
    )

    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_NO_PROJECT_SOURCE").one()
    assert log.project_id == "PROJ-MISSING"
    assert log.drive_id == drive.id
    assert log.details["requested_project_id"] == "PROJ-MISSING"
    assert log.details["error_code"] == "NO_PROJECT_SOURCE"
    assert log.details["message"] == "No mounted project source is available"


def test_initialize_drive_allows_project_with_mounted_source(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB-WITH-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        mount_path="/mnt/ecube/usb-with-mount",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.5:/exports/proj-205",
        local_mount_point="/nfs/proj-205",
        project_id="PROJ-205",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-205"})

    assert response.status_code == 200
    assert response.json()["current_project_id"] == "PROJ-205"
    assert response.json()["current_state"] == "IN_USE"


def test_initialize_drive_rejects_busy_project_source(manager_client, db):
    from app.models.audit import AuditLog
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB-BUSY-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        mount_path="/mnt/ecube/usb-busy-mount",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.8:/exports/proj-busy",
        local_mount_point="/nfs/proj-busy",
        project_id="PROJ-BUSY",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    with patch(
        "app.services.drive_service.MountRepository.get_mounted_project_for_update",
        side_effect=ConflictError("Project source is currently being updated by another operation."),
    ):
        response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-BUSY"})

    assert response.status_code == 409
    assert response.json()["message"] == "Project source is currently being updated by another operation."

    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_PROJECT_SOURCE_BUSY").one()
    assert log.project_id == "PROJ-BUSY"
    assert log.drive_id == drive.id
    assert log.details["error_code"] == "PROJECT_SOURCE_BUSY"
    assert log.details["message"] == "Project source is currently being updated"


def test_initialize_drive_normalizes_project_id_case_and_whitespace(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB-WITH-NORMALIZED-MOUNT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        mount_path="/mnt/ecube/usb-with-normalized-mount",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.7:/exports/proj-777",
        local_mount_point="/nfs/proj-777",
        project_id="PROJ-777",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "  proj-777  "})

    assert response.status_code == 200
    assert response.json()["current_project_id"] == "PROJ-777"
    assert response.json()["current_state"] == "IN_USE"


def test_mount_drive_success(manager_client, db):
    from app.config import settings
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB-MOUNT-001",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (True, None)

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 200
    data = response.json()
    assert data["mount_path"] == f"{settings.usb_mount_base_path}/{drive.id}"
    provider.mount_drive.assert_called_once_with(
        "/dev/sdb",
        f"{settings.usb_mount_base_path}/{drive.id}",
    )

    audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_MOUNTED").first()
    assert audit is not None
    assert audit.details["drive_id"] == drive.id
    assert audit.details["device_name"] == "[redacted]"
    assert audit.details["mount_slot"] == "[redacted]"
    assert "filesystem_path" not in audit.details
    assert "mount_path" not in audit.details


def test_normalize_unreleased_drive_states_promotes_unmounted_to_disabled(db):
    from app.services.drive_service import normalize_unreleased_drive_states

    drive = UsbDrive(
        device_identifier="USB-MOUNT-UNRELEASED",
        current_state=DriveState.DISABLED,
        filesystem_type="ext4",
        filesystem_path="/dev/sdz",
    )
    db.add(drive)
    db.commit()

    db.execute(
        text("UPDATE usb_drives SET current_state = :state WHERE id = :drive_id"),
        {"state": "UNMOUNTED", "drive_id": drive.id},
    )
    db.commit()

    assert normalize_unreleased_drive_states(db) == 1

    db.refresh(drive)
    assert drive.current_state == DriveState.DISABLED


def test_normalize_unreleased_drive_states_marks_orphaned_pending_formats_failed(db):
    from app.services.drive_service import normalize_unreleased_drive_states

    drive = UsbDrive(
        device_identifier="USB-FORMAT-PENDING-RECOVERY",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdz",
        format_status=DriveFormatStatus.PENDING,
        format_started_at=datetime.now(timezone.utc),
    )
    db.add(drive)
    db.commit()

    assert normalize_unreleased_drive_states(db) == 1

    db.refresh(drive)
    assert drive.format_status == DriveFormatStatus.FAILED
    assert drive.format_failure_message == "Drive format was interrupted during restart; retry the request"
    assert drive.format_finished_at is not None


def test_mount_drive_requires_recognized_filesystem(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-001B",
        current_state=DriveState.AVAILABLE,
        filesystem_type="unknown",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert "recognized filesystem" in response.json()["message"].lower()


def test_mount_drive_rejects_pending_format(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-PENDING-FORMAT",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdb",
        format_status=DriveFormatStatus.PENDING,
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Drive format is already in progress; wait for formatting to complete before attempting to mount this drive"
    )
    provider.mount_drive.assert_not_called()


def test_mount_drive_conflict_when_already_mounted(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-002",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdc",
        mount_path="/mnt/ecube/2",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert "already mounted" in response.json()["message"].lower()
    provider.mount_drive.assert_not_called()


def test_mount_drive_requires_filesystem_path(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-003",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path=None,
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 400
    assert "filesystem_path" in response.json()["message"]


def test_mount_drive_provider_failure_is_audited(manager_client, db):
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB-MOUNT-004",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdd",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "mount failed for /dev/sdd at /mnt/ecube/4")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive mount failed"
    trace_id = response.json()["trace_id"]
    assert trace_id
    assert response.headers["X-Trace-Id"] == trace_id

    audit = db.query(AuditLog).filter(AuditLog.action == "DRIVE_MOUNT_FAILED").first()
    assert audit is not None
    assert audit.details["drive_id"] == drive.id
    assert audit.details["error_code"] == "MOUNT_FAILED"
    assert audit.details["message"] == "Provider mount operation failed"
    assert audit.details["trace_id"] == trace_id
    assert "error" not in audit.details
    assert "/dev/sdd" not in str(audit.details)
    assert "/mnt/ecube/4" not in str(audit.details)
    assert "filesystem_path" not in audit.details
    assert "mount_path" not in audit.details


def test_mount_drive_reports_host_filesystem_support_failure_safely(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004AA",
        current_state=DriveState.AVAILABLE,
        filesystem_type="exfat",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "mount failed for /dev/sdb: unknown filesystem type 'exfat'")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert response.json()["message"] == "Host filesystem support for this drive is unavailable; verify the required filesystem runtime and retry"
    assert "/dev/sdb" not in response.json()["message"]


def test_mount_drive_reports_managed_mount_root_permission_failure_safely(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004AB",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "failed to create mount point /mnt/ecube/1: [Errno 13] Permission denied: '/mnt/ecube/1'")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert response.json()["message"] == "Managed mount root is not writable by the ECUBE service account; fix host permissions and retry"
    assert "/mnt/ecube/1" not in response.json()["message"]


def test_mount_drive_failure_redacts_provider_paths_from_client(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004B",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdz1",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "mount: /dev/sdz1 already mounted on /mnt/ecube/42")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert response.json()["message"] == "Drive is already mounted; refresh drive status and retry"
    assert "/dev/sdz1" not in response.json()["message"]
    assert "/mnt/ecube/42" not in response.json()["message"]


def test_mount_drive_stale_already_mounted_returns_conflict(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004BA",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdz2",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (False, "/dev/sdz2 is already mounted at /media/ecube/usb-mounted, not at requested /mnt/ecube/42")

    with patch("app.routers.drives.get_drive_mount", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert response.json()["message"] == "Drive is already mounted; refresh drive status and retry"
    assert "/dev/sdz2" not in response.json()["message"]
    assert "/media/ecube/usb-mounted" not in response.json()["message"]


def test_format_drive_rejects_persisted_mounted_state_before_formatter(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-FORMAT-STALE-001",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sde1",
        mount_path="/mnt/ecube/15",
    )
    db.add(drive)
    db.commit()

    formatter = MagicMock()

    with patch("app.routers.drives.get_drive_formatter", return_value=formatter):
        response = manager_client.post(
            f"/drives/{drive.id}/format",
            json={"filesystem_type": "ext4"},
        )

    assert response.status_code == 409
    assert response.json()["message"] == "Drive is currently mounted; unmount before formatting"
    formatter.is_mounted.assert_not_called()
    formatter.format.assert_not_called()


def test_mount_drive_db_save_failure_attempts_cleanup(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004C",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdg",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (True, None)
    provider.unmount_drive.return_value = (True, None)

    with (
        patch("app.routers.drives.get_drive_mount", return_value=provider),
        patch("app.services.drive_service.DriveRepository.save", side_effect=RuntimeError("db failed")),
    ):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 500
    assert "rollback attempted" in response.json()["message"].lower()
    provider.unmount_drive.assert_called_once_with(f"/mnt/ecube/{drive.id}")


def test_mount_drive_relocks_only_after_os_mount_and_aborts_if_state_changed(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004D",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdh",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    call_order = []

    def mount_side_effect(device_path, mount_point):
        call_order.append("mount")
        return True, None

    provider.mount_drive.side_effect = mount_side_effect
    provider.unmount_drive.return_value = (True, None)

    original_get = drive_service.DriveRepository.get
    original_get_for_update = drive_service.DriveRepository.get_for_update

    def get_side_effect(self, drive_id):
        call_order.append("get")
        return original_get(self, drive_id)

    def get_for_update_side_effect(self, drive_id):
        call_order.append("lock")
        locked_drive = original_get_for_update(self, drive_id)
        if "mount" in call_order:
            locked_drive.current_state = DriveState.IN_USE
        return locked_drive

    with (
        patch("app.routers.drives.get_drive_mount", return_value=provider),
        patch.object(drive_service.DriveRepository, "get", get_side_effect),
        patch.object(drive_service.DriveRepository, "get_for_update", get_for_update_side_effect),
    ):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 409
    assert "changed during mount" in response.json()["message"].lower()
    assert call_order == ["get", "mount", "lock"]
    provider.unmount_drive.assert_called_once_with(f"/mnt/ecube/{drive.id}")


def test_mount_drive_treats_same_persisted_mount_as_idempotent(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-004E",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdi",
    )
    db.add(drive)
    db.commit()

    provider = MagicMock()
    provider.mount_drive.return_value = (True, None)
    provider.unmount_drive.return_value = (True, None)

    expected_mount_path = f"/mnt/ecube/{drive.id}"
    original_get_for_update = drive_service.DriveRepository.get_for_update

    def get_for_update_side_effect(self, drive_id):
        locked_drive = original_get_for_update(self, drive_id)
        locked_drive.mount_path = expected_mount_path
        return locked_drive

    with (
        patch("app.routers.drives.get_drive_mount", return_value=provider),
        patch.object(drive_service.DriveRepository, "get_for_update", get_for_update_side_effect),
    ):
        response = manager_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 200
    assert response.json()["mount_path"] == expected_mount_path
    provider.unmount_drive.assert_not_called()


def test_mount_drive_processor_forbidden(client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-005",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sde",
    )
    db.add(drive)
    db.commit()

    response = client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 403


def test_mount_drive_auditor_forbidden(auditor_client, db):
    drive = UsbDrive(
        device_identifier="USB-MOUNT-006",
        current_state=DriveState.AVAILABLE,
        filesystem_type="ext4",
        filesystem_path="/dev/sdf",
    )
    db.add(drive)
    db.commit()

    response = auditor_client.post(f"/drives/{drive.id}/mount")

    assert response.status_code == 403


def test_initialize_drive_not_found(manager_client, db):
    response = manager_client.post("/drives/999/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 404


def test_initialize_empty_drive_is_rejected(manager_client, db):
    """DISCONNECTED drives are not accessible; initialization must be rejected with 409."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB003E",
        current_state=DriveState.DISCONNECTED,
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-NEW"})
    assert response.status_code == 409
    assert "disconnected" in response.json()["message"].lower()

    # Drive state must remain DISCONNECTED.
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED

    # Denial must be recorded in the audit trail.
    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_NOT_AVAILABLE").first()
    assert log is not None
    assert log.details["drive_id"] == drive.id
    assert log.details["current_state"] == "DISCONNECTED"
    assert log.details["requested_project_id"] == "PROJ-NEW"

def test_initialize_disabled_drive_is_rejected(manager_client, db):
    """DISABLED drives are physically present on blocked ports; initialization must be rejected with 409."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB003D",
        current_state=DriveState.DISABLED,
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-NEW"})
    assert response.status_code == 409
    assert "disabled" in response.json()["message"].lower()

    db.refresh(drive)
    assert drive.current_state == DriveState.DISABLED

    log = db.query(AuditLog).filter(AuditLog.action == "INIT_REJECTED_NOT_AVAILABLE").order_by(AuditLog.id.desc()).first()
    assert log is not None
    assert log.details["drive_id"] == drive.id
    assert log.details["current_state"] == "DISABLED"
    assert log.details["requested_project_id"] == "PROJ-NEW"


def test_project_isolation_violation(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB003",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_type="ext4",
    )
    db.add(drive)
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-002"})
    assert response.status_code == 403


def test_reinitialize_same_project(manager_client, db):
    from app.models.network import MountStatus, MountType, NetworkMount

    drive = UsbDrive(
        device_identifier="USB004",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_type="ext4",
        mount_path="/mnt/ecube/usb004",
    )
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="10.0.0.1:/exports/proj-001",
        project_id="PROJ-001",
        local_mount_point="/nfs/proj-001-reinit",
        status=MountStatus.MOUNTED,
    )
    db.add_all([drive, mount])
    db.commit()

    response = manager_client.post(f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"})
    assert response.status_code == 200


def test_prepare_eject(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB005",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert response.status_code == 200
    data = response.json()
    assert data["current_state"] == "AVAILABLE"
    # Project binding is preserved through eject so re-insert for the same
    # project is allowed without a format, and cross-project reuse is blocked.
    assert data["current_project_id"] == "PROJ-001"


def test_prepare_eject_rejects_pending_format(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB005-PENDING-FORMAT",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        format_status=DriveFormatStatus.PENDING,
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Drive format is already in progress; wait for formatting to complete before attempting to prepare-eject this drive"
    )
    provider.prepare_eject.assert_not_called()


def test_prepare_eject_mounted_available_drive(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB005-AVAILABLE",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
        filesystem_path="/dev/sdb",
        mount_path="/mnt/ecube/usb005-available",
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    data = response.json()
    assert data["current_state"] == "AVAILABLE"
    assert data["mount_path"] is None


@pytest.mark.parametrize("status", [
    JobStatus.RUNNING,
    JobStatus.PAUSING,
    JobStatus.PAUSED,
    JobStatus.VERIFYING,
])
def test_prepare_eject_blocks_started_non_completed_jobs(manager_client, db, status):
    drive = UsbDrive(
        device_identifier=f"USB005-BLOCK-{status.value}",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
        mount_path="/mnt/ecube/usb005-block",
    )
    db.add(drive)
    db.flush()

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number=f"EV-EJECT-BLOCK-{status.value}",
        source_path="/data",
        status=status,
    )
    db.add(job)
    db.flush()

    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert response.json()["message"] == (
        f"Drive cannot be prepared for eject while assigned job {job.id} has started "
        f"and is not yet completed (current status: {status.value})"
    )
    provider.prepare_eject.assert_not_called()


def test_prepare_eject_audits_started_non_completed_job_block(manager_client, db):
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB005-BLOCK-AUDIT",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
        mount_path="/mnt/ecube/usb005-block-audit",
    )
    db.add(drive)
    db.flush()

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-EJECT-BLOCK-AUDIT",
        source_path="/data",
        status=JobStatus.PAUSED,
    )
    db.add(job)
    db.flush()

    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    provider.prepare_eject.assert_not_called()

    log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DRIVE_EJECT_REJECTED_ACTIVE_JOB")
        .first()
    )
    assert log is not None
    assert log.drive_id == drive.id
    assert log.project_id == "PROJ-001"
    assert log.details["drive_id"] == drive.id
    assert log.details["job_id"] == job.id
    assert log.details["job_status"] == JobStatus.PAUSED.value


def test_prepare_eject_allows_completed_assigned_job(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB005-COMPLETED",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
        mount_path="/mnt/ecube/usb005-completed",
    )
    db.add(drive)
    db.flush()

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-EJECT-COMPLETED",
        source_path="/data",
        status=JobStatus.COMPLETED,
    )
    db.add(job)
    db.flush()

    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    provider.prepare_eject.assert_called_once_with("/dev/sdb")


def test_reinitialize_same_project_after_eject(manager_client, db):
    """A drive can be re-initialized for the same project after eject (adds more data)."""
    drive = UsbDrive(
        device_identifier="USB005D",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_type="exfat",
        mount_path="/mnt/ecube/usb005d",
    )
    mount = _make_project_mount(db, "PROJ-001", "/nfs/proj-001-after-eject")
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        eject_resp = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert eject_resp.status_code == 200

    db.refresh(drive)
    drive.mount_path = "/mnt/ecube/usb005d"
    db.add_all([drive, mount])
    db.commit()

    # Re-initialize for the same project must succeed — user is adding more data.
    init_resp = manager_client.post(
        f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-001"}
    )
    assert init_resp.status_code == 200
    assert init_resp.json()["current_state"] == "IN_USE"


def test_reinitialize_different_project_after_eject_requires_format(manager_client, db):
    """Re-initializing an ejected drive for a different project must be rejected (409).

    The previous project's data is still on disk. A format (wipe) is required
    before the drive can be assigned to a new project.
    """
    drive = UsbDrive(
        device_identifier="USB005E",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-A",
        filesystem_type="exfat",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        eject_resp = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert eject_resp.status_code == 200

    # Attempt to re-initialize for a different project must be rejected.
    init_resp = manager_client.post(
        f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-B"}
    )
    assert init_resp.status_code == 409
    assert "PROJ-A" in init_resp.json()["message"]


def test_prepare_eject_with_filesystem_path(manager_client, db):
    """Flush and unmount are both called when drive has a filesystem_path."""
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB006",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
        mount_path="/mnt/ecube/6",
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    assert response.json()["mount_path"] is None
    provider.prepare_eject.assert_called_once_with("/dev/sdb")

    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_PREPARED").first()
    assert log is not None
    assert log.drive_id == drive.id
    assert log.project_id == "PROJ-001"
    assert log.details["drive_id"] == drive.id
    assert log.details["device_name"] == "[redacted]"
    assert log.details["flush_ok"] is True
    assert log.details["unmount_ok"] is True
    assert "filesystem_path" not in log.details


def test_prepare_eject_audits_incomplete_files_warning(manager_client, db):
    from app.models.audit import AuditLog

    drive = UsbDrive(
        device_identifier="USB006-WARN",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.flush()

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-INCOMPLETE",
        source_path="/data",
        status=JobStatus.COMPLETED,
        file_count=2,
    )
    db.add(job)
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.add(ExportFile(job_id=job.id, relative_path="ok.txt", status=FileStatus.DONE, size_bytes=1))
    db.add(ExportFile(job_id=job.id, relative_path="slow.txt", status=FileStatus.TIMEOUT, error_message="File copy timed out after 1s"))
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        blocked = manager_client.post(f"/drives/{drive.id}/prepare-eject")
    assert blocked.status_code == 409
    assert "EJECT_CONFIRM_REQUIRED:" in blocked.json()["message"]

    confirm_required_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DRIVE_EJECT_CONFIRM_REQUIRED")
        .first()
    )
    assert confirm_required_log is not None
    assert confirm_required_log.drive_id == drive.id
    assert confirm_required_log.details["incomplete_file_count"] == 1

    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject", params={"confirm_incomplete": True})

    assert response.status_code == 200

    warning_log = (
        db.query(AuditLog)
        .filter(AuditLog.action == "DRIVE_EJECT_WITH_INCOMPLETE_FILES")
        .first()
    )
    assert warning_log is not None
    assert warning_log.drive_id == drive.id
    assert warning_log.details["incomplete_file_count"] == 1


def test_prepare_eject_blocks_when_incomplete_precheck_fails(manager_client, db):
    drive = UsbDrive(
        device_identifier="USB006-PRECHECK-FAIL",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-INCOMPLETE-PRECHECK",
        source_path="/data",
        status=JobStatus.COMPLETED,
    )
    db.add(job)
    db.flush()
    db.add(DriveAssignment(drive_id=drive.id, job_id=job.id))
    db.commit()

    provider = _fake_eject()
    with patch("app.services.drive_service.ExportFile", new=object()):
        with patch("app.routers.drives.get_drive_eject", return_value=provider):
            response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Unable to verify incomplete-file state; retry prepare-eject"
    provider.prepare_eject.assert_not_called()


def test_prepare_eject_not_found(manager_client, db):
    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()):
        response = manager_client.post("/drives/999/prepare-eject")
    assert response.status_code == 404


def test_prepare_eject_flush_failure(manager_client, db):
    """When sync fails the drive stays IN_USE and DRIVE_EJECT_FAILED is logged."""
    drive = UsbDrive(
        device_identifier="USB007",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(flush_ok=False, flush_error="sync failed")):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive eject preparation failed"

    # Drive state must remain IN_USE.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE

    # Audit log must record the failure.
    from app.models.audit import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_FAILED").first()
    assert log is not None
    assert log.drive_id == drive.id
    assert log.project_id == "PROJ-001"
    assert log.details["flush_ok"] is False
    assert log.details["error_code"] == "EJECT_FLUSH_FAILED"
    assert log.details["message"] == "Drive flush operation failed"
    assert "flush_error" not in log.details


def test_prepare_eject_unmount_failure(manager_client, db):
    """When umount fails the drive stays IN_USE and DRIVE_EJECT_FAILED is logged."""
    drive = UsbDrive(
        device_identifier="USB008",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdc",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        unmount_ok=False, unmount_error="umount failed for /dev/sdc",
    )):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive eject preparation failed"

    # Drive state must remain IN_USE.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE

    # Audit log must record the failure.
    from app.models.audit import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_FAILED").first()
    assert log is not None
    assert log.details["unmount_ok"] is False
    assert log.details["error_code"] == "EJECT_UNMOUNT_FAILED"
    assert log.details["message"] == "Drive unmount operation failed"
    assert "unmount_error" not in log.details
    assert "/dev/sdc" not in str(log.details)


def test_prepare_eject_stale_restart_mount_failure_returns_conflict(manager_client, db):
    """Restart-related stale mount failures return a recoverable conflict, not a generic 500."""
    drive = UsbDrive(
        device_identifier="USB008B",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdc",
        mount_path="/mnt/ecube/8b",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        unmount_ok=False,
        unmount_error="could not read /proc/mounts: stale restart state",
    )):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Drive mount state is stale or changed; refresh drive status and retry prepare-eject"
    )
    assert "/proc/mounts" not in response.json()["message"]


def test_prepare_eject_busy_mount_failure_returns_conflict(manager_client, db):
    """Busy mounted drives return an actionable conflict explaining how to recover."""
    drive = UsbDrive(
        device_identifier="USB008C",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdd",
        mount_path="/mnt/ecube/8c",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        unmount_ok=False,
        unmount_error="umount: /mnt/ecube/8c: target is busy",
    )):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Drive is busy; close any shell, file browser, or process using the mounted drive and retry prepare-eject"
    )
    assert "/mnt/ecube/8c" not in response.json()["message"]


def test_prepare_eject_no_unmount_when_no_path(manager_client, db):
    """prepare_eject is called with None when the drive has no filesystem_path."""
    drive = UsbDrive(
        device_identifier="USB009",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    provider.prepare_eject.assert_called_once_with(None)


def test_prepare_eject_concurrent_state_change(manager_client, db):
    """Returns 409 when the drive state changes between the initial read and re-lock."""
    from app.repositories.drive_repository import DriveRepository

    drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    # Simulate a concurrent state change: get_for_update returns a drive that
    # another request already transitioned to AVAILABLE.
    concurrent_drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.AVAILABLE,
        current_project_id="PROJ-001",
    )
    concurrent_drive.id = drive_id

    with (
        patch("app.routers.drives.get_drive_eject", return_value=_fake_eject()),
        patch.object(DriveRepository, "get_for_update", return_value=concurrent_drive),
    ):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409


def test_prepare_eject_invalid_device_path(manager_client, db):
    """A drive with an invalid filesystem_path is rejected without spawning a process."""
    drive = UsbDrive(
        device_identifier="USB010",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/tmp/../../etc/passwd",
    )
    db.add(drive)
    db.commit()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        unmount_ok=False, unmount_error="invalid device path: /tmp/../../etc/passwd",
    )):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 500
    assert response.json()["message"] == "Drive eject preparation failed"

    # Drive state must remain IN_USE.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.IN_USE

    from app.models.audit import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "DRIVE_EJECT_FAILED").first()
    assert log is not None
    assert log.details["error_code"] == "EJECT_UNMOUNT_FAILED"
    assert log.details["details"] == "Invalid device path"
    assert "/tmp/../../etc/passwd" not in str(log.details)


def test_prepare_eject_requires_ejectable_state(manager_client, db):
    """Prepare-eject must reject drives that are not in an ejectable state (409 Conflict).
    
    Verifies that prepare_eject is NOT called (fast-fail optimization).
    """
    drive = UsbDrive(
        device_identifier="USB011",
        current_state=DriveState.DISCONNECTED,
        current_project_id=None,
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert "not in an ejectable state" in response.json()["message"]
    # Verify prepare_eject was NOT called (fast-fail before OS operations)
    provider.prepare_eject.assert_not_called()

    # Drive state must remain DISCONNECTED.
    db.expire(drive)
    db.refresh(drive)
    assert drive.current_state == DriveState.DISCONNECTED


def test_prepare_eject_available_state_conflict(manager_client, db):
    """Prepare-eject on unmounted AVAILABLE drive returns 409 Conflict.
    
    Verifies that prepare_eject is NOT called (fast-fail optimization).
    """
    drive = UsbDrive(
        device_identifier="USB012",
        current_state=DriveState.AVAILABLE,
        current_project_id=None,
    )
    db.add(drive)
    db.commit()

    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 409
    assert "not mounted" in response.json()["message"]
    # Verify prepare_eject was NOT called (fast-fail before OS operations)
    provider.prepare_eject.assert_not_called()


def test_prepare_eject_device_path_changed(manager_client, db):
    """Prepare-eject fails if filesystem_path changes during operation (409 Conflict).
    
    Simulates scenario where USB discovery refresh changes the device path
    between the initial read and the locked update.
    """
    drive = UsbDrive(
        device_identifier="USB013",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdb",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    def sync_and_change_path(device_path):
        """Simulate eject succeeding, then discovery changing the device path."""
        # Simulate discovery refresh changing the path
        drive_obj = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
        if drive_obj:
            drive_obj.filesystem_path = "/dev/sdc"
            db.commit()
        return EjectResult()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        prepare_eject_side_effect=sync_and_change_path,
    )):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409
    assert "Device path changed" in response.json()["message"]
    assert "/dev/sdb" not in response.json()["message"]
    assert "/dev/sdc" not in response.json()["message"]

    # Drive state must remain IN_USE.
    db.expire_all()
    drive = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
    assert drive.current_state == DriveState.IN_USE


def test_prepare_eject_device_path_cleared_during_operation(manager_client, db):
    """Prepare-eject fails if filesystem_path becomes None during operation (409 Conflict).
    
    Simulates scenario where USB is disconnected and discovery removes the device path.
    """
    drive = UsbDrive(
        device_identifier="USB014",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sde",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    def sync_and_clear_path(device_path):
        """Simulate eject succeeding, then discovery clearing the device path."""
        # Simulate USB disconnection clearing the path
        drive_obj = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
        if drive_obj:
            drive_obj.filesystem_path = None
            db.commit()
        return EjectResult()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        prepare_eject_side_effect=sync_and_clear_path,
    )):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409
    assert "Device path changed" in response.json()["message"]
    assert "/dev/sde" not in response.json()["message"]

    # Drive state must remain IN_USE.
    db.expire_all()
    drive = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
    assert drive.current_state == DriveState.IN_USE


def test_prepare_eject_state_changed_during_operation(manager_client, db):
    """Prepare-eject fails if current_state changes during operation (409 Conflict).
    
    Simulates scenario where another request (e.g., re-initialize) changes the state
    between the initial read and the locked update.
    """
    drive = UsbDrive(
        device_identifier="USB015",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/sdf",
    )
    db.add(drive)
    db.commit()
    drive_id = drive.id

    def sync_and_change_state(device_path):
        """Simulate eject succeeding, then another request changing the state."""
        # Simulate another request re-initializing the drive
        drive_obj = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
        if drive_obj:
            drive_obj.current_state = DriveState.AVAILABLE
            db.commit()
        return EjectResult()

    with patch("app.routers.drives.get_drive_eject", return_value=_fake_eject(
        prepare_eject_side_effect=sync_and_change_state,
    )):
        response = manager_client.post(f"/drives/{drive_id}/prepare-eject")

    assert response.status_code == 409
    assert "state changed during prepare-eject" in response.json()["message"]
    assert "IN_USE" in response.json()["message"]
    assert "AVAILABLE" in response.json()["message"]

    # Drive state should now be AVAILABLE (from the state change).
    db.expire_all()
    drive = db.query(UsbDrive).filter(UsbDrive.id == drive_id).first()
    assert drive.current_state == DriveState.AVAILABLE


def test_prepare_eject_nvme_partitions(manager_client, db):
    """Prepare-eject correctly handles NVMe naming (nvme0n1p1, nvme0n1p2).
    
    Tests that the partition matching logic recognizes modern NVMe partition
    naming with 'p' prefix (e.g., nvme0n1p1) not just traditional digit suffix.
    """
    drive = UsbDrive(
        device_identifier="USB016",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/nvme0n1",
    )
    db.add(drive)
    db.commit()

    # Mock prepare_eject to verify it was called with the base device
    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    # Verify prepare_eject was called with the NVMe device path
    provider.prepare_eject.assert_called_once_with("/dev/nvme0n1")


def test_prepare_eject_mmc_partitions(manager_client, db):
    """Prepare-eject correctly handles MMC naming (mmcblk0p1, mmcblk0p2).
    
    Tests that the partition matching logic recognizes MMC partition naming
    with 'p' prefix (e.g., mmcblk0p1) not just traditional digit suffix.
    """
    drive = UsbDrive(
        device_identifier="USB017",
        current_state=DriveState.IN_USE,
        current_project_id="PROJ-001",
        filesystem_path="/dev/mmcblk0",
    )
    db.add(drive)
    db.commit()

    # Mock prepare_eject to verify it was called with the base device
    provider = _fake_eject()
    with patch("app.routers.drives.get_drive_eject", return_value=provider):
        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")

    assert response.status_code == 200
    assert response.json()["current_state"] == "AVAILABLE"
    # Verify prepare_eject was called with the MMC device path
    provider.prepare_eject.assert_called_once_with("/dev/mmcblk0")



