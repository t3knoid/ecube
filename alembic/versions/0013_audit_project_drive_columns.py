"""Add project_id and drive_id columns to audit_logs with backfill and indexes.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _backfill_sqlite() -> None:
    # Backfill project_id only when JSON key exists and is text.
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET project_id = json_extract(details, '$.project_id')
            WHERE project_id IS NULL
              AND details IS NOT NULL
              AND json_type(details, '$.project_id') = 'text'
            """
        )
    )

    # Backfill drive_id for integer JSON values and numeric strings.
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET drive_id = CAST(json_extract(details, '$.drive_id') AS INTEGER)
            WHERE drive_id IS NULL
              AND details IS NOT NULL
              AND (
                    json_type(details, '$.drive_id') = 'integer'
                 OR (
                        json_type(details, '$.drive_id') = 'text'
                    AND json_extract(details, '$.drive_id') GLOB '[0-9]*'
                    AND json_extract(details, '$.drive_id') <> ''
                 )
              )
            """
        )
    )


def _backfill_postgresql() -> None:
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET project_id = details->>'project_id'
            WHERE project_id IS NULL
              AND details IS NOT NULL
              AND jsonb_typeof(details::jsonb -> 'project_id') = 'string'
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET drive_id = (details->>'drive_id')::integer
            WHERE drive_id IS NULL
              AND details IS NOT NULL
              AND (
                    jsonb_typeof(details::jsonb -> 'drive_id') = 'number'
                 OR (
                        jsonb_typeof(details::jsonb -> 'drive_id') = 'string'
                    AND details->>'drive_id' ~ '^[0-9]+$'
                 )
              )
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("drive_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_audit_logs_drive_id_usb_drives",
            "usb_drives",
            ["drive_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if dialect == "sqlite":
        _backfill_sqlite()
    else:
        _backfill_postgresql()

    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_project_timestamp ON audit_logs (project_id, timestamp DESC)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_drive_timestamp ON audit_logs (drive_id, timestamp DESC)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_action_timestamp ON audit_logs (action, timestamp DESC)"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_action_timestamp"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_drive_timestamp"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_audit_logs_project_timestamp"))

    with op.batch_alter_table("audit_logs") as batch_op:
        batch_op.drop_constraint("fk_audit_logs_drive_id_usb_drives", type_="foreignkey")
        batch_op.drop_column("drive_id")
        batch_op.drop_column("project_id")
