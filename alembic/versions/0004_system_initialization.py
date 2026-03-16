"""Add system_initialization table for cross-process setup guard

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-16 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_initialization",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("initialized_by", sa.String(), nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_single_initialization_row"),
    )


def downgrade() -> None:
    op.drop_table("system_initialization")
