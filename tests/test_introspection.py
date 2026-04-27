from unittest.mock import MagicMock, mock_open, patch

from app.exceptions import ConflictError
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort


def test_system_health(client, db):
    response = client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "active_jobs" in data
    assert "worker_queue_size" in data
    # metric fields are present (may be null when psutil unavailable in CI)
    assert "cpu_percent" in data
    assert "memory_percent" in data
    assert "memory_used_bytes" in data
    assert "memory_total_bytes" in data
    assert "disk_read_bytes" in data
    assert "disk_write_bytes" in data


def test_system_health_psutil_metrics(client, db):
    """When psutil is available the metric fields are populated with real values."""
    fake_vm = MagicMock()
    fake_vm.percent = 42.0
    fake_vm.used = 2_000_000_000
    fake_vm.total = 8_000_000_000

    fake_io = MagicMock()
    fake_io.read_bytes = 1_000_000
    fake_io.write_bytes = 500_000

    with (
        patch("app.routers.introspection._PSUTIL_AVAILABLE", True),
        patch("app.routers.introspection._psutil") as mock_psutil,
    ):
        mock_psutil.cpu_percent.return_value = 12.5
        mock_psutil.virtual_memory.return_value = fake_vm
        mock_psutil.disk_io_counters.return_value = fake_io

        response = client.get("/introspection/system-health")

    assert response.status_code == 200
    data = response.json()
    assert data["cpu_percent"] == 12.5
    # Use assert_any_call rather than assert_called_once_with: the background
    # priming task (asyncio.to_thread(prime_cpu_sampler)) may also call
    # cpu_percent(interval=1.0) on the same mock if it races with this patch,
    # so we only assert that the endpoint made its expected non-blocking call.
    mock_psutil.cpu_percent.assert_any_call(interval=None)
    assert data["memory_percent"] == 42.0
    assert data["memory_used_bytes"] == 2_000_000_000
    assert data["memory_total_bytes"] == 8_000_000_000
    assert data["disk_read_bytes"] == 1_000_000
    assert data["disk_write_bytes"] == 500_000


def test_system_health_psutil_unavailable(client, db):
    """When psutil is not installed all metric fields are null."""
    with patch("app.routers.introspection._PSUTIL_AVAILABLE", False):
        response = client.get("/introspection/system-health")

    assert response.status_code == 200
    data = response.json()
    assert data["cpu_percent"] is None
    assert data["memory_percent"] is None
    assert data["memory_used_bytes"] is None
    assert data["memory_total_bytes"] is None
    assert data["disk_read_bytes"] is None
    assert data["disk_write_bytes"] is None


