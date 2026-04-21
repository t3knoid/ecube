import json
from pathlib import Path

import pytest

from app.models.hardware import DriveState, UsbDrive, UsbPort
from app.models.jobs import DriveAssignment, ExportJob, JobStatus
from app.models.network import MountStatus, MountType, NetworkMount
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_role_repository import UserRoleRepository


class _FakeOsUserProvider:
    def __init__(self):
        self.users = set()
        self.created = []
        self.reset = []
        self.group_updates = []
        self.groups_ensured = False

    def ensure_ecube_groups(self):
        self.groups_ensured = True
        return []

    def user_exists(self, username: str) -> bool:
        return username in self.users

    def create_user(self, username: str, password: str, groups=None):
        self.users.add(username)
        self.created.append({
            "username": username,
            "password": password,
            "groups": list(groups or []),
        })
        return None

    def reset_password(self, username: str, password: str, *, _skip_managed_check: bool = False):
        self.reset.append({
            "username": username,
            "password": password,
            "skip": _skip_managed_check,
        })
        return None

    def add_user_to_groups(self, username: str, groups, *, _skip_managed_check: bool = False):
        self.group_updates.append({
            "username": username,
            "groups": list(groups or []),
            "skip": _skip_managed_check,
        })
        return None


class _FakeFilesystemDetector:
    def detect(self, _path: str) -> str:
        return "ext4"


class _FakeDriveMountProvider:
    def __init__(self):
        self.mounted = []

    def mount_drive(self, device_path: str, mount_point: str):
        self.mounted.append({"device_path": device_path, "mount_point": mount_point})
        return True, None

    def unmount_drive(self, _mount_point: str):
        return True, None


class _FakeNetworkMountProvider:
    def __init__(self):
        self.mounted = []

    def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None):
        self.mounted.append(
            {
                "type": getattr(mount_type, "value", str(mount_type)),
                "remote_path": remote_path,
                "local_mount_point": local_mount_point,
                "credentials_file": credentials_file,
                "username": username,
                "password": password,
            }
        )
        return True, None

    def os_unmount(self, _local_mount_point):
        return True, None

    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        return True


def test_seed_demo_environment_is_repeatable_and_sanitized(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import DEMO_SEED_MARKER, seed_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "demo_manager",
                "label": "Manager demo",
                "description": "Synthetic workflow review",
                "roles": ["manager"],
            },
            {
                "username": "demo_auditor",
                "label": "Auditor demo",
                "description": "Synthetic audit review",
                "roles": ["auditor"],
            },
        ],
        raising=False,
    )

    provider = _FakeOsUserProvider()
    demo_root = tmp_path / "demo-share"

    first = seed_demo_environment(
        db,
        data_root=demo_root,
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )
    second = seed_demo_environment(
        db,
        data_root=demo_root,
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    role_repo = UserRoleRepository(db)
    assert role_repo.get_roles("demo_manager") == ["manager"]
    assert role_repo.get_roles("demo_auditor") == ["auditor"]

    seeded_jobs = db.query(ExportJob).filter(ExportJob.created_by == DEMO_SEED_MARKER).all()
    assert len(seeded_jobs) == first.jobs_seeded == second.jobs_seeded
    assert len(seeded_jobs) == 0

    readme_text = (demo_root / "README.txt").read_text(encoding="utf-8")
    assert "synthetic" in readme_text.lower()
    assert "do not use for real evidence" in readme_text.lower()

    metadata_text = (demo_root / "demo-metadata.json").read_text(encoding="utf-8")
    assert "must-not-leak" not in metadata_text.lower()
    assert provider.groups_ensured is True
    assert {entry["username"] for entry in provider.created} == {"demo_manager", "demo_auditor"}
    assert first.files_staged == second.files_staged

    logs = AuditRepository(db).query(action="DEMO_BOOTSTRAP_APPLIED", limit=10)
    assert len(logs) >= 2
    assert logs[0].details["data_root"] == "[redacted-path]"
    assert first.data_root == str(demo_root.resolve())


def test_seed_demo_environment_resets_existing_demo_users_to_explicit_shared_password(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "demo_manager",
                "label": "Manager demo",
                "description": "Synthetic workflow review",
                "roles": ["manager"],
                "password": "stale-password",
            },
        ],
        raising=False,
    )

    provider = _FakeOsUserProvider()
    provider.users.add("demo_manager")
    demo_root = tmp_path / "demo-share"

    seed_demo_environment(
        db,
        data_root=demo_root,
        provider=provider,
        shared_password="FreshShared#123",
        actor="demo-seed-test",
    )

    assert provider.created == []
    assert provider.reset == [
        {
            "username": "demo_manager",
            "password": "FreshShared#123",
            "skip": True,
        }
    ]


