import os
import subprocess
from pathlib import Path


def test_post_install_demo_setup_creates_missing_local_database(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    install_dir = tmp_path / "install"
    demo_data_dir = install_dir / "demo-data"
    env_file = install_dir / ".env"
    source_metadata = tmp_path / "demo-metadata.json"
    fake_bin = tmp_path / "bin"
    state_file = tmp_path / "psql-state.txt"
    psql_log = tmp_path / "psql.log"
    bootstrap_log = tmp_path / "bootstrap.log"

    source_metadata.write_text(
        '{"demo_config": {"shared_password": "Scene.9Pratt"}}',
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin").mkdir(parents=True)
    (install_dir / "venv" / "bin" / "ecube-demo-bootstrap").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${BOOTSTRAP_LOG:?}\"\n",
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin" / "ecube-demo-bootstrap").chmod(0o755)

    fake_bin.mkdir()
    (fake_bin / "sudo").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ ${1:-} == -u ]]; then\n"
        "  shift 2\n"
        "fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "sudo").chmod(0o755)
    (fake_bin / "psql").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${FAKE_PSQL_LOG:?}\"\n"
        "command_line=\"$*\"\n"
        "if [[ \"${command_line}\" == *\"SELECT 1\"* && \"${command_line}\" != *\"FROM pg_database\"* ]]; then\n"
        "  printf '1\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"${command_line}\" == *\"FROM pg_database\"* ]]; then\n"
        "  if [[ -f \"${FAKE_PSQL_STATE}\" ]] && grep -q '^created=1$' \"${FAKE_PSQL_STATE}\"; then\n"
        "    printf '1\\n'\n"
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"${command_line}\" == *\"CREATE DATABASE \\\"ecube\\\" OWNER \\\"ecube\\\";\"* ]]; then\n"
        "  printf 'created=1\\n' > \"${FAKE_PSQL_STATE}\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "psql").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "INSTALL_DIR": str(install_dir),
        "DEMO_DATA_DIR": str(demo_data_dir),
        "SOURCE_METADATA": str(source_metadata),
        "ENV_FILE": str(env_file),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_STATE": str(state_file),
        "FAKE_PSQL_LOG": str(psql_log),
    }

    result = subprocess.run(
        ["bash", "./scripts/post_install_demo_setup.sh"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )

    assert result.returncode == 0, (
        f"post_install_demo_setup.sh failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert env_file.read_text(encoding="utf-8") == "DATABASE_URL=postgresql://ecube:ecube@localhost/ecube\n"
    assert (demo_data_dir / "demo-metadata.json").read_text(encoding="utf-8") == source_metadata.read_text(encoding="utf-8")
    assert "CREATE DATABASE \"ecube\" OWNER \"ecube\";" in psql_log.read_text(encoding="utf-8")
    assert bootstrap_log.read_text(encoding="utf-8").strip() == f"--data-root {demo_data_dir} seed"