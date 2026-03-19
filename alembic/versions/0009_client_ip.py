"""Add client_ip column to audit_logs and export_jobs.

Revision ID: 0009
Create Date: 2026-03-19

Tracks the originating client IP address for audit trail entries and
export job records.  Background-task entries remain NULL.
"""

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("client_ip", sa.String(45), nullable=True))
    op.add_column("export_jobs", sa.Column("client_ip", sa.String(45), nullable=True))


def downgrade() -> None:
    op.drop_column("export_jobs", "client_ip")
    op.drop_column("audit_logs", "client_ip")
