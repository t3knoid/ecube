from pathlib import Path
from unittest.mock import patch

import pytest

from app.utils.release_migration import (
    ReleaseMigrationError,
    ReleaseMigrationResult,
    autogenerate_release_migration,
    create_release_migration,
    ensure_release_migration,
    release_migration_module_name,
    release_migration_revision_id,
)


def _write_pyproject(repo_root: Path, version: str) -> None:
    (repo_root / "pyproject.toml").write_text(
        """
[project]
name = "ecube"
version = "%s"
""".strip()
        % version,
        encoding="utf-8",
    )


def _write_migration(path: Path, revision: str, down_revision: str | None) -> None:
    rendered_down_revision = f'"{down_revision}"' if down_revision is not None else "None"
    path.write_text(
        """
revision = "%s"
down_revision = %s
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
""".strip()
        % (revision, rendered_down_revision),
        encoding="utf-8",
    )


def test_release_migration_module_name_normalizes_semver() -> None:
    assert release_migration_module_name("0.2.0") == "v0_2_0.py"
    assert release_migration_revision_id("0.2.0") == "v0_2_0"


def test_release_migration_module_name_rejects_non_semver() -> None:
    with pytest.raises(ReleaseMigrationError, match=r"must use major\.minor\.patch"):
        release_migration_module_name("0.2")


def test_ensure_release_migration_returns_existing_release_file(tmp_path: Path) -> None:
    repo_root = tmp_path
    versions_dir = repo_root / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    _write_pyproject(repo_root, "0.2.0")
    existing_path = versions_dir / "v0_2_0.py"
    _write_migration(existing_path, revision="0001", down_revision=None)

    result = ensure_release_migration(repo_root)

    assert result.path == existing_path
    assert result.created is False
    assert result.version == "0.2.0"


def test_ensure_release_migration_accepts_typed_alembic_metadata(tmp_path: Path) -> None:
    repo_root = tmp_path
    versions_dir = repo_root / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    _write_pyproject(repo_root, "0.2.0")
    existing_path = versions_dir / "v0_2_0.py"
    existing_path.write_text(
        """
revision: str = "v0_2_0"
down_revision: str | None = None
branch_labels = None
depends_on = None
""".strip(),
        encoding="utf-8",
    )

    result = ensure_release_migration(repo_root)

    assert result.path == existing_path
    assert result.revision == "v0_2_0"
    assert result.down_revision is None


def test_create_release_migration_fails_when_current_release_file_exists(tmp_path: Path) -> None:
    repo_root = tmp_path
    versions_dir = repo_root / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    _write_pyproject(repo_root, "0.2.0")
    _write_migration(versions_dir / "v0_2_0.py", revision="0001", down_revision=None)

    with pytest.raises(ReleaseMigrationError, match="already exists.*update it in place"):
        create_release_migration(repo_root)


def test_create_release_migration_creates_single_file_for_current_version(tmp_path: Path) -> None:
    repo_root = tmp_path
    versions_dir = repo_root / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    _write_pyproject(repo_root, "0.2.0")
    _write_migration(versions_dir / "v0_1_0.py", revision="v0_1_0", down_revision=None)

    result = create_release_migration(repo_root)

    assert result.created is True
    assert result.path == versions_dir / "v0_2_0.py"
    created_text = result.path.read_text(encoding="utf-8")
    assert 'revision = "v0_2_0"' in created_text
    assert 'down_revision = "v0_1_0"' in created_text
    assert "ECUBE release-scoped migration for v0.2.0" in created_text


def test_autogenerate_release_migration_requires_existing_release_file(tmp_path: Path) -> None:
    repo_root = tmp_path
    versions_dir = repo_root / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    _write_pyproject(repo_root, "0.2.0")

    with pytest.raises(ReleaseMigrationError, match="Run 'ecube-release-migration create' first"):
        autogenerate_release_migration(repo_root)


def test_autogenerate_release_migration_replaces_existing_release_file(tmp_path: Path) -> None:
    repo_root = tmp_path
    versions_dir = repo_root / "alembic" / "versions"
    versions_dir.mkdir(parents=True)
    _write_pyproject(repo_root, "0.2.0")
    release_path = versions_dir / "v0_2_0.py"
    _write_migration(release_path, revision="v0_2_0", down_revision=None)

    generated_path = versions_dir / "generated.py"
    generated_path.write_text(
        """
revision: str = "v0_2_0"
down_revision: str | None = None
branch_labels = None
depends_on = None
""".strip(),
        encoding="utf-8",
    )

    temp_dir = versions_dir / "ecube-release-migration-temp"
    temp_dir.mkdir()

    with patch("app.utils.release_migration._run_autogenerate_revision", return_value=(generated_path, temp_dir)):
        result = autogenerate_release_migration(repo_root)

    assert result.path == release_path
    assert result.revision == "v0_2_0"
    assert release_path.read_text(encoding="utf-8").startswith('revision: str = "v0_2_0"')
    assert not generated_path.exists()
    assert not release_path.with_suffix(".py.bak").exists()
    assert not temp_dir.exists()