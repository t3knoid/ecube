"""Add retry/resume columns to export_jobs and export_files

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-06 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add retry configuration columns to export_jobs.
    op.add_column(
        "export_jobs",
        sa.Column("max_file_retries", sa.Integer(), nullable=True, server_default="3"),
    )
    op.add_column(
        "export_jobs",
        sa.Column("retry_delay_seconds", sa.Integer(), nullable=True, server_default="1"),
    )
    # Add per-file retry tracking column to export_files.
    op.add_column(
        "export_files",
        sa.Column("retry_attempts", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("export_files", "retry_attempts")
    op.drop_column("export_jobs", "retry_delay_seconds")
    op.drop_column("export_jobs", "max_file_retries")
