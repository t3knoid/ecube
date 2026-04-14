"""Tests for ``GET /browse`` — directory browser endpoint."""

import os
import stat
import time
from unittest.mock import patch, MagicMock

import jwt
import pytest

from app.config import settings
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


def _make_entry(name: str, is_dir: bool = False, is_link: bool = False, size: int = 1024):
    """Return a fake ``os.DirEntry``-style stat result tuple for mocking."""
    entry = MagicMock()
    entry.name = name
    mode = stat.S_IFDIR if is_dir else (stat.S_IFLNK if is_link else stat.S_IFREG)
    entry_stat = MagicMock()
    entry_stat.st_mode = mode
    entry_stat.st_size = size if not (is_dir or is_link) else 0
    entry_stat.st_mtime = 1_700_000_000.0
    return entry, entry_stat


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

    def test_path_traversal_absolute_subdir_returns_400(self, client, db, tmp_path):
        """Subdir that resolves to /etc even via absolute path is rejected."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        # Try an absolute path subdir that would escape the root after realpath
        with patch("app.config.settings.browse_allowed_prefixes", [str(tmp_path)]):
            response = client.get(f"/browse?path={mount_point}&subdir=../../../tmp")

        assert response.status_code == 400

    def test_not_allowed_prefix_returns_403(self, client, db, tmp_path):
        """A valid DB mount root outside the allowed prefix list returns 403."""
        mount_point = str(tmp_path)
        _make_network_mount(db, mount_point)

        # Restrict allowed prefixes to something that does NOT include tmp_path
        with patch("app.config.settings.browse_allowed_prefixes", ["/mnt/ecube/", "/nfs/", "/smb/"]):
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
        assert entry.details["reason"] == "unknown_mount_root"


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
