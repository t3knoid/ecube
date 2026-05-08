import subprocess
from unittest.mock import patch

import pytest

from app.infrastructure.runtime_repair import LinuxRuntimeRepairProvider


def test_runtime_repair_uses_non_interactive_sudo_when_configured(monkeypatch):
    provider = LinuxRuntimeRepairProvider()

    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.use_sudo", True)
    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.modprobe_binary_path", "/usr/sbin/modprobe")
    monkeypatch.setattr("app.infrastructure.runtime_repair.os.geteuid", lambda: 1000)

    with patch("app.infrastructure.runtime_repair.subprocess.run") as run_mock:
        provider.load_kernel_module("exfat")

    run_mock.assert_called_once_with(
        ["sudo", "-n", "/usr/sbin/modprobe", "exfat"],
        check=True,
        capture_output=True,
        timeout=30,
    )


def test_runtime_repair_surfaces_sudoers_remediation(monkeypatch):
    provider = LinuxRuntimeRepairProvider()

    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.use_sudo", True)
    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.modprobe_binary_path", "/usr/sbin/modprobe")
    monkeypatch.setattr("app.infrastructure.runtime_repair.os.geteuid", lambda: 1000)

    with patch(
        "app.infrastructure.runtime_repair.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1,
            ["sudo", "-n", "/usr/sbin/modprobe", "exfat"],
            stderr=b"sudo: a password is required",
        ),
    ):
        with pytest.raises(RuntimeError, match="service account is not allowed"):
            provider.load_kernel_module("exfat")


def test_runtime_repair_surfaces_host_privilege_remediation(monkeypatch):
    provider = LinuxRuntimeRepairProvider()

    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.use_sudo", True)
    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.modprobe_binary_path", "/usr/sbin/modprobe")
    monkeypatch.setattr("app.infrastructure.runtime_repair.os.geteuid", lambda: 0)

    with patch(
        "app.infrastructure.runtime_repair.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1,
            ["/usr/sbin/modprobe", "exfat"],
            stderr=b"modprobe: ERROR: could not insert 'exfat': Operation not permitted",
        ),
    ):
        with pytest.raises(RuntimeError, match="host rejected the kernel module load"):
            provider.load_kernel_module("exfat")


def test_runtime_repair_surfaces_missing_modprobe_command(monkeypatch):
    provider = LinuxRuntimeRepairProvider()

    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.use_sudo", False)
    monkeypatch.setattr("app.infrastructure.runtime_repair.settings.modprobe_binary_path", "/usr/sbin/modprobe")

    with patch(
        "app.infrastructure.runtime_repair.subprocess.run",
        side_effect=FileNotFoundError("No such file or directory: '/usr/sbin/modprobe'"),
    ):
        with pytest.raises(RuntimeError, match="host modprobe command is unavailable"):
            provider.load_kernel_module("exfat")