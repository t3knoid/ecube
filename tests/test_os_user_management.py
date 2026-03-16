"""Tests for OS user/group management and first-run setup wizard.

All subprocess calls (sudo useradd, groupadd, etc.) and OS database lookups
(pwd, grp) are mocked — no real OS changes occur.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from app.models.users import UserRole
from app.repositories.user_role_repository import UserRoleRepository
from app.services import os_user_service
from app.services.os_user_service import (
    OSUser,
    OSUserError,
    create_group,
    create_user,
    delete_group,
    delete_user,
    ensure_ecube_groups,
    list_groups,
    list_users,
    reset_password,
    set_user_groups,
    validate_group_name,
    validate_username,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pw(name="testuser", uid=1000, gid=1000, home="/home/testuser", shell="/bin/bash"):
    """Create a mock pwd.struct_passwd tuple."""
    pw = MagicMock()
    pw.pw_name = name
    pw.pw_uid = uid
    pw.pw_gid = gid
    pw.pw_dir = home
    pw.pw_shell = shell
    return pw


def _make_grp(name="testgroup", gid=2000, members=None):
    """Create a mock grp.struct_group tuple."""
    g = MagicMock()
    g.gr_name = name
    g.gr_gid = gid
    g.gr_mem = members or []
    return g


def _ok_result(stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail_result(stderr="error", returncode=1):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


# ===========================================================================
# Service-layer tests (os_user_service)
# ===========================================================================


class TestValidation:
    """Username and group name validation."""

    def test_valid_usernames(self):
        for name in ["alice", "bob", "user_1", "_test", "a-b-c"]:
            validate_username(name)  # should not raise

    def test_invalid_usernames(self):
        for name in ["Alice", "1user", "a" * 33, "bob;rm", "root/../etc", ""]:
            with pytest.raises(ValueError):
                validate_username(name)

    def test_valid_group_names(self):
        for name in ["ecube-admins", "testgroup", "group_1"]:
            validate_group_name(name)

    def test_invalid_group_names(self):
        for name in ["Group", "1group", "a" * 33, "grp;cmd", ""]:
            with pytest.raises(ValueError):
                validate_group_name(name)


class TestCreateUser:
    """os_user_service.create_user()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_basic_user(self, mock_pwd, mock_grp, mock_subprocess):
        pw = _make_pw()
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),   # user_exists check
            pw,                         # final lookup after creation
            pw,                         # _get_user_groups lookup
        ]
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        user = create_user("testuser", "s3cret")

        assert user.username == "testuser"
        assert user.uid == 1000
        # Should have called sudo useradd and sudo chpasswd.
        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/useradd", "-m", "testuser"] in calls
        assert ["sudo", "/usr/sbin/chpasswd"] in calls

    @patch("app.services.os_user_service.pwd")
    def test_create_user_already_exists(self, mock_pwd):
        mock_pwd.getpwnam.return_value = _make_pw()
        with pytest.raises(OSUserError, match="already exists"):
            create_user("testuser", "password")

    def test_create_reserved_username(self):
        with pytest.raises(ValueError, match="reserved"):
            create_user("root", "password")

    def test_create_empty_password(self):
        with pytest.raises(ValueError, match="empty"):
            create_user("testuser", "")

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_with_groups(self, mock_pwd, mock_grp, mock_subprocess):
        pw = _make_pw()
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),   # user_exists
            pw,                         # final lookup
            pw,                         # _get_user_groups
        ]
        # group_exists checks
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        user = create_user("testuser", "s3cret", groups=["ecube-admins"])

        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/usermod", "-aG", "ecube-admins", "testuser"] in calls


