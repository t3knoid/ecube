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


def test_audit_log_has_project_and_drive_columns_and_indexes(migrated_engine):
    """HEAD migration should expose first-class project/drive audit columns and indexes."""
    inspector = inspect(migrated_engine)
    columns = {c["name"] for c in inspector.get_columns("audit_logs")}

    assert "project_id" in columns
    assert "drive_id" in columns

    index_names = {idx["name"] for idx in inspector.get_indexes("audit_logs")}
    assert "ix_audit_logs_project_timestamp" in index_names
    assert "ix_audit_logs_drive_timestamp" in index_names


def test_migration_0013_backfills_project_and_drive_from_details(sqlite_db_path):
    """Migration 0013 should defensively backfill audit_logs.project_id/drive_id from JSON details."""
    db_url = f"sqlite:///{sqlite_db_path}"
    env = {**os.environ, "DATABASE_URL": db_url}
    repo_root = os.path.dirname(os.path.dirname(__file__))

    up_0012 = subprocess.run(
        ["alembic", "upgrade", "0012"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )
    assert up_0012.returncode == 0, f"upgrade to 0012 failed:\n{up_0012.stderr}"

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO usb_drives (id, device_identifier, current_state) VALUES (7, 'BACKFILL-7', 'AVAILABLE')"
        ))
        conn.execute(text(
            "INSERT INTO usb_drives (id, device_identifier, current_state) VALUES (42, 'BACKFILL-42', 'AVAILABLE')"
        ))

        conn.execute(text(
            "INSERT INTO audit_logs (action, details) VALUES ('A_OK_NUM', :details)"
        ), {"details": '{"project_id":"PROJ-001","drive_id":7}'})

        conn.execute(text(
            "INSERT INTO audit_logs (action, details) VALUES ('A_OK_STR', :details)"
        ), {"details": '{"drive_id":"42"}'})

        conn.execute(text(
            "INSERT INTO audit_logs (action, details) VALUES ('A_BAD', :details)"
        ), {"details": '{"project_id":123,"drive_id":"x42"}'})

        conn.execute(text(
            "INSERT INTO audit_logs (action, details) VALUES ('A_PARTIAL', :details)"
        ), {"details": '{"project_id":"PROJ-PARTIAL","drive_id":"42x"}'})

        conn.execute(text(
            "INSERT INTO audit_logs (action, details) VALUES ('A_ORPHAN', :details)"
        ), {"details": '{"project_id":"PROJ-ORPHAN","drive_id":"999"}'})
    engine.dispose()

    up_head = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )
    assert up_head.returncode == 0, f"upgrade to head failed:\n{up_head.stderr}"

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            ok_num = conn.execute(text(
                "SELECT project_id, drive_id FROM audit_logs WHERE action = 'A_OK_NUM'"
            )).fetchone()
            ok_str = conn.execute(text(
                "SELECT project_id, drive_id FROM audit_logs WHERE action = 'A_OK_STR'"
            )).fetchone()
            bad = conn.execute(text(
                "SELECT project_id, drive_id FROM audit_logs WHERE action = 'A_BAD'"
            )).fetchone()
            partial = conn.execute(text(
                "SELECT project_id, drive_id FROM audit_logs WHERE action = 'A_PARTIAL'"
            )).fetchone()
            orphan = conn.execute(text(
                "SELECT project_id, drive_id FROM audit_logs WHERE action = 'A_ORPHAN'"
            )).fetchone()

        assert ok_num == ("PROJ-001", 7)
        assert ok_str == (None, 42)
        assert bad == (None, None)
        assert partial == ("PROJ-PARTIAL", None)
        assert orphan == ("PROJ-ORPHAN", None)
    finally:
        engine.dispose()


def test_migration_0008_deduplicates_ports(sqlite_db_path):
    """Migration 0008 must coalesce duplicate system_path rows and keep best values."""
    db_url = f"sqlite:///{sqlite_db_path}"
    env = {**os.environ, "DATABASE_URL": db_url}
    repo_root = os.path.dirname(os.path.dirname(__file__))

    # Migrate to 0007 (before unique constraint).
    result = subprocess.run(
        ["alembic", "upgrade", "0007"],
        capture_output=True, text=True, cwd=repo_root, env=env,
    )
    assert result.returncode == 0, f"upgrade to 0007 failed:\n{result.stderr}"

    # Manually insert duplicate port rows.
    engine = create_engine(db_url)
    with engine.begin() as conn:
        # Create a hub first.
        conn.execute(text(
            "INSERT INTO usb_hubs (id, name, system_identifier) "
            "VALUES (1, 'Hub', 'usb1')"
        ))
        # Survivor (lowest id) — has stale/null values.
        conn.execute(text(
            "INSERT INTO usb_ports (id, hub_id, port_number, system_path, "
            "friendly_label, enabled, vendor_id, product_id, speed) "
            "VALUES (1, 1, 1, 'dup-path', NULL, 0, NULL, NULL, NULL)"
        ))
        # Duplicate — has the good data.
        conn.execute(text(
            "INSERT INTO usb_ports (id, hub_id, port_number, system_path, "
            "friendly_label, enabled, vendor_id, product_id, speed) "
            "VALUES (2, 1, 1, 'dup-path', 'Bay 1', 1, '0781', '5583', '5000')"
        ))
        # Create a drive pointing to the duplicate.
        conn.execute(text(
            "INSERT INTO usb_drives (id, port_id, device_identifier, current_state) "
            "VALUES (1, 2, 'serial-1', 'AVAILABLE')"
        ))
    engine.dispose()

    # Now upgrade to 0008 — should dedup and coalesce.
    result = subprocess.run(
        ["alembic", "upgrade", "0008"],
        capture_output=True, text=True, cwd=repo_root, env=env,
    )
    assert result.returncode == 0, f"upgrade to 0008 failed:\n{result.stderr}"

    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            # Only one port row should remain.
            ports = conn.execute(text(
                "SELECT id, friendly_label, enabled, vendor_id, product_id, speed "
                "FROM usb_ports WHERE system_path = 'dup-path'"
            )).fetchall()
            assert len(ports) == 1, f"Expected 1 port after dedup, got {len(ports)}"

            survivor = ports[0]
            assert survivor[0] == 1, "Survivor should be the lowest-id row"
            assert survivor[1] == "Bay 1", "friendly_label should be coalesced from duplicate"
            assert survivor[2] == 1, "enabled should be True (coalesced from duplicate)"
            assert survivor[3] == "0781", "vendor_id should be coalesced"
            assert survivor[4] == "5583", "product_id should be coalesced"
            assert survivor[5] == "5000", "speed should be coalesced"

            # Drive should be re-pointed to the survivor.
            drive = conn.execute(text(
                "SELECT port_id FROM usb_drives WHERE id = 1"
            )).fetchone()
            assert drive[0] == 1, "Drive should be re-pointed to survivor port"
    finally:
        engine.dispose()
