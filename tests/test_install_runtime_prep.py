import os
import subprocess
import textwrap
from pathlib import Path


def _run_install_function(tmp_path: Path, script_body: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
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


def test_ensure_runtime_host_packages_adds_kernel_extras_when_available(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    apt_log = tmp_path / "apt.log"

    (fake_bin / "dpkg").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "dpkg").chmod(0o755)
    (fake_bin / "apt-cache").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == show && \"${2:-}\" == \"linux-modules-extra-6.8.0-test\" ]]; then\n"
        "  printf 'Package: %s\\n' \"$2\"\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "apt-cache").chmod(0o755)
    (fake_bin / "apt-get").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' \"$*\" >> \"${APT_LOG:?}\"\n",
        encoding="utf-8",
    )
    (fake_bin / "apt-get").chmod(0o755)
    (fake_bin / "uname").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"${1:-}\" == -r ]]; then\n"
        "  printf '6.8.0-test\\n'\n"
          "else\n"
        "  /usr/bin/uname \"$@\"\n"
        "fi\n",
        encoding="utf-8",
    )
    (fake_bin / "uname").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "APT_LOG": str(apt_log),
        "LOG_FILE": str(tmp_path / "install.log"),
    }
    result = _run_install_function(
        tmp_path,
        "ID=ubuntu\nID_LIKE=debian\nDRY_RUN=false\n_ensure_runtime_host_packages\n",
        env,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    apt_commands = apt_log.read_text(encoding="utf-8")
    assert "update -qq" in apt_commands
    assert "install -y" in apt_commands
    assert "exfatprogs" in apt_commands
    assert "linux-modules-extra-6.8.0-test" in apt_commands


def test_prepare_managed_mount_roots_honors_usb_mount_base_path_from_env(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / ".env").write_text("USB_MOUNT_BASE_PATH=/srv/ecube-usb\n", encoding="utf-8")

    for command in ("mkdir", "chown", "chmod"):
        (fake_bin / command).write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf '{command} %s\\n' \"$*\" >> \"${{COMMAND_LOG:?}}\"\n",
            encoding="utf-8",
        )
        (fake_bin / command).chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "COMMAND_LOG": str(command_log),
        "LOG_FILE": str(tmp_path / "install.log"),
    }
    result = _run_install_function(
        tmp_path,
        f"INSTALL_DIR={install_dir}\nDRY_RUN=false\n_prepare_managed_mount_roots\n",
        env,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    commands = command_log.read_text(encoding="utf-8")
    assert "mkdir -p /nfs /smb /srv/ecube-usb" in commands
    assert "chown ecube:ecube /nfs /smb /srv/ecube-usb" in commands
    assert "chmod 755 /nfs /smb /srv/ecube-usb" in commands


def test_prepare_managed_mount_roots_honors_installer_environment_before_env_exists(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "commands.log"
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    for command in ("mkdir", "chown", "chmod"):
        (fake_bin / command).write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"printf '{command} %s\\n' \"$*\" >> \"${{COMMAND_LOG:?}}\"\n",
            encoding="utf-8",
        )
        (fake_bin / command).chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "COMMAND_LOG": str(command_log),
        "LOG_FILE": str(tmp_path / "install.log"),
        "USB_MOUNT_BASE_PATH": "/srv/ecube-usb",
    }
    result = _run_install_function(
        tmp_path,
        f"INSTALL_DIR={install_dir}\nDRY_RUN=false\n_prepare_managed_mount_roots\n",
        env,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    commands = command_log.read_text(encoding="utf-8")
    assert "mkdir -p /nfs /smb /srv/ecube-usb" in commands
    assert "chown ecube:ecube /nfs /smb /srv/ecube-usb" in commands
    assert "chmod 755 /nfs /smb /srv/ecube-usb" in commands


def test_write_env_file_persists_configured_usb_mount_base_path(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    install_dir = tmp_path / "install"
    install_dir.mkdir()

    (fake_bin / "chown").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "chown").chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "USB_MOUNT_BASE_PATH": "/srv/ecube-usb",
    }
    result = _run_install_function(
        tmp_path,
        f"INSTALL_DIR={install_dir}\nLOG_FILE={tmp_path / 'install.log'}\nDRY_RUN=false\n_write_env_file\n",
        env,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    env_text = (install_dir / ".env").read_text(encoding="utf-8")
    assert "USB_MOUNT_BASE_PATH=/srv/ecube-usb\n" in env_text