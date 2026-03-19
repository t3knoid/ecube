"""Add enabled column to usb_ports

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-19 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usb_ports",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("usb_ports", "enabled")
