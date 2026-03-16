"""Tests for issue #63 — missing configuration settings.

Covers:
- New Settings fields have correct defaults.
- Audit log retention cleanup purges old records and respects retention_days=0.
- Copy job timeout enforcement marks job FAILED on timeout.
- LdapGroupRoleResolver stores LDAP connection parameters.
- USB discovery interval setting is present and usable.
- TLS settings are present with None defaults.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.auth_providers import LdapGroupRoleResolver, get_role_resolver
from app.config import Settings
from app.models.audit import AuditLog
from app.models.jobs import ExportFile, ExportJob, FileStatus, JobStatus
from app.repositories.audit_repository import AuditRepository
from app.services.audit_service import purge_expired_audit_logs


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    """All new settings have documented defaults."""

    def test_tls_certfile_default(self):
        s = Settings(database_url="sqlite://")
        assert s.tls_certfile == "/opt/ecube/certs/cert.pem"

    def test_tls_keyfile_default(self):
        s = Settings(database_url="sqlite://")
        assert s.tls_keyfile == "/opt/ecube/certs/key.pem"

    def test_audit_log_retention_days_default(self):
        s = Settings(database_url="sqlite://")
        assert s.audit_log_retention_days == 365

    def test_copy_job_timeout_default(self):
        s = Settings(database_url="sqlite://")
        assert s.copy_job_timeout == 3600

    def test_usb_discovery_interval_default(self):
        s = Settings(database_url="sqlite://")
        assert s.usb_discovery_interval == 30

    def test_ldap_server_default(self):
        s = Settings(database_url="sqlite://")
        assert s.ldap_server is None

    def test_ldap_bind_dn_default(self):
        s = Settings(database_url="sqlite://")
        assert s.ldap_bind_dn is None

    def test_ldap_bind_password_default(self):
        s = Settings(database_url="sqlite://")
        assert s.ldap_bind_password is None

    def test_ldap_base_dn_default(self):
        s = Settings(database_url="sqlite://")
        assert s.ldap_base_dn is None


# ---------------------------------------------------------------------------
# Audit log retention cleanup
# ---------------------------------------------------------------------------


class TestAuditLogRetention:
    def test_purge_deletes_old_records(self, db):
        """Records older than retention_days are deleted."""
        old_time = datetime.now(timezone.utc) - timedelta(days=400)
        recent_time = datetime.now(timezone.utc) - timedelta(days=10)

        db.add(AuditLog(action="OLD_EVENT", timestamp=old_time))
        db.add(AuditLog(action="RECENT_EVENT", timestamp=recent_time))
        db.commit()

        count = purge_expired_audit_logs(db, retention_days=365)

        assert count == 1
        remaining = db.query(AuditLog).all()
        assert len(remaining) == 1
        assert remaining[0].action == "RECENT_EVENT"

    def test_purge_zero_retention_skips_cleanup(self, db):
        """retention_days=0 disables cleanup entirely."""
        old_time = datetime.now(timezone.utc) - timedelta(days=9999)
        db.add(AuditLog(action="ANCIENT", timestamp=old_time))
        db.commit()

        count = purge_expired_audit_logs(db, retention_days=0)

        assert count == 0
        assert db.query(AuditLog).count() == 1

    def test_purge_no_expired_records(self, db):
        """No records deleted when all are within retention window."""
        recent = datetime.now(timezone.utc) - timedelta(days=10)
        db.add(AuditLog(action="RECENT", timestamp=recent))
        db.commit()

        count = purge_expired_audit_logs(db, retention_days=365)
        assert count == 0

    def test_delete_older_than_repository_method(self, db):
        """AuditRepository.delete_older_than works correctly."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        old = datetime.now(timezone.utc) - timedelta(days=60)
        new = datetime.now(timezone.utc)

        db.add(AuditLog(action="OLD", timestamp=old))
        db.add(AuditLog(action="NEW", timestamp=new))
        db.commit()

        deleted = AuditRepository(db).delete_older_than(cutoff)
        assert deleted == 1
        assert db.query(AuditLog).count() == 1


# ---------------------------------------------------------------------------
# Copy job timeout
# ---------------------------------------------------------------------------


