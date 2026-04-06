#!/usr/bin/env python3
"""Generate DBML from SQLAlchemy metadata.

This script imports ECUBE models, walks ``Base.metadata``, and writes a
deterministic DBML file used by docs and CI drift checks.
"""

from __future__ import annotations

import argparse
import re
from collections import OrderedDict
from pathlib import Path
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql.schema import Index, UniqueConstraint

from app.database import Base

# Import models so all tables are registered on Base.metadata.
import app.models  # noqa: F401


HEADER = """Project ECUBE {
  database_type: \"PostgreSQL\"
  Note: \"ECUBE core operational schema (generated from SQLAlchemy metadata)\"
}
"""


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _enum_name(enum_type: SAEnum, column=None) -> str:
    if enum_type.name and "_" in enum_type.name:
        return str(enum_type.name)
    if enum_type.enum_class is not None:
        return _camel_to_snake(enum_type.enum_class.__name__)
    if enum_type.name:
        return str(enum_type.name)
    assert column is not None
    return f"{column.table.name}_{column.name}_enum"


def _enum_values(enum_type: SAEnum) -> list[str]:
    if enum_type.enum_class is not None:
        return [str(member.value) for member in enum_type.enum_class]
    return [str(value) for value in (enum_type.enums or [])]


def _dbml_type(column) -> str:
    col_type = column.type
    if isinstance(col_type, SAEnum):
        return _enum_name(col_type, column)
    if isinstance(col_type, BigInteger):
        return "bigint"
    if isinstance(col_type, Integer):
        return "int"
    if isinstance(col_type, Boolean):
        return "boolean"
    if isinstance(col_type, DateTime):
        return "timestamptz" if col_type.timezone else "timestamp"
    if isinstance(col_type, Text):
        return "text"
    if isinstance(col_type, String):
        if col_type.length:
            return f"varchar({col_type.length})"
        return "varchar"
    if isinstance(col_type, (JSON, JSONB)):
        return "json"
    return str(col_type).lower()


def _format_default_value(value) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if hasattr(value, "value"):
        return f"'{value.value}'"
    return f"'{value}'"


def _column_settings(column) -> list[str]:
    settings: list[str] = []
    if column.primary_key:
        settings.append("pk")
    if not column.nullable:
        settings.append("not null")
    if column.unique:
        settings.append("unique")

    default_value = None
    if column.default is not None and getattr(column.default, "is_scalar", False):
        default_value = column.default.arg
    if default_value is not None:
        settings.append(f"default: {_format_default_value(default_value)}")

    return settings


def _render_indexes(table) -> list[str]:
    entries: list[str] = []

    unique_constraints = sorted(
        [c for c in table.constraints if isinstance(c, UniqueConstraint)],
        key=lambda c: c.name or "",
    )
    for constraint in unique_constraints:
        col_names = [col.name for col in constraint.columns]

        if (
            len(col_names) == 1
            and table.columns[col_names[0]].unique
            and not constraint.name
        ):
            continue

        if len(col_names) == 1:
            target = col_names[0]
        else:
            target = f"({', '.join(col_names)})"

        opts = ["unique"]
        if constraint.name:
            opts.append(f"name: '{constraint.name}'")
        entries.append(f"    {target} [{', '.join(opts)}]")

    indexes = sorted(table.indexes, key=lambda i: i.name or "")
    for index in indexes:
        assert isinstance(index, Index)
        col_names = [col.name for col in index.columns]

        # SQLAlchemy may emit implicit indexes for ``unique=True`` columns.
        # Skip those when uniqueness is already represented on the column.
        if (
            len(col_names) == 1
            and index.unique
            and table.columns[col_names[0]].unique
            and not index.name
        ):
            continue

        if len(col_names) == 1:
            target = col_names[0]
        else:
            target = f"({', '.join(col_names)})"

        opts = []
        if index.unique:
            opts.append("unique")
        if index.name:
            opts.append(f"name: '{index.name}'")
        if opts:
            entries.append(f"    {target} [{', '.join(opts)}]")
        else:
            entries.append(f"    {target}")

    return entries


def generate_dbml() -> str:
    lines: list[str] = [HEADER.strip(), ""]

    enum_defs: OrderedDict[str, list[str]] = OrderedDict()
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, SAEnum):
                enum_name = _enum_name(column.type, column)
                enum_defs.setdefault(enum_name, _enum_values(column.type))

    for enum_name, values in enum_defs.items():
        lines.append(f"Enum {enum_name} {{")
        for value in values:
            lines.append(f"  {value}")
        lines.append("}")
        lines.append("")

    refs: list[str] = []
    for table in Base.metadata.sorted_tables:
        lines.append(f"Table {table.name} {{")
        for column in table.columns:
            settings = _column_settings(column)
            if settings:
                settings_block = f" [{', '.join(settings)}]"
            else:
                settings_block = ""
            lines.append(f"  {column.name} {_dbml_type(column)}{settings_block}")

        index_entries = _render_indexes(table)
        if index_entries:
            lines.append("")
            lines.append("  indexes {")
            lines.extend(index_entries)
            lines.append("  }")

        lines.append("}")
        lines.append("")

        for fk in table.foreign_keys:
            refs.append(
                "Ref: "
                f"{table.name}.{fk.parent.name} > "
                f"{fk.column.table.name}.{fk.column.name}"
            )

    for ref in sorted(set(refs)):
        lines.append(ref)

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ECUBE DBML schema file")
    parser.add_argument(
        "--output",
        default="docs/database/ecube-schema.dbml",
        help="Output DBML file path",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(generate_dbml(), encoding="utf-8")
    print(f"Wrote DBML to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
