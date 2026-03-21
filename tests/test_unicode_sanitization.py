"""Tests for Unicode input sanitization (issue #124).

Verifies that null bytes, unpaired surrogates, and other malformed Unicode
sequences are stripped by the SafeStr Pydantic type and the sanitize_string
helper so they never reach the database layer.
"""

from unittest.mock import MagicMock, patch

import pytest

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
        """Unpaired surrogates in mount fields are stripped — no 500 error."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = manager_client.post(
                "/mounts",
                json={
                    "type": "NFS",
                    "remote_path": "server:/share",
                    "local_mount_point": "/mnt/test",
                    "credentials_file": "/etc/creds\x00file",
                },
            )
        assert response.status_code != 500


# ---------------------------------------------------------------------------
# Integration tests: POST /jobs with malformed Unicode
# ---------------------------------------------------------------------------


class TestJobsUnicodeSanitization:

    def test_post_job_surrogates_stripped(self, admin_client, db):
        """Fuzzed surrogate payload in job fields does not produce 500."""
        response = admin_client.post(
            "/jobs",
            json={
                "project_id": "PROJ\x00001",
                "evidence_number": "EV-123",
                "source_path": "/mnt/source/data",
            },
        )
        # Should not be 500 — either 200 (success) or 4xx (business rule).
        assert response.status_code != 500

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
        assert response.status_code != 500


# ---------------------------------------------------------------------------
# Integration tests: GET /drives?project_id with malformed Unicode
# ---------------------------------------------------------------------------


class TestDrivesQueryParamSanitization:

    def test_get_drives_null_in_project_id(self, client, db):
        """Null byte in project_id query param does not produce 500."""
        response = client.get("/drives", params={"project_id": "PRJ\x00123"})
        assert response.status_code != 500

    def test_get_drives_normal_project_id(self, client, db):
        """Normal project_id query still works."""
        response = client.get("/drives", params={"project_id": "PRJ-001"})
        assert response.status_code == 200
