import os
import subprocess
import textwrap
from pathlib import Path


def _run_install_function(script_body: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parent.parent
    script = textwrap.dedent(
        f"""
        set -euo pipefail
        cd {repo_root}
        source ./install.sh
        {script_body}
        """
    )
    return subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        env=env,
    )


def _write_fake_python(fake_bin: Path, command_name: str, version: str, *, has_venv: bool) -> None:
    major, minor = version.split(".", 1)
    script = textwrap.dedent(
        f"""
        #!/usr/bin/env bash
        set -euo pipefail
        if [[ "${{1:-}}" == "-c" ]]; then
          code="${{2:-}}"
          if [[ "${{code}}" == *"sys.version_info >="* ]]; then
            if (( {major} > 3 || ({major} == 3 && {minor} >= 11) )); then
              exit 0
            fi
            exit 1
          fi
          if [[ "${{code}}" == *"sys.version_info[0]"* && "${{code}}" == *"sys.version_info[1]"* ]]; then
            printf '{version}\n'
            exit 0
          fi
        fi

        if [[ "${{1:-}}" == "-m" && "${{2:-}}" == "venv" && "${{3:-}}" == "--help" ]]; then
          if [[ "{str(has_venv).lower()}" == "true" ]]; then
            printf 'venv help\n'
            exit 0
          fi
          exit 1
        fi

        echo "unexpected fake python invocation: $*" >&2
        exit 97
        """
    ).strip()
    target = fake_bin / command_name
    target.write_text(script + "\n", encoding="utf-8")
    target.chmod(0o755)


def test_resolve_compatible_python_bin_prefers_highest_supported_version(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_python(fake_bin, "python3.10", "3.10", has_venv=True)
    _write_fake_python(fake_bin, "python3.12", "3.12", has_venv=True)
    _write_fake_python(fake_bin, "python3.99", "3.99", has_venv=True)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
    }

    result = _run_install_function(
        textwrap.dedent(
            """
            _resolve_compatible_python_bin
            printf '%s\n%s\n%s\n' "$PYTHON_BIN" "$PYTHON_VERSION_MM" "$PYTHON_VENV_PACKAGE"
            """
        ),
        env,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    output_lines = result.stdout.strip().splitlines()
    assert output_lines == ["python3.99", "3.99", "python3.99-venv"]


def test_select_python_bin_tracks_matching_venv_package_and_detects_missing_venv(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_fake_python(fake_bin, "python3.12", "3.12", has_venv=False)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
    }

    result = _run_install_function(
        textwrap.dedent(
            """
            _select_python_bin python3.12
            printf '%s\n' "$PYTHON_VENV_PACKAGE"
            if _python_has_venv "$PYTHON_BIN"; then
              exit 9
            fi
            """
        ),
        env,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert result.stdout.strip() == "python3.12-venv"