import logging
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.hardware import DriveState, UsbDrive, UsbPort
from app.models.jobs import DriveAssignment, ExportJob, JobStatus
from app.models.network import MountStatus, MountType, NetworkMount
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_role_repository import UserRoleRepository
from app.utils.drive_identity import build_persistent_device_identifier


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

    def os_mount(self, mount_type, remote_path, local_mount_point, *, credentials_file=None, username=None, password=None, nfs_client_version=None):
        self.mounted.append(
            {
                "type": getattr(mount_type, "value", str(mount_type)),
                "remote_path": remote_path,
                "local_mount_point": local_mount_point,
                "credentials_file": credentials_file,
                "username": username,
                "password": password,
                "nfs_client_version": nfs_client_version,
            }
        )
        return True, None

    def os_unmount(self, _local_mount_point):
        return True, None

    def check_mounted(self, _local_mount_point, *, timeout_seconds=None):
        return True


def test_seed_demo_environment_is_repeatable_and_sanitized(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import DEMO_SEED_MARKER, seed_demo_environment

    provider = _FakeOsUserProvider()
    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
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
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    first = seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )
    second = seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    role_repo = UserRoleRepository(db)
    assert role_repo.get_roles("demo_manager") == ["manager"]
    assert role_repo.get_roles("demo_auditor") == ["auditor"]

    seeded_jobs = db.query(ExportJob).all()
    assert len(seeded_jobs) == first.jobs_seeded == second.jobs_seeded
    assert len(seeded_jobs) == 0

    assert provider.groups_ensured is True
    assert {entry["username"] for entry in provider.created} == {"demo_manager", "demo_auditor"}
    assert {path.name for path in demo_root.iterdir()} == {"demo-metadata.json"}

    logs = AuditRepository(db).query(action="DEMO_BOOTSTRAP_APPLIED", limit=10)
    assert len(logs) >= 2
    assert logs[0].details["usernames"] == ["demo_manager", "demo_auditor"]


def test_seed_demo_environment_resets_existing_demo_users_to_explicit_shared_password(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    provider = _FakeOsUserProvider()
    provider.users.add("demo_manager")
    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
                        {
                            "username": "demo_manager",
                            "label": "Manager demo",
                            "description": "Synthetic workflow review",
                            "roles": ["manager"],
                            "password": "stale-password",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
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


def test_seed_runtime_demo_environment_skips_password_reset_for_selected_existing_user(db):
    from app.services.demo_seed_service import seed_runtime_demo_environment

    provider = _FakeOsUserProvider()
    provider.users.add("demo_admin")

    with patch("app.config.Settings.get_demo_accounts", return_value=[]), patch(
        "app.config.Settings.get_demo_shared_password",
        return_value="SharedDemo#123",
    ):
        result = seed_runtime_demo_environment(
            db,
            provider=provider,
            actor="demo-seed-test",
            skip_password_usernames=["demo_admin"],
        )

    assert result.users_seeded == 4
    assert provider.reset == []
    assert provider.created == [
        {
            "username": "demo_manager",
            "password": "SharedDemo#123",
            "groups": ["ecube-managers"],
        },
        {
            "username": "demo_processor",
            "password": "SharedDemo#123",
            "groups": ["ecube-processors"],
        },
        {
            "username": "demo_auditor",
            "password": "SharedDemo#123",
            "groups": ["ecube-auditors"],
        },
    ]
    assert provider.group_updates == [
        {
            "username": "demo_admin",
            "groups": ["ecube-admins"],
            "skip": True,
        }
    ]


def test_seed_demo_environment_creates_missing_demo_users_with_shared_password_over_account_password(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    provider = _FakeOsUserProvider()
    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
                        {
                            "username": "demo_manager",
                            "label": "Manager demo",
                            "description": "Synthetic workflow review",
                            "roles": ["manager"],
                            "password": "legacy-password",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="FreshShared#123",
        actor="demo-seed-test",
    )

    assert provider.created == [
        {
            "username": "demo_manager",
            "password": "FreshShared#123",
            "groups": ["ecube-managers"],
        }
    ]


def test_seed_demo_environment_ignores_usb_mount_and_job_seed_metadata(db, tmp_path, monkeypatch):
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
                "usb_seed": {"enabled": True, "drives": [{"port_system_path": "1-1", "project_id": 1}]},
                "mount_seed": {"enabled": True, "mounts": [{"type": "NFS", "remote_path": "192.168.1.10:/exports/demo-case-001", "project_id": 1}]},
                "job_seed": {"jobs": [{"project_id": 1, "evidence_number": "EVID-JOB-001", "source_path": "/incoming"}]},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [],
        raising=False,
    )

    original_metadata_text = (demo_root / "demo-metadata.json").read_text(encoding="utf-8")
    provider = _FakeOsUserProvider()

    result = seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    metadata = json.loads((demo_root / "demo-metadata.json").read_text(encoding="utf-8"))
    seeded_jobs = db.query(ExportJob).all()

    assert metadata["usb_seed"]["enabled"] is True
    assert metadata["mount_seed"]["enabled"] is True
    assert metadata["job_seed"]["jobs"][0]["evidence_number"] == "EVID-JOB-001"
    assert (demo_root / "demo-metadata.json").read_text(encoding="utf-8") == original_metadata_text
    assert result.jobs_seeded == 0
    assert seeded_jobs == []
    assert provider.created == [
        {
            "username": "demo_processor",
            "password": "SharedDemo#123",
            "groups": ["ecube-processors"],
        }
    ]


def test_seed_demo_environment_uses_only_metadata_accounts(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "settings_default",
                "label": "Settings default",
                "description": "Should not be seeded when metadata exists.",
                "roles": ["admin"],
            }
        ],
        raising=False,
    )

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
                        {
                            "username": "metadata_manager",
                            "label": "Metadata manager",
                            "description": "Should be the only seeded demo user.",
                            "roles": ["manager"],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    provider = _FakeOsUserProvider()
    seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    assert provider.created == [
        {
            "username": "metadata_manager",
            "password": "SharedDemo#123",
            "groups": ["ecube-managers"],
        }
    ]
    assert UserRoleRepository(db).get_roles("metadata_manager") == ["manager"]
    assert UserRoleRepository(db).get_roles("settings_default") == []


def test_seed_runtime_demo_environment_ignores_audit_write_failures(db, caplog):
    from app.services.demo_seed_service import seed_runtime_demo_environment

    caplog.set_level(logging.INFO, logger="app.services.demo_seed_service")

    with patch("app.config.Settings.get_demo_accounts", return_value=[]), patch(
        "app.config.Settings.get_demo_shared_password",
        return_value="SharedDemo#123",
    ), patch(
        "app.services.demo_seed_service.AuditRepository.add",
        side_effect=RuntimeError("audit unavailable"),
    ):
        result = seed_runtime_demo_environment(db, provider=None, actor="demo-seed-test")

    assert result.users_seeded == 0
    assert result.roles_seeded == 4
    assert result.jobs_seeded == 0
    assert "Demo seed audit write failed" in caplog.text


def test_seed_demo_environment_does_not_fallback_to_default_accounts_when_metadata_has_no_accounts(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import seed_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "settings_default",
                "label": "Settings default",
                "description": "Should not be seeded when metadata exists.",
                "roles": ["admin"],
            }
        ],
        raising=False,
    )

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "login_message": "Demo mode",
                }
            }
        ),
        encoding="utf-8",
    )

    provider = _FakeOsUserProvider()
    result = seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    assert result.users_seeded == 0
    assert result.roles_seeded == 0
    assert provider.created == []
    assert UserRoleRepository(db).get_roles("settings_default") == []


