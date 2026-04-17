"""rename drive state EMPTY to DISCONNECTED

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename stored state value EMPTY → DISCONNECTED.
    # The column uses native_enum=False (VARCHAR), so this is a plain UPDATE
    # with no DDL enum type changes required on any database.
    op.execute(
        "UPDATE usb_drives SET current_state = 'DISCONNECTED' WHERE current_state = 'EMPTY'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE usb_drives SET current_state = 'EMPTY' WHERE current_state = 'DISCONNECTED'"
    )
