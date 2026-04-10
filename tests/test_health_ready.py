import app.main as main_module
from app.models.network import MountType, NetworkMount


class _HealthyMountProvider:
    def check_mounted(self, _local_mount_point):
        return True


class _FailingMountProvider:
    def check_mounted(self, _local_mount_point):
        return False


class _HealthyDiscoveryProvider:
    def discover_topology(self):
        return {"hubs": [], "ports": [], "drives": []}


class _FailingDiscoveryProvider:
    def discover_topology(self):
        raise RuntimeError("usb init pending")


def test_health_ready_returns_200_when_all_checks_pass(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _HealthyMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"] == {
        "database": "healthy",
        "file_system": "mounted",
        "usb_discovery": "initialized",
    }


def test_health_ready_returns_503_when_database_fails(unauthenticated_client, db, monkeypatch):
    def _raise_db_error(*_args, **_kwargs):
        raise RuntimeError("database offline")

    monkeypatch.setattr(db, "execute", _raise_db_error)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "database_connection_failed"
    assert payload["checks"]["database"] == "unhealthy"


def test_health_ready_returns_503_when_mount_check_fails(unauthenticated_client, db, monkeypatch):
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _FailingMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "filesystem_mount_unavailable"
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "unmounted"


def test_health_ready_returns_503_when_usb_discovery_not_ready(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _HealthyMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _FailingDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "usb_discovery_not_initialized"
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "mounted"
    assert payload["checks"]["usb_discovery"] == "not_initialized"