def _make_job(db, source_path, **kwargs):
    defaults = dict(
        project_id="PROJ-001",
        evidence_number="EV-001",
        source_path=source_path,
        thread_count=1,
        max_file_retries=0,
        retry_delay_seconds=0,
    )
    defaults.update(kwargs)
    job = ExportJob(**defaults)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _session_factory(db):
    class _NonClosing:
        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    return lambda: _NonClosing()


class TestCopyJobTimeout:
    def test_timeout_marks_job_failed(self, db, tmp_path):
        """Job is marked FAILED when copy_job_timeout is exceeded."""
        from app.services import copy_engine

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "a.txt").write_bytes(b"aaa")
        (source_dir / "b.txt").write_bytes(b"bbb")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

        # Simulate an already-elapsed monotonic clock by making time.monotonic
        # return a large offset after the first call.
        import time as _time

        real_monotonic = _time.monotonic
        call_count = 0

        def _fast_monotonic():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 0.0
            # After first call, return well past the timeout
            return 99999.0

        with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
            with patch("app.services.copy_engine.settings") as mock_settings:
                mock_settings.copy_job_timeout = 1  # 1 second timeout
                with patch("app.services.copy_engine.time") as mock_time:
                    mock_time.monotonic = _fast_monotonic
                    mock_time.sleep = _time.sleep
                    copy_engine.run_copy_job(job.id)

        db.expire_all()
        db.refresh(job)
        assert job.status == JobStatus.FAILED

        # Verify a JOB_TIMEOUT audit entry was created.
        timeout_entries = (
            db.query(AuditLog).filter(AuditLog.action == "JOB_TIMEOUT").all()
        )
        assert len(timeout_entries) == 1
        assert timeout_entries[0].details["timeout_seconds"] == 1

    def test_zero_timeout_disables_enforcement(self, db, tmp_path):
        """copy_job_timeout=0 disables timeout enforcement."""
        from app.services import copy_engine

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "file.txt").write_bytes(b"data")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

        with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
            with patch("app.services.copy_engine.settings") as mock_settings:
                mock_settings.copy_job_timeout = 0
                copy_engine.run_copy_job(job.id)

        db.expire_all()
        db.refresh(job)
        assert job.status == JobStatus.COMPLETED


# ---------------------------------------------------------------------------
# LDAP resolver with connection settings
# ---------------------------------------------------------------------------


class TestLdapResolverSettings:
    def test_ldap_resolver_stores_connection_params(self):
        resolver = LdapGroupRoleResolver(
            {"CN=Admins,DC=ex,DC=com": ["admin"]},
            ldap_server="ldap://ldap.example.com",
            ldap_bind_dn="CN=svc,DC=ex,DC=com",
            ldap_bind_password="secret",
            ldap_base_dn="DC=ex,DC=com",
        )
        assert resolver.ldap_server == "ldap://ldap.example.com"
        assert resolver.ldap_bind_dn == "CN=svc,DC=ex,DC=com"
        assert resolver.ldap_bind_password == "secret"
        assert resolver.ldap_base_dn == "DC=ex,DC=com"

    def test_ldap_resolver_still_resolves_roles(self):
        resolver = LdapGroupRoleResolver(
            {"CN=Admins,DC=ex,DC=com": ["admin"]},
            ldap_server="ldap://ldap.example.com",
        )
        assert resolver.resolve(["CN=Admins,DC=ex,DC=com"]) == ["admin"]
        assert resolver.resolve(["CN=Unknown,DC=ex,DC=com"]) == []

    def test_get_role_resolver_passes_ldap_settings(self):
        from app.config import settings

        get_role_resolver.cache_clear()
        try:
            with patch.object(settings, "role_resolver", "ldap"), \
                 patch.object(settings, "ldap_server", "ldap://test"), \
                 patch.object(settings, "ldap_bind_dn", "cn=bind"), \
                 patch.object(settings, "ldap_bind_password", "pw"), \
                 patch.object(settings, "ldap_base_dn", "dc=test"):
                resolver = get_role_resolver()
            assert isinstance(resolver, LdapGroupRoleResolver)
            assert resolver.ldap_server == "ldap://test"
            assert resolver.ldap_bind_dn == "cn=bind"
            assert resolver.ldap_bind_password == "pw"
            assert resolver.ldap_base_dn == "dc=test"
        finally:
            get_role_resolver.cache_clear()
