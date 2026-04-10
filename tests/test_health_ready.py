import app.main as main_module
from app.models.network import MountType, NetworkMount
from sqlalchemy.exc import ProgrammingError


class _HealthyMountProvider:
    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        return True


class _FailingMountProvider:
    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        return False


class _UnknownMountProvider:
    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        return None


class _RaisingMountProvider:
    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        raise RuntimeError("mountpoint command failed")


class _RecordingMountProvider:
    def __init__(self):
        self.last_timeout_seconds = None

    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        self.last_timeout_seconds = timeout_seconds
        return True

class _HealthyDiscoveryProvider:
    def discover_topology(self):
        return {"hubs": [], "ports": [], "drives": []}


class _FailingDiscoveryProvider:
    def discover_topology(self):
        raise RuntimeError("usb init pending")


def test_health_ready_returns_200_when_all_checks_pass(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _HealthyMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())
    monkeypatch.setattr(main_module, "_probe_usb_sysfs_available", lambda: True)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"] == {
        "database": "healthy",
        "file_system": "mounted",
        "usb_discovery": "initialized",
    }


def test_health_ready_returns_200_when_no_mounts_configured(unauthenticated_client, db, monkeypatch):
    """Readiness should pass without provider when no mounts are configured."""
    def _raise_provider_error():
        raise ValueError("Mount provider not available")

    monkeypatch.setattr(main_module, "get_mount_provider", _raise_provider_error)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())
    monkeypatch.setattr(main_module, "_probe_usb_sysfs_available", lambda: True)

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
    monkeypatch.setattr(main_module.settings, "database_url", "")

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


def test_health_ready_returns_503_when_database_misconfigured(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module.db_module, "is_database_configured", lambda: False)
    monkeypatch.setattr(main_module.settings, "database_url", "postgresql://invalid-url")

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "database_misconfigured"
    assert payload["details"] == "Database is configured but failed to initialize."
    assert isinstance(payload.get("timestamp"), str)
    assert payload["checks"] == {
        "database": "unhealthy",
        "file_system": "unknown",
        "usb_discovery": "unknown",
    }


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


def test_health_ready_returns_503_when_mount_provider_unavailable(unauthenticated_client, db, monkeypatch):
    # Add a mount so provider resolution is attempted
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    def _raise_provider_error():
        raise ValueError("Unsupported platform")

    monkeypatch.setattr(main_module, "get_mount_provider", _raise_provider_error)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "mount_provider_unavailable"
    assert payload["details"] == "Filesystem mount provider is not available."
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
    assert payload["reason"] == "filesystem_mount_check_unknown"
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "unknown"


def test_health_ready_returns_503_when_mount_check_raises(unauthenticated_client, db, monkeypatch):
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _RaisingMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "filesystem_mount_check_error"
    assert payload["details"] == "A required filesystem mount readiness check encountered a runtime error."
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "unknown"


def test_health_ready_passes_configured_mount_check_timeout(unauthenticated_client, db, monkeypatch):
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    provider = _RecordingMountProvider()
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: provider)
    monkeypatch.setattr(main_module.settings, "readiness_mount_check_timeout_seconds", 0.25)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())
    monkeypatch.setattr(main_module, "_probe_usb_sysfs_available", lambda: True)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 200
    assert provider.last_timeout_seconds == 0.25


def test_health_ready_non_positive_mount_timeout_uses_default_when_no_budget(unauthenticated_client, db, monkeypatch):
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    provider = _RecordingMountProvider()
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: provider)
    monkeypatch.setattr(main_module.settings, "readiness_mount_check_timeout_seconds", 0)
    monkeypatch.setattr(main_module.settings, "readiness_mount_checks_total_timeout_seconds", 0)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())
    monkeypatch.setattr(main_module, "_probe_usb_sysfs_available", lambda: True)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 200
    assert provider.last_timeout_seconds == 1.0


def test_health_ready_non_positive_mount_timeout_uses_remaining_budget(unauthenticated_client, db, monkeypatch):
    db.add(
        NetworkMount(
            type=MountType.NFS,
            remote_path="10.0.0.1:/evidence",
            local_mount_point="/mnt/evidence",
        )
    )
    db.commit()

    provider = _RecordingMountProvider()
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: provider)
    monkeypatch.setattr(main_module.settings, "readiness_mount_check_timeout_seconds", -1)
    monkeypatch.setattr(main_module.settings, "readiness_mount_checks_total_timeout_seconds", 0.5)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())
    monkeypatch.setattr(main_module, "_probe_usb_sysfs_available", lambda: True)

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 200
    assert provider.last_timeout_seconds > 0
    assert provider.last_timeout_seconds <= 0.5


def test_health_ready_returns_503_when_mount_checks_exceed_total_budget(unauthenticated_client, monkeypatch):
    class _FakeQuery:
        def all(self):
            return [
                type("M", (), {"local_mount_point": "/mnt/evidence-a"})(),
                type("M", (), {"local_mount_point": "/mnt/evidence-b"})(),
            ]

    class _FakeDB:
        def execute(self, *_args, **_kwargs):
            return None

        def query(self, *_args, **_kwargs):
            return _FakeQuery()

        def close(self):
            return None

    def _override_get_db_or_none():
        yield _FakeDB()

    monkeypatch.setitem(
        main_module.app.dependency_overrides,
        main_module._get_db_or_none,
        _override_get_db_or_none,
    )

    class _SlowMountedProvider:
        def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
            main_module.time.sleep(0.1)
            return True

    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _SlowMountedProvider())
    monkeypatch.setattr(main_module.settings, "readiness_mount_check_timeout_seconds", 1.0)
    monkeypatch.setattr(main_module.settings, "readiness_mount_checks_total_timeout_seconds", 0.05)
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _HealthyDiscoveryProvider())

    response = unauthenticated_client.get("/health/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["reason"] == "filesystem_mount_checks_timed_out"
    assert payload["details"] == "Filesystem mount checks exceeded readiness time budget."
    assert payload["checks"]["database"] == "healthy"
    assert payload["checks"]["file_system"] == "unknown"


def test_health_ready_returns_503_when_usb_discovery_not_ready(unauthenticated_client, db, monkeypatch):
    monkeypatch.setattr(main_module, "get_mount_provider", lambda: _HealthyMountProvider())
    monkeypatch.setattr(main_module, "get_drive_discovery", lambda: _FailingDiscoveryProvider())
    monkeypatch.setattr(main_module, "_probe_usb_sysfs_available", lambda: True)

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
