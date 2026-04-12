"""Add ARCHIVED as an allowed usb_drives.current_state value.

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
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    old_state_enum = sa.Enum("EMPTY", "AVAILABLE", "IN_USE", name="drivestate", native_enum=False)
    new_state_enum = sa.Enum("EMPTY", "AVAILABLE", "IN_USE", "ARCHIVED", name="drivestate", native_enum=False)

    if dialect_name == "sqlite":
        # SQLite requires table recreation for this kind of constraint/type change.
        with op.batch_alter_table("usb_drives", recreate="always") as batch_op:
            batch_op.alter_column(
                "current_state",
                existing_type=old_state_enum,
                type_=new_state_enum,
                existing_nullable=True,
            )
        return

    _drop_current_state_check_constraints(bind)

    op.alter_column(
        "usb_drives",
        "current_state",
        existing_type=old_state_enum,
        type_=new_state_enum,
        existing_nullable=True,
    )

    op.create_check_constraint(
        "ck_usb_drives_current_state",
        "usb_drives",
        "current_state IN ('EMPTY', 'AVAILABLE', 'IN_USE', 'ARCHIVED')",
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    old_state_enum = sa.Enum("EMPTY", "AVAILABLE", "IN_USE", name="drivestate", native_enum=False)
    new_state_enum = sa.Enum("EMPTY", "AVAILABLE", "IN_USE", "ARCHIVED", name="drivestate", native_enum=False)

    # Ensure rows remain valid when tightening back to the prior allowed set.
    op.execute(sa.text("UPDATE usb_drives SET current_state = 'IN_USE' WHERE current_state = 'ARCHIVED'"))

    if dialect_name == "sqlite":
        with op.batch_alter_table("usb_drives", recreate="always") as batch_op:
            batch_op.alter_column(
                "current_state",
                existing_type=new_state_enum,
                type_=old_state_enum,
                existing_nullable=True,
            )
        return

    _drop_current_state_check_constraints(bind)

    op.alter_column(
        "usb_drives",
        "current_state",
        existing_type=new_state_enum,
        type_=old_state_enum,
        existing_nullable=True,
    )

    op.create_check_constraint(
        "ck_usb_drives_current_state",
        "usb_drives",
        "current_state IN ('EMPTY', 'AVAILABLE', 'IN_USE')",
    )


def _drop_current_state_check_constraints(bind) -> None:
    inspector = sa.inspect(bind)
    checks = inspector.get_check_constraints("usb_drives")
    for check in checks:
        name = check.get("name")
        sqltext = (check.get("sqltext") or "").lower()
        if not name:
            continue
        if "current_state" in sqltext and "empty" in sqltext and "available" in sqltext and "in_use" in sqltext:
            op.drop_constraint(name, "usb_drives", type_="check")
