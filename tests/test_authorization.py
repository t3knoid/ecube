"""Tests for require_roles(*roles) route-level authorization.

Verifies that:
- Every endpoint allows exactly the roles specified in the design matrix.
- Authenticated users who lack the required role receive HTTP 403.
- The 403 response body uses the standard error envelope
  ({"code": "FORBIDDEN", "message": "...", "trace_id": "..."}).
- Unauthenticated requests still receive HTTP 401.
"""

import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_db
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(roles: list[str]) -> str:
    payload = {
        "sub": "authz-test-user",
        "username": "authz-tester",
        "roles": roles,
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _headers(roles: list[str]) -> dict:
    return {"Authorization": f"Bearer {_make_token(roles)}"}


class _RoleClient:
    """Stateless request helper that injects role-scoped auth and test DB per request."""

    def __init__(self, db_session, roles: list[str]) -> None:
        self._db_session = db_session
        self._headers = _headers(roles)

    def _request(self, method: str, path: str, **kwargs):
        def override_get_db():
            try:
                yield self._db_session
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.headers.update(self._headers)
                return getattr(client, method)(path, **kwargs)
        finally:
            app.dependency_overrides.clear()

    def get(self, path: str, **kwargs):
        return self._request("get", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._request("post", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self._request("delete", path, **kwargs)


def _client_for_role(db_session, roles: list[str]) -> _RoleClient:
    return _RoleClient(db_session, roles)


# ---------------------------------------------------------------------------
# 403 response shape helper
# ---------------------------------------------------------------------------


def _assert_forbidden(response) -> None:
    assert response.status_code == 403, response.json()
    body = response.json()
    assert body.get("code") == "FORBIDDEN"
    assert "message" in body
    assert "trace_id" in body


# ---------------------------------------------------------------------------
# Drive endpoints
# ---------------------------------------------------------------------------


class TestDriveAuthorization:
    """GET /drives  — all four roles allowed; others denied."""

    def test_list_drives_admin_allowed(self, db):
        c = _client_for_role(db, ["admin"])
        assert c.get("/drives").status_code == 200

    def test_list_drives_manager_allowed(self, db):
        c = _client_for_role(db, ["manager"])
        assert c.get("/drives").status_code == 200

    def test_list_drives_processor_allowed(self, db):
        c = _client_for_role(db, ["processor"])
        assert c.get("/drives").status_code == 200

    def test_list_drives_auditor_allowed(self, db):
        c = _client_for_role(db, ["auditor"])
        assert c.get("/drives").status_code == 200

    def test_list_drives_no_role_denied(self, db):
        c = _client_for_role(db, [])
        _assert_forbidden(c.get("/drives"))

    # POST /drives/{id}/initialize — admin, manager only
    def test_initialize_drive_admin_allowed(self, db):
        from app.models.hardware import DriveState, UsbDrive

        drive = UsbDrive(device_identifier="AUTHZ-INIT-ADMIN", current_state=DriveState.AVAILABLE, filesystem_type="ext4")
        db.add(drive)
        db.commit()
        c = _client_for_role(db, ["admin"])
        assert c.post(f"/drives/{drive.id}/initialize", json={"project_id": "P-1"}).status_code == 200

    def test_initialize_drive_manager_allowed(self, db):
        from app.models.hardware import DriveState, UsbDrive

        drive = UsbDrive(device_identifier="AUTHZ-INIT-MGR", current_state=DriveState.AVAILABLE, filesystem_type="ext4")
        db.add(drive)
        db.commit()
        c = _client_for_role(db, ["manager"])
        assert c.post(f"/drives/{drive.id}/initialize", json={"project_id": "P-1"}).status_code == 200

    def test_initialize_drive_processor_denied(self, db):
        c = _client_for_role(db, ["processor"])
        _assert_forbidden(c.post("/drives/1/initialize", json={"project_id": "P-1"}))

    def test_initialize_drive_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.post("/drives/1/initialize", json={"project_id": "P-1"}))

    # POST /drives/{id}/prepare-eject — admin, manager only
    def test_prepare_eject_admin_allowed(self, db):
        from app.models.hardware import DriveState, UsbDrive
        from unittest.mock import patch

        drive = UsbDrive(
            device_identifier="AUTHZ-EJECT-ADMIN",
            current_state=DriveState.IN_USE,
            current_project_id="P-1",
        )
        db.add(drive)
        db.commit()
        c = _client_for_role(db, ["admin"])
        with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)):
            assert c.post(f"/drives/{drive.id}/prepare-eject").status_code == 200

    def test_prepare_eject_manager_allowed(self, db):
        from app.models.hardware import DriveState, UsbDrive
        from unittest.mock import patch

        drive = UsbDrive(
            device_identifier="AUTHZ-EJECT-MGR",
            current_state=DriveState.IN_USE,
            current_project_id="P-1",
        )
        db.add(drive)
        db.commit()
        c = _client_for_role(db, ["manager"])
        with patch("app.services.drive_service.sync_filesystem", return_value=(True, None)):
            assert c.post(f"/drives/{drive.id}/prepare-eject").status_code == 200

    def test_prepare_eject_processor_denied(self, db):
        c = _client_for_role(db, ["processor"])
        _assert_forbidden(c.post("/drives/1/prepare-eject"))

    def test_prepare_eject_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.post("/drives/1/prepare-eject"))


