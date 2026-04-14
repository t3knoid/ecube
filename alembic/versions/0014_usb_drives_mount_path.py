"""Add mount_path column to usb_drives.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usb_drives", sa.Column("mount_path", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("usb_drives", "mount_path")