def test_system_health_worker_queue_size(client, db):
    """worker_queue_size counts PENDING jobs."""
    from app.models.jobs import ExportJob, JobStatus

    job = ExportJob(
        project_id="PROJ-Q",
        evidence_number="EV-Q",
        source_path="/data/q",
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()

    response = client.get("/introspection/system-health")
    assert response.status_code == 200
    assert response.json()["worker_queue_size"] >= 1


def test_system_health_worker_queue_size_null_on_count_failure(client, db):
    """worker_queue_size is None when only the PENDING count query raises.

    The SELECT 1 connectivity probe uses Session.execute (not Query.count), so the
    database is still reported as reachable.  The RUNNING count (active_jobs) is
    allowed to succeed (returns 0); only the subsequent PENDING count raises, isolating
    the worker_queue_size error path from the active_jobs path.  The endpoint must
    leave worker_queue_size as None rather than defaulting to 0 so callers can
    distinguish "no pending jobs" from "count unknown".
    """
    from sqlalchemy.exc import OperationalError

    # side_effect list: first call (RUNNING / active_jobs) returns 0;
    # second call (PENDING / worker_queue_size) raises.
    with patch(
        "sqlalchemy.orm.Query.count",
        side_effect=[0, OperationalError("", {}, None)],
    ):
        response = client.get("/introspection/system-health")

    assert response.status_code == 200
    data = response.json()
    # DB connectivity check still passes — status/database must not be degraded.
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    # Only the PENDING count failed — size must be null, not zero.
    assert data["worker_queue_size"] is None


def test_system_mounts(client, db):
    mock_content = "sysfs /sys sysfs rw,nosuid 0 0\ntmpfs /tmp tmpfs rw 0 0\n"
    with patch("builtins.open", mock_open(read_data=mock_content)):
        response = client.get("/introspection/mounts")
    assert response.status_code == 200
    data = response.json()
    assert "mounts" in data


def test_block_devices(client, db):
    response = client.get("/introspection/block-devices")
    assert response.status_code == 200
    assert "block_devices" in response.json()


def test_usb_topology(client, db):
    response = client.get("/introspection/usb/topology")
    assert response.status_code == 200
    assert "devices" in response.json()


def test_usb_topology_includes_serial_when_available(client, db):
    file_values = {
        "/sys/bus/usb/devices/2-1/serial": "SER-USB-001",
        "/sys/bus/usb/devices/2-1/idVendor": "abcd",
        "/sys/bus/usb/devices/2-1/idProduct": "1234",
        "/sys/bus/usb/devices/2-1/product": "Evidence Drive",
        "/sys/bus/usb/devices/2-1/manufacturer": "ECUBE",
    }

    def _open_side_effect(path, *args, **kwargs):
        handle = mock_open(read_data=file_values[path]).return_value
        handle.__iter__.return_value = file_values[path].splitlines(True)
        return handle

    with (
        patch("app.routers.introspection.os.path.exists", return_value=True),
        patch("app.routers.introspection.os.listdir", return_value=["2-1"]),
        patch("app.routers.introspection.os.path.isfile", return_value=True),
        patch("builtins.open", side_effect=_open_side_effect),
    ):
        response = client.get("/introspection/usb/topology")

    assert response.status_code == 200
    assert response.json()["devices"] == [{
        "device": "2-1",
        "serial": "SER-USB-001",
        "idVendor": "abcd",
        "idProduct": "1234",
        "product": "Evidence Drive",
        "manufacturer": "ECUBE",
    }]


def test_introspection_drives_exposes_port_and_serial_identifiers(auditor_client, db):
    hub = UsbHub(name="Hub Ticket260", system_identifier="hub-ticket260-introspection")
    db.add(hub)
    db.flush()

    port = UsbPort(hub_id=hub.id, port_number=92, system_path="9-2", enabled=True)
    db.add(port)
    db.flush()

    drive = UsbDrive(device_identifier="SER-INV-001", port_id=port.id, current_state=DriveState.AVAILABLE)
    db.add(drive)
    db.commit()

    response = auditor_client.get("/introspection/drives")
    assert response.status_code == 200
    payload = response.json()["drives"]
    match = next(item for item in payload if item["id"] == drive.id)
    assert match["port_system_path"] == "9-2"
    assert match["serial_number"] == "SER-INV-001"


def test_system_health_degraded(client, db):
    from unittest.mock import patch
    from sqlalchemy.exc import OperationalError

    with patch("sqlalchemy.orm.Session.execute", side_effect=OperationalError("", {}, None)):
        response = client.get("/introspection/system-health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["database"] == "error"
    assert data["database_error"] is not None


def test_reconcile_managed_mounts_requires_authentication(unauthenticated_client, db):
    response = unauthenticated_client.post("/introspection/reconcile-managed-mounts")
    assert response.status_code == 401


def test_reconcile_managed_mounts_forbidden_for_auditor(auditor_client, db):
    response = auditor_client.post("/introspection/reconcile-managed-mounts")
    assert response.status_code == 403


def test_reconcile_managed_mounts_manager_success(manager_client, db):
    with patch(
        "app.routers.introspection.reconciliation_service.run_manual_managed_mount_reconciliation",
        return_value={
            "status": "ok",
            "scope": "managed_mounts_only",
            "network_mounts_checked": 2,
            "network_mounts_corrected": 1,
            "usb_mounts_checked": 1,
            "usb_mounts_corrected": 1,
            "failure_count": 0,
        },
    ) as run_mock:
        response = manager_client.post("/introspection/reconcile-managed-mounts")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["scope"] == "managed_mounts_only"
    assert payload["failure_count"] == 0
    run_mock.assert_called_once()


def test_reconcile_managed_mounts_conflict_when_run_in_progress(manager_client, db):
    with patch(
        "app.routers.introspection.reconciliation_service.run_manual_managed_mount_reconciliation",
        side_effect=ConflictError(
            message="A manual mount reconciliation run is already in progress.",
            code="MANUAL_RECONCILIATION_IN_PROGRESS",
        ),
    ):
        response = manager_client.post("/introspection/reconcile-managed-mounts")

    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "MANUAL_RECONCILIATION_IN_PROGRESS"
