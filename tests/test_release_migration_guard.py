from pathlib import Path

from scripts.check_release_migration import (
    build_error_message,
    disallowed_changed_migration_paths,
    expected_release_migration_path,
)


def test_expected_release_migration_path_uses_project_version() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    path = expected_release_migration_path(repo_root)

    assert path == repo_root / "alembic" / "versions" / "v0_2_0.py"


def test_disallowed_changed_migration_paths_ignores_current_release_file() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    disallowed = disallowed_changed_migration_paths(
        repo_root,
        ["alembic/versions/v0_2_0.py", "app/services/job_service.py"],
    )

    assert disallowed == []


def test_disallowed_changed_migration_paths_rejects_second_release_file() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    disallowed = disallowed_changed_migration_paths(
        repo_root,
        ["alembic/versions/v0_2_1_add_archived_job_status.py"],
    )

    assert disallowed == [repo_root / "alembic" / "versions" / "v0_2_1_add_archived_job_status.py"]


def test_build_error_message_references_expected_release_file() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    disallowed = [repo_root / "alembic" / "versions" / "v0_2_1_add_archived_job_status.py"]

    message = build_error_message(repo_root, disallowed)

    assert "alembic/versions/v0_2_0.py" in message
    assert "v0_2_1_add_archived_job_status.py" in message
    assert "ecube-release-migration" in message