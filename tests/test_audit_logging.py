"""Tests verifying that sensitive operations emit structured audit log entries.

Covers:
- Actor identity present in service-level audit events.
- Role denial (AUTHORIZATION_DENIED) logged with actor and context.
- Project isolation violations logged with actor.
- Drive init/eject audit events.
- Mount add/remove/validate audit events.
- Job create/start/verify/manifest audit events.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.models.audit import AuditLog
from app.models.hardware import DriveState, UsbDrive
from app.models.network import MountStatus, MountType, NetworkMount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _audit_entries(db):
    return db.query(AuditLog).order_by(AuditLog.id).all()


def _last_audit(db):
    return db.query(AuditLog).order_by(AuditLog.id.desc()).first()


def _audit_by_action(db, action):
    return (
        db.query(AuditLog)
        .filter(AuditLog.action == action)
        .order_by(AuditLog.id.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Drive operations
# ---------------------------------------------------------------------------


class TestDriveAuditLogging:
    def test_initialize_drive_logs_actor(self, manager_client, db):
        drive = UsbDrive(device_identifier="AUDIT-INIT", current_state=DriveState.AVAILABLE)
        db.add(drive)
        db.commit()

        response = manager_client.post(
            f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-AUDIT"}
        )
        assert response.status_code == 200

        entry = _audit_by_action(db, "DRIVE_INITIALIZED")
        assert entry is not None
        assert entry.user == "manager-user"
        assert entry.details["drive_id"] == drive.id
        assert entry.details["project_id"] == "PROJ-AUDIT"

    def test_project_isolation_violation_logs_actor(self, manager_client, db):
        drive = UsbDrive(
            device_identifier="AUDIT-ISO",
            current_state=DriveState.IN_USE,
            current_project_id="PROJ-A",
        )
        db.add(drive)
        db.commit()

        response = manager_client.post(
            f"/drives/{drive.id}/initialize", json={"project_id": "PROJ-B"}
        )
        assert response.status_code == 409

        entry = _audit_by_action(db, "PROJECT_ISOLATION_VIOLATION")
        assert entry is not None
        assert entry.user == "manager-user"
        assert entry.details["drive_id"] == drive.id
        assert entry.details["existing_project_id"] == "PROJ-A"
        assert entry.details["requested_project_id"] == "PROJ-B"

    def test_prepare_eject_logs_actor(self, manager_client, db):
        drive = UsbDrive(
            device_identifier="AUDIT-EJECT",
            current_state=DriveState.IN_USE,
            current_project_id="PROJ-AUDIT",
        )
        db.add(drive)
        db.commit()

        response = manager_client.post(f"/drives/{drive.id}/prepare-eject")
        assert response.status_code == 200

        entry = _audit_by_action(db, "DRIVE_EJECT_PREPARED")
        assert entry is not None
        assert entry.user == "manager-user"
        assert entry.details["drive_id"] == drive.id


# ---------------------------------------------------------------------------
# Mount operations
# ---------------------------------------------------------------------------


class TestMountAuditLogging:
    def test_add_mount_logs_actor(self, manager_client, db):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "1.2.3.4:/audit-data",
                    "local_mount_point": "/mnt/audit",
                },
            )
        assert response.status_code == 200

        entry = _audit_by_action(db, "MOUNT_ADDED")
        assert entry is not None
        assert entry.user == "manager-user"
        assert entry.details["remote_path"] == "1.2.3.4:/audit-data"
        assert entry.details["status"] == "MOUNTED"

    def test_remove_mount_logs_actor(self, manager_client, db):
        mount = NetworkMount(
            type=MountType.NFS,
            remote_path="1.2.3.4:/remove-data",
            local_mount_point="/mnt/remove",
            status=MountStatus.MOUNTED,
        )
        db.add(mount)
        db.commit()
        mount_id = mount.id

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = manager_client.delete(f"/mounts/{mount_id}")
        assert response.status_code == 204

        entry = _audit_by_action(db, "MOUNT_REMOVED")
        assert entry is not None
        assert entry.user == "manager-user"
        assert entry.details["mount_id"] == mount_id

    def test_validate_mount_logs_actor(self, manager_client, db):
        mount = NetworkMount(
            type=MountType.NFS,
            remote_path="1.2.3.4:/validate-data",
            local_mount_point="/mnt/validate",
            status=MountStatus.MOUNTED,
        )
        db.add(mount)
        db.commit()
        mount_id = mount.id

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = manager_client.post(f"/mounts/{mount_id}/validate")
        assert response.status_code == 200

        entry = _audit_by_action(db, "MOUNT_VALIDATED")
        assert entry is not None
        assert entry.user == "manager-user"
        assert entry.details["mount_id"] == mount_id
        assert entry.details["status"] == "MOUNTED"

    def test_validate_mount_not_found(self, manager_client, db):
        response = manager_client.post("/mounts/9999/validate")
        assert response.status_code == 404

    def test_validate_mount_logs_unmounted_status(self, manager_client, db):
        mount = NetworkMount(
            type=MountType.NFS,
            remote_path="1.2.3.4:/unmounted",
            local_mount_point="/mnt/unmounted",
            status=MountStatus.MOUNTED,
        )
        db.add(mount)
        db.commit()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            response = manager_client.post(f"/mounts/{mount.id}/validate")
        assert response.status_code == 200
        assert response.json()["status"] == "UNMOUNTED"

        entry = _audit_by_action(db, "MOUNT_VALIDATED")
        assert entry is not None
        assert entry.details["status"] == "UNMOUNTED"


# ---------------------------------------------------------------------------
# Job operations
# ---------------------------------------------------------------------------


class TestJobAuditLogging:
    def test_create_job_logs_actor(self, client, db):
        response = client.post(
            "/jobs",
            json={
                "project_id": "PROJ-AUDIT",
                "evidence_number": "EV-AUDIT",
                "source_path": "/data/evidence",
            },
        )
        assert response.status_code == 200
        job_id = response.json()["id"]

        entry = _audit_by_action(db, "JOB_CREATED")
        assert entry is not None
        assert entry.user == "test-user"
        assert entry.job_id == job_id
        assert entry.details["project_id"] == "PROJ-AUDIT"

    def test_job_create_project_isolation_violation_logs_actor(self, client, db):
        drive = UsbDrive(
            device_identifier="AUDIT-JOB-ISO",
            current_state=DriveState.AVAILABLE,
            current_project_id="PROJ-OTHER",
        )
        db.add(drive)
        db.commit()

        response = client.post(
            "/jobs",
            json={
                "project_id": "PROJ-DIFFERENT",
                "evidence_number": "EV-ISO",
                "source_path": "/data",
                "drive_id": drive.id,
            },
        )
        assert response.status_code == 409

        entry = _audit_by_action(db, "PROJECT_ISOLATION_VIOLATION")
        assert entry is not None
        assert entry.user == "test-user"
        assert entry.details["existing_project_id"] == "PROJ-OTHER"
        assert entry.details["requested_project_id"] == "PROJ-DIFFERENT"

    def test_start_job_logs_actor(self, client, db):
        create_resp = client.post(
            "/jobs",
            json={
                "project_id": "PROJ-AUDIT",
                "evidence_number": "EV-START",
                "source_path": "/tmp",
            },
        )
        job_id = create_resp.json()["id"]

        with patch("app.services.copy_engine.run_copy_job"):
            response = client.post(f"/jobs/{job_id}/start", json={})
        assert response.status_code == 200

        entry = _audit_by_action(db, "JOB_STARTED")
        assert entry is not None
        assert entry.user == "test-user"
        assert entry.job_id == job_id

    def test_verify_job_logs_actor(self, client, db):
        create_resp = client.post(
            "/jobs",
            json={
                "project_id": "PROJ-AUDIT",
                "evidence_number": "EV-VERIFY",
                "source_path": "/tmp",
            },
        )
        job_id = create_resp.json()["id"]

        with patch("app.services.copy_engine.run_verify_job"):
            response = client.post(f"/jobs/{job_id}/verify")
        assert response.status_code == 200

        entry = _audit_by_action(db, "JOB_VERIFY_STARTED")
        assert entry is not None
        assert entry.user == "test-user"
        assert entry.job_id == job_id

    def test_create_manifest_logs_actor(self, client, db):
        create_resp = client.post(
            "/jobs",
            json={
                "project_id": "PROJ-AUDIT",
                "evidence_number": "EV-MANIFEST",
                "source_path": "/tmp",
            },
        )
        job_id = create_resp.json()["id"]

        response = client.post(f"/jobs/{job_id}/manifest")
        assert response.status_code == 200

        entry = _audit_by_action(db, "MANIFEST_CREATED")
        assert entry is not None
        assert entry.user == "test-user"
        assert entry.job_id == job_id


# ---------------------------------------------------------------------------
# Authorization denial audit logging
# ---------------------------------------------------------------------------


class TestAuthorizationDeniedAuditLogging:
    def test_role_denial_logs_authorization_denied(self, auditor_client, db):
        """auditor role cannot initialize a drive; denial must be logged."""
        response = auditor_client.post(
            "/drives/1/initialize", json={"project_id": "PROJ-DENY"}
        )
        assert response.status_code == 403

        entry = _audit_by_action(db, "AUTHORIZATION_DENIED")
        assert entry is not None
        assert entry.user == "auditor-user"
        assert set(entry.details["required_roles"]) & {"admin", "manager"}
        assert entry.details["path"] == "/drives/1/initialize"
        assert entry.details["method"] == "POST"
        assert "auditor" in entry.details["user_roles"]

    def test_role_denial_on_job_create_logs_authorization_denied(self, auditor_client, db):
        """auditor role cannot create a job; denial must be logged."""
        response = auditor_client.post(
            "/jobs",
            json={
                "project_id": "PROJ-DENY",
                "evidence_number": "EV-DENY",
                "source_path": "/tmp",
            },
        )
        assert response.status_code == 403

        entry = _audit_by_action(db, "AUTHORIZATION_DENIED")
        assert entry is not None
        assert entry.user == "auditor-user"

    def test_role_denial_on_add_mount_logs_authorization_denied(self, auditor_client, db):
        """auditor role cannot add a mount; denial must be logged."""
        response = auditor_client.post(
            "/mounts",
            json={
                "type": "NFS",
                "remote_path": "1.2.3.4:/data",
                "local_mount_point": "/mnt/a",
            },
        )
        assert response.status_code == 403

        entry = _audit_by_action(db, "AUTHORIZATION_DENIED")
        assert entry is not None
        assert entry.user == "auditor-user"
        assert entry.details["path"] == "/mounts"

    def test_authorization_denied_details_schema(self, auditor_client, db):
        """AUTHORIZATION_DENIED entries must include all required context fields."""
        auditor_client.post("/drives/1/prepare-eject")

        entry = _audit_by_action(db, "AUTHORIZATION_DENIED")
        assert entry is not None
        assert "path" in entry.details
        assert "method" in entry.details
        assert "required_roles" in entry.details
        assert "user_roles" in entry.details
        assert isinstance(entry.details["required_roles"], list)
        assert isinstance(entry.details["user_roles"], list)


# ---------------------------------------------------------------------------
# Authentication failure audit logging
# ---------------------------------------------------------------------------


class TestAuthenticationFailureAuditLogging:
    def test_missing_token_logs_auth_failure(self, unauthenticated_client, db):
        response = unauthenticated_client.get("/drives")
        assert response.status_code == 401

        entry = _audit_by_action(db, "AUTH_FAILURE")
        assert entry is not None
        assert entry.details["path"] == "/drives"
        assert entry.details["method"] == "GET"
        assert "missing" in entry.details["reason"].lower()
        assert entry.details["trace_id"]

    def test_invalid_token_logs_auth_failure(self, unauthenticated_client, db):
        response = unauthenticated_client.get(
            "/drives",
            headers={"Authorization": "Bearer not.a.valid.token"},
        )
        assert response.status_code == 401

        entry = _audit_by_action(db, "AUTH_FAILURE")
        assert entry is not None
        assert entry.details["path"] == "/drives"
        assert entry.details["method"] == "GET"
        assert "invalid" in entry.details["reason"].lower()
        assert entry.details["trace_id"]
