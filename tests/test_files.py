"""Tests for GET /files/{file_id}/hashes and POST /files/compare."""

import time
from pathlib import Path
from unittest.mock import patch

import jwt
import pytest

from app.config import settings
from app.models.jobs import ExportFile, ExportJob, FileStatus, JobStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(db, project_id="PROJ-001"):
    job = ExportJob(
        project_id=project_id,
        evidence_number="EV-001",
        source_path="/data/evidence",
        status=JobStatus.COMPLETED,
        total_bytes=0,
        copied_bytes=0,
        file_count=1,
        thread_count=4,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _make_file(db, job_id, relative_path="file.txt", size_bytes=1024, checksum=None):
    ef = ExportFile(
        job_id=job_id,
        relative_path=relative_path,
        size_bytes=size_bytes,
        checksum=checksum or "a" * 64,  # dummy sha256
        status=FileStatus.DONE,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)
    return ef


# ---------------------------------------------------------------------------
# GET /files/{file_id}/hashes
# ---------------------------------------------------------------------------


def test_get_file_hashes_stored_checksum(admin_client, db):
    """Returns stored SHA-256 when file is not on disk."""
    job = _make_job(db)
    ef = _make_file(db, job.id, checksum="deadbeef" * 8)

    response = admin_client.get(f"/files/{ef.id}/hashes")

    assert response.status_code == 200
    data = response.json()
    assert data["file_id"] == ef.id
    assert data["sha256"] == "deadbeef" * 8
    assert data["md5"] is None  # not on disk, no live computation
    assert data["relative_path"] == "file.txt"
    assert data["size_bytes"] == 1024


def test_get_file_hashes_live_computation(admin_client, db, tmp_path):
    """Computes MD5 and SHA-256 live when file exists on disk."""
    import hashlib

    content = b"hello world"
    source_path = str(tmp_path)
    file_path = tmp_path / "live_file.txt"
    file_path.write_bytes(content)

    expected_md5 = hashlib.md5(content).hexdigest()
    expected_sha256 = hashlib.sha256(content).hexdigest()

    job = ExportJob(
        project_id="PROJ-001",
        evidence_number="EV-LV",
        source_path=source_path,
        status=JobStatus.COMPLETED,
        total_bytes=len(content),
        copied_bytes=len(content),
        file_count=1,
        thread_count=4,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    ef = ExportFile(
        job_id=job.id,
        relative_path="live_file.txt",
        size_bytes=len(content),
        checksum="old_checksum",
        status=FileStatus.DONE,
    )
    db.add(ef)
    db.commit()
    db.refresh(ef)

    response = admin_client.get(f"/files/{ef.id}/hashes")

    assert response.status_code == 200
    data = response.json()
    assert data["md5"] == expected_md5
    assert data["sha256"] == expected_sha256


def test_get_file_hashes_auditor_allowed(auditor_client, db):
    """Auditor role can access the hashes endpoint."""
    job = _make_job(db)
    ef = _make_file(db, job.id)

    response = auditor_client.get(f"/files/{ef.id}/hashes")
    assert response.status_code == 200


def test_get_file_hashes_not_found(admin_client, db):
    response = admin_client.get("/files/9999/hashes")
    assert response.status_code == 404


def test_get_file_hashes_role_denied(client, db):
    """Processor role is denied access."""
    job = _make_job(db)
    ef = _make_file(db, job.id)

    response = client.get(f"/files/{ef.id}/hashes")
    assert response.status_code == 403


def test_get_file_hashes_creates_audit_log(admin_client, db):
    """A FILE_HASHES_RETRIEVED audit entry is written."""
    from app.models.audit import AuditLog

    job = _make_job(db)
    ef = _make_file(db, job.id)

    admin_client.get(f"/files/{ef.id}/hashes")

    entry = (
        db.query(AuditLog)
        .filter(AuditLog.action == "FILE_HASHES_RETRIEVED")
        .first()
    )
    assert entry is not None
    assert entry.details["file_id"] == ef.id


# ---------------------------------------------------------------------------
# POST /files/compare
# ---------------------------------------------------------------------------


def test_compare_files_match(admin_client, db):
    """Two identical files (same checksum, size, path) should match."""
    job = _make_job(db)
    checksum = "c" * 64
    ef_a = _make_file(db, job.id, relative_path="doc.txt", size_bytes=512, checksum=checksum)
    ef_b = _make_file(db, job.id, relative_path="doc.txt", size_bytes=512, checksum=checksum)

    response = admin_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["match"] is True
    assert data["hash_match"] is True
    assert data["size_match"] is True
    assert data["path_match"] is True


def test_compare_files_hash_mismatch(admin_client, db):
    """Different checksums → match=False, hash_match=False."""
    job = _make_job(db)
    ef_a = _make_file(db, job.id, relative_path="doc.txt", size_bytes=512, checksum="a" * 64)
    ef_b = _make_file(db, job.id, relative_path="doc.txt", size_bytes=512, checksum="b" * 64)

    response = admin_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["match"] is False
    assert data["hash_match"] is False


def test_compare_files_size_mismatch(admin_client, db):
    """Same hash but different size → match depends on logic; size_match=False."""
    job = _make_job(db)
    checksum = "d" * 64
    ef_a = _make_file(db, job.id, relative_path="doc.txt", size_bytes=100, checksum=checksum)
    ef_b = _make_file(db, job.id, relative_path="doc.txt", size_bytes=200, checksum=checksum)

    response = admin_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["size_match"] is False


def test_compare_files_path_mismatch(admin_client, db):
    """Same hash/size but different relative path → path_match=False, match=False."""
    job = _make_job(db)
    checksum = "e" * 64
    ef_a = _make_file(db, job.id, relative_path="dir/a.txt", size_bytes=128, checksum=checksum)
    ef_b = _make_file(db, job.id, relative_path="dir/b.txt", size_bytes=128, checksum=checksum)

    response = admin_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["path_match"] is False
    assert data["match"] is False


def test_compare_files_auditor_allowed(auditor_client, db):
    """Auditor role can use the compare endpoint."""
    job = _make_job(db)
    ef_a = _make_file(db, job.id, relative_path="f.txt")
    ef_b = _make_file(db, job.id, relative_path="f.txt")

    response = auditor_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )
    assert response.status_code == 200


def test_compare_files_role_denied(client, db):
    """Processor role is denied access to compare endpoint."""
    job = _make_job(db)
    ef_a = _make_file(db, job.id)
    ef_b = _make_file(db, job.id)

    response = client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )
    assert response.status_code == 403


def test_compare_files_first_not_found(admin_client, db):
    job = _make_job(db)
    ef_b = _make_file(db, job.id)

    response = admin_client.post(
        "/files/compare",
        json={"file_id_a": 9999, "file_id_b": ef_b.id},
    )
    assert response.status_code == 404


def test_compare_files_second_not_found(admin_client, db):
    job = _make_job(db)
    ef_a = _make_file(db, job.id)

    response = admin_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": 9999},
    )
    assert response.status_code == 404


def test_compare_files_creates_audit_log(admin_client, db):
    """A FILE_COMPARE audit entry is written."""
    from app.models.audit import AuditLog

    job = _make_job(db)
    ef_a = _make_file(db, job.id)
    ef_b = _make_file(db, job.id)

    admin_client.post(
        "/files/compare",
        json={"file_id_a": ef_a.id, "file_id_b": ef_b.id},
    )

    entry = (
        db.query(AuditLog).filter(AuditLog.action == "FILE_COMPARE").first()
    )
    assert entry is not None
    assert entry.details["file_id_a"] == ef_a.id
    assert entry.details["file_id_b"] == ef_b.id
