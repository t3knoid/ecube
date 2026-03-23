"""Tests for OS user/group management and first-run setup wizard.

All subprocess calls (sudo useradd, groupadd, etc.) and OS database lookups
(pwd, grp) are mocked — no real OS changes occur.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.models.users import UserRole
from app.models.system import SystemInitialization
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
    validate_password,
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

    def test_valid_passwords(self):
        for pw in ["s3cret!", "p@ss w0rd", "helloWorld123", "a"]:
            validate_password(pw)  # should not raise

    @pytest.mark.parametrize("bad_pw,expected_label", [
        ("pass\nword", "newline"),
        ("pass\rword", "carriage-return"),
        ("user:pass", "colon"),
        ("a\nb\rc:", "carriage-return, colon, newline"),
    ])
    def test_invalid_passwords(self, bad_pw, expected_label):
        with pytest.raises(ValueError, match=expected_label):
            validate_password(bad_pw)

    def test_empty_password(self):
        with pytest.raises(ValueError, match="empty"):
            validate_password("")


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
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        user = create_user("testuser", "s3cret", groups=["ecube-admins"])

        assert user.username == "testuser"
        assert user.uid == 1000
        # Should have called sudo useradd, sudo chpasswd, and sudo usermod.
        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/useradd", "-m", "testuser"] in calls
        assert ["sudo", "/usr/sbin/chpasswd"] in calls
        assert ["sudo", "/usr/sbin/usermod", "-aG", "ecube-admins", "testuser"] in calls

    @patch("app.services.os_user_service.pwd")
    def test_create_user_already_exists(self, mock_pwd):
        mock_pwd.getpwnam.return_value = _make_pw()
        with pytest.raises(OSUserError, match="already exists"):
            create_user("testuser", "password", groups=["ecube-admins"])

    def test_create_reserved_username(self):
        with pytest.raises(ValueError, match="reserved"):
            create_user("root", "password", groups=["ecube-admins"])

    def test_create_empty_password(self):
        with pytest.raises(ValueError, match="empty"):
            create_user("testuser", "", groups=["ecube-admins"])

    def test_create_user_no_ecube_group_rejected(self):
        """create_user without any ecube-* group must raise ValueError."""
        with pytest.raises(ValueError, match="ecube-"):
            create_user("testuser", "s3cret")

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_only_non_ecube_groups_rejected(self, mock_pwd, mock_grp):
        """Providing only non-ecube groups must raise ValueError."""
        mock_pwd.getpwnam.side_effect = KeyError("no such user")
        mock_grp.getgrnam.return_value = _make_grp(name="developers")
        with pytest.raises(ValueError, match="ecube-"):
            create_user("testuser", "s3cret", groups=["developers"])

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

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_missing_group_no_account_created(self, mock_pwd, mock_grp):
        """If a requested group doesn't exist, the user should never be created."""
        mock_pwd.getpwnam.side_effect = KeyError("no such user")  # user_exists
        mock_grp.getgrnam.side_effect = KeyError("no such group")  # group_exists

        with pytest.raises(OSUserError, match="does not exist"):
            create_user("testuser", "s3cret", groups=["no-such-group"])

        # useradd should never have been called.
        # pwd.getpwnam was only called once (for user_exists), never for
        # the post-creation lookup, proving useradd was not invoked.
        assert mock_pwd.getpwnam.call_count == 1

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_usermod_failure_deletes_user(self, mock_pwd, mock_grp, mock_subprocess):
        """If usermod (group assignment) fails, the created user is cleaned up."""
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),   # user_exists
        ]
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")

        # useradd and chpasswd succeed, usermod fails, userdel succeeds.
        mock_subprocess.side_effect = [
            _ok_result(),       # useradd
            _ok_result(),       # chpasswd
            _fail_result(stderr="usermod: group 'ecube-admins' does not exist"),  # usermod
            _ok_result(),       # userdel (compensation)
        ]

        with pytest.raises(OSUserError, match="usermod"):
            create_user("testuser", "s3cret", groups=["ecube-admins"])

        # Verify userdel was called as compensation.
        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/userdel", "-r", "testuser"] in calls


