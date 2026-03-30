"""Tests for user-role management (issue #70).

Covers:
- UserRole ORM model and repository
- /users role management API endpoints (admin-only)
- DB-first role resolution in POST /auth/token
- Audit logging for role changes
- Setup script helpers (non-root checks)
"""

import sys

import jwt
import pytest
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.main import app as fastapi_app
from app.models.users import UserRole
from app.repositories.user_role_repository import UserRoleRepository
from app.routers.auth import _get_pam


# ───────────────────────────────────────────────────────────────────────
# Repository tests
# ───────────────────────────────────────────────────────────────────────

class TestUserRoleRepository:
    def test_get_roles_empty(self, db):
        repo = UserRoleRepository(db)
        assert repo.get_roles("nobody") == []

    def test_set_and_get_roles(self, db):
        repo = UserRoleRepository(db)
        repo.set_roles("griffin", ["admin", "manager"])
        assert sorted(repo.get_roles("griffin")) == ["admin", "manager"]

    def test_set_roles_replaces_existing(self, db):
        repo = UserRoleRepository(db)
        repo.set_roles("alba", ["admin", "processor"])
        repo.set_roles("alba", ["auditor"])
        assert repo.get_roles("alba") == ["auditor"]

    def test_delete_roles(self, db):
        repo = UserRoleRepository(db)
        repo.set_roles("charlie", ["admin"])
        count = repo.delete_roles("charlie")
        assert count == 1
        assert repo.get_roles("charlie") == []

    def test_delete_roles_nonexistent_user(self, db):
        repo = UserRoleRepository(db)
        assert repo.delete_roles("ghost") == 0

    def test_list_users(self, db):
        repo = UserRoleRepository(db)
        repo.set_roles("griffin", ["admin"])
        repo.set_roles("alba", ["processor", "auditor"])
        users = repo.list_users()
        assert len(users) == 2
        griffin = next(u for u in users if u["username"] == "griffin")
        alba = next(u for u in users if u["username"] == "alba")
        assert griffin["roles"] == ["admin"]
        assert sorted(alba["roles"]) == ["auditor", "processor"]

    def test_has_any_admin(self, db):
        repo = UserRoleRepository(db)
        assert repo.has_any_admin() is False
        repo.set_roles("admin-user", ["admin"])
        assert repo.has_any_admin() is True

    def test_unique_constraint(self, db):
        db.add(UserRole(username="dup", role="admin"))
        db.commit()
        db.add(UserRole(username="dup", role="admin"))
        with pytest.raises(IntegrityError):
            db.commit()


# ───────────────────────────────────────────────────────────────────────
# API endpoint tests
# ───────────────────────────────────────────────────────────────────────