# ---------------------------------------------------------------------------
# Mount endpoints
# ---------------------------------------------------------------------------


class TestMountAuthorization:
    """POST /mounts and DELETE /mounts/{id} — admin, manager only.
       GET  /mounts — all four roles."""

    def test_add_mount_admin_allowed(self, db):
        from unittest.mock import MagicMock, patch

        c = _client_for_role(db, ["admin"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            r = c.post(
                "/mounts",
                json={"type": "NFS", "remote_path": "1.2.3.4:/data", "local_mount_point": "/mnt/a"},
            )
        assert r.status_code == 200

    def test_add_mount_manager_allowed(self, db):
        from unittest.mock import MagicMock, patch

        c = _client_for_role(db, ["manager"])
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            r = c.post(
                "/mounts",
                json={"type": "NFS", "remote_path": "1.2.3.4:/data2", "local_mount_point": "/mnt/b"},
            )
        assert r.status_code == 200

    def test_add_mount_processor_denied(self, db):
        c = _client_for_role(db, ["processor"])
        _assert_forbidden(
            c.post(
                "/mounts",
                json={"type": "NFS", "remote_path": "1.2.3.4:/data3", "local_mount_point": "/mnt/c"},
            )
        )

    def test_add_mount_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(
            c.post(
                "/mounts",
                json={"type": "NFS", "remote_path": "1.2.3.4:/data4", "local_mount_point": "/mnt/d"},
            )
        )

    def test_delete_mount_processor_denied(self, db):
        c = _client_for_role(db, ["processor"])
        _assert_forbidden(c.delete("/mounts/1"))

    def test_delete_mount_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.delete("/mounts/1"))

    def test_list_mounts_all_roles_allowed(self, db):
        for role in ["admin", "manager", "processor", "auditor"]:
            c = _client_for_role(db, [role])
            assert c.get("/mounts").status_code == 200, f"role={role} should be allowed"

    def test_list_mounts_no_role_denied(self, db):
        c = _client_for_role(db, [])
        _assert_forbidden(c.get("/mounts"))


# ---------------------------------------------------------------------------
# Job endpoints
# ---------------------------------------------------------------------------


class TestJobAuthorization:
    """POST /jobs, POST /jobs/{id}/start, /verify, /manifest — admin, manager, processor.
       GET  /jobs/{id} — all four roles."""

    def _create_job_payload(self):
        return {
            "project_id": "PROJ-AUTHZ",
            "evidence_number": "EV-AUTHZ",
            "source_path": "/tmp",
        }

    def test_create_job_admin_allowed(self, db):
        c = _client_for_role(db, ["admin"])
        assert c.post("/jobs", json=self._create_job_payload()).status_code == 200

    def test_create_job_manager_allowed(self, db):
        c = _client_for_role(db, ["manager"])
        assert c.post("/jobs", json=self._create_job_payload()).status_code == 200

    def test_create_job_processor_allowed(self, db):
        c = _client_for_role(db, ["processor"])
        assert c.post("/jobs", json=self._create_job_payload()).status_code == 200

    def test_create_job_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.post("/jobs", json=self._create_job_payload()))

    def test_get_job_all_roles_allowed(self, db):
        # Create a job first via admin
        admin_c = _client_for_role(db, ["admin"])
        job_id = admin_c.post("/jobs", json=self._create_job_payload()).json()["id"]

        for role in ["admin", "manager", "processor", "auditor"]:
            c = _client_for_role(db, [role])
            assert c.get(f"/jobs/{job_id}").status_code == 200, f"role={role} should be allowed"

    def test_get_job_no_role_denied(self, db):
        c = _client_for_role(db, [])
        _assert_forbidden(c.get("/jobs/1"))

    def test_start_job_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.post("/jobs/1/start", json={}))

    def test_verify_job_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.post("/jobs/1/verify"))

    def test_manifest_auditor_denied(self, db):
        c = _client_for_role(db, ["auditor"])
        _assert_forbidden(c.post("/jobs/1/manifest"))


