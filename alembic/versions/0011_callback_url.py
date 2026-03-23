"""Add callback_url column to export_jobs.

Revision ID: 0011
Create Date: 2026-03-28

Optional HTTPS URL to receive a POST callback when the job reaches
a terminal state (COMPLETED or FAILED).
"""

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("export_jobs", sa.Column("callback_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("export_jobs", "callback_url")