class TestDeleteUser:
    """os_user_service.delete_user()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.pwd")
    def test_delete_user(self, mock_pwd, mock_subprocess):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_subprocess.return_value = _ok_result()

        delete_user("testuser")

        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/userdel", "-r", "testuser"] in calls

    @patch("app.services.os_user_service.pwd")
    def test_delete_nonexistent_user(self, mock_pwd):
        mock_pwd.getpwnam.side_effect = KeyError("no such user")
        with pytest.raises(OSUserError, match="does not exist"):
            delete_user("nobody_here")

    def test_delete_reserved_user(self):
        with pytest.raises(ValueError, match="reserved"):
            delete_user("ecube")


class TestResetPassword:
    """os_user_service.reset_password()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.pwd")
    def test_reset_password(self, mock_pwd, mock_subprocess):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_subprocess.return_value = _ok_result()

        reset_password("testuser", "newpass")

        call = mock_subprocess.call_args_list[-1]
        assert call.args[0] == ["sudo", "/usr/sbin/chpasswd"]
        assert call.kwargs["input"] == "testuser:newpass"


class TestSetUserGroups:
    """os_user_service.set_user_groups()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_groups(self, mock_pwd, mock_grp, mock_subprocess):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        groups = set_user_groups("testuser", ["ecube-admins"])
        assert "ecube-admins" in groups


class TestCreateGroup:
    """os_user_service.create_group()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_create_group(self, mock_grp, mock_subprocess):
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),  # group_exists check
            _make_grp(name="newgroup", gid=3000),  # lookup after creation
        ]
        mock_subprocess.return_value = _ok_result()

        group = create_group("newgroup")
        assert group.name == "newgroup"
        assert group.gid == 3000

    @patch("app.services.os_user_service.grp")
    def test_create_existing_group(self, mock_grp):
        mock_grp.getgrnam.return_value = _make_grp(name="existing")
        with pytest.raises(OSUserError, match="already exists"):
            create_group("existing")


class TestDeleteGroup:
    """os_user_service.delete_group()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_delete_group(self, mock_grp, mock_subprocess):
        mock_grp.getgrnam.return_value = _make_grp(name="oldgroup")
        mock_subprocess.return_value = _ok_result()

        delete_group("oldgroup")

        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/groupdel", "oldgroup"] in calls

    @patch("app.services.os_user_service.grp")
    def test_delete_nonexistent_group(self, mock_grp):
        mock_grp.getgrnam.side_effect = KeyError("no such group")
        with pytest.raises(OSUserError, match="does not exist"):
            delete_group("nope")


class TestListUsers:
    """os_user_service.list_users()."""

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_list_users_ecube_only(self, mock_pwd, mock_grp):
        mock_pwd.getpwall.return_value = [
            _make_pw(name="admin1", uid=1001),
            _make_pw(name="sysuser", uid=999),
        ]
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["admin1"]),
        ]
        mock_grp.getgrgid.side_effect = [
            _make_grp(name="admin1", gid=1001),
            _make_grp(name="sysuser", gid=999),
        ]

        users = list_users(ecube_only=True)
        assert len(users) == 1
        assert users[0].username == "admin1"


class TestListGroups:
    """os_user_service.list_groups()."""

    @patch("app.services.os_user_service.grp")
    def test_list_ecube_groups(self, mock_grp):
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", gid=3001),
            _make_grp(name="ecube-managers", gid=3002),
            _make_grp(name="wheel", gid=10),
        ]

        groups = list_groups(ecube_only=True)
        assert len(groups) == 2
        names = [g.name for g in groups]
        assert "ecube-admins" in names
        assert "wheel" not in names


class TestEnsureEcubeGroups:
    """os_user_service.ensure_ecube_groups()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_creates_missing_groups(self, mock_grp, mock_subprocess):
        # All groups missing.
        mock_grp.getgrnam.side_effect = KeyError("no such group")
        mock_subprocess.return_value = _ok_result()

        created = ensure_ecube_groups()
        assert len(created) == 4
        assert "ecube-admins" in created


class TestSubprocessTimeout:
    """Subprocess timeout handling."""

    @patch("app.services.os_user_service.pwd")
    @patch("app.services.os_user_service.subprocess.run")
    def test_timeout_raises_os_user_error(self, mock_subprocess, mock_pwd):
        mock_pwd.getpwnam.side_effect = KeyError("no such user")
        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="useradd", timeout=30)

        with pytest.raises(OSUserError, match="timed out"):
            create_user("testuser", "password")


# ===========================================================================
# Router-layer tests (admin OS endpoints)
# ===========================================================================


