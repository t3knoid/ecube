"""Tests for ``GET /browse`` — directory browser endpoint."""

import os
from unittest.mock import patch

import pytest

from app.models.hardware import UsbDrive
from app.models.network import NetworkMount, MountStatus, MountType


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


def _make_drive_with_mount(db, mount_path: str) -> UsbDrive:
    """Insert a UsbDrive row with *mount_path* set."""
    drive = UsbDrive(
        device_identifier="TEST-DRIVE-001",
        mount_path=mount_path,
    )
    db.add(drive)
    db.commit()
    db.refresh(drive)
    return drive


def _make_network_mount(db, local_mount_point: str) -> NetworkMount:
    """Insert a NetworkMount row with *local_mount_point* set."""
    mount = NetworkMount(
        type=MountType.NFS,
        remote_path="192.168.1.1:/exports/evidence",
        local_mount_point=local_mount_point,
        status=MountStatus.MOUNTED,
    )
    db.add(mount)
    db.commit()
    db.refresh(mount)
    return mount


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestBrowseHappyPath:
    def test_browse_network_mount_root(self, client, db, tmp_path):
        """GET /browse returns entries for a registered network mount."""
        mount_point = str(tmp_path)
        # Create a file and directory inside tmp_path
        (tmp_path / "report.pdf").write_bytes(b"x" * 2048)
        (tmp_path / "photos").mkdir()

        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 200
        data = response.json()
        assert data["path"] == mount_point
        assert data["subdir"] == ""
        assert data["page"] == 1
        assert data["page_size"] == 100
        assert data["total"] == 2

        names = {e["name"] for e in data["entries"]}
        assert "report.pdf" in names
        assert "photos" in names

        file_entry = next(e for e in data["entries"] if e["name"] == "report.pdf")
        assert file_entry["type"] == "file"
        assert file_entry["size_bytes"] == 2048

        dir_entry = next(e for e in data["entries"] if e["name"] == "photos")
        assert dir_entry["type"] == "directory"
        assert dir_entry["size_bytes"] is None

    def test_browse_usb_drive_mount(self, client, db, tmp_path):
        """GET /browse returns entries for a registered USB drive mount path."""
        mount_point = str(tmp_path)
        (tmp_path / "evidence.zip").write_bytes(b"z" * 512)

        _make_drive_with_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 1
        assert data["entries"][0]["name"] == "evidence.zip"

    def test_browse_subdirectory(self, client, db, tmp_path):
        """GET /browse with subdir navigates into a subdirectory."""
        mount_point = str(tmp_path)
        subdir = tmp_path / "docs"
        subdir.mkdir()
        (subdir / "contract.pdf").write_bytes(b"c" * 4096)

        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}&subdir=docs")

        assert response.status_code == 200
        data = response.json()
        assert data["subdir"] == "docs"
        assert data["total"] == 1
        assert data["entries"][0]["name"] == "contract.pdf"

    def test_browse_pagination(self, client, db, tmp_path):
        """Pagination correctly slices entries and reports total."""
        mount_point = str(tmp_path)
        for i in range(15):
            (tmp_path / f"file_{i:02d}.txt").write_bytes(b"x")

        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            resp_p1 = client.get(f"/browse?path={mount_point}&page=1&page_size=10")
            resp_p2 = client.get(f"/browse?path={mount_point}&page=2&page_size=10")

        assert resp_p1.status_code == 200
        d1 = resp_p1.json()
        assert d1["total"] == 15
        assert len(d1["entries"]) == 10
        assert d1["page"] == 1

        assert resp_p2.status_code == 200
        d2 = resp_p2.json()
        assert d2["total"] == 15
        assert len(d2["entries"]) == 5
        assert d2["page"] == 2

    def test_browse_empty_directory(self, client, db, tmp_path):
        """Browsing an empty directory returns entries=[] and total=0."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 200
        data = response.json()
        assert data["entries"] == []
        assert data["total"] == 0

    def test_browse_symlink_reported_not_followed(self, client, db, tmp_path):
        """Symlinks are listed as type 'symlink' and not dereferenced."""
        mount_point = str(tmp_path)
        target = tmp_path / "real_file.txt"
        target.write_bytes(b"real")
        link = tmp_path / "link_to_file"
        link.symlink_to(target)

        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 200
        entries = {e["name"]: e for e in response.json()["entries"]}
        assert entries["link_to_file"]["type"] == "symlink"
        assert entries["link_to_file"]["size_bytes"] is None

    def test_browse_audit_log_written(self, client, db, tmp_path):
        """A BROWSE_DIRECTORY audit record is written for every successful call."""
        from app.models.audit import AuditLog

        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 200
        entry = db.query(AuditLog).filter(AuditLog.action == "BROWSE_DIRECTORY").first()
        assert entry is not None
        assert entry.details["path"] == mount_point


# ---------------------------------------------------------------------------
# Security / rejection tests
# ---------------------------------------------------------------------------


class TestBrowseSecurity:
    def test_unknown_path_returns_403(self, client, db):
        """Requesting a path that is not a registered mount root returns 403."""
        response = client.get("/browse?path=/etc")
        assert response.status_code == 403

    def test_path_traversal_via_subdir_returns_400(self, client, db, tmp_path):
        """Subdir containing ../ that resolves outside the mount root returns 400."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}&subdir=../../etc")

        assert response.status_code == 400

    def test_path_traversal_relative_dotdot_subdir_returns_400(self, client, db, tmp_path):
        """Subdir using multiple ../ levels that resolves outside the mount root returns 400."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}&subdir=../../../tmp")

        assert response.status_code == 400

    def test_symlink_subdir_navigation_returns_400(self, client, db, tmp_path):
        """Subdir that traverses a symlink directory is rejected even if it stays inside the root."""
        mount_point = str(tmp_path)
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "secret.txt").write_text("data")
        link = tmp_path / "link"
        link.symlink_to(real_dir)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}&subdir=link")

        assert response.status_code == 400
        assert "symbolic link" in response.json()["message"].lower()

    def test_not_allowed_prefix_returns_403(self, client, db, tmp_path):
        """A valid DB mount root outside the allowed prefix list returns 403."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        # Restrict allowed prefixes to something that does NOT include tmp_path
        with patch("app.config.settings.browse_allowed_prefixes", ["/mnt/ecube/", "/nfs/", "/smb/"]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 403

    def test_prefix_boundary_bypass_returns_403(self, client, db, tmp_path):
        """A mount root whose name starts with an allowed prefix but is a different directory is rejected."""
        # e.g. allowed = /tmp/ecube  but mount root = /tmp/ecube2
        allowed_prefix = str(tmp_path) + "allowed"
        mount_point = str(tmp_path) + "allowed2"  # overlaps but is a different dir
        os.makedirs(mount_point, exist_ok=True)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [allowed_prefix]):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 403

    def test_unauthenticated_returns_401(self, unauthenticated_client, db, tmp_path):
        """Unauthenticated request returns 401."""
        response = unauthenticated_client.get(f"/browse?path={tmp_path}")
        assert response.status_code == 401

    def test_denied_audit_log_written(self, client, db):
        """A BROWSE_DENIED audit record is written when the mount root is unknown."""
        from app.models.audit import AuditLog

        client.get("/browse?path=/unknown/path/42")

        entry = db.query(AuditLog).filter(AuditLog.action == "BROWSE_DENIED").first()
        assert entry is not None
        assert "not a registered active mount root" in entry.details["reason"]

    def test_admin_role_allowed(self, admin_client, db, tmp_path):
        """Admin role can access the browse endpoint."""
        mount_point = str(tmp_path)
        (tmp_path / "file.txt").write_bytes(b"x")
        _make_network_mount(db, mount_point)
        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = admin_client.get(f"/browse?path={mount_point}")
        assert response.status_code == 200

    def test_manager_role_allowed(self, manager_client, db, tmp_path):
        """Manager role can access the browse endpoint."""
        mount_point = str(tmp_path)
        (tmp_path / "file.txt").write_bytes(b"x")
        _make_network_mount(db, mount_point)
        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = manager_client.get(f"/browse?path={mount_point}")
        assert response.status_code == 200

    def test_auditor_role_allowed(self, auditor_client, db, tmp_path):
        """Auditor role can access the browse endpoint."""
        mount_point = str(tmp_path)
        (tmp_path / "file.txt").write_bytes(b"x")
        _make_network_mount(db, mount_point)
        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = auditor_client.get(f"/browse?path={mount_point}")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


