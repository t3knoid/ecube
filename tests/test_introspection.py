from unittest.mock import MagicMock, mock_open, patch


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


def test_job_debug_not_found(auditor_client, db):
    response = auditor_client.get("/introspection/jobs/999/debug")
    assert response.status_code == 404


def test_job_debug(auditor_client, db):
    from app.models.jobs import ExportJob

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path="/data/evidence",
    )
    db.add(job)
    db.commit()

    response = auditor_client.get(f"/introspection/jobs/{job.id}/debug")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job.id
    assert data["project_id"] == "PROJ-001"