class TestUserRoleEndpoints:
    def test_list_users_empty(self, admin_client):
        resp = admin_client.get("/users")
        assert resp.status_code == 200
        assert resp.json()["users"] == []

    def test_set_and_get_roles(self, admin_client):
        resp = admin_client.put(
            "/users/testuser/roles",
            json={"roles": ["processor", "auditor"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert sorted(data["roles"]) == ["auditor", "processor"]

        resp = admin_client.get("/users/testuser/roles")
        assert resp.status_code == 200
        assert sorted(resp.json()["roles"]) == ["auditor", "processor"]

    def test_set_roles_replaces(self, admin_client):
        admin_client.put("/users/u1/roles", json={"roles": ["admin"]})
        admin_client.put("/users/u1/roles", json={"roles": ["processor"]})
        resp = admin_client.get("/users/u1/roles")
        assert resp.json()["roles"] == ["processor"]

    def test_set_roles_deduplicates(self, admin_client):
        resp = admin_client.put(
            "/users/u2/roles",
            json={"roles": ["admin", "admin", "processor"]},
        )
        assert resp.status_code == 200
        assert sorted(resp.json()["roles"]) == ["admin", "processor"]

    def test_set_roles_invalid_role(self, admin_client):
        resp = admin_client.put(
            "/users/u3/roles",
            json={"roles": ["admin", "superuser"]},
        )
        assert resp.status_code == 422
        body = resp.json()
        # Uniform error format from RequestValidationError handler
        assert "VALIDATION_ERROR" == body["code"]
        assert "admin" in body["message"] or "processor" in body["message"]

    def test_set_roles_empty_list(self, admin_client):
        resp = admin_client.put(
            "/users/u4/roles",
            json={"roles": []},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body

    def test_delete_roles(self, admin_client):
        admin_client.put("/users/delme/roles", json={"roles": ["admin"]})
        resp = admin_client.delete("/users/delme/roles")
        assert resp.status_code == 200
        assert resp.json()["roles"] == []

        resp = admin_client.get("/users/delme/roles")
        assert resp.json()["roles"] == []

    def test_list_users_after_assignments(self, admin_client):
        admin_client.put("/users/a/roles", json={"roles": ["admin"]})
        admin_client.put("/users/b/roles", json={"roles": ["processor"]})
        resp = admin_client.get("/users")
        assert resp.status_code == 200
        usernames = [u["username"] for u in resp.json()["users"]]
        assert "a" in usernames
        assert "b" in usernames

    def test_get_roles_nonexistent_user(self, admin_client):
        resp = admin_client.get("/users/nobody/roles")
        assert resp.status_code == 200
        assert resp.json() == {"username": "nobody", "roles": []}

    # --- Authorization ---

    def test_processor_cannot_list_users(self, client):
        """client fixture has processor role."""
        resp = client.get("/users")
        assert resp.status_code == 403

    def test_processor_cannot_set_roles(self, client):
        resp = client.put("/users/x/roles", json={"roles": ["admin"]})
        assert resp.status_code == 403

    def test_processor_cannot_delete_roles(self, client):
        resp = client.delete("/users/x/roles")
        assert resp.status_code == 403

    def test_unauthenticated_cannot_access(self, unauthenticated_client):
        resp = unauthenticated_client.get("/users")
        assert resp.status_code == 401


# ───────────────────────────────────────────────────────────────────────
# Audit logging tests
# ───────────────────────────────────────────────────────────────────────

class TestUserRoleAuditLogging:
    def test_role_assigned_audit(self, admin_client, db):
        admin_client.put("/users/auditee/roles", json={"roles": ["processor"]})
        from app.models.audit import AuditLog
        logs = db.query(AuditLog).filter(AuditLog.action == "ROLE_ASSIGNED").all()
        assert len(logs) >= 1
        log = logs[-1]
        assert log.details["target_user"] == "auditee"
        assert log.details["roles"] == ["processor"]

    def test_role_removed_audit(self, admin_client, db):
        admin_client.put("/users/auditee2/roles", json={"roles": ["admin"]})
        admin_client.delete("/users/auditee2/roles")
        from app.models.audit import AuditLog
        logs = db.query(AuditLog).filter(AuditLog.action == "ROLE_REMOVED").all()
        assert len(logs) >= 1
        log = logs[-1]
        assert log.details["target_user"] == "auditee2"


# ───────────────────────────────────────────────────────────────────────
# DB-first role resolution in login
# ───────────────────────────────────────────────────────────────────────

class TestDbRoleResolution:
    def test_db_roles_override_group_roles(self, db, unauthenticated_client, monkeypatch):
        """When user_roles has entries, those are used instead of OS group mapping."""
        # Seed DB role
        repo = UserRoleRepository(db)
        repo.set_roles("testpam", ["manager"])

        # Mock PAM authenticator via the _get_pam dependency
        fake_pam = type("FakePam", (), {
            "authenticate": lambda self, u, p: True,
            "get_user_groups": lambda self, u: ["some-group"],
        })()
        fastapi_app.dependency_overrides[_get_pam] = lambda: fake_pam

        resp = unauthenticated_client.post(
            "/auth/token",
            json={"username": "testpam", "password": "pass"},
        )
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert payload["roles"] == ["manager"]

    def test_fallback_to_group_resolver_when_no_db_roles(self, db, unauthenticated_client, monkeypatch):
        """When user_roles is empty for this user, fall back to group resolver."""
        from app.auth_providers import get_role_resolver

        fake_pam = type("FakePam", (), {
            "authenticate": lambda self, u, p: True,
            "get_user_groups": lambda self, u: ["test-admins"],
        })()
        fastapi_app.dependency_overrides[_get_pam] = lambda: fake_pam

        # Temporarily set a group map that maps test-admins → admin
        original_map = settings.local_group_role_map
        settings.local_group_role_map = {"test-admins": ["admin"]}
        # Clear the cached resolver so it picks up the new map
        get_role_resolver.cache_clear()
        try:
            resp = unauthenticated_client.post(
                "/auth/token",
                json={"username": "fallbackuser", "password": "pass"},
            )
            assert resp.status_code == 200
            token = resp.json()["access_token"]
            payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
            assert payload["roles"] == ["admin"]
        finally:
            settings.local_group_role_map = original_map
            get_role_resolver.cache_clear()


# ───────────────────────────────────────────────────────────────────────
# Model tests
# ───────────────────────────────────────────────────────────────────────

class TestUserRoleModel:
    def test_create_user_role(self, db):
        role = UserRole(username="modeltest", role="admin")
        db.add(role)
        db.commit()
        db.refresh(role)
        assert role.id is not None
        assert role.username == "modeltest"
        assert role.role == "admin"

    def test_repr(self, db):
        """Model instances are created correctly."""
        role = UserRole(username="repr_test", role="processor")
        db.add(role)
        db.commit()
        db.refresh(role)
        assert role.username == "repr_test"
        assert role.role == "processor"


# ───────────────────────────────────────────────────────────────────────
# Username validation tests
# ───────────────────────────────────────────────────────────────────────

class TestUsernameValidation:
    """Ensure _validate_username rejects shell metacharacters and invalid formats."""

    @pytest.mark.parametrize("bad_name", [
        "Admin",          # uppercase
        "root;rm",        # shell metacharacter
        # "../etc" omitted — Starlette normalises the path before routing,
        # so the request never reaches _validate_username (returns 404).
        "a" * 33,         # too long (max 32)
        "1user",          # starts with digit
        "user name",      # space
        "user$var",       # dollar sign
    ])
    def test_invalid_usernames_rejected(self, admin_client, bad_name):
        resp = admin_client.get(f"/users/{bad_name}/roles")
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "username" in body["message"].lower()

    @pytest.mark.parametrize("good_name", [
        "griffin",
        "_svc-account",
        "user-01",
        "a",
    ])
    def test_valid_usernames_accepted(self, admin_client, good_name):
        resp = admin_client.get(f"/users/{good_name}/roles")
        assert resp.status_code == 200


# ───────────────────────────────────────────────────────────────────────
# Setup script tests (non-root parts only)
# ───────────────────────────────────────────────────────────────────────

class TestSetupScript:
    @pytest.mark.skipif(sys.platform == "win32", reason="os.geteuid is POSIX-only")
    def test_refuses_to_run_as_non_root(self, monkeypatch):
        """Setup script should exit if not root."""
        monkeypatch.setattr("os.geteuid", lambda: 1000)
        from app.setup import main
        with pytest.raises(SystemExit):
            main()

    def test_group_exists_helper(self, monkeypatch):
        from app.setup import _group_exists
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: type("R", (), {"returncode": 0})(),
        )
        assert _group_exists("existing-group") is True

    def test_user_exists_helper(self, monkeypatch):
        from app.setup import _user_exists
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: type("R", (), {"returncode": 2})(),
        )
        assert _user_exists("nobody-here") is False