def test_reset_demo_environment_removes_seeded_state(db, tmp_path, monkeypatch):
    from app.services.demo_seed_service import DEMO_SEED_MARKER, reset_demo_environment, seed_demo_environment

    provider = _FakeOsUserProvider()
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
            }
        ),
        encoding="utf-8",
    )
    seed_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        provider=provider,
        shared_password="SharedDemo#123",
        actor="demo-seed-test",
    )

    result = reset_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        actor="demo-seed-test",
    )

    assert result.jobs_removed == 0
    assert result.roles_removed >= 1
    assert demo_root.exists()
    assert {path.name for path in demo_root.iterdir()} == {"demo-metadata.json"}
    assert db.query(ExportJob).filter(ExportJob.created_by == DEMO_SEED_MARKER).count() == 0
    assert UserRoleRepository(db).get_roles("demo_processor") == []

    logs = AuditRepository(db).query(action="DEMO_BOOTSTRAP_RESET", limit=10)
    assert len(logs) >= 1
    assert logs[0].details["usernames"] == ["demo_processor"]


def test_reset_demo_environment_uses_metadata_accounts_for_role_cleanup(db, tmp_path, monkeypatch):
    from app.models.users import UserRole
    from app.services.demo_seed_service import reset_demo_environment

    monkeypatch.setattr(
        "app.services.demo_seed_service.settings.demo_accounts",
        [
            {
                "username": "settings_default",
                "label": "Settings default",
                "description": "Should not control reset cleanup.",
                "roles": ["admin"],
            }
        ],
        raising=False,
    )

    demo_root = tmp_path / "demo-share"
    demo_root.mkdir()
    (demo_root / "demo-metadata.json").write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
                        {
                            "username": "metadata_manager",
                            "label": "Metadata manager",
                            "description": "Should control reset cleanup.",
                            "roles": ["manager"],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    db.add(UserRole(username="metadata_manager", role="manager"))
    db.add(UserRole(username="settings_default", role="admin"))
    db.commit()

    result = reset_demo_environment(
        db,
        metadata_path=demo_root / "demo-metadata.json",
        actor="demo-seed-test",
    )

    assert result.roles_removed == 1
    assert UserRoleRepository(db).get_roles("metadata_manager") == []
    assert UserRoleRepository(db).get_roles("settings_default") == ["admin"]