def test_seed_demo_environment_can_seed_connected_usb_drives_from_metadata(db, tmp_path, monkeypatch):
    from app.infrastructure.usb_discovery import DiscoveredDrive, DiscoveredHub, DiscoveredPort, DiscoveredTopology
    from app.services.demo_seed_service import seed_demo_environment

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
                        {
                            "username": "demo_processor",
                            "label": "Processor demo",
                            "description": "Synthetic export review",
                            "roles": ["processor"],
                        }
                    ]
                },
                "usb_seed": {
                    "enabled": True,
                    "drives": [
                        {
                            "port_system_path": "1-1",
                            "project_id": "DEMO-CASE-001",
                            "device_identifier": "usb-demo-001"
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Demo hub")],
        ports=[
            DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1"),
            DiscoveredPort(hub_system_identifier="usb1", port_number=2, system_path="1-2"),
        ],
        drives=[
            DiscoveredDrive(
                device_identifier="usb-demo-001",
                port_system_path="1-1",
                filesystem_path="/dev/sdz",
                capacity_bytes=64 * 1024 * 1024,
                mount_path=None,
            ),
            DiscoveredDrive(
                device_identifier="usb-demo-002",
                port_system_path="1-2",
                filesystem_path="/dev/sdy",
                capacity_bytes=32 * 1024 * 1024,
                mount_path=None,
            ),
        ],
    )
    mount_provider = _FakeDriveMountProvider()

    result = seed_demo_environment(
        db,
        data_root=demo_root,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
        topology_source=lambda: topology,
        filesystem_detector=_FakeFilesystemDetector(),
        mount_provider=mount_provider,
    )

    configured_drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "usb-demo-001").one()
    other_drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "usb-demo-002").one()
    configured_port = db.query(UsbPort).filter(UsbPort.id == configured_drive.port_id).one()
    other_port = db.query(UsbPort).filter(UsbPort.id == other_drive.port_id).one()
    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))

    assert configured_port.system_path == "1-1"
    assert configured_port.enabled is True
    assert configured_drive.current_state == DriveState.IN_USE
    assert configured_drive.current_project_id == "DEMO-CASE-001"
    assert configured_drive.mount_path is not None

    assert other_port.system_path == "1-2"
    assert other_port.enabled is False
    assert other_drive.current_project_id is None

    assert metadata["usb_seed"]["enabled"] is True
    assert metadata["usb_seed"]["drives"][0]["port_system_path"] == "1-1"
    assert metadata["usb_seed"]["drives"][0]["project_id"] == 1
    assert metadata["projects"][0]["project_name"] == "DEMO-CASE-001"
    assert result.usb_drives_seeded == 1
    assert result.usb_drives_mounted == 1
    assert len(mount_provider.mounted) == 1

def test_seed_demo_environment_uses_current_usb_drive_when_port_has_history(db, tmp_path, monkeypatch):
    from app.infrastructure.usb_discovery import DiscoveredDrive, DiscoveredHub, DiscoveredPort, DiscoveredTopology
    from app.models.hardware import UsbHub
    from app.services.demo_seed_service import seed_demo_environment

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "usb_seed": {
                    "enabled": True,
                    "drives": [
                        {
                            "port_system_path": "1-1",
                            "project_id": "DEMO-CASE-001",
                            "device_identifier": "usb-demo-new"
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    hub = UsbHub(name="Existing hub", system_identifier="usb1")
    db.add(hub)
    db.flush()
    port = UsbPort(hub_id=hub.id, port_number=1, system_path="1-1", enabled=False)
    db.add(port)
    db.flush()
    db.add(
        UsbDrive(
            device_identifier="usb-demo-old",
            port_id=port.id,
            filesystem_path=None,
            filesystem_type="ext4",
            current_state=DriveState.DISCONNECTED,
            current_project_id="DEMO-CASE-001",
        )
    )
    db.commit()

    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Demo hub")],
        ports=[DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")],
        drives=[
            DiscoveredDrive(
                device_identifier="usb-demo-new",
                port_system_path="1-1",
                filesystem_path="/dev/sdz",
                capacity_bytes=64 * 1024 * 1024,
                mount_path=None,
            )
        ],
    )
    mount_provider = _FakeDriveMountProvider()

    result = seed_demo_environment(
        db,
        data_root=demo_root,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
        topology_source=lambda: topology,
        filesystem_detector=_FakeFilesystemDetector(),
        mount_provider=mount_provider,
    )

    new_drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "usb-demo-new").one()
    old_drive = db.query(UsbDrive).filter(UsbDrive.device_identifier == "usb-demo-old").one()
    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))

    assert new_drive.current_project_id == "DEMO-CASE-001"
    assert new_drive.current_state == DriveState.IN_USE
    assert new_drive.mount_path is not None
    assert old_drive.port_id is None
    assert metadata["usb_seed"]["drives"][0]["id"] == new_drive.id
    assert result.usb_drives_seeded == 1
    assert result.usb_drives_mounted == 1
    assert len(mount_provider.mounted) == 1