class TestDeleteUser:
    """os_user_service.delete_user()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_delete_user(self, mock_pwd, mock_grp, mock_subprocess):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_subprocess.return_value = _ok_result()

        delete_user("testuser")

        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/userdel", "-r", "testuser"] in calls

    @patch("app.services.os_user_service.pwd")
    def test_delete_nonexistent_user(self, mock_pwd):
        mock_pwd.getpwnam.side_effect = KeyError("no such user")
        with pytest.raises(OSUserError, match="does not exist"):
            delete_user("nobody_here")

    @patch("app.services.os_user_service.pwd")
    def test_delete_reserved_user(self, mock_pwd):
        mock_pwd.getpwnam.return_value = _make_pw(name="ecube")
        with pytest.raises(ValueError, match="reserved"):
            delete_user("ecube")

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_delete_non_ecube_user_rejected(self, mock_pwd, mock_grp):
        """Users not in any ecube-* group cannot be deleted."""
        mock_pwd.getpwnam.return_value = _make_pw(name="postgres")
        mock_grp.getgrgid.return_value = _make_grp(name="postgres", gid=1000)
        mock_grp.getgrall.return_value = [
            _make_grp(name="postgres", members=["postgres"]),
        ]
        with pytest.raises(ValueError, match="not in any ecube"):
            delete_user("postgres")


class TestResetPassword:
    """os_user_service.reset_password()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_reset_password(self, mock_pwd, mock_grp, mock_subprocess):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_subprocess.return_value = _ok_result()

        reset_password("testuser", "newpass")

        call = mock_subprocess.call_args_list[-1]
        assert call.args[0] == ["sudo", "/usr/sbin/chpasswd"]
        assert call.kwargs["input"] == "testuser:newpass"

    @patch("app.services.os_user_service.pwd")
    def test_reset_password_reserved_username(self, mock_pwd):
        mock_pwd.getpwnam.return_value = _make_pw(name="root")
        with pytest.raises(ValueError, match="reserved"):
            reset_password("root", "newpass")

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_reset_password_non_ecube_user_rejected(self, mock_pwd, mock_grp):
        """Users not in any ecube-* group cannot have passwords reset."""
        mock_pwd.getpwnam.return_value = _make_pw(name="postgres")
        mock_grp.getgrgid.return_value = _make_grp(name="postgres", gid=1000)
        mock_grp.getgrall.return_value = [
            _make_grp(name="postgres", members=["postgres"]),
        ]
        with pytest.raises(ValueError, match="not in any ecube"):
            reset_password("postgres", "newpass")


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

        result = set_user_groups("testuser", ["ecube-admins"])
        assert isinstance(result, OSUser)
        assert "ecube-admins" in result.groups

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_groups_preserves_non_ecube_groups(self, mock_pwd, mock_grp, mock_subprocess):
        """Non-ecube supplementary groups must be preserved when replacing."""
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-processors")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
            _make_grp(name="docker", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        set_user_groups("testuser", ["ecube-processors"])

        # usermod -G should include ecube-processors (requested) + docker (preserved).
        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        usermod_call = [c for c in calls if settings.usermod_binary_path in c][0]
        groups_arg = usermod_call[usermod_call.index("-G") + 1]
        assert "ecube-processors" in groups_arg
        assert "docker" in groups_arg
        assert "ecube-admins" not in groups_arg  # old ecube group removed

    def test_set_groups_empty_rejected(self):
        """Empty group list must be rejected."""
        with pytest.raises(ValueError, match="ecube-"):
            set_user_groups("testuser", [])

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_groups_non_ecube_group_rejected(self, mock_pwd, mock_grp):
        """Non-ecube-* group names must be rejected."""
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        with pytest.raises(ValueError, match="does not start with"):
            set_user_groups("testuser", ["docker"])

    @patch("app.services.os_user_service.pwd")
    def test_set_groups_reserved_username(self, mock_pwd):
        mock_pwd.getpwnam.return_value = _make_pw(name="root")
        with pytest.raises(ValueError, match="reserved"):
            set_user_groups("root", ["ecube-admins"])

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_groups_non_ecube_user_rejected(self, mock_pwd, mock_grp):
        """Users not in any ecube-* group cannot have groups modified."""
        mock_pwd.getpwnam.return_value = _make_pw(name="postgres")
        mock_grp.getgrgid.return_value = _make_grp(name="postgres", gid=1000)
        mock_grp.getgrall.return_value = [
            _make_grp(name="postgres", members=["postgres"]),
        ]
        with pytest.raises(ValueError, match="not in any ecube"):
            set_user_groups("postgres", ["ecube-admins"])


class TestAddUserToGroups:
    """os_user_service.add_user_to_groups()."""

    @patch("app.services.os_user_service.pwd")
    def test_add_to_groups_reserved_username(self, mock_pwd):
        mock_pwd.getpwnam.return_value = _make_pw(name="ecube")
        with pytest.raises(ValueError, match="reserved"):
            os_user_service.add_user_to_groups("ecube", ["ecube-admins"])

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_add_to_groups_non_ecube_user_rejected(self, mock_pwd, mock_grp):
        """Users not in any ecube-* group cannot have groups appended."""
        mock_pwd.getpwnam.return_value = _make_pw(name="www-data")
        mock_grp.getgrgid.return_value = _make_grp(name="www-data", gid=1000)
        mock_grp.getgrall.return_value = [
            _make_grp(name="www-data", members=["www-data"]),
        ]
        with pytest.raises(ValueError, match="not in any ecube"):
            os_user_service.add_user_to_groups("www-data", ["ecube-admins"])


class TestCreateGroup:
    """os_user_service.create_group()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_create_group(self, mock_grp, mock_subprocess):
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),  # group_exists check
            _make_grp(name="ecube-newgroup", gid=3000),  # lookup after creation
        ]
        mock_subprocess.return_value = _ok_result()

        group = create_group("ecube-newgroup")
        assert group.name == "ecube-newgroup"
        assert group.gid == 3000

    @patch("app.services.os_user_service.grp")
    def test_create_existing_group(self, mock_grp):
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-existing")
        with pytest.raises(OSUserError, match="already exists"):
            create_group("ecube-existing")

    def test_create_group_without_ecube_prefix_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            create_group("wheel")


class TestDeleteGroup:
    """os_user_service.delete_group()."""

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_delete_group(self, mock_grp, mock_subprocess):
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-oldgroup")
        mock_subprocess.return_value = _ok_result()

        delete_group("ecube-oldgroup")

        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        assert ["sudo", "/usr/sbin/groupdel", "ecube-oldgroup"] in calls

    @patch("app.services.os_user_service.grp")
    def test_delete_nonexistent_group(self, mock_grp):
        mock_grp.getgrnam.side_effect = KeyError("no such group")
        with pytest.raises(OSUserError, match="does not exist"):
            delete_group("ecube-nope")

    def test_delete_group_without_ecube_prefix_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            delete_group("wheel")


class TestListUsers:
    """os_user_service.list_users()."""

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_list_users_ecube_only(self, mock_pwd, mock_grp):
        mock_pwd.getpwall.return_value = [
            _make_pw(name="admin1", uid=1001),
            _make_pw(name="customuser", uid=1002),
            _make_pw(name="sysuser", uid=999),
        ]
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["admin1"]),
            _make_grp(name="ecube-reviewers", members=["customuser"]),
        ]
        mock_grp.getgrgid.side_effect = [
            _make_grp(name="admin1", gid=1001),
            _make_grp(name="customuser", gid=1002),
            _make_grp(name="sysuser", gid=999),
        ]

        users = list_users(ecube_only=True)
        assert len(users) == 2
        names = [u.username for u in users]
        assert "admin1" in names
        assert "customuser" in names
        assert "sysuser" not in names


class TestListGroups:
    """os_user_service.list_groups()."""

    @patch("app.services.os_user_service.grp")
    def test_list_ecube_groups(self, mock_grp):
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", gid=3001),
            _make_grp(name="ecube-managers", gid=3002),
            _make_grp(name="ecube-custom", gid=3010),
            _make_grp(name="wheel", gid=10),
        ]

        groups = list_groups(ecube_only=True)
        assert len(groups) == 3
        names = [g.name for g in groups]
        assert "ecube-admins" in names
        assert "ecube-custom" in names
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

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    @patch("app.services.os_user_service.subprocess.run")
    def test_timeout_raises_os_user_error(self, mock_subprocess, mock_pwd, mock_grp):
        mock_pwd.getpwnam.side_effect = KeyError("no such user")
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_subprocess.side_effect = subprocess.TimeoutExpired(cmd="useradd", timeout=30)

        with pytest.raises(OSUserError, match="timed out"):
            create_user("testuser", "password", groups=["ecube-admins"])


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
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["newuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="newuser", gid=1050)
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-users", json={
            "username": "newuser",
            "password": "s3cret",
            "groups": ["ecube-admins"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["uid"] == 1050

    def test_create_user_no_ecube_group_returns_422(self, admin_client):
        """POST without ecube-* group returns 422."""
        resp = admin_client.post("/admin/os-users", json={
            "username": "newuser",
            "password": "s3cret",
        })
        assert resp.status_code == 422
        assert "ecube-" in resp.json()["message"]

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
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["roleuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="roleuser", gid=1051)
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-users", json={
            "username": "roleuser",
            "password": "pass",
            "groups": ["ecube-admins"],
            "roles": ["admin", "manager"],
        })
        assert resp.status_code == 201

        # Verify DB roles were set.
        repo = UserRoleRepository(db)
        roles = repo.get_roles("roleuser")
        assert "admin" in roles
        assert "manager" in roles

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_role_db_error_cleans_up_os_user(
        self, mock_pwd, mock_grp, mock_subprocess, admin_client, db,
    ):
        """If set_roles raises a DB error, the OS user should be deleted."""
        pw = _make_pw(name="dbfail", uid=1060)
        mock_pwd.getpwnam.side_effect = [
            KeyError("no such user"),  # user_exists (create_user)
            pw,                        # final lookup (create_user)
            pw,                        # _get_user_groups (create_user)
            pw,                        # user_exists (delete_user compensation)
        ]
        # After user creation, user is in ecube-admins (requested groups).
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["dbfail"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="dbfail", gid=1060)
        mock_subprocess.return_value = _ok_result()

        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        with patch.object(
            UserRoleRepository, "set_roles", side_effect=RuntimeError("DB down"),
        ):
            resp = admin_client.post("/admin/os-users", json={
                "username": "dbfail",
                "password": "pass",
                "groups": ["ecube-admins"],
                "roles": ["admin"],
            })
        assert resp.status_code == 500
        assert "role assignment failed" in resp.json()["message"]

        # Verify userdel was called (compensation).
        del_calls = [
            c for c in mock_subprocess.call_args_list
            if "userdel" in str(c)
        ]
        assert len(del_calls) == 1

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_create_user_already_exists(self, mock_pwd, mock_grp, admin_client):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        resp = admin_client.post("/admin/os-users", json={
            "username": "testuser",
            "password": "pass",
            "groups": ["ecube-admins"],
        })
        assert resp.status_code == 409

    def test_create_user_invalid_username(self, admin_client):
        resp = admin_client.post("/admin/os-users", json={
            "username": "Invalid!",
            "password": "pass",
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "body -> username" in body["message"]

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
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_delete_os_user(self, mock_pwd, mock_grp, mock_subprocess, admin_client, db):
        mock_pwd.getpwnam.return_value = _make_pw(name="deluser")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["deluser"]),
        ]
        mock_subprocess.return_value = _ok_result()

        # Seed some DB roles so we can verify cleanup.
        db.add(UserRole(username="deluser", role="processor"))
        db.commit()

        resp = admin_client.delete("/admin/os-users/deluser")
        assert resp.status_code == 200

        # DB roles should be cleaned up.
        roles = UserRoleRepository(db).get_roles("deluser")
        assert roles == []

    @patch("app.services.os_user_service.pwd")
    def test_delete_reserved_user(self, mock_pwd, admin_client):
        mock_pwd.getpwnam.return_value = _make_pw(name="root")
        resp = admin_client.delete("/admin/os-users/root")
        assert resp.status_code == 422

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_delete_non_ecube_user_rejected(self, mock_pwd, mock_grp, admin_client):
        """Users not in any ecube-* group cannot be deleted via the API."""
        mock_pwd.getpwnam.return_value = _make_pw(name="postgres")
        mock_grp.getgrgid.return_value = _make_grp(name="postgres", gid=1000)
        mock_grp.getgrall.return_value = [
            _make_grp(name="postgres", members=["postgres"]),
        ]
        resp = admin_client.delete("/admin/os-users/postgres")
        assert resp.status_code == 422
        assert "ecube" in resp.json()["message"].lower()

    def test_delete_invalid_username(self, admin_client):
        resp = admin_client.delete("/admin/os-users/Bob;rm")
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "invalid username" in body["message"].lower()

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_reset_password(self, mock_pwd, mock_grp, mock_subprocess, admin_client):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.put("/admin/os-users/testuser/password", json={
            "password": "newpass",
        })
        assert resp.status_code == 200
        assert "reset" in resp.json()["message"].lower()

    def test_create_user_unsafe_password_rejected(self, admin_client):
        """Passwords with newlines or colons are rejected at the schema layer."""
        for bad_pw in ["pass\nword", "pass\rword", "user:pass"]:
            resp = admin_client.post("/admin/os-users", json={
                "username": "newuser",
                "password": bad_pw,
            })
            assert resp.status_code == 422
            body = resp.json()
            assert body["code"] == "VALIDATION_ERROR"
            assert "trace_id" in body
            assert "body -> password" in body["message"]

    def test_reset_password_unsafe_password_rejected(self, admin_client):
        resp = admin_client.put("/admin/os-users/testuser/password", json={
            "password": "new\npass",
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "body -> password" in body["message"]

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_user_groups(self, mock_pwd, mock_grp, mock_subprocess, admin_client):
        pw = _make_pw()
        mock_pwd.getpwnam.return_value = pw
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

    def test_set_user_groups_empty_returns_422(self, admin_client):
        """PUT with empty groups list returns 422."""
        resp = admin_client.put("/admin/os-users/testuser/groups", json={
            "groups": [],
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_set_user_groups_non_ecube_returns_422(self, mock_pwd, mock_grp, admin_client):
        """PUT with non-ecube-* group name returns 422."""
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        resp = admin_client.put("/admin/os-users/testuser/groups", json={
            "groups": ["docker"],
        })
        assert resp.status_code == 422

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_add_user_to_groups(self, mock_pwd, mock_grp, mock_subprocess, admin_client):
        pw = _make_pw()
        mock_pwd.getpwnam.return_value = pw
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-managers")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
            _make_grp(name="ecube-managers", members=["testuser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="testuser", gid=1000)
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-users/testuser/groups", json={
            "groups": ["ecube-managers"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"
        assert "ecube-managers" in data["groups"]

        # Verify usermod -aG was used (append, not replace).
        calls = [c.args[0] for c in mock_subprocess.call_args_list]
        aG_calls = [c for c in calls if "-aG" in c]
        assert len(aG_calls) == 1

    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_add_user_to_groups_reserved_username(self, mock_pwd, mock_grp, admin_client):
        mock_pwd.getpwnam.return_value = _make_pw(name="root")
        mock_grp.getgrall.return_value = []
        resp = admin_client.post("/admin/os-users/root/groups", json={
            "groups": ["ecube-admins"],
        })
        assert resp.status_code == 422

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
            _make_grp(name="ecube-newgroup", gid=4000),
        ]
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.post("/admin/os-groups", json={"name": "ecube-newgroup"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "ecube-newgroup"

    @patch("app.services.os_user_service.grp")
    def test_create_existing_group(self, mock_grp, admin_client):
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-existing")

        resp = admin_client.post("/admin/os-groups", json={"name": "ecube-existing"})
        assert resp.status_code == 409

    def test_create_group_without_ecube_prefix(self, admin_client):
        resp = admin_client.post("/admin/os-groups", json={"name": "wheel"})
        assert resp.status_code == 422
        assert "ecube-" in resp.json()["message"]

    @patch("app.services.os_user_service.grp")
    def test_list_groups(self, mock_grp, admin_client):
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", gid=3001),
            _make_grp(name="ecube-managers", gid=3002),
            _make_grp(name="ecube-reviewers", gid=3010),
            _make_grp(name="wheel", gid=10),
        ]

        resp = admin_client.get("/admin/os-groups")
        assert resp.status_code == 200
        names = [g["name"] for g in resp.json()["groups"]]
        assert "ecube-admins" in names
        assert "ecube-reviewers" in names
        assert "wheel" not in names

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    def test_delete_group(self, mock_grp, mock_subprocess, admin_client):
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-oldgroup")
        mock_subprocess.return_value = _ok_result()

        resp = admin_client.delete("/admin/os-groups/ecube-oldgroup")
        assert resp.status_code == 200

    @patch("app.services.os_user_service.grp")
    def test_delete_nonexistent_group(self, mock_grp, admin_client):
        mock_grp.getgrnam.side_effect = KeyError("no such group")

        resp = admin_client.delete("/admin/os-groups/ecube-nope")
        assert resp.status_code == 422

    def test_delete_group_without_ecube_prefix(self, admin_client):
        resp = admin_client.delete("/admin/os-groups/wheel")
        assert resp.status_code == 422
        assert "ecube-" in resp.json()["message"]

    def test_delete_invalid_group_name(self, admin_client):
        resp = admin_client.delete("/admin/os-groups/Bad;Name")
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "invalid group name" in body["message"].lower()

    def test_group_endpoints_require_admin(self, client):
        """Processor-role client gets 403."""
        resp = client.post("/admin/os-groups", json={"name": "testgroup"})
        assert resp.status_code == 403


# ===========================================================================
# Non-local deployment: OS endpoints must return 404
# ===========================================================================


class TestOSEndpointsNonLocalMode:
    """OS endpoints return 404 before auth when role_resolver is not 'local'.

    Because _ensure_local_role_resolver runs as a FastAPI dependency
    (before require_roles), even unauthenticated callers must get 404 —
    never 401 or 403.
    """

    _OS_ROUTES = [
        ("POST", "/admin/os-users", {"username": "x", "password": "p"}),
        ("GET", "/admin/os-users", None),
        ("DELETE", "/admin/os-users/testuser", None),
        ("PUT", "/admin/os-users/testuser/password", {"password": "p"}),
        ("PUT", "/admin/os-users/testuser/groups", {"groups": ["g"]}),
        ("POST", "/admin/os-users/testuser/groups", {"groups": ["g"]}),
        ("POST", "/admin/os-groups", {"name": "grp"}),
        ("GET", "/admin/os-groups", None),
        ("DELETE", "/admin/os-groups/grp", None),
    ]

    @pytest.mark.parametrize("method,path,body", _OS_ROUTES)
    def test_unauthenticated_gets_404(self, unauthenticated_client, method, path, body):
        """Unauthenticated caller must see 404, not 401."""
        with patch.object(settings, "role_resolver", "oidc"):
            resp = unauthenticated_client.request(method, path, json=body)
        assert resp.status_code == 404

    @pytest.mark.parametrize("method,path,body", _OS_ROUTES)
    def test_non_admin_gets_404(self, client, method, path, body):
        """Processor-role caller must see 404, not 403."""
        with patch.object(settings, "role_resolver", "ldap"):
            resp = client.request(method, path, json=body)
        assert resp.status_code == 404


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
        assert isinstance(data["groups_created"], list)
        assert len(data["groups_created"]) == 4

        # Verify admin role seeded in DB.
        repo = UserRoleRepository(db)
        assert repo.has_any_admin()
        assert "admin" in repo.get_roles("admin1")

        # Verify system_initialization row was created.
        init_row = db.query(SystemInitialization).first()
        assert init_row is not None
        assert init_row.initialized_by == "admin1"

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
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "body -> username" in body["message"]

    def test_initialize_empty_password(self, unauthenticated_client):
        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "",
        })
        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert "trace_id" in body
        assert "body -> password" in body["message"]

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
            pw,                        # add_user_to_groups → pwd.getpwnam (OSUser)
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
        # Verify groups_created is reported.
        data = resp.json()
        assert isinstance(data["groups_created"], list)
        assert len(data["groups_created"]) == 4

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_initialize_existing_user_not_in_ecube_group(
        self, mock_pwd, mock_grp, mock_subprocess, unauthenticated_client, db
    ):
        """Recovery works even when the pre-existing user is not yet in any
        ecube-* group (e.g. useradd succeeded but usermod -aG failed on a
        previous attempt)."""
        mock_grp.getgrnam.side_effect = [
            KeyError("no such group"),  # ensure: ecube-admins
            KeyError("no such group"),  # ensure: ecube-auditors
            KeyError("no such group"),  # ensure: ecube-managers
            KeyError("no such group"),  # ensure: ecube-processors
            _make_grp(name="ecube-admins"),  # add_user_to_groups validation
        ]
        # User is NOT in any ecube-* group yet.
        mock_grp.getgrall.return_value = []
        mock_grp.getgrgid.return_value = _make_grp(name="admin1", gid=1000)
        pw = _make_pw(name="admin1")
        mock_pwd.getpwnam.side_effect = [
            pw,                        # create_user → user_exists (True → raises)
            pw,                        # add_user_to_groups → user_exists
            pw,                        # add_user_to_groups → pwd.getpwnam (OSUser)
            pw,                        # add_user_to_groups → _get_user_groups
            pw,                        # reset_password → user_exists
        ]
        mock_subprocess.return_value = _ok_result()

        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "s3cret",
        })
        assert resp.status_code == 200

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_initialize_releases_lock_on_os_failure(
        self, mock_pwd, mock_grp, mock_subprocess, unauthenticated_client, db
    ):
        """If OS group creation fails, the init lock row is removed so setup
        can be retried."""
        mock_grp.getgrnam.side_effect = KeyError("no such group")
        mock_subprocess.return_value = _fail_result("groupadd failed")

        resp = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "s3cret",
        })
        assert resp.status_code == 500

        # Lock row must be gone so a retry can succeed.
        assert db.query(SystemInitialization).first() is None

        # A subsequent attempt should NOT return 409 — it should be retryable.
        # (It will still fail because mocks haven't changed, but the status
        # code proves the guard was released.)
        resp2 = unauthenticated_client.post("/setup/initialize", json={
            "username": "admin1",
            "password": "s3cret",
        })
        assert resp2.status_code == 500  # OS failure again, not 409

    def test_status_returns_404_when_not_local(self, unauthenticated_client):
        """GET /setup/status returns 404 when role_resolver is not 'local'."""
        with patch.object(settings, "role_resolver", "ldap"):
            resp = unauthenticated_client.get("/setup/status")
        assert resp.status_code == 404

    def test_initialize_returns_404_when_not_local(self, unauthenticated_client):
        """POST /setup/initialize returns 404 when role_resolver is not 'local'."""
        with patch.object(settings, "role_resolver", "oidc"):
            resp = unauthenticated_client.post("/setup/initialize", json={
                "username": "admin1",
                "password": "s3cret",
            })
        assert resp.status_code == 404


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
        mock_grp.getgrnam.return_value = _make_grp(name="ecube-admins")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["audituser"]),
        ]
        mock_grp.getgrgid.return_value = _make_grp(name="audituser", gid=1060)
        mock_subprocess.return_value = _ok_result()

        admin_client.post("/admin/os-users", json={
            "username": "audituser",
            "password": "secret",
            "groups": ["ecube-admins"],
        })

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_USER_CREATED")
        assert len(logs) >= 1
        assert logs[0].details["target_user"] == "audituser"

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_delete_user_audit(self, mock_pwd, mock_grp, mock_subprocess, admin_client, db):
        mock_pwd.getpwnam.return_value = _make_pw(name="delaudit")
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["delaudit"]),
        ]
        mock_subprocess.return_value = _ok_result()

        admin_client.delete("/admin/os-users/delaudit")

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_USER_DELETED")
        assert len(logs) >= 1

    @patch("app.services.os_user_service.subprocess.run")
    @patch("app.services.os_user_service.grp")
    @patch("app.services.os_user_service.pwd")
    def test_password_reset_audit(self, mock_pwd, mock_grp, mock_subprocess, admin_client, db):
        mock_pwd.getpwnam.return_value = _make_pw()
        mock_grp.getgrall.return_value = [
            _make_grp(name="ecube-admins", members=["testuser"]),
        ]
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
            _make_grp(name="ecube-audgrp", gid=5000),
        ]
        mock_subprocess.return_value = _ok_result()

        admin_client.post("/admin/os-groups", json={"name": "ecube-audgrp"})

        from app.repositories.audit_repository import AuditRepository
        logs = AuditRepository(db).query(action="OS_GROUP_CREATED")
        assert len(logs) >= 1
        assert logs[0].details["group_name"] == "ecube-audgrp"
