"""Tests for issue #63 — missing configuration settings.

Covers:
- New Settings fields have correct defaults.
- Audit log retention cleanup purges old records and respects retention_days=0.
- Per-file copy timeout enforcement marks timed-out files as TIMEOUT, job continues.
- LdapGroupRoleResolver stores LDAP connection parameters.
- USB discovery interval setting is present and usable.
- TLS settings are present with None defaults.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.auth_providers import LdapGroupRoleResolver, get_role_resolver
from app.config import Settings
from app.utils.password_policy import DEFAULT_PASSWORD_POLICY_VALUES
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

    def test_callback_default_url_default(self):
        s = Settings(database_url="sqlite://")
        assert s.callback_default_url is None

    def test_callback_hmac_secret_default(self):
        s = Settings(database_url="sqlite://")
        assert s.callback_hmac_secret is None

    def test_callback_proxy_url_default(self):
        s = Settings(database_url="sqlite://")
        assert s.callback_proxy_url is None

    def test_callback_payload_fields_default(self):
        s = Settings(database_url="sqlite://")
        assert s.callback_payload_fields is None

    def test_callback_payload_field_map_default(self):
        s = Settings(database_url="sqlite://")
        assert s.callback_payload_field_map is None

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

    def test_copy_chunk_size_bytes_default(self):
        s = Settings(database_url="sqlite://")
        assert s.copy_chunk_size_bytes == 1_048_576

    def test_copy_default_thread_count_default(self):
        s = Settings(database_url="sqlite://")
        assert s.copy_default_thread_count == 4

    def test_copy_default_max_retries_default(self):
        s = Settings(database_url="sqlite://")
        assert s.copy_default_max_retries == 3

    def test_copy_default_retry_delay_seconds_default(self):
        s = Settings(database_url="sqlite://")
        assert s.copy_default_retry_delay_seconds == 1.0

    def test_subprocess_timeout_seconds_default(self):
        s = Settings(database_url="sqlite://")
        assert s.subprocess_timeout_seconds == 30

    def test_drive_format_timeout_seconds_default(self):
        s = Settings(database_url="sqlite://")
        assert s.drive_format_timeout_seconds == 900

    def test_drive_mount_timeout_seconds_default(self):
        s = Settings(database_url="sqlite://")
        assert s.drive_mount_timeout_seconds == 120

    def test_nfs_client_version_default(self):
        s = Settings(database_url="sqlite://")
        assert s.nfs_client_version == "4.1"

    def test_sync_binary_path_default(self):
        s = Settings(database_url="sqlite://")
        assert s.sync_binary_path == "/bin/sync"

    def test_umount_binary_path_default(self):
        s = Settings(database_url="sqlite://")
        assert s.umount_binary_path == "/bin/umount"

    def test_procfs_mounts_path_default(self):
        s = Settings(database_url="sqlite://")
        assert s.procfs_mounts_path == "/proc/mounts"

    def test_sysfs_usb_devices_path_default(self):
        s = Settings(database_url="sqlite://")
        assert s.sysfs_usb_devices_path == "/sys/bus/usb/devices"

    def test_sysfs_block_path_default(self):
        s = Settings(database_url="sqlite://")
        assert s.sysfs_block_path == "/sys/block"

    def test_audit_log_default_limit_default(self):
        s = Settings(database_url="sqlite://")
        assert s.audit_log_default_limit == 100

    def test_audit_log_max_limit_default(self):
        s = Settings(database_url="sqlite://")
        assert s.audit_log_max_limit == 1000

    def test_db_pool_size_default(self):
        s = Settings(database_url="sqlite://")
        assert s.db_pool_size == 5

    def test_db_pool_max_overflow_default(self):
        s = Settings(database_url="sqlite://")
        assert s.db_pool_max_overflow == 10

    def test_db_pool_recycle_seconds_default(self):
        s = Settings(database_url="sqlite://")
        assert s.db_pool_recycle_seconds == -1

    def test_startup_analysis_batch_size_default(self):
        s = Settings(database_url="sqlite://")
        assert s.startup_analysis_batch_size == 500

    def test_mkfs_exfat_cluster_size_default(self):
        s = Settings(database_url="sqlite://")
        assert s.mkfs_exfat_cluster_size == "4K"

    def test_startup_analysis_batch_size_rejects_values_above_maximum(self):
        with pytest.raises(ValidationError):
            Settings(database_url="sqlite://", startup_analysis_batch_size=5001)

    def test_oidc_allowed_algorithms_default(self):
        s = Settings(database_url="sqlite://")
        assert s.oidc_allowed_algorithms == ["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"]

    def test_oidc_discovery_timeout_seconds_default(self):
        s = Settings(database_url="sqlite://")
        assert s.oidc_discovery_timeout_seconds == 10

    def test_api_contact_name_default(self):
        s = Settings(database_url="sqlite://")
        assert s.api_contact_name == "ECUBE Support"

    def test_api_contact_email_default(self):
        s = Settings(database_url="sqlite://")
        assert s.api_contact_email == "support@ecube.local"

    def test_cors_allowed_origins_default(self):
        s = Settings(database_url="sqlite://")
        assert s.cors_allowed_origins == []

    def test_cors_allowed_origins_from_env(self):
        env = {"CORS_ALLOWED_ORIGINS": '["http://localhost:5173","https://example.com"]'}
        with patch.dict("os.environ", env):
            s = Settings(database_url="sqlite://")
        assert s.cors_allowed_origins == [
            "http://localhost:5173",
            "https://example.com",
        ]

    def test_trust_proxy_headers_default(self):
        s = Settings(database_url="sqlite://")
        assert s.trust_proxy_headers is False

    def test_api_root_path_default(self):
        s = Settings(database_url="sqlite://")
        assert s.api_root_path == ""

    def test_api_root_path_from_env(self):
        with patch.dict("os.environ", {"API_ROOT_PATH": "/api"}):
            s = Settings(database_url="sqlite://")
        assert s.api_root_path == "/api"

    def test_pam_service_name_default(self):
        s = Settings(database_url="sqlite://")
        assert s.pam_service_name == "ecube"

    def test_pam_fallback_services_default(self):
        s = Settings(database_url="sqlite://")
        assert s.pam_fallback_services == []

    def test_serve_frontend_path_default_empty(self):
        s = Settings(database_url="sqlite://")
        assert s.serve_frontend_path == ""

    def test_serve_frontend_path_absolute(self):
        s = Settings(database_url="sqlite://", serve_frontend_path="/opt/ecube/www")
        assert s.serve_frontend_path == "/opt/ecube/www"

    def test_serve_frontend_path_normalized(self):
        s = Settings(database_url="sqlite://", serve_frontend_path="/opt/ecube/www/")
        assert s.serve_frontend_path == "/opt/ecube/www"

    def test_serve_frontend_path_normalizes_dotdot(self):
        s = Settings(database_url="sqlite://", serve_frontend_path="/opt/ecube/../ecube/www")
        assert s.serve_frontend_path == "/opt/ecube/www"

    def test_serve_frontend_path_blank_treated_as_empty(self):
        with patch.dict("os.environ", {"SERVE_FRONTEND_PATH": "  "}):
            s = Settings(database_url="sqlite://")
        assert s.serve_frontend_path == ""

    def test_serve_frontend_path_from_env(self):
        with patch.dict("os.environ", {"SERVE_FRONTEND_PATH": "/srv/ecube/www"}):
            s = Settings(database_url="sqlite://")
        assert s.serve_frontend_path == "/srv/ecube/www"

    def test_serve_frontend_path_relative_rejected(self):
        with pytest.raises(ValueError, match="absolute path"):
            Settings(database_url="sqlite://", serve_frontend_path="relative/path")

    def test_serve_frontend_path_relative_from_env_rejected(self):
        with pytest.raises(ValueError, match="absolute path"):
            with patch.dict("os.environ", {"SERVE_FRONTEND_PATH": "relative/path"}):
                Settings(database_url="sqlite://")

    def test_serve_frontend_path_root_rejected(self):
        with pytest.raises(ValueError, match="system root"):
            Settings(database_url="sqlite://", serve_frontend_path="/")


class TestDemoRuntimeBehavior:
    """Demo behavior is driven by runtime environment values only."""

    def test_demo_runtime_helpers_use_env_values_only(self):
        s = Settings(
            database_url="sqlite://",
            demo_mode=True,
            demo_login_message="Use the shared demo accounts below.",
            demo_shared_password="Demo#123456",
            demo_accounts=[{"username": "demo_admin", "label": "Admin demo", "description": "Guided walkthrough"}],
            demo_disable_password_change=False,
        )

        assert s.is_demo_mode_enabled() is True
        assert s.get_demo_login_message() == "Use the shared demo accounts below."
        assert s.get_demo_shared_password() == "Demo#123456"
        assert s.get_demo_accounts() == [
            {"username": "demo_admin", "label": "Admin demo", "description": "Guided walkthrough"}
        ]
        assert s.get_demo_disable_password_change() is False

    def test_demo_runtime_helpers_fall_back_to_built_in_defaults(self):
        s = Settings(
            database_url="sqlite://",
            demo_mode=True,
            demo_login_message="",
            demo_shared_password="",
            demo_accounts=[],
        )

        assert s.is_demo_mode_enabled() is True
        assert s.get_demo_login_message() == "Use the shared demo accounts below."
        generated_password = s.get_demo_shared_password()
        assert len(generated_password) >= DEFAULT_PASSWORD_POLICY_VALUES["minlen"]
        assert any(ch.islower() for ch in generated_password)
        assert any(ch.isupper() for ch in generated_password)
        assert any(ch.isdigit() for ch in generated_password)
        assert s.get_demo_accounts() == [
            {
                "username": "demo_admin",
                "label": "Admin demo",
                "description": "Full demo access for guided product walkthroughs.",
                "roles": ["admin"],
            },
            {
                "username": "demo_manager",
                "label": "Manager demo",
                "description": "Drive lifecycle, mounts, and job visibility.",
                "roles": ["manager"],
            },
            {
                "username": "demo_processor",
                "label": "Processor demo",
                "description": "Create and review sanitized export activity.",
                "roles": ["processor"],
            },
            {
                "username": "demo_auditor",
                "label": "Auditor demo",
                "description": "Read-only audit and verification review.",
                "roles": ["auditor"],
            },
        ]
        assert s.get_demo_disable_password_change() is True

    def test_demo_runtime_generated_shared_password_is_not_deterministic(self):
        first = Settings(
            database_url="sqlite://",
            demo_mode=True,
            demo_shared_password="",
            demo_accounts=[],
        ).get_demo_shared_password()

        second = Settings(
            database_url="sqlite://",
            demo_mode=True,
            demo_shared_password="",
            demo_accounts=[],
        ).get_demo_shared_password()

        assert first != second
        assert len(first) >= DEFAULT_PASSWORD_POLICY_VALUES["minlen"]
        assert len(second) >= DEFAULT_PASSWORD_POLICY_VALUES["minlen"]

    def test_demo_runtime_shared_password_follows_active_password_policy(self, tmp_path):
        policy_path = tmp_path / "pwquality.conf"
        policy_path.write_text(
            "minlen = 18\nminclass = 4\nmaxrepeat = 1\nmaxsequence = 2\nmaxclassrepeat = 1\n",
            encoding="utf-8",
        )

        s = Settings(
            database_url="sqlite://",
            demo_mode=True,
            demo_shared_password="",
            pwquality_conf_path=str(policy_path),
        )

        generated_password = s.get_demo_shared_password()

        assert len(generated_password) >= 18
        assert any(ch.islower() for ch in generated_password)
        assert any(ch.isupper() for ch in generated_password)
        assert any(ch.isdigit() for ch in generated_password)
        assert any(not ch.isalnum() for ch in generated_password)

    def test_demo_runtime_generated_shared_password_is_stable_within_one_settings_instance(self):
        s = Settings(
            database_url="sqlite://",
            demo_mode=True,
            demo_shared_password="",
            demo_accounts=[],
        )

        first = s.get_demo_shared_password()
        second = s.get_demo_shared_password()

        assert first == second

    def test_serve_frontend_path_system_dir_rejected(self):
        for dangerous in ("/etc", "/var", "/tmp", "/usr", "/home"):
            with pytest.raises(ValueError, match="system root"):
                Settings(database_url="sqlite://", serve_frontend_path=dangerous)

    def test_serve_frontend_path_system_dir_trailing_slash_rejected(self):
        """normpath strips trailing slashes, so '/etc/' should also be caught."""
        with pytest.raises(ValueError, match="system root"):
            Settings(database_url="sqlite://", serve_frontend_path="/etc/")

    def test_serve_frontend_path_under_system_dir_allowed(self):
        """Subdirectories of system roots are fine (e.g. /opt/ecube/www)."""
        s = Settings(database_url="sqlite://", serve_frontend_path="/opt/ecube/www")
        assert s.serve_frontend_path == "/opt/ecube/www"


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
    def test_timeout_marks_file_timeout_job_continues(self, db, tmp_path):
        """A per-file timeout marks the file TIMEOUT and the job continues (COMPLETED, not FAILED)."""
        from app.services import copy_engine

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "a.txt").write_bytes(b"aaa")
        (source_dir / "b.txt").write_bytes(b"bbb")

        target_dir = tmp_path / "target"
        target_dir.mkdir()

        job = _make_job(db, str(source_dir), target_mount_path=str(target_dir))

        def _always_timeout(*_args, **_kwargs):
            raise TimeoutError("File copy timed out after 1s")

        with patch("app.services.copy_engine.SessionLocal", _session_factory(db)):
            with patch("app.services.copy_engine.settings") as mock_settings:
                mock_settings.copy_job_timeout = 1  # 1 second timeout
                mock_settings.startup_analysis_batch_size = 500
                mock_settings.copy_chunk_size_bytes = 1_048_576
                mock_settings.copy_default_max_retries = 3
                mock_settings.copy_default_retry_delay_seconds = 1.0
                mock_settings.copy_default_thread_count = 4
                with patch("app.services.copy_engine.copy_file", side_effect=_always_timeout):
                    copy_engine.run_copy_job(job.id)

        db.expire_all()
        db.refresh(job)
        # Job should be COMPLETED (not FAILED) even though files timed out
        assert job.status == JobStatus.COMPLETED

        files = db.query(ExportFile).filter(ExportFile.job_id == job.id).all()
        assert files
        assert any(f.status == FileStatus.TIMEOUT for f in files), "At least one file should be marked TIMEOUT"
        assert any((f.error_message or "") == "Operation timed out" for f in files)

        # Timeout should emit FILE_COPY_TIMEOUT audit record, not JOB_TIMEOUT
        timeout_entries = db.query(AuditLog).filter(AuditLog.action == "FILE_COPY_TIMEOUT").all()
        assert timeout_entries, "Should have FILE_COPY_TIMEOUT audit entries"
        
        # Per-file timeout should not emit the legacy whole-job timeout audit record.
        job_timeout_entries = db.query(AuditLog).filter(AuditLog.action == "JOB_TIMEOUT").all()
        assert job_timeout_entries == []

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
                mock_settings.startup_analysis_batch_size = 500
                mock_settings.copy_chunk_size_bytes = 1_048_576
                mock_settings.copy_default_max_retries = 3
                mock_settings.copy_default_retry_delay_seconds = 1.0
                mock_settings.copy_default_thread_count = 4
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
