import os
import stat
import subprocess
import textwrap
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_package_local_generates_help_before_frontend_build(tmp_path):
    source_repo_root = Path(__file__).resolve().parent.parent
    repo_root = tmp_path / "repo"
    package_script = repo_root / "scripts" / "package-local.sh"
    package_script.parent.mkdir(parents=True)
    package_script.write_text(
        (source_repo_root / "scripts" / "package-local.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    package_script.chmod(0o755)

    (repo_root / "app").mkdir(parents=True)
    (repo_root / "alembic").mkdir()
    (repo_root / "deploy").mkdir()
    (repo_root / "frontend").mkdir()

    for relative_path in ["install.sh", "pyproject.toml", "alembic.ini", "README.md", "LICENSE"]:
        (repo_root / relative_path).write_text("placeholder\n", encoding="utf-8")

    npm_log = tmp_path / "npm.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    _write_executable(
        fake_bin / "npm",
        textwrap.dedent(
            f"""#!/usr/bin/env bash
            set -Eeuo pipefail
            printf '%s\n' "$*" >> {npm_log}

            if [[ "$*" == "run build:help" ]]; then
              mkdir -p public/help
              printf '%s\n' '<html>generated help</html>' > public/help/manual.html
              exit 0
            fi

            if [[ "$*" == "run build" ]]; then
              mkdir -p dist/help
              cp public/help/manual.html dist/help/manual.html
              printf '%s\n' 'built frontend' > dist/index.html
              exit 0
            fi

            exit 0
            """
        ),
    )
    _write_executable(fake_bin / "tar", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(fake_bin / "sha256sum", "#!/usr/bin/env bash\nexit 0\n")

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["bash", str(package_script), "--artifact-name", "test-artifact", "--build-only"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, (
        f"package-local.sh failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert npm_log.read_text(encoding="utf-8").splitlines() == ["ci", "run build:help", "run build"]
    assert (repo_root / "frontend" / "public" / "help" / "manual.html").read_text(encoding="utf-8") == (
        "<html>generated help</html>\n"
    )
    assert (repo_root / "dist" / "test-artifact" / "dist" / "help" / "manual.html").exists()