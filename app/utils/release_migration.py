from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_REVISION_RE = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_DOWN_REVISION_RE = re.compile(r'^down_revision\s*=\s*(None|["\']([^"\']+)["\'])', re.MULTILINE)


class ReleaseMigrationError(RuntimeError):
    """Raised when the release-scoped migration workflow cannot continue."""


@dataclass(frozen=True)
class ReleaseMigrationResult:
    version: str
    path: Path
    revision: str
    down_revision: str | None
    created: bool


@dataclass(frozen=True)
class _MigrationFile:
    path: Path
    revision: str
    down_revision: str | None


def release_migration_revision_id(version: str) -> str:
    match = _SEMVER_RE.fullmatch(version.strip())
    if not match:
        raise ReleaseMigrationError(
            f"Unsupported project.version '{version}'. Release migrations must use major.minor.patch format."
        )
    return f"v{match.group(1)}_{match.group(2)}_{match.group(3)}"


def release_migration_module_name(version: str) -> str:
    return f"{release_migration_revision_id(version)}.py"


def resolve_project_version(pyproject_path: Path) -> str:
    text = pyproject_path.read_text(encoding="utf-8")
    in_project_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project_section = line == "[project]"
            continue
        if in_project_section and line.startswith("version"):
            _, value = line.split("=", 1)
            return value.strip().strip('"\'')
    raise ReleaseMigrationError(f"Could not resolve [project].version from {pyproject_path}")


def ensure_release_migration(repo_root: Path) -> ReleaseMigrationResult:
    version = resolve_project_version(repo_root / "pyproject.toml")
    path = _versions_dir(repo_root) / release_migration_module_name(version)
    revision = release_migration_revision_id(version)
    if not path.exists():
        return ReleaseMigrationResult(
            version=version,
            path=path,
            revision=revision,
            down_revision=_current_head_revision(repo_root),
            created=False,
        )

    metadata = _read_migration_file(path)
    return ReleaseMigrationResult(
        version=version,
        path=path,
        revision=metadata.revision,
        down_revision=metadata.down_revision,
        created=False,
    )


def create_release_migration(repo_root: Path) -> ReleaseMigrationResult:
    pending = ensure_release_migration(repo_root)
    if pending.path.exists():
        raise ReleaseMigrationError(
            f"Release migration {pending.path.name} already exists for ECUBE {pending.version}; update it in place instead of creating a second unreleased migration."
        )

    pending.path.write_text(
        _render_migration_template(
            version=pending.version,
            revision=pending.revision,
            down_revision=pending.down_revision,
        ),
        encoding="utf-8",
    )
    return ReleaseMigrationResult(
        version=pending.version,
        path=pending.path,
        revision=pending.revision,
        down_revision=pending.down_revision,
        created=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Locate or create the single unreleased ECUBE Alembic migration for the current project.version."
    )
    parser.add_argument(
        "command",
        choices=("ensure", "create"),
        help="'ensure' prints the current release migration path; 'create' scaffolds it if missing and otherwise fails clearly.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root that contains pyproject.toml and alembic/versions (default: current directory).",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    try:
        result = ensure_release_migration(repo_root) if args.command == "ensure" else create_release_migration(repo_root)
    except ReleaseMigrationError as exc:
        parser.exit(1, f"error: {exc}\n")

    status = "created" if result.created else "ready"
    print(f"{status}: {result.path}")
    return 0


def _versions_dir(repo_root: Path) -> Path:
    versions_dir = repo_root / "alembic" / "versions"
    if not versions_dir.is_dir():
        raise ReleaseMigrationError(f"Alembic versions directory not found at {versions_dir}")
    return versions_dir


def _migration_files(repo_root: Path) -> list[_MigrationFile]:
    versions_dir = _versions_dir(repo_root)
    migrations: list[_MigrationFile] = []
    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        migrations.append(_read_migration_file(path))
    return migrations


def _read_migration_file(path: Path) -> _MigrationFile:
    text = path.read_text(encoding="utf-8")
    revision_match = _REVISION_RE.search(text)
    down_revision_match = _DOWN_REVISION_RE.search(text)
    if not revision_match or not down_revision_match:
        raise ReleaseMigrationError(f"Could not parse Alembic revision metadata from {path}")
    down_revision = down_revision_match.group(2) if down_revision_match.group(1) != "None" else None
    return _MigrationFile(path=path, revision=revision_match.group(1), down_revision=down_revision)


def _current_head_revision(repo_root: Path) -> str | None:
    migrations = _migration_files(repo_root)
    if not migrations:
        return None

    referenced = {migration.down_revision for migration in migrations if migration.down_revision is not None}
    heads = [migration for migration in migrations if migration.revision not in referenced]
    if len(heads) != 1:
        raise ReleaseMigrationError(
            "Expected exactly one Alembic head revision before creating a new release migration."
        )
    return heads[0].revision


def _render_migration_template(*, version: str, revision: str, down_revision: str | None) -> str:
    rendered_down_revision = f'"{down_revision}"' if down_revision is not None else "None"
    return f'''"""ECUBE release-scoped migration for v{version}.

This module is the single unreleased Alembic migration for ECUBE v{version}.
Accumulate all schema changes for this unreleased version here until the release ships.

Revision ID: {revision}
Revises: {down_revision or ''}
"""
from alembic import op
import sqlalchemy as sa

revision = "{revision}"
down_revision = {rendered_down_revision}
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
'''
