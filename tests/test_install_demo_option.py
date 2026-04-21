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
    fake_devices.mkdir()
    (fake_devices / "sda").write_text("usb-a", encoding="utf-8")
    (fake_devices / "sdb").write_text("usb-b", encoding="utf-8")

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
    (fake_bin / "udevadm").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "device_arg=\"${*: -1}\"\n"
        "device_arg=\"${device_arg#--name=}\"\n"
        "case \"${device_arg}\" in\n"
        f"  {fake_devices / 'sda'})\n"
        "    cat <<'EOF'\n"
        "ID_SERIAL_SHORT=SERIAL-A\n"
        "DEVPATH=/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host0/target0:0:0/0:0:0:0/block/sda\n"
        "EOF\n"
        "    ;;\n"
        f"  {fake_devices / 'sdb'})\n"
        "    cat <<'EOF'\n"
        "ID_SERIAL_SHORT=SERIAL-B\n"
        "DEVPATH=/devices/pci0000:00/0000:00:14.0/usb2/2-2/2-2:1.0/host0/target0:0:0/0:0:0:0/block/sdb\n"
        "EOF\n"
        "    ;;\n"
        "  *)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (fake_bin / "udevadm").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
        "CHOWN_LOG": str(chown_log),
        "ALEMBIC_LOG": str(alembic_log),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_LOG": str(psql_log),
        "FAKE_PSQL_STATE": str(psql_state),
        "DEMO_USB_DEVICE_GLOB": str(fake_devices / "sd?"),
        "DEMO_USB_ALLOW_NONBLOCK": "true",
    }

    script = textwrap.dedent(
        f"""
        set -e
        cd {repo_root}
        source ./install.sh
        INSTALL_DIR={install_dir}
        DEMO_INSTALL=true
        DEMO_SERVER=10.20.30.40
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
    assert "DEMO_DATA_ROOT=" in env_text
    assert "DATABASE_URL=postgresql://ecube:ecube@localhost/ecube\n" in env_text

    installed_metadata = json.loads((install_dir / "demo-metadata.json").read_text(encoding="utf-8"))
    assert installed_metadata["managed_by"] == "ecube-demo-seed-v1"
    assert installed_metadata["generated_at"] is None
    assert installed_metadata["demo_config"]["demo_mode"] is True
    assert installed_metadata["demo_config"]["login_message"] == "Use the shared demo accounts below."
    assert installed_metadata["demo_config"]["shared_password"] == "Scene.9Pratt"
    assert installed_metadata["demo_config"]["demo_disable_password_change"] is True
    assert installed_metadata["demo_config"]["password_change_allowed"] is False
    assert installed_metadata["demo_config"]["accounts"][0]["username"] == "demo_admin"
    assert installed_metadata["usb_seed"]["drives"][0]["device_identifier"] == "SERIAL-A"
    assert installed_metadata["usb_seed"]["drives"][1]["device_identifier"] == "SERIAL-B"
    assert installed_metadata["projects"][0]["project_name"] == "DEMO-CASE-001"
    assert installed_metadata["projects"][1]["project_name"] == "DEMO-CASE-002"
    assert installed_metadata["projects"][0]["folder"] == "demo-case-001"
    assert installed_metadata["projects"][1]["folder"] == "demo-case-002"
    assert not (install_dir / "demo-data" / "demo-metadata.json").exists()
    mounts = installed_metadata["mount_seed"]["mounts"]
    assert mounts[0]["remote_path"] == "10.20.30.40:/mnt/Data/ecube/demo-case-001"
    assert mounts[1]["remote_path"] == "//10.20.30.40/demo-case-002"
    assert installed_metadata["job_seed"]["jobs"][0]["status"] == "PENDING"
    assert installed_metadata["job_seed"]["jobs"][0]["evidence_number"] == "EVID-DEMO-JOB-001"
    assert installed_metadata["job_seed"]["jobs"][0]["source_path"] == "/incoming"
    assert installed_metadata["job_seed"]["jobs"][1]["status"] == "PENDING"
    assert f"-R ecube:ecube {install_dir}" in chown_log.read_text(encoding="utf-8")
    assert 'CREATE DATABASE "ecube" OWNER "ecube";' in psql_log.read_text(encoding="utf-8")
    assert alembic_log.read_text(encoding="utf-8").strip() == "upgrade head"
    assert not bootstrap_log.exists()


def test_install_demo_tasks_metadata_only_generates_metadata(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    install_dir = tmp_path / "install"
    env_file = install_dir / ".env"
    fake_bin = tmp_path / "bin"
    fake_devices = tmp_path / "devices"
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
    fake_devices.mkdir()
    (fake_devices / "sda").write_text("usb-a", encoding="utf-8")

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
        "printf '%s\\n' \"$*\" >> \"${FAKE_PSQL_LOG:?}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "psql").chmod(0o755)
    (fake_bin / "udevadm").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "device_arg=\"${*: -1}\"\n"
        "device_arg=\"${device_arg#--name=}\"\n"
        "case \"${device_arg}\" in\n"
        f"  {fake_devices / 'sda'})\n"
        "    cat <<'EOF'\n"
        "ID_SERIAL_SHORT=SERIAL-A\n"
        "DEVPATH=/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host0/target0:0:0/0:0:0:0/block/sda\n"
        "EOF\n"
        "    ;;\n"
        "  *)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (fake_bin / "udevadm").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
        "CHOWN_LOG": str(chown_log),
        "ALEMBIC_LOG": str(alembic_log),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_LOG": str(psql_log),
        "DEMO_USB_DEVICE_GLOB": str(fake_devices / "sd?"),
        "DEMO_USB_ALLOW_NONBLOCK": "true",
    }

    script = textwrap.dedent(
        f"""
        set -e
        cd {repo_root}
        source ./install.sh
        INSTALL_DIR={install_dir}
        DEMO_INSTALL=true
        DEMO_METADATA_ONLY=true
        DEMO_SERVER=10.20.30.40
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
        f"metadata-only demo installer tasks failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert env_file.read_text(encoding="utf-8") == original_env_text

    installed_metadata = json.loads((install_dir / "demo-metadata.json").read_text(encoding="utf-8"))
    assert installed_metadata["managed_by"] == "ecube-demo-seed-v1"
    assert installed_metadata["generated_at"] is None
    assert installed_metadata["demo_config"]["shared_password"] == "Scene.9Pratt"
    assert installed_metadata["projects"][0]["project_name"] == "DEMO-CASE-001"
    assert installed_metadata["usb_seed"]["drives"][0]["device_identifier"] == "SERIAL-A"
    assert installed_metadata["mount_seed"]["mounts"][0]["remote_path"] == "10.20.30.40:/mnt/Data/ecube/demo-case-001"
    assert installed_metadata["job_seed"]["jobs"][0]["status"] == "PENDING"
    assert installed_metadata["job_seed"]["jobs"][0]["project_id"] == 1
    assert f"-R ecube:ecube {install_dir}" in chown_log.read_text(encoding="utf-8")
    assert not psql_log.exists() or psql_log.read_text(encoding="utf-8") == ""
    assert not alembic_log.exists()
    assert not bootstrap_log.exists()


def test_install_demo_tasks_metadata_only_writes_custom_output_path(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    install_dir = tmp_path / "install"
    env_file = install_dir / ".env"
    metadata_output = tmp_path / "exports" / "demo-metadata.json"
    fake_bin = tmp_path / "bin"
    fake_devices = tmp_path / "devices"
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
    fake_devices.mkdir()
    (fake_devices / "sda").write_text("usb-a", encoding="utf-8")

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
        "printf '%s\\n' \"$*\" >> \"${FAKE_PSQL_LOG:?}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "psql").chmod(0o755)
    (fake_bin / "udevadm").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "device_arg=\"${*: -1}\"\n"
        "device_arg=\"${device_arg#--name=}\"\n"
        "case \"${device_arg}\" in\n"
        f"  {fake_devices / 'sda'})\n"
        "    cat <<'EOF'\n"
        "ID_SERIAL_SHORT=SERIAL-A\n"
        "DEVPATH=/devices/pci0000:00/0000:00:14.0/usb2/2-1/2-1:1.0/host0/target0:0:0/0:0:0:0/block/sda\n"
        "EOF\n"
        "    ;;\n"
        "  *)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    (fake_bin / "udevadm").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "LOG_FILE": str(tmp_path / "install.log"),
        "CHOWN_LOG": str(chown_log),
        "ALEMBIC_LOG": str(alembic_log),
        "BOOTSTRAP_LOG": str(bootstrap_log),
        "FAKE_PSQL_LOG": str(psql_log),
        "DEMO_USB_DEVICE_GLOB": str(fake_devices / "sd?"),
        "DEMO_USB_ALLOW_NONBLOCK": "true",
    }

    script = textwrap.dedent(
        f"""
        set -e
        cd {repo_root}
        source ./install.sh
        INSTALL_DIR={install_dir}
        DEMO_INSTALL=true
        DEMO_METADATA_ONLY=true
        DEMO_SERVER=10.20.30.40
        DEMO_METADATA_OUTPUT={metadata_output}
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
        f"metadata-only custom-output demo installer tasks failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert env_file.read_text(encoding="utf-8") == original_env_text

    installed_metadata = json.loads(metadata_output.read_text(encoding="utf-8"))
    assert installed_metadata["generated_at"] is None
    assert installed_metadata["demo_config"]["shared_password"] == "Scene.9Pratt"
    assert installed_metadata["projects"][0]["project_name"] == "DEMO-CASE-001"
    assert installed_metadata["usb_seed"]["drives"][0]["device_identifier"] == "SERIAL-A"
    assert installed_metadata["mount_seed"]["mounts"][0]["remote_path"] == "10.20.30.40:/mnt/Data/ecube/demo-case-001"
    assert installed_metadata["job_seed"]["jobs"][0]["status"] == "PENDING"
    assert not (install_dir / "demo-metadata.json").exists()
    assert f"-R ecube:ecube {metadata_output.parent}" in chown_log.read_text(encoding="utf-8")
    assert not psql_log.exists() or psql_log.read_text(encoding="utf-8") == ""
    assert not alembic_log.exists()
    assert not bootstrap_log.exists()


def test_main_metadata_only_skips_install_backend(tmp_path):
        repo_root = Path(__file__).resolve().parent.parent
        marker_file = tmp_path / "metadata-only-ran.txt"

        script = textwrap.dedent(
                f"""
                set -e
                cd {repo_root}
                source ./install.sh
                DEMO_INSTALL=true
                DEMO_METADATA_ONLY=true
                DEMO_SERVER=10.20.30.40
                LOG_FILE={tmp_path / 'install.log'}
                _run_demo_install_tasks() {{
                    printf 'ran\n' > {marker_file}
                }}
                install_backend() {{
                    echo install_backend_should_not_run >&2
                    return 99
                }}
                preflight() {{
                    echo preflight_should_not_run >&2
                    return 98
                }}
                configure_firewall() {{
                    echo firewall_should_not_run >&2
                    return 97
                }}
                print_summary() {{
                    echo print_summary_should_not_run >&2
                    return 96
                }}
                main
                """
        )
        result = subprocess.run(
                ["bash", "-lc", script],
                capture_output=True,
                text=True,
        )

        assert result.returncode == 0, (
                f"metadata-only main flow failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert marker_file.read_text(encoding="utf-8").strip() == "ran"
        assert "install_backend_should_not_run" not in result.stderr
        assert "preflight_should_not_run" not in result.stderr
        assert "firewall_should_not_run" not in result.stderr
        assert "print_summary_should_not_run" not in result.stderr