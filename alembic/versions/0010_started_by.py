"""Add started_by column to export_jobs.

Revision ID: 0010
Create Date: 2026-03-21

Tracks the username of the user who started the job via
POST /jobs/{id}/start, distinct from created_by.
"""

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("export_jobs", sa.Column("started_by", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("export_jobs", "started_by")
