"""Tests for Unicode input sanitization (issue #124).

Verifies that null bytes, unpaired surrogates, and other malformed Unicode
sequences are stripped by the SafeStr Pydantic type and the sanitize_string
helper so they never reach the database layer.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.models.hardware import DriveState, UsbDrive
from app.utils.sanitize import SafeStr, is_encoding_error, sanitize_string


# ---------------------------------------------------------------------------
# Unit tests: sanitize_string
# ---------------------------------------------------------------------------


class TestSanitizeString:
    """Direct tests for the sanitize_string helper."""

    def test_strips_null_bytes(self):
        assert sanitize_string("hello\x00world") == "helloworld"

    def test_strips_multiple_null_bytes(self):
        assert sanitize_string("\x00a\x00b\x00") == "ab"

    def test_strips_unpaired_high_surrogate(self):
        result = sanitize_string("test\ud800value")
        assert "\ud800" not in result
        assert result == "testvalue"

    def test_strips_unpaired_low_surrogate(self):
        result = sanitize_string("test\udc00value")
        assert "\udc00" not in result
        assert result == "testvalue"

    def test_strips_surrogate_pair_used_as_lone_surrogates(self):
        # Even paired surrogates in Python strings are invalid in UTF-8.
        result = sanitize_string("\ud838\uddce")
        assert result == ""

    def test_strips_mixed_dangerous_chars(self):
        # Combines null bytes and surrogates as in the fuzz payload.
        result = sanitize_string("\t\ud838\uddce\u00af")
        assert "\ud838" not in result
        assert "\uddce" not in result
        assert "\x00" not in result
        # Legitimate characters are preserved.
        assert "\t" in result
        assert "\u00af" in result

    def test_normal_ascii_unchanged(self):
        assert sanitize_string("hello world 123") == "hello world 123"

    def test_normal_unicode_unchanged(self):
        assert sanitize_string("日本語テスト") == "日本語テスト"

    def test_empty_string(self):
        assert sanitize_string("") == ""

    def test_passthrough_non_string(self):
        assert sanitize_string(42) == 42
        assert sanitize_string(None) is None
        assert sanitize_string(3.14) == 3.14


# ---------------------------------------------------------------------------
# Unit tests: is_encoding_error
# ---------------------------------------------------------------------------


class TestIsEncodingError:

    def test_detects_invalid_byte_sequence(self):
        exc = Exception("invalid byte sequence for encoding UTF8")
        assert is_encoding_error(exc) is True

    def test_detects_null_character(self):
        exc = Exception("null character not allowed")
        assert is_encoding_error(exc) is True

    def test_detects_hex_null(self):
        exc = Exception("value contains \\x00")
        assert is_encoding_error(exc) is True

    def test_normal_exception_not_detected(self):
        exc = Exception("unique constraint violated")
        assert is_encoding_error(exc) is False


# ---------------------------------------------------------------------------
# Unit tests: SafeStr Pydantic type
# ---------------------------------------------------------------------------


class TestSafeStrPydantic:
    """Verify SafeStr works as a Pydantic field type."""

    def test_strips_null_in_model(self):
        from pydantic import BaseModel

        class M(BaseModel):
            name: SafeStr

        m = M(name="a\x00b")
        assert m.name == "ab"

    def test_strips_surrogate_in_model(self):
        from pydantic import BaseModel
        from typing import Optional

        class M(BaseModel):
            value: Optional[SafeStr] = None

        m = M(value="x\ud800y")
        assert m.value == "xy"

    def test_none_passthrough_optional(self):
        from pydantic import BaseModel
        from typing import Optional

        class M(BaseModel):
            value: Optional[SafeStr] = None

        m = M(value=None)
        assert m.value is None


# ---------------------------------------------------------------------------
# Integration tests: POST /mounts with malformed Unicode
# ---------------------------------------------------------------------------


class TestMountsUnicodeSanitization:

    def test_post_mount_null_bytes_stripped(self, manager_client, db):
        """Null bytes in mount fields are stripped — no 500 error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "192.168.1.1:/export\x00s",
                    "local_mount_point": "/mnt/evi\x00dence",
                },
            )
        assert response.status_code != 500
        data = response.json()
        assert data["remote_path"] == "192.168.1.1:/exports"
        assert data["local_mount_point"] == "/mnt/evidence"

    def test_post_mount_surrogates_stripped(self, manager_client, db):
        """Surrogate code points in persisted mount fields are sanitized."""
        payload = json.dumps({
            "type": "NFS",
            "remote_path": "server\ud800:/share",
            "local_mount_point": "/mnt/\udc00test",
        }).encode("utf-8", "surrogatepass")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = manager_client.post(
                "/mounts",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
        assert response.status_code != 500
        data = response.json()
        assert data["remote_path"] == "server:/share"
        assert data["local_mount_point"] == "/mnt/test"


# ---------------------------------------------------------------------------
# Integration tests: POST /jobs with malformed Unicode
# ---------------------------------------------------------------------------


class TestJobsUnicodeSanitization:

    def test_post_job_surrogates_stripped(self, admin_client, db):
        """Unpaired surrogates in job fields are sanitized before persistence."""
        payload = json.dumps({
            "project_id": "PROJ\ud800001",
            "evidence_number": "EV\udc00123",
            "source_path": "/mnt/source/\ud83ddata",
        }).encode("utf-8", "surrogatepass")
        response = admin_client.post(
            "/jobs",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == "PROJ001"
        assert data["evidence_number"] == "EV123"
        assert data["source_path"] == "/mnt/source/data"

    def test_post_job_null_bytes_sanitized(self, admin_client, db):
        """Null bytes are stripped from job string fields."""
        response = admin_client.post(
            "/jobs",
            json={
                "project_id": "PROJ001",
                "evidence_number": "EV\x00123",
                "source_path": "/mnt/source",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["evidence_number"] == "EV123"


# ---------------------------------------------------------------------------
# Integration tests: GET /drives?project_id with malformed Unicode
# ---------------------------------------------------------------------------


class TestDrivesQueryParamSanitization:

    def test_get_drives_null_in_project_id(self, client, db):
        """Null byte in project_id is sanitized; matching drive is returned."""
        drive = UsbDrive(
            device_identifier="USB-NULL-TEST",
            current_state=DriveState.IN_USE,
            current_project_id="PRJ123",
        )
        db.add(drive)
        db.commit()

        response = client.get("/drives", params={"project_id": "PRJ\x00123"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["device_identifier"] == "USB-NULL-TEST"
        assert data[0]["current_project_id"] == "PRJ123"

    def test_get_drives_surrogate_in_project_id(self, client, db):
        """Percent-encoded surrogate bytes in project_id don't crash the endpoint.

        Unlike JSON bodies, surrogates in query params are decoded by urllib
        into U+FFFD replacement characters before reaching application code,
        so exact matching against a stored project_id isn't possible.  This
        test verifies the endpoint still returns 200 (not 500).
        """
        drive = UsbDrive(
            device_identifier="USB-SURR-TEST",
            current_state=DriveState.IN_USE,
            current_project_id="PRJ456",
        )
        db.add(drive)
        db.commit()

        surrogate_bytes = "\ud800".encode("utf-8", "surrogatepass")
        pct = "".join(f"%{b:02X}" for b in surrogate_bytes)
        response = client.get(f"/drives?project_id=PRJ{pct}456")
        assert response.status_code == 200

    def test_get_drives_normal_project_id(self, client, db):
        """Normal project_id query still works."""
        drive = UsbDrive(
            device_identifier="USB-NORMAL-TEST",
            current_state=DriveState.IN_USE,
            current_project_id="PRJ-001",
        )
        db.add(drive)
        db.commit()

        response = client.get("/drives", params={"project_id": "PRJ-001"})
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    def test_get_drives_all_null_project_id_returns_422(self, client, db):
        """project_id that becomes empty after sanitization returns 422."""
        response = client.get("/drives", params={"project_id": "\x00\x00\x00"})
        assert response.status_code == 422
