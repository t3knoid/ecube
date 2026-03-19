"""Add unique constraint to usb_ports.system_path.

Revision ID: 0008
Create Date: 2026-03-19

The discovery sync and PortRepository.get_by_system_path() treat
system_path as a stable unique key.  Enforce this at the database level
to prevent duplicate rows and MultipleResultsFound errors.

Before creating the constraint, any pre-existing duplicate rows are
consolidated: for each duplicated system_path the best attribute values
are coalesced into the lowest-id survivor row, drives referencing
duplicate rows are re-pointed, and the duplicates are deleted.
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
        # Fetch all duplicate rows ordered by id (survivor = lowest).
        rows = conn.execute(
            sa.text(
                "SELECT id, friendly_label, enabled, vendor_id, product_id, speed "
                "FROM usb_ports WHERE system_path = :sp ORDER BY id"
            ),
            {"sp": system_path},
        ).fetchall()

        survivor = rows[0]
        survivor_id = survivor[0]
        duplicate_ids = [r[0] for r in rows[1:]]

        # Coalesce best values from all rows into the survivor.
        # For friendly_label/vendor_id/product_id/speed: first non-null wins.
        # For enabled: True wins (any row enabled means the port is enabled).
        best_friendly_label = survivor[1]
        best_enabled = bool(survivor[2])
        best_vendor_id = survivor[3]
        best_product_id = survivor[4]
        best_speed = survivor[5]

        for dup in rows[1:]:
            if best_friendly_label is None and dup[1] is not None:
                best_friendly_label = dup[1]
            if not best_enabled and dup[2]:
                best_enabled = True
            if best_vendor_id is None and dup[3] is not None:
                best_vendor_id = dup[3]
            if best_product_id is None and dup[4] is not None:
                best_product_id = dup[4]
            if best_speed is None and dup[5] is not None:
                best_speed = dup[5]

        # Apply coalesced values to the survivor row.
        conn.execute(
            sa.text(
                "UPDATE usb_ports SET "
                "friendly_label = :fl, enabled = :en, "
                "vendor_id = :vi, product_id = :pi, speed = :sp "
                "WHERE id = :sid"
            ),
            {
                "fl": best_friendly_label,
                "en": best_enabled,
                "vi": best_vendor_id,
                "pi": best_product_id,
                "sp": best_speed,
                "sid": survivor_id,
            },
        )

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
