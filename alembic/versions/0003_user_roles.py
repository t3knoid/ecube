"""Add user_roles table for DB-managed authorization

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-16 00:00:00.000000
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False, index=True),
        sa.Column(
            "role",
            sa.Enum(
                "admin", "manager", "processor", "auditor",
                name="ecube_role",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.UniqueConstraint("username", "role", name="uq_user_role"),
    )
    op.create_index(
        "ix_user_roles_username",
        "user_roles",
        ["username"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_roles_username", table_name="user_roles")
    op.drop_table("user_roles")
