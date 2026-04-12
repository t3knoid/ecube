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
    # Backfill project_id only when JSON key exists, is text, and non-empty.
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET project_id = json_extract(details, '$.project_id')
            WHERE project_id IS NULL
              AND details IS NOT NULL
              AND json_type(details, '$.project_id') = 'text'
              AND json_extract(details, '$.project_id') <> ''
            """
        )
    )

    # Backfill drive_id for integer JSON values, whole-number real values,
    # and strings containing only digits.
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
                                json_type(details, '$.drive_id') = 'real'
                          AND json_extract(details, '$.drive_id') > 0
                          AND json_extract(details, '$.drive_id') = CAST(json_extract(details, '$.drive_id') AS INTEGER)
                      )
                 OR (
                        json_type(details, '$.drive_id') = 'text'
                    AND json_extract(details, '$.drive_id') <> ''
                          AND json_extract(details, '$.drive_id') NOT GLOB '*[^0-9]*'
                 )
              )
              AND EXISTS (
                    SELECT 1
                    FROM usb_drives u
                    WHERE u.id = CAST(json_extract(details, '$.drive_id') AS INTEGER)
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
                            AND details->>'project_id' <> ''
            """
        )
    )

    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET drive_id = CASE
                               WHEN jsonb_typeof(details::jsonb -> 'drive_id') = 'number'
                                   THEN (details->>'drive_id')::numeric::integer
                               WHEN details->>'drive_id' ~ '^[0-9]+$'
                                   THEN (details->>'drive_id')::integer
                               ELSE split_part(details->>'drive_id', '.', 1)::integer
                           END
            WHERE drive_id IS NULL
              AND details IS NOT NULL
              AND (
                    (
                        jsonb_typeof(details::jsonb -> 'drive_id') = 'number'
                        AND (details->>'drive_id')::numeric = trunc((details->>'drive_id')::numeric)
                        AND (details->>'drive_id')::numeric >= 1
                        AND (details->>'drive_id')::numeric <= 2147483647
                    )
                 OR (
                        jsonb_typeof(details::jsonb -> 'drive_id') = 'string'
                        AND details->>'drive_id' ~ '^[0-9]+$'
                        AND (
                              length(details->>'drive_id') < 10
                           OR (
                                  length(details->>'drive_id') = 10
                              AND details->>'drive_id' <= '2147483647'
                           )
                        )
                    )
                 OR (
                        jsonb_typeof(details::jsonb -> 'drive_id') = 'string'
                        AND details->>'drive_id' ~ '^[0-9]+\\.0+$'
                        AND (
                              length(split_part(details->>'drive_id', '.', 1)) < 10
                           OR (
                                  length(split_part(details->>'drive_id', '.', 1)) = 10
                              AND split_part(details->>'drive_id', '.', 1) <= '2147483647'
                           )
                        )
                    )
              )
              AND EXISTS (
                    SELECT 1
                    FROM usb_drives u
                    WHERE u.id = CASE
                                     WHEN jsonb_typeof(details::jsonb -> 'drive_id') = 'number'
                                         THEN (details->>'drive_id')::numeric::integer
                                     WHEN details->>'drive_id' ~ '^[0-9]+$'
                                         THEN (details->>'drive_id')::integer
                                     ELSE split_part(details->>'drive_id', '.', 1)::integer
                                 END
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
