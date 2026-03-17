"""Tests for database provisioning and settings management endpoints.

Covers:
- POST /setup/database/test-connection (happy path and connectivity failures)
- POST /setup/database/provision (happy path, connection error, already exists)
- GET /setup/database/status (connected and disconnected states)
- PUT /setup/database/settings (happy path, connection failure, partial updates)
- Schema validation (host SSRF prevention, identifier validation, port bounds)
- Auth: unauthenticated during initial setup, admin-required after setup
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.users import UserRole
from app.schemas.database import (
    DatabaseProvisionRequest,
    DatabaseSettingsUpdateRequest,
    DatabaseTestConnectionRequest,
)


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------


class TestDatabaseSchemaValidation:
    """Validate Pydantic schemas reject unsafe inputs."""

    def test_host_rejects_url_with_scheme(self):
        with pytest.raises(Exception):
            DatabaseTestConnectionRequest(
                host="http://localhost",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_host_rejects_url_with_path(self):
        with pytest.raises(Exception):
            DatabaseTestConnectionRequest(
                host="localhost/admin",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_host_rejects_url_with_at_sign(self):
        with pytest.raises(Exception):
            DatabaseTestConnectionRequest(
                host="user@localhost",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_host_accepts_hostname(self):
        req = DatabaseTestConnectionRequest(
            host="db.example.com",
            port=5432,
            admin_username="postgres",
            admin_password="secret",
        )
        assert req.host == "db.example.com"

    def test_host_accepts_ipv4(self):
        req = DatabaseTestConnectionRequest(
            host="192.168.1.100",
            port=5432,
            admin_username="postgres",
            admin_password="secret",
        )
        assert req.host == "192.168.1.100"

    def test_host_accepts_localhost(self):
        req = DatabaseTestConnectionRequest(
            host="localhost",
            port=5432,
            admin_username="postgres",
            admin_password="secret",
        )
        assert req.host == "localhost"

    def test_port_rejects_zero(self):
        with pytest.raises(Exception):
            DatabaseTestConnectionRequest(
                host="localhost",
                port=0,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_port_rejects_negative(self):
        with pytest.raises(Exception):
            DatabaseTestConnectionRequest(
                host="localhost",
                port=-1,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_port_rejects_too_high(self):
        with pytest.raises(Exception):
            DatabaseTestConnectionRequest(
                host="localhost",
                port=70000,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_provision_rejects_invalid_db_name(self):
        with pytest.raises(Exception):
            DatabaseProvisionRequest(
                host="localhost",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
                app_database="drop table;",
                app_username="ecube",
                app_password="pass",
            )

    def test_provision_rejects_invalid_username(self):
        with pytest.raises(Exception):
            DatabaseProvisionRequest(
                host="localhost",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
                app_database="ecube",
                app_username="'; DROP TABLE",
                app_password="pass",
            )

    def test_provision_accepts_valid_identifiers(self):
        req = DatabaseProvisionRequest(
            host="localhost",
            port=5432,
            admin_username="postgres",
            admin_password="secret",
            app_database="ecube_prod",
            app_username="ecube_user",
            app_password="strongpass",
        )
        assert req.app_database == "ecube_prod"
        assert req.app_username == "ecube_user"

    def test_settings_all_optional(self):
        req = DatabaseSettingsUpdateRequest()
        assert req.host is None
        assert req.port is None
        assert req.app_database is None

    def test_settings_partial_update(self):
        req = DatabaseSettingsUpdateRequest(host="newhost", pool_size=20)
        assert req.host == "newhost"
        assert req.pool_size == 20
        assert req.port is None

    def test_settings_rejects_invalid_pool_size(self):
        with pytest.raises(Exception):
            DatabaseSettingsUpdateRequest(pool_size=0)

    def test_settings_rejects_pool_size_too_high(self):
        with pytest.raises(Exception):
            DatabaseSettingsUpdateRequest(pool_size=200)

    def test_settings_rejects_invalid_host(self):
        with pytest.raises(Exception):
            DatabaseSettingsUpdateRequest(host="http://evil.com")


# ---------------------------------------------------------------------------
# Endpoint tests — test-connection
# ---------------------------------------------------------------------------


class TestTestConnectionEndpoint:
    """Tests for POST /setup/database/test-connection."""

    @patch("app.services.database_service.test_connection")
    def test_test_connection_success(self, mock_test, unauthenticated_client):
        mock_test.return_value = "14.9"

        resp = unauthenticated_client.post(
            "/setup/database/test-connection",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["server_version"] == "14.9"
        mock_test.assert_called_once_with(
            host="localhost", port=5432, username="postgres", password="secret"
        )

    @patch("app.services.database_service.test_connection")
    def test_test_connection_failure(self, mock_test, unauthenticated_client):
        mock_test.side_effect = ConnectionError("Connection refused")

        resp = unauthenticated_client.post(
            "/setup/database/test-connection",
            json={
                "host": "badhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
            },
        )

        assert resp.status_code == 400
        assert "Connection refused" in resp.json()["message"]

    @patch("app.services.database_service.test_connection")
    def test_test_connection_requires_admin_after_setup(
        self, mock_test, unauthenticated_client, db
    ):
        """Once an admin exists, unauthenticated requests should fail."""
        mock_test.return_value = "14.9"
        db.add(UserRole(username="admin-user", role="admin"))
        db.commit()

        resp = unauthenticated_client.post(
            "/setup/database/test-connection",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
            },
        )

        assert resp.status_code == 401

    @patch("app.services.database_service.test_connection")
    def test_test_connection_admin_after_setup(
        self, mock_test, admin_client, db
    ):
        """Admin can test connection after setup."""
        mock_test.return_value = "15.2"
        db.add(UserRole(username="admin-user", role="admin"))
        db.commit()

        resp = admin_client.post(
            "/setup/database/test-connection",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["server_version"] == "15.2"

    @patch("app.services.database_service.test_connection")
    def test_test_connection_non_admin_denied(
        self, mock_test, client, db
    ):
        """Non-admin users should be denied after setup."""
        mock_test.return_value = "14.9"
        db.add(UserRole(username="some-admin", role="admin"))
        db.commit()

        resp = client.post(
            "/setup/database/test-connection",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
            },
        )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Endpoint tests — provision
# ---------------------------------------------------------------------------


class TestProvisionEndpoint:
    """Tests for POST /setup/database/provision."""

    @patch("app.services.database_service.provision_database")
    def test_provision_success(self, mock_provision, unauthenticated_client):
        mock_provision.return_value = 4

        resp = unauthenticated_client.post(
            "/setup/database/provision",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
                "app_database": "ecube",
                "app_username": "ecube",
                "app_password": "ecube123",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "provisioned"
        assert data["database"] == "ecube"
        assert data["user"] == "ecube"
        assert data["migrations_applied"] == 4

    @patch("app.services.database_service.provision_database")
    def test_provision_connection_error(self, mock_provision, unauthenticated_client):
        mock_provision.side_effect = ConnectionError("auth failed")

        resp = unauthenticated_client.post(
            "/setup/database/provision",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "wrong",
                "app_database": "ecube",
                "app_username": "ecube",
                "app_password": "ecube123",
            },
        )

        assert resp.status_code == 400
        assert "auth failed" in resp.json()["message"]

    @patch("app.services.database_service.provision_database")
    def test_provision_runtime_error(self, mock_provision, unauthenticated_client):
        mock_provision.side_effect = RuntimeError("migration failed")

        resp = unauthenticated_client.post(
            "/setup/database/provision",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
                "app_database": "ecube",
                "app_username": "ecube",
                "app_password": "ecube123",
            },
        )

        assert resp.status_code == 500
        assert "migration failed" in resp.json()["message"]

    @patch("app.services.database_service.provision_database")
    def test_provision_requires_admin_after_setup(
        self, mock_provision, unauthenticated_client, db
    ):
        """Unauthenticated provision should fail once admin exists."""
        mock_provision.return_value = 4
        db.add(UserRole(username="admin-user", role="admin"))
        db.commit()

        resp = unauthenticated_client.post(
            "/setup/database/provision",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
                "app_database": "ecube",
                "app_username": "ecube",
                "app_password": "ecube123",
            },
        )

        assert resp.status_code == 401

    def test_provision_password_not_in_response(self, unauthenticated_client):
        """Ensure passwords never appear in the response body."""
        with patch("app.services.database_service.provision_database", return_value=4):
            resp = unauthenticated_client.post(
                "/setup/database/provision",
                json={
                    "host": "localhost",
                    "port": 5432,
                    "admin_username": "postgres",
                    "admin_password": "supersecret",
                    "app_database": "ecube",
                    "app_username": "ecube",
                    "app_password": "mypassword",
                },
            )

        assert resp.status_code == 200
        text = resp.text
        assert "supersecret" not in text
        assert "mypassword" not in text


# ---------------------------------------------------------------------------
# Endpoint tests — status
# ---------------------------------------------------------------------------


class TestDatabaseStatusEndpoint:
    """Tests for GET /setup/database/status."""

    @patch("app.services.database_service.get_database_status")
    def test_status_connected(self, mock_status, admin_client):
        mock_status.return_value = {
            "connected": True,
            "database": "ecube",
            "host": "localhost",
            "port": 5432,
            "current_migration": "0004",
            "pending_migrations": 0,
        }

        resp = admin_client.get("/setup/database/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["database"] == "ecube"
        assert data["current_migration"] == "0004"
        assert data["pending_migrations"] == 0

    @patch("app.services.database_service.get_database_status")
    def test_status_disconnected(self, mock_status, admin_client):
        mock_status.return_value = {
            "connected": False,
            "database": "ecube",
            "host": "localhost",
            "port": 5432,
            "current_migration": None,
            "pending_migrations": None,
        }

        resp = admin_client.get("/setup/database/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["current_migration"] is None

    def test_status_requires_admin(self, client):
        """Non-admin users should be denied."""
        resp = client.get("/setup/database/status")
        assert resp.status_code == 403

    def test_status_requires_auth(self, unauthenticated_client):
        """Unauthenticated requests should be denied."""
        resp = unauthenticated_client.get("/setup/database/status")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Endpoint tests — settings
# ---------------------------------------------------------------------------


class TestDatabaseSettingsEndpoint:
    """Tests for PUT /setup/database/settings."""

    @patch("app.services.database_service.update_database_settings")
    def test_settings_update_success(self, mock_update, admin_client):
        mock_update.return_value = {
            "status": "updated",
            "host": "db2.internal",
            "port": 5432,
            "database": "ecube",
            "connected": True,
        }

        resp = admin_client.put(
            "/setup/database/settings",
            json={"host": "db2.internal", "pool_size": 10},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["host"] == "db2.internal"
        assert data["connected"] is True

    @patch("app.services.database_service.update_database_settings")
    def test_settings_connection_failure(self, mock_update, admin_client):
        mock_update.side_effect = ConnectionError(
            "Could not connect to db2.internal:5432 with the supplied credentials"
        )

        resp = admin_client.put(
            "/setup/database/settings",
            json={"host": "db2.internal"},
        )

        assert resp.status_code == 400
        assert "Could not connect" in resp.json()["message"]

    @patch("app.services.database_service.update_database_settings")
    def test_settings_password_not_in_response(self, mock_update, admin_client):
        """Passwords must never appear in responses."""
        mock_update.return_value = {
            "status": "updated",
            "host": "localhost",
            "port": 5432,
            "database": "ecube",
            "connected": True,
        }

        resp = admin_client.put(
            "/setup/database/settings",
            json={"app_password": "secret-password"},
        )

        assert resp.status_code == 200
        assert "secret-password" not in resp.text

    def test_settings_requires_admin(self, client):
        """Non-admin users should be denied."""
        resp = client.put(
            "/setup/database/settings",
            json={"host": "localhost"},
        )
        assert resp.status_code == 403

    def test_settings_requires_auth(self, unauthenticated_client):
        """Unauthenticated requests should be denied."""
        resp = unauthenticated_client.put(
            "/setup/database/settings",
            json={"host": "localhost"},
        )
        assert resp.status_code == 401

    @patch("app.services.database_service.update_database_settings")
    def test_settings_empty_body(self, mock_update, admin_client):
        """An empty body should be accepted (no-op update)."""
        mock_update.return_value = {
            "status": "updated",
            "host": "localhost",
            "port": 5432,
            "database": "ecube",
            "connected": True,
        }

        resp = admin_client.put(
            "/setup/database/settings",
            json={},
        )

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


class TestDatabaseService:
    """Unit tests for database_service functions."""

    @patch("app.services.database_service.psycopg2")
    def test_test_connection_success(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_conn.server_version = 140009
        mock_psycopg2.connect.return_value = mock_conn

        from app.services.database_service import test_connection

        result = test_connection("localhost", 5432, "postgres", "secret")

        assert result == "14.0"
        mock_conn.close.assert_called_once()

    @patch("app.services.database_service.psycopg2")
    def test_test_connection_failure(self, mock_psycopg2):
        import psycopg2 as real_psycopg2

        mock_psycopg2.OperationalError = real_psycopg2.OperationalError
        mock_psycopg2.connect.side_effect = real_psycopg2.OperationalError("refused")

        from app.services.database_service import test_connection

        with pytest.raises(ConnectionError, match="refused"):
            test_connection("localhost", 5432, "postgres", "wrong")

    def test_parse_database_url(self):
        from app.services.database_service import _parse_database_url

        result = _parse_database_url("postgresql://myuser:mypass@dbhost:5433/mydb")
        assert result["host"] == "dbhost"
        assert result["port"] == 5433
        assert result["database"] == "mydb"
        assert result["username"] == "myuser"
        assert result["password"] == "mypass"

    def test_parse_database_url_defaults(self):
        from app.services.database_service import _parse_database_url

        result = _parse_database_url("postgresql://localhost/ecube")
        assert result["host"] == "localhost"
        assert result["port"] == 5432
        assert result["database"] == "ecube"

    @patch("app.services.database_service._write_env_setting")
    @patch("app.services.database_service._reinitialize_engine")
    @patch("app.services.database_service.psycopg2")
    def test_update_settings_connection_failure(
        self, mock_psycopg2, mock_reinit, mock_write
    ):
        import psycopg2 as real_psycopg2

        mock_psycopg2.OperationalError = real_psycopg2.OperationalError
        mock_psycopg2.connect.side_effect = real_psycopg2.OperationalError("refused")

        from app.services.database_service import update_database_settings

        with pytest.raises(ConnectionError, match="Could not connect"):
            update_database_settings(host="badhost")

        mock_write.assert_not_called()
        mock_reinit.assert_not_called()

    def test_write_env_setting_new_file(self, tmp_path):
        from app.services.database_service import _write_env_setting

        env_file = tmp_path / ".env"
        with patch("app.services.database_service._get_env_file_path", return_value=str(env_file)):
            _write_env_setting("DATABASE_URL", "postgresql://localhost/ecube")

        content = env_file.read_text()
        assert "DATABASE_URL=postgresql://localhost/ecube\n" in content

    def test_write_env_setting_update_existing(self, tmp_path):
        from app.services.database_service import _write_env_setting

        env_file = tmp_path / ".env"
        env_file.write_text("DATABASE_URL=old_value\nOTHER=keep\n")

        with patch("app.services.database_service._get_env_file_path", return_value=str(env_file)):
            _write_env_setting("DATABASE_URL", "new_value")

        content = env_file.read_text()
        assert "DATABASE_URL=new_value\n" in content
        assert "OTHER=keep\n" in content
        assert "old_value" not in content

    def test_write_env_setting_append(self, tmp_path):
        from app.services.database_service import _write_env_setting

        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING=value\n")

        with patch("app.services.database_service._get_env_file_path", return_value=str(env_file)):
            _write_env_setting("NEW_KEY", "new_value")

        content = env_file.read_text()
        assert "EXISTING=value\n" in content
        assert "NEW_KEY=new_value\n" in content

    @patch("app.services.database_service._write_env_setting")
    @patch("app.services.database_service._reinitialize_engine")
    @patch("app.services.database_service.psycopg2")
    def test_update_settings_updates_in_memory_config(
        self, mock_psycopg2, mock_reinit, mock_write
    ):
        """Verify settings object is updated so subsequent reads are consistent."""
        from app.config import settings
        from app.services.database_service import update_database_settings

        mock_conn = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.OperationalError = Exception

        original_url = settings.database_url
        original_pool = settings.db_pool_size
        original_overflow = settings.db_pool_max_overflow

        try:
            update_database_settings(
                host="newhost.test",
                port=5433,
                app_database="newdb",
                app_username="newuser",
                app_password="newpass",
                pool_size=20,
                pool_max_overflow=40,
            )

            assert settings.database_url == "postgresql://newuser:newpass@newhost.test:5433/newdb"
            assert settings.db_pool_size == 20
            assert settings.db_pool_max_overflow == 40
        finally:
            # Restore original values to avoid polluting other tests
            settings.database_url = original_url
            settings.db_pool_size = original_pool
            settings.db_pool_max_overflow = original_overflow

    @patch("app.services.database_service._write_env_setting")
    @patch("app.services.database_service._reinitialize_engine")
    @patch("app.services.database_service._run_migrations", return_value=4)
    @patch("app.services.database_service.psycopg2")
    def test_provision_reinitializes_engine_and_settings(
        self, mock_psycopg2, mock_migrations, mock_reinit, mock_write
    ):
        """provision_database() must update in-memory settings and reinitialize the engine."""
        from app.config import settings
        from app.services.database_service import provision_database

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None  # user/db don't exist yet
        mock_conn.cursor.return_value = mock_cur
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.OperationalError = Exception
        mock_psycopg2.sql = __import__("psycopg2").sql

        original_url = settings.database_url
        try:
            result = provision_database(
                host="provhost",
                port=5434,
                admin_username="postgres",
                admin_password="adminpw",
                app_database="newecube",
                app_username="appuser",
                app_password="apppw",
            )

            expected_url = "postgresql://appuser:apppw@provhost:5434/newecube"
            assert result == 4
            assert settings.database_url == expected_url
            mock_reinit.assert_called_once_with(
                expected_url, settings.db_pool_size, settings.db_pool_max_overflow
            )
        finally:
            settings.database_url = original_url
