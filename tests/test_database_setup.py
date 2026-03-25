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

from pydantic import ValidationError

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
        with pytest.raises(ValidationError, match="host"):
            DatabaseTestConnectionRequest(
                host="http://localhost",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_host_rejects_url_with_path(self):
        with pytest.raises(ValidationError, match="host"):
            DatabaseTestConnectionRequest(
                host="localhost/admin",
                port=5432,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_host_rejects_url_with_at_sign(self):
        with pytest.raises(ValidationError, match="host"):
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
        with pytest.raises(ValidationError, match="port"):
            DatabaseTestConnectionRequest(
                host="localhost",
                port=0,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_port_rejects_negative(self):
        with pytest.raises(ValidationError, match="port"):
            DatabaseTestConnectionRequest(
                host="localhost",
                port=-1,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_port_rejects_too_high(self):
        with pytest.raises(ValidationError, match="port"):
            DatabaseTestConnectionRequest(
                host="localhost",
                port=70000,
                admin_username="postgres",
                admin_password="secret",
            )

    def test_provision_rejects_invalid_db_name(self):
        with pytest.raises(ValidationError, match="app_database"):
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
        with pytest.raises(ValidationError, match="app_username"):
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

    def test_settings_accepts_explicit_nulls_as_noop(self):
        """Explicit null values for known fields are schema-compliant."""
        req = DatabaseSettingsUpdateRequest(app_database=None)
        assert req.host is None
        assert req.app_database is None

    def test_settings_rejects_empty(self):
        with pytest.raises(ValidationError, match="At least one setting"):
            DatabaseSettingsUpdateRequest()

    def test_settings_partial_update(self):
        req = DatabaseSettingsUpdateRequest(host="newhost", pool_size=20)
        assert req.host == "newhost"
        assert req.pool_size == 20
        assert req.port is None

    def test_settings_rejects_invalid_pool_size(self):
        with pytest.raises(ValidationError, match="pool_size"):
            DatabaseSettingsUpdateRequest(pool_size=0)

    def test_settings_rejects_pool_size_too_high(self):
        with pytest.raises(ValidationError, match="pool_size"):
            DatabaseSettingsUpdateRequest(pool_size=200)

    def test_settings_rejects_invalid_host(self):
        with pytest.raises(ValidationError, match="host"):
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

        assert resp.status_code == 503
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

    @patch("app.services.database_service.is_database_provisioned", return_value=False)
    @patch("app.services.database_service.provision_database")
    def test_provision_success(self, mock_provision, mock_provisioned, unauthenticated_client):
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

    @patch("app.services.database_service.is_database_provisioned", return_value=False)
    @patch("app.services.database_service.provision_database")
    def test_provision_connection_error(self, mock_provision, mock_provisioned, unauthenticated_client):
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

        assert resp.status_code == 503
        assert "auth failed" in resp.json()["message"]

    @patch("app.services.database_service.is_database_provisioned", return_value=False)
    @patch("app.services.database_service.provision_database")
    def test_provision_runtime_error(self, mock_provision, mock_provisioned, unauthenticated_client):
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
        with patch("app.services.database_service.is_database_provisioned", return_value=False), \
             patch("app.services.database_service.provision_database", return_value=4):
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

    @patch("app.services.database_service.is_database_provisioned", return_value=True)
    def test_provision_blocked_when_already_provisioned(
        self, mock_provisioned, unauthenticated_client
    ):
        """Provisioning returns 409 when database is already provisioned."""
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

        assert resp.status_code == 409
        assert "already provisioned" in resp.json()["message"]

    @patch("app.services.database_service.provision_database", return_value=0)
    @patch("app.services.database_service.is_database_provisioned", return_value=True)
    def test_provision_force_overrides_guard(
        self, mock_provisioned, mock_provision, admin_client, db
    ):
        """Setting force=true allows re-provisioning (admin-only)."""
        from app.models.users import UserRole

        db.add(UserRole(username="admin-user", role="admin"))
        db.commit()

        resp = admin_client.post(
            "/setup/database/provision",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
                "app_database": "ecube",
                "app_username": "ecube",
                "app_password": "ecube123",
                "force": True,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "provisioned"

    @patch("app.services.database_service.is_database_provisioned", return_value=True)
    def test_provision_force_rejected_when_unauthenticated(
        self, mock_provisioned, unauthenticated_client
    ):
        """Unauthenticated callers cannot use force=true."""
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
                "force": True,
            },
        )

        assert resp.status_code == 403
        assert "force" in resp.json()["message"].lower()

    def test_provision_503_when_provisioning_state_unknown(
        self, unauthenticated_client
    ):
        """POST /provision returns 503 when DB is unreachable (fail-closed)."""
        from app.exceptions import DatabaseStatusUnknownError

        with patch(
            "app.services.database_service.is_database_provisioned",
            side_effect=DatabaseStatusUnknownError(),
        ):
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

        assert resp.status_code == 503
        assert "provisioning state" in resp.json()["message"].lower()

    def test_provision_unexpected_error_is_not_swallowed(
        self, unauthenticated_client
    ):
        """Unexpected errors from is_database_provisioned are not caught as 503.

        Only DatabaseStatusUnknownError should be caught and converted to
        503.  Other exceptions (coding bugs, ImportError, etc.) must
        propagate so they surface as real failures rather than misleading
        "temporarily unreachable" messages.
        """
        with patch(
            "app.services.database_service.is_database_provisioned",
            side_effect=RuntimeError("unexpected coding bug"),
        ):
            with pytest.raises(RuntimeError, match="unexpected coding bug"):
                unauthenticated_client.post(
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

    @patch("app.services.database_service.provision_database", return_value=4)
    @patch("app.services.database_service.is_database_provisioned", return_value=False)
    def test_provision_proceeds_when_db_does_not_exist(
        self, mock_provisioned, mock_provision, unauthenticated_client
    ):
        """POST /provision succeeds when is_database_provisioned returns False.

        On a true first-run install, the target database/role doesn't
        exist yet.  is_database_provisioned() should return False (not
        raise), allowing provisioning to proceed without force=true.
        """
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
        assert resp.json()["status"] == "provisioned"
        mock_provision.assert_called_once()

    @patch("app.services.database_service.provision_database", return_value=0)
    def test_provision_force_skips_provisioned_check(
        self, mock_provision, admin_client, db
    ):
        """force=true skips the is_database_provisioned check entirely.

        is_database_provisioned is NOT mocked here.  In the test environment
        it would raise (no real PostgreSQL), which proves the check is
        skipped when force=true — otherwise we'd get a 503.
        """
        db.add(UserRole(username="admin-user", role="admin"))
        db.commit()

        resp = admin_client.post(
            "/setup/database/provision",
            json={
                "host": "localhost",
                "port": 5432,
                "admin_username": "postgres",
                "admin_password": "secret",
                "app_database": "ecube",
                "app_username": "ecube",
                "app_password": "ecube123",
                "force": True,
            },
        )

        assert resp.status_code == 200


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

        assert resp.status_code == 503
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
        """An empty body must be rejected — at least one field required."""
        resp = admin_client.put(
            "/setup/database/settings",
            json={},
        )

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Endpoint tests — fail-closed when DB is unreachable
# ---------------------------------------------------------------------------


class TestFailClosedBehavior:
    """Verify 503 when DB is unreachable and no admin JWT is provided."""

    def test_unauthenticated_returns_503_when_db_unreachable(
        self, unauthenticated_client
    ):
        """Without a JWT and without a reachable DB, fail closed with 503."""
        from app.main import app
        from app.routers.database_setup import _get_db_or_none

        def _override():
            yield None

        app.dependency_overrides[_get_db_or_none] = _override
        try:
            resp = unauthenticated_client.post(
                "/setup/database/test-connection",
                json={
                    "host": "localhost",
                    "port": 5432,
                    "admin_username": "postgres",
                    "admin_password": "secret",
                },
            )

            assert resp.status_code == 503
            assert "Database is unavailable" in resp.json()["message"]
        finally:
            app.dependency_overrides.pop(_get_db_or_none, None)

    @patch("app.services.database_service.test_connection", return_value="16.2")
    def test_admin_jwt_accepted_when_db_unreachable(
        self, mock_test_conn, admin_client
    ):
        """An admin JWT should be accepted even when DB is unreachable."""
        from app.main import app
        from app.routers.database_setup import _get_db_or_none

        def _override():
            yield None

        app.dependency_overrides[_get_db_or_none] = _override
        try:
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
        finally:
            app.dependency_overrides.pop(_get_db_or_none, None)

    @patch("app.services.database_service.test_connection", return_value="16.2")
    def test_unauthenticated_allowed_when_schema_not_migrated(
        self, mock_test_conn, unauthenticated_client, db
    ):
        """A reachable DB with no user_roles table is treated as initial setup, not 503."""
        from app.repositories.user_role_repository import UserRoleRepository
        from sqlalchemy.exc import ProgrammingError

        original_has_any_admin = UserRoleRepository.has_any_admin

        def _raise_missing_table(self):
            raise ProgrammingError(
                "SELECT", {}, Exception('relation "user_roles" does not exist')
            )

        UserRoleRepository.has_any_admin = _raise_missing_table
        try:
            resp = unauthenticated_client.post(
                "/setup/database/test-connection",
                json={
                    "host": "localhost",
                    "port": 5432,
                    "admin_username": "postgres",
                    "admin_password": "secret",
                },
            )

            # Should be treated as initial setup (200), not 503
            assert resp.status_code == 200
        finally:
            UserRoleRepository.has_any_admin = original_has_any_admin

    @patch("app.services.database_service.test_connection", return_value="16.2")
    def test_operational_error_fails_closed(
        self, mock_test_conn, unauthenticated_client, db
    ):
        """An OperationalError from has_any_admin on a reachable DB must NOT
        be treated as initial setup — fail closed (require auth → 401/403)."""
        from app.repositories.user_role_repository import UserRoleRepository
        from sqlalchemy.exc import OperationalError as SAOperationalError

        original_has_any_admin = UserRoleRepository.has_any_admin

        def _raise_operational(self):
            raise SAOperationalError(
                "SELECT", {}, Exception("permission denied for table user_roles")
            )

        UserRoleRepository.has_any_admin = _raise_operational
        try:
            resp = unauthenticated_client.post(
                "/setup/database/test-connection",
                json={
                    "host": "localhost",
                    "port": 5432,
                    "admin_username": "postgres",
                    "admin_password": "secret",
                },
            )
            # Must NOT return 200; unauthenticated requests should be
            # rejected because we couldn't confirm there are no admins.
            assert resp.status_code in (401, 403, 503)
        finally:
            UserRoleRepository.has_any_admin = original_has_any_admin

    @patch("app.services.database_service.test_connection", return_value="16.2")
    def test_unexpected_error_fails_closed(
        self, mock_test_conn, unauthenticated_client, db
    ):
        """An unexpected exception (e.g. AttributeError) from has_any_admin
        must NOT be treated as initial setup — fail closed."""
        from app.repositories.user_role_repository import UserRoleRepository

        original_has_any_admin = UserRoleRepository.has_any_admin

        def _raise_unexpected(self):
            raise AttributeError("some coding bug")

        UserRoleRepository.has_any_admin = _raise_unexpected
        try:
            resp = unauthenticated_client.post(
                "/setup/database/test-connection",
                json={
                    "host": "localhost",
                    "port": 5432,
                    "admin_username": "postgres",
                    "admin_password": "secret",
                },
            )
            # Must NOT return 200
            assert resp.status_code in (401, 403, 500, 503)
        finally:
            UserRoleRepository.has_any_admin = original_has_any_admin


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

        assert result == "14.9"
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

    @patch("app.services.database_service._write_env_settings")
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

    @patch("app.services.database_service._write_env_settings")
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

    def test_write_env_settings_batch_atomic(self, tmp_path):
        """All keys are written in a single pass - no partial updates."""
        from app.services.database_service import _write_env_settings

        env_file = tmp_path / ".env"
        env_file.write_text("DATABASE_URL=old_url\nKEEP=yes\nDB_POOL_SIZE=5\n")

        with patch("app.services.database_service._get_env_file_path", return_value=str(env_file)):
            _write_env_settings({
                "DATABASE_URL": "postgresql://new/db",
                "DB_POOL_SIZE": "20",
                "DB_POOL_MAX_OVERFLOW": "40",
            })

        content = env_file.read_text()
        assert "DATABASE_URL=postgresql://new/db\n" in content
        assert "KEEP=yes\n" in content
        assert "DB_POOL_SIZE=20\n" in content
        assert "DB_POOL_MAX_OVERFLOW=40\n" in content
        assert "old_url" not in content
        assert "DB_POOL_SIZE=5" not in content

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

    def test_get_current_revision_returns_none_when_database_missing(self):
        """pgcode 3D000 (database does not exist) → None, not 503."""
        import psycopg2 as real_psycopg2
        from app.services.database_service import _get_current_revision

        # psycopg2's pgcode is a readonly C-level attr; subclass to override.
        class _PgError(real_psycopg2.OperationalError):
            pgcode = "3D000"

        with patch("app.services.database_service.psycopg2") as mock_pg:
            mock_pg.OperationalError = real_psycopg2.OperationalError
            mock_pg.connect.side_effect = _PgError('database "ecube" does not exist')

            result = _get_current_revision("postgresql://ecube:pw@localhost/ecube")
            assert result is None

    def test_get_current_revision_returns_none_when_role_missing(self):
        """pgcode 28000 (role does not exist) → None, not 503."""
        import psycopg2 as real_psycopg2
        from app.services.database_service import _get_current_revision

        class _PgError(real_psycopg2.OperationalError):
            pgcode = "28000"

        with patch("app.services.database_service.psycopg2") as mock_pg:
            mock_pg.OperationalError = real_psycopg2.OperationalError
            mock_pg.connect.side_effect = _PgError('role "ecube" does not exist')

            result = _get_current_revision("postgresql://ecube:pw@localhost/ecube")
            assert result is None

    def test_get_current_revision_raises_on_other_operational_errors(self):
        """Connection refused (no pgcode) still raises DatabaseStatusUnknownError."""
        import psycopg2 as real_psycopg2
        from app.exceptions import DatabaseStatusUnknownError
        from app.services.database_service import _get_current_revision

        exc = real_psycopg2.OperationalError("connection refused")
        # No pgcode set — simulates server unreachable

        with patch("app.services.database_service.psycopg2") as mock_pg:
            mock_pg.OperationalError = real_psycopg2.OperationalError
            mock_pg.connect.side_effect = exc

            with pytest.raises(DatabaseStatusUnknownError, match="provisioning state"):
                _get_current_revision("postgresql://ecube:pw@localhost/ecube")

    def test_is_database_provisioned_returns_false_when_db_missing(self):
        """is_database_provisioned() returns False when the target DB doesn't exist."""
        import psycopg2 as real_psycopg2

        class _PgError(real_psycopg2.OperationalError):
            pgcode = "3D000"

        with patch("app.services.database_service.psycopg2") as mock_pg:
            mock_pg.OperationalError = real_psycopg2.OperationalError
            mock_pg.connect.side_effect = _PgError('database "ecube" does not exist')

            from app.services.database_service import is_database_provisioned
            assert is_database_provisioned() is False

    @patch("app.services.database_service._write_env_setting")
    @patch("app.services.database_service._reinitialize_engine")
    @patch("app.services.database_service._run_migrations", side_effect=Exception("alembic boom"))
    @patch("app.services.database_service.psycopg2")
    def test_provision_migration_failure_skips_env_and_engine(
        self, mock_psycopg2, mock_migrations, mock_reinit, mock_write
    ):
        """If _run_migrations fails, .env must NOT be written and engine must NOT be swapped."""
        from app.services.database_service import provision_database

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.OperationalError = Exception
        mock_psycopg2.sql = __import__("psycopg2").sql

        with pytest.raises(RuntimeError, match="migration failed"):
            provision_database(
                host="h", port=5432, admin_username="pg", admin_password="pw",
                app_database="db", app_username="u", app_password="p",
            )

        mock_write.assert_not_called()
        mock_reinit.assert_not_called()

    @patch("app.services.database_service._reinitialize_engine")
    @patch("app.services.database_service._run_migrations", return_value=4)
    @patch("app.services.database_service._write_env_setting", side_effect=OSError("disk full"))
    @patch("app.services.database_service.psycopg2")
    def test_provision_env_write_failure_skips_engine(
        self, mock_psycopg2, mock_write, mock_migrations, mock_reinit
    ):
        """If .env write fails after migration, engine must NOT be swapped."""
        from app.services.database_service import provision_database

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.OperationalError = Exception
        mock_psycopg2.sql = __import__("psycopg2").sql

        with pytest.raises(RuntimeError, match="failed to persist"):
            provision_database(
                host="h", port=5432, admin_username="pg", admin_password="pw",
                app_database="db", app_username="u", app_password="p",
            )

        mock_reinit.assert_not_called()

    @patch("app.services.database_service._write_env_setting")
    @patch("app.services.database_service._run_migrations", return_value=4)
    @patch("app.services.database_service._reinitialize_engine",
           side_effect=RuntimeError("lock contention"))
    @patch("app.services.database_service.psycopg2")
    def test_provision_engine_reinit_failure_raises(
        self, mock_psycopg2, mock_reinit, mock_migrations, mock_write
    ):
        """If engine reinitialization fails, a RuntimeError surfaces."""
        from app.services.database_service import provision_database

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cur
        mock_psycopg2.connect.return_value = mock_conn
        mock_psycopg2.OperationalError = Exception
        mock_psycopg2.sql = __import__("psycopg2").sql

        with pytest.raises(RuntimeError, match="engine could not be switched"):
            provision_database(
                host="h", port=5432, admin_username="pg", admin_password="pw",
                app_database="db", app_username="u", app_password="p",
            )
