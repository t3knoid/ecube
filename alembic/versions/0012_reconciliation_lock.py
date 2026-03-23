"""Add reconciliation_lock table for cross-process startup guard

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-02

Single-row guard table that prevents multiple uvicorn workers from
running startup reconciliation concurrently.
"""

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "reconciliation_lock",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("locked_by", sa.String(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_single_reconciliation_lock"),
    )


def downgrade() -> None:
    op.drop_table("reconciliation_lock")
