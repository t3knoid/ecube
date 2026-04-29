"""Migration smoke tests.

Validates that the Alembic migration scripts run cleanly against a SQLite
file-based database, covering the same enum/JSON portability conventions
enforced by the ORM models in tests.

We use a file-based SQLite DB (rather than in-memory) because Alembic's
``alembic upgrade`` is invoked via subprocess, which runs in a separate
process and therefore cannot share a StaticPool in-memory connection.
"""
import os
import sqlite3
import subprocess
import sys
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
    alembic_cmd = [sys.executable, "-m", "alembic"]

    result = subprocess.run(
        [*alembic_cmd, "upgrade", "head"],
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
        "projects",
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
    alembic_cmd = [sys.executable, "-m", "alembic"]

    up = subprocess.run(
        [*alembic_cmd, "upgrade", "head"],
        capture_output=True, text=True, cwd=repo_root, env=env,
    )
    assert up.returncode == 0, f"upgrade failed:\n{up.stdout}\n{up.stderr}"

    down = subprocess.run(
        [*alembic_cmd, "downgrade", "base"],
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


def test_network_mounts_include_nfs_client_version_column(migrated_engine):
    inspector = inspect(migrated_engine)
    columns = {c["name"] for c in inspector.get_columns("network_mounts")}
    assert "nfs_client_version" in columns


def test_drive_assignments_include_manifest_counters(migrated_engine):
    inspector = inspect(migrated_engine)
    columns = {c["name"] for c in inspector.get_columns("drive_assignments")}
    assert "file_count" in columns
    assert "copied_bytes" in columns


def test_audit_log_has_project_and_drive_columns_and_indexes(migrated_engine):
    """HEAD migration should expose first-class project/drive audit columns and indexes."""
    inspector = inspect(migrated_engine)
    columns = {c["name"] for c in inspector.get_columns("audit_logs")}

    assert "project_id" in columns
    assert "drive_id" in columns

    index_names = {idx["name"] for idx in inspector.get_indexes("audit_logs")}
    assert "ix_audit_logs_project_timestamp" in index_names
    assert "ix_audit_logs_drive_timestamp" in index_names


def test_export_jobs_project_id_references_projects(migrated_engine):
    """HEAD migration should expose a first-class projects table for jobs."""
    inspector = inspect(migrated_engine)

    project_columns = {c["name"] for c in inspector.get_columns("projects")}
    assert "normalized_project_id" in project_columns

    export_job_fks = inspector.get_foreign_keys("export_jobs")
    assert any(
        fk.get("referred_table") == "projects"
        and fk.get("constrained_columns") == ["project_id"]
        and fk.get("referred_columns") == ["normalized_project_id"]
        for fk in export_job_fks
    )


def test_export_files_project_id_references_projects(migrated_engine):
    """HEAD migration should expose first-class project ownership for copied files."""
    inspector = inspect(migrated_engine)

    export_file_columns = {c["name"] for c in inspector.get_columns("export_files")}
    assert "project_id" in export_file_columns

    export_file_fks = inspector.get_foreign_keys("export_files")
    assert any(
        fk.get("referred_table") == "projects"
        and fk.get("constrained_columns") == ["project_id"]
        and fk.get("referred_columns") == ["normalized_project_id"]
        for fk in export_file_fks
    )

    index_names = {idx["name"] for idx in inspector.get_indexes("export_files")}
    assert "ix_export_files_project_id" in index_names
    assert "ix_export_files_project_status" in index_names


def test_upgrade_head_backfills_projects_from_legacy_export_jobs(sqlite_db_path):
    """Legacy export_jobs rows should backfill into projects during upgrade."""
    with sqlite3.connect(sqlite_db_path) as conn:
        conn.execute(
            """
            CREATE TABLE export_jobs (
                id INTEGER PRIMARY KEY,
                project_id VARCHAR NOT NULL,
                evidence_number VARCHAR NOT NULL,
                source_path VARCHAR NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE export_files (
                id INTEGER PRIMARY KEY,
                job_id INTEGER NOT NULL,
                relative_path VARCHAR NOT NULL,
                size_bytes BIGINT,
                checksum VARCHAR,
                status VARCHAR,
                error_message TEXT,
                retry_attempts INTEGER DEFAULT 0
            )
            """
        )
        conn.executemany(
            "INSERT INTO export_jobs (id, project_id, evidence_number, source_path) VALUES (?, ?, ?, ?)",
            [
                (1, "Case-001", "EV-1", "/src/one"),
                (2, " case-001 ", "EV-2", "/src/two"),
                (3, "CASE-002", "EV-3", "/src/three"),
            ],
        )
        conn.executemany(
            "INSERT INTO export_files (id, job_id, relative_path, status) VALUES (?, ?, ?, ?)",
            [
                (10, 1, "one.txt", "DONE"),
                (11, 2, "two.txt", "ERROR"),
                (12, 3, "three.txt", "DONE"),
            ],
        )
        conn.commit()

    db_url = f"sqlite:///{sqlite_db_path}"
    env = {**os.environ, "DATABASE_URL": db_url}
    repo_root = os.path.dirname(os.path.dirname(__file__))
    alembic_cmd = [sys.executable, "-m", "alembic"]

    result = subprocess.run(
        [*alembic_cmd, "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )
    assert result.returncode == 0, (
        f"alembic upgrade head failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            project_rows = conn.execute(
                text("SELECT normalized_project_id FROM projects ORDER BY normalized_project_id")
            ).fetchall()
            job_rows = conn.execute(
                text("SELECT id, project_id FROM export_jobs ORDER BY id")
            ).fetchall()
            file_rows = conn.execute(
                text("SELECT id, project_id FROM export_files ORDER BY id")
            ).fetchall()
        inspector = inspect(engine)
    finally:
        engine.dispose()

    assert [row[0] for row in project_rows] == ["CASE-001", "CASE-002"]
    assert job_rows == [(1, "CASE-001"), (2, "CASE-001"), (3, "CASE-002")]
    assert file_rows == [(10, "CASE-001"), (11, "CASE-001"), (12, "CASE-002")]
    assert any(
        fk.get("referred_table") == "projects"
        and fk.get("constrained_columns") == ["project_id"]
        and fk.get("referred_columns") == ["normalized_project_id"]
        for fk in inspector.get_foreign_keys("export_jobs")
    )
    assert any(
        fk.get("referred_table") == "projects"
        and fk.get("constrained_columns") == ["project_id"]
        and fk.get("referred_columns") == ["normalized_project_id"]
        for fk in inspector.get_foreign_keys("export_files")
    )
