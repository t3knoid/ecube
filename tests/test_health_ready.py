import app.main as main_module
from app.models.network import MountType, NetworkMount
from sqlalchemy.exc import ProgrammingError


class _HealthyMountProvider:
    def check_mounted(self, _local_mount_point):
        return True


class _FailingMountProvider:
    def check_mounted(self, _local_mount_point):
        return False


class _UnknownMountProvider:
    def check_mounted(self, _local_mount_point):
        return None


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

    monkeypatch.setattr(main_module.db_module, "is_database_configured", lambda: True)
    monkeypatch.setattr(main_module.db_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "execute", _raise_db_error)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "database_connection_failed"
    assert payload["checks"]["database"] == "unhealthy"


def test_health_ready_returns_503_when_database_not_configured(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module.db_module, "is_database_configured", lambda: False)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "database_not_configured"
    assert payload["details"] == "Database is not configured."
    assert isinstance(payload.get("timestamp"), str)
    assert payload["checks"] == {
        "database": "unhealthy",
        "file_system": "unknown",
        "usb_discovery": "unknown",
    }
    # Guard against accidental fallback to global ErrorResponse payload shape.
    assert "code" not in payload
    assert "message" not in payload
    assert "trace_id" not in payload


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


def test_health_ready_returns_503_when_mount_metadata_table_missing(unauthenticated_client, db, monkeypatch):
    def _raise_missing_table(*_args, **_kwargs):
        raise ProgrammingError("SELECT ...", {}, Exception("no such table: network_mounts"))

    monkeypatch.setattr(main_module.db_module, "is_database_configured", lambda: True)
    monkeypatch.setattr(main_module.db_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())
    monkeypatch.setattr(db, "query", _raise_missing_table)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "mount_metadata_unavailable"
    assert payload["details"] == "Mount metadata is not available yet."
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "unknown"


def test_health_ready_returns_503_when_mount_check_is_unknown(unauthenticated_client, db, monkeypatch):
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _UnknownMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "filesystem_mount_check_failed"
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "unknown"


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


def test_health_ready_returns_503_when_usb_sysfs_unavailable(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _HealthyMountProvider())
    monkeypatch.setattr(main_module.os.path, "isdir", lambda _path: False)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "usb_discovery_unavailable"
    assert payload["details"] == "USB discovery runtime path is not accessible."
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "mounted"
    assert payload["checks"]["usb_discovery"] == "unavailable"
