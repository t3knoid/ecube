"""Add filesystem_type column to usb_drives

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-17 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usb_drives",
        sa.Column("filesystem_type", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("usb_drives", "filesystem_type")
