from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.utils.release_migration import release_migration_module_name, resolve_project_version


def expected_release_migration_path(repo_root: Path) -> Path:
    version = resolve_project_version(repo_root / "pyproject.toml")
    return repo_root / "alembic" / "versions" / release_migration_module_name(version)


def disallowed_changed_migration_paths(repo_root: Path, changed_paths: list[str]) -> list[Path]:
    expected = expected_release_migration_path(repo_root).resolve()
    versions_dir = (repo_root / "alembic" / "versions").resolve()
    disallowed: list[Path] = []

    for raw_path in changed_paths:
        path = (repo_root / raw_path).resolve()
        if path.suffix != ".py":
            continue
        if path.name == "__init__.py":
            continue
        if path.parent != versions_dir:
            continue
        if path != expected:
            disallowed.append(path)

    return disallowed


def build_error_message(repo_root: Path, disallowed: list[Path]) -> str:
    expected = expected_release_migration_path(repo_root)
    changed = ", ".join(sorted(path.relative_to(repo_root).as_posix() for path in disallowed))
    return (
        "ECUBE uses a single unreleased Alembic migration per app version. "
        f"Only {expected.relative_to(repo_root).as_posix()} may be created or modified for the current release. "
        f"Disallowed migration changes: {changed}. "
        "Update the current release migration in place and use 'ecube-release-migration' instead of creating a second Alembic revision file."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when changed files introduce or modify a non-current ECUBE release migration.",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root containing pyproject.toml and alembic/versions.",
    )
    parser.add_argument(
        "changed_paths",
        nargs="*",
        help="Changed repository-relative file paths to validate.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    disallowed = disallowed_changed_migration_paths(repo_root, list(args.changed_paths))
    if not disallowed:
        print(expected_release_migration_path(repo_root).relative_to(repo_root).as_posix())
        return 0

    print(build_error_message(repo_root, disallowed), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())