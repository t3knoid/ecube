"""Add vendor_id, product_id to hubs and vendor_id, product_id, speed to ports

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-19 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usb_hubs", sa.Column("vendor_id", sa.String(), nullable=True))
    op.add_column("usb_hubs", sa.Column("product_id", sa.String(), nullable=True))
    op.add_column("usb_ports", sa.Column("vendor_id", sa.String(), nullable=True))
    op.add_column("usb_ports", sa.Column("product_id", sa.String(), nullable=True))
    op.add_column("usb_ports", sa.Column("speed", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("usb_ports", "speed")
    op.drop_column("usb_ports", "product_id")
    op.drop_column("usb_ports", "vendor_id")
    op.drop_column("usb_hubs", "product_id")
    op.drop_column("usb_hubs", "vendor_id")
