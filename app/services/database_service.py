"""Database provisioning and settings management service.

Handles PostgreSQL database creation, user provisioning, migration execution,
and connection settings management.  Admin credentials are used transiently
and never persisted or logged.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import tempfile
import threading
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

logger = logging.getLogger(__name__)

# Default timeouts (seconds) for psycopg2 connections.
_ADMIN_CONNECT_TIMEOUT = 10   # For admin/provisioning operations
_STATUS_CONNECT_TIMEOUT = 5   # For lightweight status-check queries

# Guards engine/session-factory replacement so concurrent requests cannot
# observe a half-swapped state.  Also exposes "reinitialization in progress"
# to the router layer so it can return 503.
_engine_lock = threading.Lock()


def _get_env_file_path() -> str:
    """Return the resolved .env path used by Settings.

    Pydantic-settings resolves ``env_file=".env"`` relative to CWD, so we
    must write to the same location the app reads from.
    """
    from app.config import Settings

    env_file = Settings.model_config.get("env_file", ".env")
    return os.path.abspath(str(env_file))


def _get_alembic_ini_path() -> str:
    """Return the absolute path to ``alembic.ini``.

    The file lives at the repository/project root, which is the CWD when
    the application or ``alembic`` CLI is started.  Raises ``FileNotFoundError``
    if the config file cannot be located.
    """
    path = os.path.abspath("alembic.ini")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Alembic configuration not found at {path}. "
            "Ensure the application is started from the project root directory."
        )
    return path


def test_connection(
    host: str,
    port: int,
    username: str,
    password: str,
) -> str:
    """Test connectivity to a PostgreSQL server.

    Returns the server version string on success.
    Raises ``ConnectionError`` on failure.
    """
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=username,
            password=password,
            dbname="postgres",
            connect_timeout=_ADMIN_CONNECT_TIMEOUT,
        )
        try:
            version = conn.server_version
            # PostgreSQL 10+ uses two-part versioning: server_version = major*10000 + patch
            # e.g. 140009 → 14.9, 160002 → 16.2
            major = version // 10000
            patch = version % 10000
            return f"{major}.{patch}"
        finally:
            conn.close()
    except psycopg2.OperationalError as exc:
        raise ConnectionError(f"Could not connect to {host}:{port}: {exc}") from exc


def provision_database(
    host: str,
    port: int,
    admin_username: str,
    admin_password: str,
    app_database: str,
    app_username: str,
    app_password: str,
) -> int:
    """Create the application user and database, then run Alembic migrations.

    Returns the number of migrations applied.
    Raises ``ConnectionError`` on connectivity failures.
    Raises ``RuntimeError`` on provisioning failures.

    Steps are ordered so that side-effects (.env write, engine swap) only
    occur after migrations succeed.  If migrations fail, the database and
    user exist but the schema is incomplete — the operator can fix the
    migration issue and retry without ``force``.
    """
    # Step 1: Connect as admin to create user and database
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            user=admin_username,
            password=admin_password,
            dbname="postgres",
            connect_timeout=_ADMIN_CONNECT_TIMEOUT,
        )
    except psycopg2.OperationalError as exc:
        raise ConnectionError(
            f"Could not connect to {host}:{port} with admin credentials: {exc}"
        ) from exc

    try:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Create user if not exists
        cur.execute(
            "SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = %s",
            (app_username,),
        )
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE USER {} WITH PASSWORD %s").format(
                    sql.Identifier(app_username)
                ),
                (app_password,),
            )
            logger.info("Created database user: %s", app_username)
        else:
            # Update password for existing user
            cur.execute(
                sql.SQL("ALTER USER {} WITH PASSWORD %s").format(
                    sql.Identifier(app_username)
                ),
                (app_password,),
            )
            logger.info("Updated password for existing user: %s", app_username)

        # Create database if not exists
        cur.execute(
            "SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s",
            (app_database,),
        )
        if cur.fetchone() is None:
            cur.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(app_database),
                    sql.Identifier(app_username),
                )
            )
            logger.info("Created database: %s", app_database)
        else:
            logger.info("Database already exists: %s", app_database)

        cur.close()
    except psycopg2.Error as exc:
        logger.error("Database provisioning failed: %s", exc)
        raise RuntimeError(
            "Database provisioning failed during user/database creation"
        ) from exc
    finally:
        conn.close()

    # Step 2: Run Alembic migrations against the new database.
    # If this fails the database/user have been created but the schema is
    # incomplete — we intentionally do NOT write .env or swap the engine
    # so the operator can retry without ``force``.
    new_url = _build_database_url(host, port, app_database, app_username, app_password)
    try:
        migrations_applied = _run_migrations(new_url)
    except Exception as exc:
        logger.error("Alembic migration failed: %s", exc)
        raise RuntimeError(
            "Database and user were created, but schema migration failed. "
            "Resolve the migration issue and retry provisioning."
        ) from exc

    # Step 3: Write DATABASE_URL to .env — only after migrations succeed.
    try:
        _write_env_setting("DATABASE_URL", new_url)
    except Exception as exc:
        logger.error("Failed to write DATABASE_URL to .env: %s", exc)
        raise RuntimeError(
            "Database provisioned and migrated, but failed to persist "
            "DATABASE_URL to .env. Update .env manually or retry."
        ) from exc

    # Step 4: Switch the running process to the newly provisioned database.
    from app.config import settings

    settings.database_url = new_url
    try:
        _reinitialize_engine(
            new_url, settings.db_pool_size, settings.db_pool_max_overflow
        )
    except Exception as exc:
        logger.error("Engine reinitialization failed: %s", exc)
        raise RuntimeError(
            "Database provisioned and .env updated, but the running "
            "engine could not be switched. Restart the application."
        ) from exc

    return migrations_applied


def is_database_provisioned() -> bool:
    """Check whether the configured database is already provisioned.

    Returns ``True`` when the configured ``DATABASE_URL`` connects
    successfully and the ``alembic_version`` table contains a revision,
    indicating that provisioning has already been completed.

    Returns ``False`` when the target database or application role does
    not exist yet (common on a fresh install where the URL points to
    resources that have not been created).

    Raises :class:`~app.exceptions.DatabaseStatusUnknownError` when the
    database server is unreachable for other reasons (transient outage,
    network failure), so callers can fail closed rather than incorrectly
    assuming the database is unprovisioned.
    """
    from app.config import settings

    return _get_current_revision(settings.database_url) is not None


def _run_migrations(database_url: str) -> int:
    """Run Alembic migrations programmatically and return the count applied."""
    # Import alembic lazily to avoid conflict with local alembic/ directory
    alembic_command = importlib.import_module("alembic.command")
    AlembicConfig = importlib.import_module("alembic.config").Config
    ScriptDirectory = importlib.import_module("alembic.script").ScriptDirectory

    alembic_ini = _get_alembic_ini_path()
    alembic_cfg = AlembicConfig(alembic_ini)
    alembic_cfg.set_main_option("sqlalchemy.url", database_url)

    script = ScriptDirectory.from_config(alembic_cfg)

    # Determine how many revisions are pending before upgrading
    current_rev = _get_current_revision(database_url)
    heads = script.get_heads()

    if current_rev and current_rev in heads:
        # Already at head — nothing to apply
        pending = 0
    elif current_rev is None:
        # Fresh database — all revisions are pending
        pending = len(list(script.walk_revisions()))
    else:
        # Count revisions between current and head
        pending = 0
        for rev in script.walk_revisions():
            if rev.revision == current_rev:
                break
            pending += 1

    alembic_command.upgrade(alembic_cfg, "head")

    return pending


def _get_current_revision(database_url: str) -> Optional[str]:
    """Read the current Alembic revision from the database, or ``None``.

    Returns ``None`` when:
    - the ``alembic_version`` table does not exist or contains no rows
      (database exists but has not been provisioned), **or**
    - the target database does not exist (PostgreSQL ``3D000``), **or**
    - the application role does not exist (PostgreSQL ``28000``).

    The last two cases arise on a true first-run install where
    ``settings.database_url`` points to a database/user that has not been
    created yet.  Treating them as "not provisioned" allows the
    ``/setup/database/provision`` endpoint to proceed without ``force``.

    Raises :class:`~app.exceptions.DatabaseStatusUnknownError` when a
    connection-level error prevents the check (transient outage, server
    unreachable, authentication failure with an *existing* role, etc.).
    """
    from app.exceptions import DatabaseStatusUnknownError

    # PostgreSQL SQLSTATE codes that indicate the target DB/role has not
    # been created yet — i.e. the system is genuinely unprovisioned.
    _NOT_PROVISIONED_PGCODES = frozenset({
        "3D000",  # invalid_catalog_name  – database does not exist
        "28000",  # invalid_authorization_specification – role does not exist
    })

    try:
        conn = psycopg2.connect(database_url, connect_timeout=_STATUS_CONNECT_TIMEOUT)
    except psycopg2.OperationalError as exc:
        pgcode = getattr(exc, "pgcode", None)
        if pgcode in _NOT_PROVISIONED_PGCODES:
            logger.info(
                "Target database/role does not exist (SQLSTATE %s); "
                "treating as not provisioned.",
                pgcode,
            )
            return None
        raise DatabaseStatusUnknownError(
            f"Cannot connect to database to verify provisioning state: {exc}"
        ) from exc

    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables "
                "  WHERE table_name = 'alembic_version'"
                ")"
            )
            if not cur.fetchone()[0]:
                return None
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()
    finally:
        conn.close()


def get_database_status() -> Dict[str, Any]:
    """Report the current database connection health and migration state."""
    from app.config import settings

    parsed = _parse_database_url(settings.database_url)

    result: Dict[str, Any] = {
        "connected": False,
        "database": parsed.get("database"),
        "host": parsed.get("host"),
        "port": parsed.get("port"),
        "current_migration": None,
        "pending_migrations": None,
    }

    try:
        conn = psycopg2.connect(
            settings.database_url,
            connect_timeout=_STATUS_CONNECT_TIMEOUT,
        )
        try:
            result["connected"] = True

            # Get current migration from alembic_version table
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables "
                    "  WHERE table_name = 'alembic_version'"
                    ")"
                )
                table_exists = cur.fetchone()[0]
                if table_exists:
                    cur.execute("SELECT version_num FROM alembic_version")
                    row = cur.fetchone()
                    if row:
                        result["current_migration"] = row[0]
            finally:
                cur.close()

            # Count pending migrations
            AlembicConfig = importlib.import_module("alembic.config").Config
            ScriptDirectory = importlib.import_module("alembic.script").ScriptDirectory

            alembic_ini = _get_alembic_ini_path()
            alembic_cfg = AlembicConfig(alembic_ini)
            script = ScriptDirectory.from_config(alembic_cfg)

            current = result["current_migration"]
            if current is not None:
                heads = script.get_heads()
                if current in heads:
                    result["pending_migrations"] = 0
                else:
                    # Count revisions between current and head
                    pending = 0
                    for rev in script.walk_revisions():
                        if rev.revision == current:
                            break
                        pending += 1
                    result["pending_migrations"] = pending
            else:
                # No migration applied yet — all are pending
                result["pending_migrations"] = len(list(script.walk_revisions()))
        finally:
            conn.close()
    except Exception:
        logger.debug("Database status check failed", exc_info=True)

    return result


def update_database_settings(
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    app_database: Optional[str] = None,
    app_username: Optional[str] = None,
    app_password: Optional[str] = None,
    pool_size: Optional[int] = None,
    pool_max_overflow: Optional[int] = None,
) -> Dict[str, Any]:
    """Update database connection settings.

    Validates new settings via a test connection before committing.
    Returns the new settings (without password) on success.
    Raises ``ConnectionError`` if the test connection fails.
    Raises ``RuntimeError`` on write failures.
    """
    from app.config import settings

    # Build new values by merging with current settings
    current = _parse_database_url(settings.database_url)

    new_host = host or current.get("host", "localhost")
    new_port = port or current.get("port", 5432)
    new_database = app_database or current.get("database", "ecube")
    new_username = app_username or current.get("username", "ecube")
    new_password = app_password or current.get("password", "")
    new_pool_size = pool_size or settings.db_pool_size
    new_pool_max_overflow = pool_max_overflow if pool_max_overflow is not None else settings.db_pool_max_overflow

    # Test the new connection before committing
    new_url = _build_database_url(new_host, new_port, new_database, new_username, new_password)
    try:
        conn = psycopg2.connect(new_url, connect_timeout=_ADMIN_CONNECT_TIMEOUT)
        conn.close()
    except psycopg2.OperationalError as exc:
        raise ConnectionError(
            f"Could not connect to {new_host}:{new_port} with the supplied credentials"
        ) from exc

    # Write all changed settings in a single atomic pass
    env_updates: Dict[str, str] = {"DATABASE_URL": new_url}
    if pool_size is not None:
        env_updates["DB_POOL_SIZE"] = str(new_pool_size)
    if pool_max_overflow is not None:
        env_updates["DB_POOL_MAX_OVERFLOW"] = str(new_pool_max_overflow)
    _write_env_settings(env_updates)

    # Update in-memory settings so subsequent reads are consistent
    settings.database_url = new_url
    settings.db_pool_size = new_pool_size
    settings.db_pool_max_overflow = new_pool_max_overflow

    # Re-initialise the SQLAlchemy engine
    _reinitialize_engine(new_url, new_pool_size, new_pool_max_overflow)

    return {
        "status": "updated",
        "host": new_host,
        "port": new_port,
        "database": new_database,
        "connected": True,
    }


def _build_database_url(
    host: str, port: int, database: str, username: str, password: str
) -> str:
    """Build a PostgreSQL DSN with properly encoded credentials."""
    return (
        f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}"
    )


def _parse_database_url(url: str) -> Dict[str, Any]:
    """Parse a PostgreSQL connection URL into components."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": (parsed.path or "/ecube").lstrip("/") or "ecube",
        "username": parsed.username or "ecube",
        "password": parsed.password or "",
    }


