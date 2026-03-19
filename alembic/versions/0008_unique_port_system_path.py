"""Add unique constraint to usb_ports.system_path.

Revision ID: 0008
Create Date: 2026-03-19

The discovery sync and PortRepository.get_by_system_path() treat
system_path as a stable unique key.  Enforce this at the database level
to prevent duplicate rows and MultipleResultsFound errors.

Before creating the constraint, any pre-existing duplicate rows are
consolidated: for each duplicated system_path the row with the lowest id
is kept, drives referencing the duplicate rows are re-pointed to the
survivor, and the duplicate rows are deleted.
"""

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    # --- De-duplicate usb_ports.system_path before adding the constraint ---
    conn = op.get_bind()

    # Find system_path values that appear more than once.
    dupes = conn.execute(
        sa.text(
            "SELECT system_path FROM usb_ports "
            "GROUP BY system_path HAVING COUNT(*) > 1"
        )
    ).fetchall()

    for (system_path,) in dupes:
        # Keep the row with the lowest id.
        rows = conn.execute(
            sa.text(
                "SELECT id FROM usb_ports "
                "WHERE system_path = :sp ORDER BY id"
            ),
            {"sp": system_path},
        ).fetchall()

        survivor_id = rows[0][0]
        duplicate_ids = [r[0] for r in rows[1:]]

        # Re-point drives from duplicate ports to the survivor.
        conn.execute(
            sa.text(
                "UPDATE usb_drives SET port_id = :survivor "
                "WHERE port_id IN :dups"
            ).bindparams(
                sa.bindparam("survivor", value=survivor_id),
                sa.bindparam("dups", value=tuple(duplicate_ids), expanding=True),
            ),
        )

        # Delete the duplicate port rows.
        conn.execute(
            sa.text(
                "DELETE FROM usb_ports WHERE id IN :dups"
            ).bindparams(
                sa.bindparam("dups", value=tuple(duplicate_ids), expanding=True),
            ),
        )

    with op.batch_alter_table("usb_ports") as batch_op:
        batch_op.create_unique_constraint(
            "uq_usb_ports_system_path", ["system_path"]
        )


def downgrade() -> None:
    with op.batch_alter_table("usb_ports") as batch_op:
        batch_op.drop_constraint("uq_usb_ports_system_path", type_="unique")
