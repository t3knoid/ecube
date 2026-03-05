"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

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
    )

    op.create_table(
        "usb_ports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("hub_id", sa.Integer, sa.ForeignKey("usb_hubs.id"), nullable=False),
        sa.Column("port_number", sa.Integer, nullable=False),
        sa.Column("system_path", sa.String, nullable=False),
        sa.Column("friendly_label", sa.String, nullable=True),
    )

    op.create_table(
        "usb_drives",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("port_id", sa.Integer, sa.ForeignKey("usb_ports.id"), nullable=True),
        sa.Column("device_identifier", sa.String, unique=True, nullable=False),
        sa.Column("filesystem_path", sa.String, nullable=True),
        sa.Column("capacity_bytes", sa.BigInteger, nullable=True),
        sa.Column("encryption_status", sa.String, nullable=True),
        sa.Column(
            "current_state",
            sa.Enum("EMPTY", "AVAILABLE", "IN_USE", name="drivestate"),
            nullable=True,
        ),
        sa.Column("current_project_id", sa.String, nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "network_mounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "type",
            sa.Enum("NFS", "SMB", name="mounttype"),
            nullable=False,
        ),
        sa.Column("remote_path", sa.String, nullable=False),
        sa.Column("local_mount_point", sa.String, nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Enum("MOUNTED", "UNMOUNTED", "ERROR", name="mountstatus"),
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
            sa.Enum("PENDING", "RUNNING", "COMPLETED", "FAILED", "VERIFYING", name="jobstatus"),
            nullable=True,
        ),
        sa.Column("total_bytes", sa.BigInteger, default=0),
        sa.Column("copied_bytes", sa.BigInteger, default=0),
        sa.Column("file_count", sa.Integer, default=0),
        sa.Column("thread_count", sa.Integer, default=4),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String, nullable=True),
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
            sa.Enum("PENDING", "COPYING", "DONE", "ERROR", name="filestatus"),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text, nullable=True),
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
        sa.Column("details", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("drive_assignments")
    op.drop_table("manifests")
    op.drop_table("export_files")
    op.drop_table("export_jobs")
    op.drop_table("network_mounts")
    op.drop_table("usb_drives")
    op.drop_table("usb_ports")
    op.drop_table("usb_hubs")
