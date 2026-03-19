"""Add unique constraint to usb_ports.system_path.

Revision ID: 0008
Create Date: 2026-03-19

The discovery sync and PortRepository.get_by_system_path() treat
system_path as a stable unique key.  Enforce this at the database level
to prevent duplicate rows and MultipleResultsFound errors.
"""

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    with op.batch_alter_table("usb_ports") as batch_op:
        batch_op.create_unique_constraint(
            "uq_usb_ports_system_path", ["system_path"]
        )


def downgrade() -> None:
    with op.batch_alter_table("usb_ports") as batch_op:
        batch_op.drop_constraint("uq_usb_ports_system_path", type_="unique")
