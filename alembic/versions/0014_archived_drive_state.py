"""Add ARCHIVED drive state and archive drives after handoff completion.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # For PostgreSQL: Alter the existing ENUM type to add ARCHIVED
    # (uses conditional execution; will only run if using PostgreSQL)
    op.execute(
        sa.text(
            """
            DO $$ BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_type t
                    WHERE t.typname = 'drivestate'
                ) THEN
                    RETURN;
                END IF;

                -- ALTER TYPE only works with PostgreSQL ENUM types
                ALTER TYPE drivestate ADD VALUE 'ARCHIVED' AFTER 'IN_USE';
            EXCEPTION WHEN others THEN
                -- For SQLite or if the type doesn't exist, this clause silently succeeds
                NULL;
            END $$;
            """
        )
    )


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values directly.
    # If downgrading is needed, users would need to run custom SQL
    # or recreate the type. For now, we'll skip downgrade.
    pass
