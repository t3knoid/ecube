"""Initial schema

This is the canonical baseline migration for ECUBE v1.0.

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
This migration may be edited in-place while ECUBE is pre-release (no
production deployments exist). All dev/test environments are rebuilt from
scratch (``drop → create → alembic upgrade head``), so columns or indexes
added here will always be applied. Once v1.0 ships, this file becomes
immutable and all schema changes must use new sequential migrations.

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


def upgrade() -> None:
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

    op.create_table(
        "network_mounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "type",
            sa.Enum("NFS", "SMB", name="mounttype", native_enum=False),
            nullable=False,
        ),
        sa.Column("remote_path", sa.String, nullable=False),
        sa.Column("local_mount_point", sa.String, nullable=False, unique=True),
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

    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String, nullable=False),
        sa.Column("evidence_number", sa.String, nullable=False),
        sa.Column("source_path", sa.String, nullable=False),
        sa.Column("target_mount_path", sa.String, nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING", "RUNNING", "COMPLETED", "FAILED", "VERIFYING",
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
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String, nullable=True),
        sa.Column("started_by", sa.String(), nullable=True),
        sa.Column("client_ip", sa.String(45), nullable=True),
        sa.Column("callback_url", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "export_files",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("export_jobs.id"), nullable=False),
        sa.Column("relative_path", sa.String, nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("checksum", sa.String, nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "COPYING", "DONE", "ERROR", name="filestatus", native_enum=False),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_attempts", sa.Integer(), nullable=True, server_default="0"),
    )

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
    op.drop_table("reconciliation_lock")
    op.drop_table("system_initialization")
    op.drop_table("user_roles")
    op.drop_table("audit_logs")
    op.drop_table("drive_assignments")
    op.drop_table("manifests")
    op.drop_table("export_files")
    op.drop_table("export_jobs")
    op.drop_table("network_mounts")
    op.drop_index("ix_usb_drives_mount_path", table_name="usb_drives")
    op.drop_table("usb_drives")
    op.drop_table("usb_ports")
    op.drop_table("usb_hubs")
