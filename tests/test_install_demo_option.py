import json
import os
import subprocess
from pathlib import Path
import textwrap


def test_install_demo_tasks_seed_and_rewrite_server(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    install_dir = tmp_path / "install"
    env_file = install_dir / ".env"
    fake_bin = tmp_path / "bin"
    fake_devices = tmp_path / "devices"
    psql_state = tmp_path / "psql-state.txt"
    psql_log = tmp_path / "psql.log"
    alembic_log = tmp_path / "alembic.log"
    bootstrap_log = tmp_path / "bootstrap.log"
    chown_log = tmp_path / "chown.log"

    install_dir.mkdir()
    env_file.write_text(
        "SECRET_KEY=test\nDATABASE_URL=\nSETUP_DEFAULT_ADMIN_USERNAME=\n",
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin").mkdir(parents=True)
    (install_dir / "venv" / "bin" / "alembic").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${ALEMBIC_LOG:?}\"\n",
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin" / "alembic").chmod(0o755)
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
    (fake_bin / "runuser").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ ${1:-} == -u ]]; then\n"
        "  shift 3\n"
        "fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "runuser").chmod(0o755)
    (fake_bin / "chown").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${CHOWN_LOG:?}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "chown").chmod(0o755)
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
        "LOG_FILE": str(tmp_path / "install.log"),
        "CHOWN_LOG": str(chown_log),
        "ALEMBIC_LOG": str(alembic_log),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_LOG": str(psql_log),
        "FAKE_PSQL_STATE": str(psql_state),
    }

    script = textwrap.dedent(
        f"""
        set -e
        cd {repo_root}
        source ./install.sh
        INSTALL_DIR={install_dir}
        DEMO_INSTALL=true
        DRY_RUN=false
        _run_demo_install_tasks
        """
    )
    result = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, (
        f"demo installer tasks failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    env_text = env_file.read_text(encoding="utf-8")
    assert "DEMO_MODE=true\n" in env_text
    assert "DATABASE_URL=postgresql://ecube:ecube@localhost/ecube\n" in env_text

    assert f"ecube:ecube {install_dir / '.env'}" in chown_log.read_text(encoding="utf-8")
    assert 'CREATE DATABASE "ecube" OWNER "ecube";' in psql_log.read_text(encoding="utf-8")
    assert alembic_log.read_text(encoding="utf-8").strip() == "upgrade head"
    bootstrap_args = bootstrap_log.read_text(encoding="utf-8").strip()
    assert f"--metadata-path {install_dir / 'demo-metadata.json'}" in bootstrap_args
    assert " seed --shared-password " in bootstrap_args
    installed_metadata = json.loads((install_dir / "demo-metadata.json").read_text(encoding="utf-8"))
    generated_password = installed_metadata["demo_config"]["shared_password"]
    assert generated_password
    assert bootstrap_args.endswith(generated_password)
    source_metadata = json.loads((repo_root / "demo-metadata.json").read_text(encoding="utf-8"))
    assert source_metadata["demo_config"]["shared_password"] == ""
    assert installed_metadata["demo_config"]["accounts"] == source_metadata["demo_config"]["accounts"]


def test_install_demo_tasks_do_not_mutate_env_before_demo_metadata_validation(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    install_dir = tmp_path / "install"
    env_file = install_dir / ".env"
    source_metadata = tmp_path / "demo-metadata.json"
    fake_bin = tmp_path / "bin"
    psql_state = tmp_path / "psql-state.txt"
    psql_log = tmp_path / "psql.log"
    alembic_log = tmp_path / "alembic.log"
    bootstrap_log = tmp_path / "bootstrap.log"
    chown_log = tmp_path / "chown.log"

    install_dir.mkdir()
    env_file.write_text(
        "SECRET_KEY=test\nDATABASE_URL=\nSETUP_DEFAULT_ADMIN_USERNAME=\n",
        encoding="utf-8",
    )
    original_env_text = env_file.read_text(encoding="utf-8")
    source_metadata.write_text(
        json.dumps(
            {
                "managed_by": "ecube-demo-seed-v1",
                "demo_config": {
                    "accounts": [
                        {
                            "username": "demo_admin",
                            "label": "Admin demo",
                            "description": "Guided walkthrough",
                            "roles": ["admin"],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin").mkdir(parents=True)
    (install_dir / "venv" / "bin" / "alembic").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${ALEMBIC_LOG:?}\"\n",
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin" / "alembic").chmod(0o755)
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
    (fake_bin / "runuser").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ ${1:-} == -u ]]; then\n"
        "  shift 3\n"
        "fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "runuser").chmod(0o755)
    (fake_bin / "chown").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${CHOWN_LOG:?}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "chown").chmod(0o755)
    (fake_bin / "psql").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${FAKE_PSQL_LOG:?}\"\n"
        "printf 'created=1\\n' > \"${FAKE_PSQL_STATE}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "psql").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
        "CHOWN_LOG": str(chown_log),
        "ALEMBIC_LOG": str(alembic_log),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_LOG": str(psql_log),
        "FAKE_PSQL_STATE": str(psql_state),
    }

    script = textwrap.dedent(
        f"""
        set +e
        cd {repo_root}
        source ./install.sh
        INSTALL_DIR={install_dir}
        DEMO_INSTALL=true
        DRY_RUN=false
        _demo_metadata_source_path() {{ printf '%s' {source_metadata}; }}
        _run_demo_install_tasks
        status=$?
        exit $status
        """
    )
    result = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, (
        f"demo installer tasks without shared password failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert env_file.read_text(encoding="utf-8") != original_env_text
    bootstrap_args = bootstrap_log.read_text(encoding="utf-8").strip()
    assert f"--metadata-path {install_dir / 'demo-metadata.json'}" in bootstrap_args
    assert " seed --shared-password " in bootstrap_args
    installed_metadata = json.loads((install_dir / "demo-metadata.json").read_text(encoding="utf-8"))
    generated_password = installed_metadata["demo_config"]["shared_password"]
    assert generated_password
    assert bootstrap_args.endswith(generated_password)
    source_payload = json.loads(source_metadata.read_text(encoding="utf-8"))
    assert installed_metadata["managed_by"] == source_payload["managed_by"]
    assert installed_metadata["demo_config"]["accounts"] == source_payload["demo_config"]["accounts"]
    assert psql_log.exists()
    assert alembic_log.exists()
    assert chown_log.exists()


def test_install_demo_tasks_do_not_mutate_env_before_demo_metadata_presence_validation(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    install_dir = tmp_path / "install"
    env_file = install_dir / ".env"
    source_metadata = tmp_path / "missing-demo-metadata.json"
    fake_bin = tmp_path / "bin"
    psql_state = tmp_path / "psql-state.txt"
    psql_log = tmp_path / "psql.log"
    alembic_log = tmp_path / "alembic.log"
    bootstrap_log = tmp_path / "bootstrap.log"
    chown_log = tmp_path / "chown.log"

    install_dir.mkdir()
    env_file.write_text(
        "SECRET_KEY=test\nDATABASE_URL=\nSETUP_DEFAULT_ADMIN_USERNAME=\n",
        encoding="utf-8",
    )
    original_env_text = env_file.read_text(encoding="utf-8")
    (install_dir / "venv" / "bin").mkdir(parents=True)
    (install_dir / "venv" / "bin" / "alembic").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" > \"${ALEMBIC_LOG:?}\"\n",
        encoding="utf-8",
    )
    (install_dir / "venv" / "bin" / "alembic").chmod(0o755)
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
    (fake_bin / "runuser").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ ${1:-} == -u ]]; then\n"
        "  shift 3\n"
        "fi\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "runuser").chmod(0o755)
    (fake_bin / "chown").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${CHOWN_LOG:?}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "chown").chmod(0o755)
    (fake_bin / "psql").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${FAKE_PSQL_LOG:?}\"\n"
        "printf 'created=1\\n' > \"${FAKE_PSQL_STATE}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "psql").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
        "CHOWN_LOG": str(chown_log),
        "ALEMBIC_LOG": str(alembic_log),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_LOG": str(psql_log),
        "FAKE_PSQL_STATE": str(psql_state),
    }

    script = textwrap.dedent(
        f"""
        set +e
        cd {repo_root}
        source ./install.sh
        INSTALL_DIR={install_dir}
        DEMO_INSTALL=true
        DRY_RUN=false
        _demo_metadata_source_path() {{ printf '%s' {source_metadata}; }}
        _run_demo_install_tasks
        status=$?
        exit $status
        """
    )
    result = subprocess.run(
        ["bash", "-lc", script],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert "--demo requires demo-metadata.json" in result.stderr
    assert env_file.read_text(encoding="utf-8") == original_env_text
    assert not (install_dir / "demo-metadata.json").exists()
    assert not psql_log.exists()
    assert not alembic_log.exists()
    assert not bootstrap_log.exists()
    assert not chown_log.exists()