class TestBrowseParameterValidation:
    def test_missing_path_returns_422(self, client, db):
        """Omitting the required 'path' parameter returns 422."""
        response = client.get("/browse")
        assert response.status_code == 422

    def test_page_size_above_max_returns_422(self, client, db, tmp_path):
        """page_size > 500 returns 422."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)
        response = client.get(f"/browse?path={mount_point}&page_size=501")
        assert response.status_code == 422

    def test_page_below_1_returns_422(self, client, db, tmp_path):
        """page < 1 returns 422."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)
        response = client.get(f"/browse?path={mount_point}&page=0")
        assert response.status_code == 422

    def test_null_byte_in_path_rejected(self, client, db):
        """Null bytes in path are rejected (either 403 unknown mount or 422 validation)."""
        # %00 decodes to null byte; StrictSafeStr should reject with 422, but
        # even if it reaches the service layer it gets 403 (unknown mount root).
        response = client.get("/browse?path=/nfs/ev%00idence")
        assert response.status_code in (403, 422)


# ---------------------------------------------------------------------------
# Filesystem error handling
# ---------------------------------------------------------------------------


class TestBrowseFilesystemErrors:
    def test_permission_denied_returns_403(self, client, db, tmp_path):
        """When os.listdir raises PermissionError, the endpoint returns 403."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]), \
             patch("os.listdir", side_effect=PermissionError("Permission denied")):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 403

    def test_not_a_directory_returns_400(self, client, db, tmp_path):
        """When os.listdir raises NotADirectoryError, the endpoint returns 400."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]), \
             patch("os.listdir", side_effect=NotADirectoryError("Not a directory")):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 400

    def test_os_error_returns_500(self, client, db, tmp_path):
        """When os.listdir raises a generic OSError, the endpoint returns 500."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]), \
             patch("os.listdir", side_effect=OSError("I/O error")):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 500

    def test_file_not_found_returns_404(self, client, db, tmp_path):
        """When the directory disappears between DB lookup and scandir (TOCTOU),
        the endpoint returns 404 with a helpful message."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]), \
             patch("os.listdir", side_effect=FileNotFoundError("No such file or directory")):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 404
        assert "unmounted" in response.json()["message"].lower()

    def test_stat_race_skips_vanished_entries(self, client, db, tmp_path):
        """When a file vanishes between listdir and lstat (_stat_entry returns
        None), the entry is silently excluded from the response."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)
        (tmp_path / "keep.txt").write_text("ok")
        (tmp_path / "vanish.txt").write_text("gone")

        # Patch _stat_entry so it returns None for 'vanish.txt'
        import app.services.browse_service as _bs

        _original = _bs._stat_entry

        def _mock_stat_entry(parent, name):
            if name == "vanish.txt":
                return None
            return _original(parent, name)

        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]), \
             patch.object(_bs, "_stat_entry", side_effect=_mock_stat_entry):
            response = client.get(f"/browse?path={mount_point}")

        assert response.status_code == 200
        names = [e["name"] for e in response.json()["entries"]]
        assert "keep.txt" in names
        assert "vanish.txt" not in names