class TestOSUserEndpoints:
    """Admin OS user management endpoints."""

    def test_create_user_requires_admin(self, client):
        """Non-admin (processor) should get 403."""
        resp = client.post("/admin/os-users", json={
            "username": "newuser",
            "password": "s3cret",
        })
        assert resp.status_code == 403

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_success(self, mock_pwd, mock_grp, mock_subprocess, admin_client):
        pw = _make_pw(name="newuser", uid=1050)
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),  # user_exists
            pw,                        # final lookup
            pw,                        # _get_user_groups
        ]
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="newuser", gid=1050)
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-users", json={
            "username": "newuser",
            "password": "s3cret",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["uid"] == 1050

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_with_roles(self, mock_pwd, mock_grp, mock_subprocess, admin_client, db):
        """Creating user with roles should seed DB role assignments."""
        pw = _make_pw(name="roleuser", uid=1051)
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),  # user_exists
            pw,                        # final lookup
            pw,                        # _get_user_groups
        ]
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="roleuser", gid=1051)
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-users", json={
            "username": "roleuser",
            "password": "pass",
            "roles": ["admin", "manager"],
        })
        assert resp.status_code == 201

        # Verify DB roles were set.
        repo = UserRoleRepository(db)
        roles = repo.get_roles("roleuser")
        assert "admin" in roles
        assert "manager" in roles

    @patch("app.services.os_user_service.pwd")
    def test_create_user_already_exists(self, mock_pwd, admin_client):
        mock_pwd.getpwnam.return_value = _make_pw()
        resp = admin_client.post("/admin/os-users", json={
            "username": "testuser",
            "password": "pass",
        })
        assert resp.status_code == 409

    def test_create_user_invalid_username(self, admin_client):
        resp = admin_client.post("/admin/os-users", json={
            "username": "Invalid!",
            "password": "pass",
        })
        assert resp.status_code == 422

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_list_os_users(self, mock_pwd, mock_grp, admin_client):
        mock_pwd.getpwall.return_value = [
            _make_pw(name="admin1", uid=1001),
        ]
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["admin1"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="admin1", gid=1001)

        resp = admin_client.get("/admin/os-users")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["users"]) == 1
        assert data["users"][0]["username"] == "admin1"

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.pwd")
    def test_delete_os_user(self, mock_pwd, mock_subprocess, admin_client, db):
        mock_pwd.getpwnam.return_value = _make_pw(name="deluser")
        mock_subprocess.return_value = _ok_result()

        # Seed some DB roles so we can verify cleanup.
        db.add(UserRole(username="deluser", role="processor"))
        db.commit()

        resp = admin_client.delete("/admin/os-users/deluser")
        assert resp.status_code == 200

        # DB roles should be cleaned up.
        roles = UserRoleRepository(db).get_roles("deluser")
        assert roles == []

    def test_delete_reserved_user(self, admin_client):
        resp = admin_client.delete("/admin/os-users/root")
        assert resp.status_code == 422

    def test_delete_invalid_username(self, admin_client):
        resp = admin_client.delete("/admin/os-users/Bob;rm")
        assert resp.status_code == 422

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.pwd")
    def test_reset_password(self, mock_pwd, mock_subprocess, admin_client):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.put("/admin/os-users/testuser/password", json={
            "password": "newpass",
        })
        assert resp.status_code == 200
        assert "reset" in resp.json()["message"].lower()

    @patch("app.routers.admin._pwd")
    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_user_groups(self, mock_pwd, mock_grp, mock_subprocess, mock_router_pwd, admin_client):
        pw = _make_pw()
        mock_pwd.getpwnam.return_value = pw
        mock_router_pwd.getpwnam.return_value = pw
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.put("/admin/os-users/testuser/groups", json={
            "groups": ["ecube-admins"],
        })
        assert resp.status_code == 200
        assert resp.json()["username"] == "testuser"

    def test_os_user_endpoints_require_auth(self, unauthenticated_client):
        """Unauthenticated requests should get 401."""
        resp = unauthenticated_client.get("/admin/os-users")
        assert resp.status_code == 401


