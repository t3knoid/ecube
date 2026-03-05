"""Migration smoke tests.

Validates that the Alembic migration scripts run cleanly against a SQLite
file-based database, covering the same enum/JSON portability conventions
enforced by the ORM models in tests.

We use a file-based SQLite DB (rather than in-memory) because Alembic's
``alembic upgrade`` is invoked via subprocess, which runs in a separate
process and therefore cannot share a StaticPool in-memory connection.
"""
import os
import subprocess
import pytest
from sqlalchemy import create_engine, inspect, text


@pytest.fixture()
def sqlite_db_path(tmp_path):
    """Return a path to a temporary SQLite database file."""
    return str(tmp_path / "test_migration.db")


@pytest.fixture()
def migrated_engine(sqlite_db_path):
    """Run 'alembic upgrade head' against a fresh SQLite file DB and yield an engine."""
    db_url = f"sqlite:///{sqlite_db_path}"
    env = {**os.environ, "DATABASE_URL": db_url}

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    engine = create_engine(db_url)
    yield engine
    engine.dispose()


def test_upgrade_head_on_sqlite(migrated_engine):
    """upgrade() must run to HEAD without errors on SQLite and create all tables."""
    inspector = inspect(migrated_engine)
    tables = set(inspector.get_table_names())

    expected_tables = {
        "usb_hubs",
        "usb_ports",
        "usb_drives",
        "network_mounts",
        "export_jobs",
        "export_files",
        "manifests",
        "drive_assignments",
        "audit_logs",
    }
    assert expected_tables.issubset(tables), (
        f"Missing tables after upgrade: {expected_tables - tables}"
    )


def test_downgrade_base_on_sqlite(sqlite_db_path):
    """downgrade() to base must drop all application tables on SQLite."""
    db_url = f"sqlite:///{sqlite_db_path}"
    env = {**os.environ, "DATABASE_URL": db_url}
    repo_root = os.path.dirname(os.path.dirname(__file__))

    up = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True, cwd=repo_root, env=env,
    )
    assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

    down = subprocess.run(
        ["alembic", "downgrade", "base"],
        capture_output=True, text=True, cwd=repo_root, env=env,
    )
    assert down.returncode == 0, f"downgrade failed:\n{down.stdout}\n{down.stderr}"

    engine = create_engine(db_url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    # Only the alembic_version tracking table should remain
    assert tables <= {"alembic_version"}, (
        f"Unexpected tables remain after downgrade: {tables - {'alembic_version'}}"
    )


def test_enum_columns_stored_as_varchar_on_sqlite(migrated_engine):
    """Enum columns must be stored as VARCHAR (native_enum=False) on SQLite."""
    inspector = inspect(migrated_engine)

    # All five enum columns defined in the migration
    enum_columns = [
        ("usb_drives", "current_state"),
        ("network_mounts", "type"),
        ("network_mounts", "status"),
        ("export_jobs", "status"),
        ("export_files", "status"),
    ]

    for table, col_name in enum_columns:
        cols = {c["name"]: c for c in inspector.get_columns(table)}
        assert col_name in cols, f"Column {col_name!r} missing from {table!r}"
        col_type = type(cols[col_name]["type"]).__name__.upper()
        assert col_type in ("VARCHAR", "TEXT", "STRING"), (
            f"{table}.{col_name} expected VARCHAR/TEXT for SQLite enum portability, "
            f"got {col_type!r}"
        )


def test_audit_log_details_accepts_json_on_sqlite(migrated_engine):
    """audit_logs.details must accept and round-trip JSON data on SQLite.

    Only the NOT NULL column (action) is supplied; all others are nullable
    or have server defaults, matching the migration schema.
    """
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_logs (action, details) VALUES (:action, :details)"
            ),
            {"action": "test_event", "details": '{"key": "value", "count": 1}'},
        )
        row = conn.execute(
            text("SELECT details FROM audit_logs WHERE action = 'test_event'")
        ).fetchone()

    assert row is not None, "No row found after insert"
    assert row[0] is not None, "details column returned NULL"