def _write_env_setting(key: str, value: str) -> None:
    """Atomically write or update a single setting in the .env file.

    Convenience wrapper around :func:`_write_env_settings` for callers
    that only need to update one key.
    """
    _write_env_settings({key: value})


def _write_env_settings(updates: Dict[str, str]) -> None:
    """Atomically write or update one or more settings in the .env file.

    All *updates* are applied in a single read/modify/write pass so the
    file is never left in a partially-updated state.  Uses a
    write-to-temp-then-rename strategy (``os.replace``) for crash safety.
    """
    if not updates:
        return

    env_path = _get_env_file_path()
    lines: list[str] = []

    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            lines = f.readlines()

    remaining = dict(updates)  # keys still to place

    for i, line in enumerate(lines):
        for key in list(remaining):
            if re.match(rf"^{re.escape(key)}\s*=", line):
                lines[i] = f"{key}={remaining.pop(key)}\n"
                break  # one key per line; move to next line

    # Append any keys that weren't already present
    for key, value in remaining.items():
        lines.append(f"{key}={value}\n")

    # Atomic write via temp file + rename
    dir_name = os.path.dirname(env_path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.writelines(lines)
        os.replace(tmp_path, env_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _reinitialize_engine(
    database_url: str,
    pool_size: int,
    pool_max_overflow: int,
) -> None:
    """Re-initialise the SQLAlchemy engine and session factory in-place.

    Acquires ``_engine_lock`` so that the swap is atomic with respect to
    other threads.  The old engine is disposed **after** the new engine is
    installed, so in-flight requests that still hold a reference to the old
    session can finish gracefully.

    The existing ``SessionLocal`` sessionmaker is reconfigured via
    ``.configure(bind=new_engine)`` rather than replaced, so that modules
    which captured a reference at import time (e.g.
    ``from app.database import SessionLocal``) see the updated binding.

    Raises ``EngineReinitializationError`` immediately if another
    reinitialization is already in progress (non-blocking).
    """
    import app.database as db_module
    from sqlalchemy import create_engine

    from app.config import settings
    from app.exceptions import EngineReinitializationError

    acquired = _engine_lock.acquire(blocking=False)
    if not acquired:
        raise EngineReinitializationError()
    try:
        old_engine = db_module.engine

        new_engine = create_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=pool_max_overflow,
            pool_recycle=settings.db_pool_recycle_seconds,
        )

        # Install new engine and reconfigure the existing SessionLocal
        # in-place so all references (including those captured via
        # ``from app.database import SessionLocal``) use the new engine.
        db_module.engine = new_engine
        db_module.SessionLocal.configure(bind=new_engine)
    finally:
        _engine_lock.release()

    # Dispose old engine outside the lock — existing connections drain
    # naturally and the pool is released.
    try:
        old_engine.dispose()
    except Exception:
        logger.debug("Failed to dispose old engine", exc_info=True)