class TestOSGroupEndpoints:
    """Admin OS group management endpoints."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_create_group(self, mock_grp, mock_subprocess, admin_client):
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),
            _make_grp(name="newgroup", gid=4000),
        ]
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-groups", json={"name": "newgroup"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "newgroup"

    @patch("app.services.os_user_service.grp")
    def test_create_existing_group(self, mock_grp, admin_client):
        mock_grp.getgrnam.return_value = _make_grp(name="existing")

        resp = admin_client.post("/admin/os-groups", json={"name": "existing"})
        assert resp.status_code == 409

    @patch("app.services.os_user_service.grp")
    def test_list_groups(self, mock_grp, admin_client):
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", gid=3001),
            _make_grp(name="ecube-managers", gid=3002),
            _make_grp(name="wheel", gid=10),
        ]

        resp = admin_client.get("/admin/os-groups")
        assert resp.status_code == 200
        names = [g["name"] for g in resp.json()["groups"]]
        assert "ecube-admins" in names
        assert "wheel" not in names

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_delete_group(self, mock_grp, mock_subprocess, admin_client):
        mock_grp.getgrnam.return_value = _make_grp(name="oldgroup")
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.delete("/admin/os-groups/oldgroup")
        assert resp.status_code == 200

    @patch("app.services.os_user_service.grp")
    def test_delete_nonexistent_group(self, mock_grp, admin_client):
        mock_grp.getgrnam.side_effect = KeyError("no such group")

        resp = admin_client.delete("/admin/os-groups/nope")
        assert resp.status_code == 404

    def test_delete_invalid_group_name(self, admin_client):
        resp = admin_client.delete("/admin/os-groups/Bad;Name")
        assert resp.status_code == 422

    def test_group_endpoints_require_admin(self, client):
        """Processor-role client gets 403."""
        resp = client.post("/admin/os-groups", json={"name": "testgroup"})
        assert resp.status_code == 403


# ===========================================================================
# Setup wizard endpoint tests
# ===========================================================================


class TestSetupEndpoints:
    """First-run setup wizard endpoints."""

    def test_status_not_initialized(self, unauthenticated_client):
        resp = unauthenticated_client.get("/setup/status")
        assert resp.status_code == 200
        assert resp.json()["initialized"] is False

    def test_status_initialized(self, unauthenticated_client, db):
        db.add(UserRole(username="admin1", role="admin"))
        db.commit()

        resp = unauthenticated_client.get("/setup/status")
        assert resp.status_code == 200
        assert resp.json()["initialized"] is True

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_initialize_success(self, mock_pwd, mock_grp, mock_subprocess, unauthenticated_client, db):
        # All groups missing — 4 KeyErrors for ensure_ecube_groups, then
        # success when set_user_groups validates "ecube-admins".
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),  # ensure: ecube-admins
            KeyError("no such group"),  # ensure: ecube-auditors
            KeyError("no such group"),  # ensure: ecube-managers
            KeyError("no such group"),  # ensure: ecube-processors
            _make_grp(name="ecube-admins"),  # set_user_groups validation
        ]
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="admin1", gid=1000)
        # User doesn't exist, then exists after creation (3 calls).
        pw = _make_pw(name="admin1")
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),  # user_exists
            pw,                        # final lookup
            pw,                        # _get_user_groups
        ]
        mock_subprocess.return_value = _ok_result()

        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "s3cret",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Setup complete"
        assert data["username"] == "admin1"

        # Verify admin role seeded in DB.
        repo = UserRoleRepository(db)
        assert repo.has_any_admin()
        assert "admin" in repo.get_roles("admin1")

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_initialize_conflict_when_already_set_up(
        self, mock_pwd, mock_grp, mock_subprocess, unauthenticated_client, db
    ):
        """After initialization, a second call returns 409."""
        # Make first init succeed.
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),  # ensure: ecube-admins
            KeyError("no such group"),  # ensure: ecube-auditors
            KeyError("no such group"),  # ensure: ecube-managers
            KeyError("no such group"),  # ensure: ecube-processors
            _make_grp(name="ecube-admins"),  # set_user_groups validation
        ]
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="admin1", gid=1000)
        pw = _make_pw(name="admin1")
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),  # user_exists
            pw,                        # final lookup
            pw,                        # _get_user_groups
        ]
        mock_subprocess.return_value = _ok_result()

        resp1 = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "s3cret",
        })
        assert resp1.status_code == 200

        # Second call should fail.
        resp2 = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin2",
            "password": "s3cret",
        })
        assert resp2.status_code == 409

    def test_initialize_invalid_username(self, unauthenticated_client):
        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "BAD USER",
            "password": "s3cret",
        })
        assert resp.status_code == 422

    def test_initialize_empty_password(self, unauthenticated_client):
        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "",
        })
        assert resp.status_code == 422

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_initialize_existing_user_recovery(
        self, mock_pwd, mock_grp, mock_subprocess, unauthenticated_client, db
    ):
        """When the OS user already exists, setup should append to ecube-admins
        (preserving existing groups) and reset the password."""
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),  # ensure: ecube-admins
            KeyError("no such group"),  # ensure: ecube-auditors
            KeyError("no such group"),  # ensure: ecube-managers
            KeyError("no such group"),  # ensure: ecube-processors
            _make_grp(name="ecube-admins"),  # add_user_to_groups validation
        ]
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["admin1"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="admin1", gid=1000)
        pw = _make_pw(name="admin1")
        mock_pwd.getpwnam.side_effect = [
            pw,                        # create_user → user_exists (True → raises)
            pw,                        # add_user_to_groups → user_exists
            pw,                        # add_user_to_groups → _get_user_groups
            pw,                        # reset_password → user_exists
        ]
        mock_subprocess.return_value = _ok_result()

        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "s3cret",
        })
        assert resp.status_code == 200

        # Verify usermod -aG was called (not -G).
        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        aG_calls = [c for c in calls if "-aG" in c]
        assert len(aG_calls) >= 1
        # Verify password was reset via chpasswd.
        chpasswd_calls = [c for c in calls if "/usr/sbin/chpasswd" in c]
        assert len(chpasswd_calls) >= 1


# ===========================================================================
# Audit logging tests
# ===========================================================================


class TestOSUserAuditLogging:
    """Verify OS user/group operations are audit-logged."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_audit(self, mock_pwd, mock_grp, mock_subprocess, admin_client, db):
        pw = _make_pw(name="audituser", uid=1060)
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),  # user_exists
            pw,                        # final lookup
            pw,                        # _get_user_groups
        ]
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="audituser", gid=1060)
        mock_subprocess.return_value = _ok_result()

        admin_client.post("/admin/os-users", json={
            "username": "audituser",
            "password": "secret",
        })

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_USER_CREATED")
        assert len(logs) >= 1
        assert logs[0].details["target_user"] == "audituser"

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.pwd")
    def test_delete_user_audit(self, mock_pwd, mock_subprocess, admin_client, db):
        mock_pwd.getpwnam.return_value = _make_pw(name="delaudit")
        mock_subprocess.return_value = _ok_result()

        admin_client.delete("/admin/os-users/delaudit")

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_USER_DELETED")
        assert len(logs) >= 1

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.pwd")
    def test_password_reset_audit(self, mock_pwd, mock_subprocess, admin_client, db):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_subprocess.return_value = _ok_result()

        sentinel_password = "SENTINEL-p4ssw0rd-MUST-NOT-APPEAR"
        admin_client.put("/admin/os-users/testuser/password", json={"password": sentinel_password})

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_PASSWORD_RESET")
        assert len(logs) >= 1
        # Password must NOT appear in audit details.
        for log in logs:
            details_str = str(log.details)
            assert sentinel_password not in details_str
            # Verify expected keys are present instead.
            assert "target_user" in log.details
            assert log.details["target_user"] == "testuser"

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_create_group_audit(self, mock_grp, mock_subprocess, admin_client, db):
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),
            _make_grp(name="audgrp", gid=5000),
        ]
        mock_subprocess.return_value = _ok_result()

        admin_client.post("/admin/os-groups", json={"name": "audgrp"})

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_GROUP_CREATED")
        assert len(logs) >= 1
        assert logs[0].details["group_name"] == "audgrp"