# ---------------------------------------------------------------------------
# Introspection endpoints
# ---------------------------------------------------------------------------


class TestIntrospectionAuthorization:
    """All introspection endpoints allow all four roles; no-role is denied."""

    @pytest.mark.parametrize(
        "path",
        [
            "/introspection/usb/topology",
            "/introspection/block-devices",
            "/introspection/mounts",
            "/introspection/system-health",
        ],
    )
    def test_all_roles_allowed(self, db, path):
        for role in ["admin", "manager", "processor", "auditor"]:
            c = _client_for_role(db, [role])
            assert c.get(path).status_code == 200, f"role={role} path={path}"

    @pytest.mark.parametrize(
        "path",
        [
            "/introspection/usb/topology",
            "/introspection/block-devices",
            "/introspection/mounts",
            "/introspection/system-health",
        ],
    )
    def test_no_role_denied(self, db, path):
        c = _client_for_role(db, [])
        _assert_forbidden(c.get(path))

    def test_job_debug_auditor_allowed(self, db):
        from app.models.jobs import ExportJob

        job = ExportJob(project_id="P", evidence_number="E", source_path="/tmp")
        db.add(job)
        db.commit()
        c = _client_for_role(db, ["auditor"])
        assert c.get(f"/introspection/jobs/{job.id}/debug").status_code == 200

    def test_job_debug_no_role_denied(self, db):
        c = _client_for_role(db, [])
        _assert_forbidden(c.get("/introspection/jobs/1/debug"))


# ---------------------------------------------------------------------------
# Unauthenticated access still returns 401
# ---------------------------------------------------------------------------


class TestUnauthenticatedAccess:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/drives"),
            ("POST", "/drives/1/initialize"),
            ("POST", "/drives/1/prepare-eject"),
            ("GET", "/mounts"),
            ("POST", "/mounts"),
            ("DELETE", "/mounts/1"),
            ("POST", "/jobs"),
            ("GET", "/jobs/1"),
            ("POST", "/jobs/1/start"),
            ("POST", "/jobs/1/verify"),
            ("POST", "/jobs/1/manifest"),
            ("GET", "/introspection/system-health"),
        ],
    )
    def test_no_token_returns_401(self, unauthenticated_client, method, path):
        response = getattr(unauthenticated_client, method.lower())(path)
        assert response.status_code == 401, f"{method} {path} should require auth"
