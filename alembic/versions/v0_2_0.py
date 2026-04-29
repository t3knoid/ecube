"""Initial schema

This is the canonical release-scoped migration for ECUBE v0.2.0.

Fresh install
-------------
Run ``alembic upgrade head`` on a clean database. This migration creates the
complete schema from scratch.

Dev environment with an old alembic_version
-------------------------------------------
Only stamp this baseline if the database schema already matches it exactly,
for example because the database was previously migrated all the way to the
old head revision before the history was collapsed. In that case, run::

    alembic stamp 0001
    # marks the existing schema as this baseline; no DDL is replayed

Do not run ``alembic stamp 0001`` against a partially migrated or otherwise
schema-drifted database. For those environments, recreate the database from
scratch and then run ``alembic upgrade head``.

Mutability notice
-----------------
This migration may be edited in-place while ECUBE v0.2.0 remains unreleased
(no production deployments exist). All dev/test environments are rebuilt from
scratch (``drop → create → alembic upgrade head``), so columns or indexes
added here will always be applied. Once v0.2.0 ships, this file becomes
immutable and the next unreleased ECUBE version must use its own single
release-scoped migration module.

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _normalize_project_id(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = value.replace("\x00", "")
    value = "".join(character for character in value if not 0xD800 <= ord(character) <= 0xDFFF)
    return value.strip().upper()


def _create_projects_table() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("normalized_project_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("normalized_project_id", name="uq_projects_normalized_project_id"),
    )


def _backfill_projects_from_jobs() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, project_id "
            "FROM export_jobs "
            "WHERE project_id IS NOT NULL"
        )
    ).fetchall()

    normalized_jobs = []
    normalized_project_ids = set()
    for job_id, project_id in rows:
        normalized = _normalize_project_id(project_id)
        if not isinstance(normalized, str) or not normalized:
            continue
        normalized_jobs.append({"id": job_id, "project_id": normalized})
        normalized_project_ids.add(normalized)

    if normalized_jobs:
        bind.execute(
            sa.text("UPDATE export_jobs SET project_id = :project_id WHERE id = :id"),
            normalized_jobs,
        )

    if normalized_project_ids:
        bind.execute(
            sa.text(
                "INSERT INTO projects (normalized_project_id) VALUES (:normalized_project_id)"
            ),
            [
                {"normalized_project_id": project_id}
                for project_id in sorted(normalized_project_ids)
            ],
        )


def _export_jobs_project_fk_exists(inspector: sa.Inspector) -> bool:
    return any(
        fk.get("referred_table") == "projects"
        and fk.get("constrained_columns") == ["project_id"]
        and fk.get("referred_columns") == ["normalized_project_id"]
        for fk in inspector.get_foreign_keys("export_jobs")
    )


def _export_files_project_fk_exists(inspector: sa.Inspector) -> bool:
    return any(
        fk.get("referred_table") == "projects"
        and fk.get("constrained_columns") == ["project_id"]
        and fk.get("referred_columns") == ["normalized_project_id"]
        for fk in inspector.get_foreign_keys("export_files")
    )


def _export_files_has_project_id(inspector: sa.Inspector) -> bool:
    return any(column.get("name") == "project_id" for column in inspector.get_columns("export_files"))


def _network_mounts_has_nfs_client_version(inspector: sa.Inspector) -> bool:
    return any(column.get("name") == "nfs_client_version" for column in inspector.get_columns("network_mounts"))


def _drive_assignments_has_manifest_counters(inspector: sa.Inspector) -> bool:
    columns = {column.get("name") for column in inspector.get_columns("drive_assignments")}
    return {"file_count", "copied_bytes"}.issubset(columns)


def _backfill_drive_assignment_manifest_counters() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT drive_assignments.id, export_jobs.file_count, export_jobs.copied_bytes "
            "FROM drive_assignments "
            "JOIN export_jobs ON export_jobs.id = drive_assignments.job_id "
            "JOIN ("
            "    SELECT job_id "
            "    FROM drive_assignments "
            "    GROUP BY job_id "
            "    HAVING COUNT(*) = 1"
            ") single_assignment_jobs ON single_assignment_jobs.job_id = drive_assignments.job_id"
        )
    ).fetchall()

    if rows:
        bind.execute(
            sa.text(
                "UPDATE drive_assignments "
                "SET file_count = :file_count, copied_bytes = :copied_bytes "
                "WHERE id = :assignment_id"
            ),
            [
                {
                    "assignment_id": assignment_id,
                    "file_count": int(file_count or 0),
                    "copied_bytes": int(copied_bytes or 0),
                }
                for assignment_id, file_count, copied_bytes in rows
            ],
        )


def _upgrade_drive_assignment_manifest_counters(inspector: sa.Inspector) -> None:
    if "drive_assignments" not in inspector.get_table_names():
        return
    if _drive_assignments_has_manifest_counters(inspector):
        return

    with op.batch_alter_table("drive_assignments") as batch_op:
        batch_op.add_column(sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("copied_bytes", sa.BigInteger(), nullable=False, server_default="0"))

    _backfill_drive_assignment_manifest_counters()

    with op.batch_alter_table("drive_assignments") as batch_op:
        batch_op.alter_column("file_count", existing_type=sa.Integer(), server_default=None)
        batch_op.alter_column("copied_bytes", existing_type=sa.BigInteger(), server_default=None)


def _backfill_export_file_projects() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT export_files.id, export_jobs.project_id "
            "FROM export_files "
            "JOIN export_jobs ON export_jobs.id = export_files.job_id "
            "WHERE export_jobs.project_id IS NOT NULL"
        )
    ).fetchall()

    normalized_files = []
    for file_id, project_id in rows:
        normalized = _normalize_project_id(project_id)
        if not isinstance(normalized, str) or not normalized:
            continue
        normalized_files.append({"id": file_id, "project_id": normalized})

    if normalized_files:
        bind.execute(
            sa.text("UPDATE export_files SET project_id = :project_id WHERE id = :id"),
            normalized_files,
        )


def _ensure_export_files_project_indexes() -> None:
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_export_files_project_id ON export_files (project_id)"))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_export_files_project_status ON export_files (project_id, status)"))


def _upgrade_legacy_export_file_project_schema(inspector: sa.Inspector) -> None:
    if not _export_files_has_project_id(inspector):
        with op.batch_alter_table("export_files") as batch_op:
            batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))

    _backfill_export_file_projects()

    if not _export_files_project_fk_exists(inspector):
        with op.batch_alter_table("export_files") as batch_op:
            batch_op.create_foreign_key(
                "fk_export_files_project_id_projects",
                "projects",
                ["project_id"],
                ["normalized_project_id"],
            )

    with op.batch_alter_table("export_files") as batch_op:
        batch_op.alter_column("project_id", existing_type=sa.String(), nullable=False)

    _ensure_export_files_project_indexes()


def _upgrade_legacy_project_schema(inspector: sa.Inspector, existing_tables: set[str]) -> None:
    if "projects" not in existing_tables:
        _create_projects_table()

    _backfill_projects_from_jobs()

    if not _export_jobs_project_fk_exists(inspector):
        with op.batch_alter_table("export_jobs") as batch_op:
            batch_op.create_foreign_key(
                "fk_export_jobs_project_id_projects",
                "projects",
                ["project_id"],
                ["normalized_project_id"],
            )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "export_jobs" in existing_tables:
        if "network_mounts" in existing_tables and not _network_mounts_has_nfs_client_version(inspector):
            with op.batch_alter_table("network_mounts") as batch_op:
                batch_op.add_column(sa.Column("nfs_client_version", sa.String(), nullable=True))
        if "drive_assignments" in existing_tables:
            _upgrade_drive_assignment_manifest_counters(inspector)
        _upgrade_legacy_project_schema(inspector, existing_tables)
        if "export_files" in existing_tables:
            _upgrade_legacy_export_file_project_schema(inspector)
        return

    op.create_table(
        "usb_hubs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("system_identifier", sa.String, unique=True, nullable=False),
        sa.Column("location_hint", sa.String, nullable=True),
        sa.Column("vendor_id", sa.String(), nullable=True),
        sa.Column("product_id", sa.String(), nullable=True),
    )

    op.create_table(
        "usb_ports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hub_id", sa.Integer, sa.ForeignKey("usb_hubs.id"), nullable=False),
        sa.Column("port_number", sa.Integer, nullable=False),
        sa.Column("system_path", sa.String, nullable=False),
        sa.Column("friendly_label", sa.String, nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("vendor_id", sa.String(), nullable=True),
        sa.Column("product_id", sa.String(), nullable=True),
        sa.Column("speed", sa.String(), nullable=True),
        sa.UniqueConstraint("system_path", name="uq_usb_ports_system_path"),
    )

    op.create_table(
        "usb_drives",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("port_id", sa.Integer, sa.ForeignKey("usb_ports.id"), nullable=True),
        sa.Column("device_identifier", sa.String, unique=True, nullable=False),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("product_name", sa.String(), nullable=True),
        sa.Column("filesystem_path", sa.String, nullable=True),
        sa.Column("filesystem_type", sa.String(), nullable=True),
        sa.Column("capacity_bytes", sa.BigInteger, nullable=True),
        sa.Column("encryption_status", sa.String, nullable=True),
        sa.Column(
            "current_state",
            sa.Enum(
                "DISCONNECTED", "AVAILABLE", "IN_USE", "ARCHIVED",
                name="drivestate",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("current_project_id", sa.String, nullable=True),
        sa.Column("mount_path", sa.String(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_usb_drives_mount_path", "usb_drives", ["mount_path"])
    op.create_index("ix_usb_drives_current_state", "usb_drives", ["current_state"])
    op.create_index("ix_usb_drives_current_project_id", "usb_drives", ["current_project_id"])
    op.create_index("ix_usb_drives_state_project", "usb_drives", ["current_state", "current_project_id"])

    op.create_table(
        "network_mounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "type",
            sa.Enum("NFS", "SMB", name="mounttype", native_enum=False),
            nullable=False,
        ),
        sa.Column("remote_path", sa.String, nullable=False),
        sa.Column("project_id", sa.String(), nullable=False, server_default="UNASSIGNED"),
        sa.Column("nfs_client_version", sa.String(), nullable=True),
        sa.Column("local_mount_point", sa.String, nullable=False, unique=True),
        sa.Column("encrypted_username", sa.String(), nullable=True),
        sa.Column("encrypted_password", sa.String(), nullable=True),
        sa.Column("encrypted_credentials_file", sa.String(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("MOUNTED", "UNMOUNTED", "ERROR", name="mountstatus", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "last_checked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_index("ix_network_mounts_status", "network_mounts", ["status"])
    op.create_index("ix_network_mounts_project_id", "network_mounts", ["project_id"])
    op.create_index("ix_network_mounts_status_project", "network_mounts", ["status", "project_id"])

    _create_projects_table()

    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.normalized_project_id"), nullable=False),
        sa.Column("evidence_number", sa.String, nullable=False),
        sa.Column("source_path", sa.String, nullable=False),
        sa.Column("target_mount_path", sa.String, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "PAUSING", "PAUSED", "COMPLETED", "FAILED", "VERIFYING", "ARCHIVED",
                name="jobstatus",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("total_bytes", sa.BigInteger, default=0),
        sa.Column("copied_bytes", sa.BigInteger, default=0),
        sa.Column("file_count", sa.Integer, default=0),
        sa.Column("thread_count", sa.Integer, default=4),
        sa.Column("max_file_retries", sa.Integer(), nullable=True, server_default="3"),
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("active_duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("started_by", sa.String(), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("callback_url", sa.String(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "startup_analysis_status",
            sa.Enum(
                "NOT_ANALYZED", "ANALYZING", "READY", "STALE", "FAILED",
                name="startupanalysisstatus",
                native_enum=False,
            ),
            nullable=False,
            server_default="NOT_ANALYZED",
        ),
        sa.Column("startup_analysis_last_analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("startup_analysis_failure_reason", sa.Text(), nullable=True),
        sa.Column("startup_analysis_file_count", sa.Integer(), nullable=True),
        sa.Column("startup_analysis_total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("startup_analysis_share_read_mbps", sa.Float(), nullable=True),
        sa.Column("startup_analysis_drive_write_mbps", sa.Float(), nullable=True),
        sa.Column("startup_analysis_estimated_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("startup_analysis_entries", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_index("ix_export_jobs_project_id", "export_jobs", ["project_id"])

    op.create_table(
        "export_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("export_jobs.id"), nullable=False),
        sa.Column("project_id", sa.String, sa.ForeignKey("projects.normalized_project_id"), nullable=False),
        sa.Column("relative_path", sa.String, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("checksum", sa.String, nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "COPYING", "DONE", "ERROR", "RETRYING", "TIMEOUT", name="filestatus", native_enum=False),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_attempts", sa.Integer(), nullable=True, server_default="0"),
    )
    op.create_index("ix_export_files_project_id", "export_files", ["project_id"])
    op.create_index("ix_export_files_project_status", "export_files", ["project_id", "status"])

    op.create_table(
        "manifests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("export_jobs.id"), nullable=False),
        sa.Column("manifest_path", sa.String, nullable=True),
        sa.Column("format", sa.String, default="JSON"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "drive_assignments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("drive_id", sa.Integer, sa.ForeignKey("usb_drives.id"), nullable=False),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("export_jobs.id"), nullable=False),
        sa.Column("file_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("copied_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("user", sa.String, nullable=True),
        sa.Column("action", sa.String, nullable=False),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("export_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("details", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("project_id", sa.String(), nullable=True),
        sa.Column(
            "drive_id",
            sa.Integer,
            sa.ForeignKey("usb_drives.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, index=True),
        sa.Column(
            "role",
            sa.Enum(
                "admin", "manager", "processor", "auditor",
                name="ecube_role",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.UniqueConstraint("username", "role", name="uq_user_role"),
    )

    op.create_table(
        "system_initialization",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("initialized_by", sa.String(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_single_initialization_row"),
    )

    op.create_table(
        "reconciliation_lock",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("locked_by", sa.String(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_single_reconciliation_lock"),
    )

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_project_timestamp "
            "ON audit_logs (project_id, timestamp DESC)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_drive_timestamp "
            "ON audit_logs (drive_id, timestamp DESC)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_action_timestamp "
            "ON audit_logs (action, timestamp DESC)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_action_timestamp"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_drive_timestamp"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_project_timestamp"))
    op.drop_index("ix_export_files_project_status", table_name="export_files")
    op.drop_index("ix_export_files_project_id", table_name="export_files")
    op.drop_index("ix_export_jobs_project_id", table_name="export_jobs")
    op.drop_index("ix_network_mounts_status_project", table_name="network_mounts")
    op.drop_index("ix_network_mounts_project_id", table_name="network_mounts")
    op.drop_index("ix_network_mounts_status", table_name="network_mounts")
    op.drop_index("ix_usb_drives_state_project", table_name="usb_drives")
    op.drop_index("ix_usb_drives_current_project_id", table_name="usb_drives")
    op.drop_index("ix_usb_drives_current_state", table_name="usb_drives")
    op.drop_index("ix_usb_drives_mount_path", table_name="usb_drives")
    op.drop_table("reconciliation_lock")
    op.drop_table("system_initialization")
    op.drop_table("user_roles")
    op.drop_table("audit_logs")
    op.drop_table("drive_assignments")
    op.drop_table("manifests")
    op.drop_table("export_files")
    op.drop_table("export_jobs")
    op.drop_table("projects")
    op.drop_table("network_mounts")
    op.drop_table("usb_drives")
    op.drop_table("usb_ports")
    op.drop_table("usb_hubs")