def test_seed_demo_environment_can_seed_network_mounts_from_metadata(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "mount_seed": {
                    "enabled": True,
                    "mounts": [
                        {
                            "type": "NFS",
                            "remote_path": "192.168.1.10:/exports/demo-case-001",
                            "project_id": "DEMO-CASE-001"
                        },
                        {
                            "type": "SMB",
                            "remote_path": "//fileserver/demo-share",
                            "project_id": "DEMO-CASE-002",
                            "username": "demo-user",
                            "password": "secret-demo",
                            "credentials_file": "/tmp/demo-smb.creds"
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    provider = _FakeNetworkMountProvider()
    result = seed_demo_environment(
        db,
        data_root=demo_root,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
        network_mount_provider=provider,
    )

    mounts = db.query(NetworkMount).order_by(NetworkMount.id).all()
    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))

    assert len(mounts) == 2
    assert mounts[0].type == MountType.NFS
    assert mounts[0].project_id == "DEMO-CASE-001"
    assert mounts[0].status == MountStatus.MOUNTED
    assert mounts[1].type == MountType.SMB
    assert mounts[1].project_id == "DEMO-CASE-002"
    assert mounts[1].status == MountStatus.MOUNTED

    assert metadata["mount_seed"]["enabled"] is True
    assert metadata["mount_seed"]["mounts"][0]["remote_path"] == "192.168.1.10:/exports/demo-case-001"
    assert metadata["mount_seed"]["mounts"][1]["credentials_file"] == "/tmp/demo-smb.creds"

    assert result.network_mounts_seeded == 2
    assert result.network_mounts_mounted == 2
    assert provider.mounted[1]["username"] == "demo-user"
    assert provider.mounted[1]["password"] == "secret-demo"
    assert provider.mounted[1]["credentials_file"] == "/tmp/demo-smb.creds"


def test_seed_demo_environment_resolves_numeric_project_references(db, tmp_path, monkeypatch):
    from app.infrastructure.usb_discovery import DiscoveredDrive, DiscoveredHub, DiscoveredPort, DiscoveredTopology
    from app.services.demo_seed_service import DEMO_SEED_MARKER, seed_demo_environment

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "projects": [
                    {
                        "project_id": 1,
                        "project_name": "DEMO-CASE-001",
                        "folder": "demo-case-001",
                        "sanitized": True,
                    }
                ],
                "usb_seed": {
                    "enabled": True,
                    "drives": [
                        {
                            "id": 99,
                            "port_system_path": "1-1",
                            "project_id": 1,
                            "device_identifier": "usb-demo-001"
                        }
                    ]
                },
                "mount_seed": {
                    "enabled": True,
                    "mounts": [
                        {
                            "id": 77,
                            "type": "NFS",
                            "remote_path": "192.168.1.10:/exports/demo-case-001",
                            "project_id": 1
                        }
                    ]
                },
                "job_seed": {
                    "jobs": [
                        {
                            "project_id": 1,
                            "evidence_number": "EVID-JOB-001",
                            "mount_id": 77,
                            "drive_id": 99,
                            "source_path": "/incoming"
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Demo hub")],
        ports=[DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")],
        drives=[
            DiscoveredDrive(
                device_identifier="usb-demo-001",
                port_system_path="1-1",
                filesystem_path="/dev/sdz",
                capacity_bytes=64 * 1024 * 1024,
                mount_path=None,
            )
        ],
    )

    seed_demo_environment(
        db,
        data_root=demo_root,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
        topology_source=lambda: topology,
        filesystem_detector=_FakeFilesystemDetector(),
        mount_provider=_FakeDriveMountProvider(),
        network_mount_provider=_FakeNetworkMountProvider(),
    )

    jobs = db.query(ExportJob).filter(ExportJob.created_by == DEMO_SEED_MARKER).order_by(ExportJob.id).all()
    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))

    assert len(jobs) == 1
    assert jobs[0].project_id == "DEMO-CASE-001"
    assert metadata["projects"][0]["project_id"] == 1
    assert metadata["projects"][0]["project_name"] == "DEMO-CASE-001"
    assert "evidence_number" not in metadata["projects"][0]
    assert "title" not in metadata["projects"][0]
    assert metadata["usb_seed"]["drives"][0]["project_id"] == 1
    assert metadata["mount_seed"]["mounts"][0]["project_id"] == 1
    assert metadata["job_seed"]["jobs"][0]["project_id"] == 1


def test_seed_demo_environment_can_seed_jobs_from_component_ids(db, tmp_path, monkeypatch):
    from app.infrastructure.usb_discovery import DiscoveredDrive, DiscoveredHub, DiscoveredPort, DiscoveredTopology
    from app.services.demo_seed_service import DEMO_SEED_MARKER, seed_demo_environment

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "usb_seed": {
                    "enabled": True,
                    "drives": [
                        {
                            "id": 99,
                            "port_system_path": "1-1",
                            "project_id": "DEMO-CASE-001",
                            "device_identifier": "usb-demo-001"
                        }
                    ]
                },
                "mount_seed": {
                    "enabled": True,
                    "mounts": [
                        {
                            "id": 77,
                            "type": "NFS",
                            "remote_path": "192.168.1.10:/exports/demo-case-001",
                            "project_id": "DEMO-CASE-001"
                        }
                    ]
                },
                "job_seed": {
                    "jobs": [
                        {
                            "id": 42,
                            "project_id": "DEMO-CASE-001",
                            "evidence_number": "EVID-JOB-001",
                            "mount_id": 77,
                            "drive_id": 99,
                            "source_path": "/incoming"
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Demo hub")],
        ports=[DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")],
        drives=[
            DiscoveredDrive(
                device_identifier="usb-demo-001",
                port_system_path="1-1",
                filesystem_path="/dev/sdz",
                capacity_bytes=64 * 1024 * 1024,
                mount_path=None,
            )
        ],
    )

    result = seed_demo_environment(
        db,
        data_root=demo_root,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
        topology_source=lambda: topology,
        filesystem_detector=_FakeFilesystemDetector(),
        mount_provider=_FakeDriveMountProvider(),
        network_mount_provider=_FakeNetworkMountProvider(),
    )

    jobs = db.query(ExportJob).filter(ExportJob.created_by == DEMO_SEED_MARKER).order_by(ExportJob.id).all()
    assignments = db.query(DriveAssignment).order_by(DriveAssignment.id).all()
    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))

    assert len(jobs) == 1
    assert jobs[0].project_id == "DEMO-CASE-001"
    assert jobs[0].evidence_number == "EVID-JOB-001"
    assert jobs[0].status == JobStatus.PENDING
    assert jobs[0].source_path == "/nfs/demo-case-001/incoming"
    assert jobs[0].target_mount_path is not None

    assert len(assignments) == 1
    assert assignments[0].job_id == jobs[0].id

    assert metadata["usb_seed"]["drives"][0]["id"] == 1
    assert metadata["mount_seed"]["mounts"][0]["id"] == 1
    assert metadata["job_seed"]["jobs"][0]["id"] == 42
    assert jobs[0].id == 42
    assert metadata["job_seed"]["jobs"][0]["ui_job_id"] == 42
    assert metadata["job_seed"]["jobs"][0]["drive_id"] == 1
    assert metadata["job_seed"]["jobs"][0]["mount_id"] == 1
    assert result.jobs_seeded == 1


def test_seed_demo_environment_can_load_metadata_from_explicit_metadata_path(db, tmp_path, monkeypatch):
    from app.infrastructure.usb_discovery import DiscoveredDrive, DiscoveredHub, DiscoveredPort, DiscoveredTopology
    from app.services.demo_seed_service import DEMO_SEED_MARKER, seed_demo_environment

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    install_root = tmp_path / "install-root"
    install_root.mkdir()
    metadata_path = install_root / "demo-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "projects": [
                    {
                        "project_id": 1,
                        "project_name": "DEMO-CASE-001",
                        "folder": "demo-case-001",
                        "sanitized": True,
                    }
                ],
                "usb_seed": {
                    "enabled": True,
                    "drives": [
                        {
                            "id": 99,
                            "port_system_path": "1-1",
                            "project_id": 1,
                            "device_identifier": "usb-demo-001"
                        }
                    ]
                },
                "mount_seed": {
                    "enabled": True,
                    "mounts": [
                        {
                            "id": 77,
                            "type": "NFS",
                            "remote_path": "192.168.1.10:/exports/demo-case-001",
                            "project_id": 1
                        }
                    ]
                },
                "job_seed": {
                    "jobs": [
                        {
                            "id": 42,
                            "project_id": 1,
                            "evidence_number": "EVID-JOB-001",
                            "mount_id": 77,
                            "drive_id": 99,
                            "source_path": "/incoming"
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    topology = DiscoveredTopology(
        hubs=[DiscoveredHub(system_identifier="usb1", name="Demo hub")],
        ports=[DiscoveredPort(hub_system_identifier="usb1", port_number=1, system_path="1-1")],
        drives=[
            DiscoveredDrive(
                device_identifier="usb-demo-001",
                port_system_path="1-1",
                filesystem_path="/dev/sdz",
                capacity_bytes=64 * 1024 * 1024,
                mount_path=None,
            )
        ],
    )

    result = seed_demo_environment(
        db,
        data_root=demo_root,
        metadata_path=metadata_path,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
        topology_source=lambda: topology,
        filesystem_detector=_FakeFilesystemDetector(),
        mount_provider=_FakeDriveMountProvider(),
        network_mount_provider=_FakeNetworkMountProvider(),
    )

    jobs = db.query(ExportJob).filter(ExportJob.created_by == DEMO_SEED_MARKER).order_by(ExportJob.id).all()
    assert len(jobs) == 1
    assert jobs[0].id == 42
    assert jobs[0].evidence_number == "EVID-JOB-001"
    assert result.jobs_seeded == 1



def test_seed_demo_environment_writes_runtime_demo_config_to_metadata(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_login_message",
        "Use the shared demo accounts below.",
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_disable_password_change",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "demo_manager",
                "label": "Manager demo",
                "description": "Synthetic workflow review",
                "roles": ["manager"],
            }
        ],
        raising=False,
    )

    demo_root = tmp_path / "demo-share"
    seed_demo_environment(
        db,
        data_root=demo_root,
        provider=_FakeOsUserProvider(),
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))
    assert metadata["managed_by"] == "ecube-demo-seed-v1"
    assert metadata["demo_config"]["login_message"] == "Use the shared demo accounts below."
    assert metadata["demo_config"]["shared_password"] == "SharedDemo#123"
    assert metadata["demo_config"]["password_change_allowed"] is False
    assert metadata["demo_config"]["accounts"][0]["username"] == "demo_manager"
    assert metadata["demo_config"]["accounts"][0]["roles"] == ["manager"]


def test_reset_demo_environment_refuses_unmanaged_directory(db, tmp_path):
    from app.services.demo_seed_service import reset_demo_environment

    unmanaged_root = tmp_path / "customer-data"
    unmanaged_root.mkdir()
    (unmanaged_root / "notes.txt").write_text("customer content", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to delete unmanaged directory"):
        reset_demo_environment(db, data_root=unmanaged_root, actor="demo-seed-test")


def test_reset_demo_environment_removes_seeded_state(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import DEMO_SEED_MARKER, reset_demo_environment, seed_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "demo_processor",
                "label": "Processor demo",
                "description": "Synthetic export review",
                "roles": ["processor"],
            }
        ],
        raising=False,
    )

    provider = _FakeOsUserProvider()
    demo_root = tmp_path / "demo-share"
    seed_demo_environment(
        db,
        data_root=demo_root,
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    result = reset_demo_environment(db, data_root=demo_root, actor="demo-seed-test")

    assert result.jobs_removed == 0
    assert result.roles_removed >= 1
    assert not demo_root.exists()
    assert db.query(ExportJob).filter(ExportJob.created_by == DEMO_SEED_MARKER).count() == 0
    assert UserRoleRepository(db).get_roles("demo_processor") == []

    logs = AuditRepository(db).query(action="DEMO_BOOTSTRAP_RESET", limit=10)
    assert len(logs) >= 1
    assert logs[0].details["data_root"] == "[redacted-path]"
    assert result.data_root == str(Path(demo_root).resolve())
