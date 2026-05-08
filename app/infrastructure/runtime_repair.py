"""Trusted host runtime-repair operations for explicit operator actions."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Protocol

from app.config import settings
from app.utils.sanitize import sanitize_error_message


logger = logging.getLogger(__name__)

_MODULE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class RuntimeRepairProvider(Protocol):
    """Run explicit host repair actions through the trusted system layer."""

    def load_kernel_module(self, module_name: str) -> None:
        """Load a kernel module needed by a runtime repair action."""
        ...


class LinuxRuntimeRepairProvider:
    """Linux runtime-repair implementation using explicit subprocess calls."""

    def load_kernel_module(self, module_name: str) -> None:
        normalized_module_name = str(module_name or "").strip()
        if not normalized_module_name or not _MODULE_NAME_PATTERN.fullmatch(normalized_module_name):
            raise RuntimeError("Invalid kernel module name")

        modprobe_path = str(getattr(settings, "modprobe_binary_path", "") or "").strip()
        if not modprobe_path:
            raise RuntimeError("The host modprobe command is unavailable")

        timeout_seconds = int(getattr(settings, "subprocess_timeout_seconds", 30) or 30)
        command = _with_sudo([modprobe_path, normalized_module_name])

        logger.info(
            "Runtime repair action started",
            extra={
                "context": {
                    "repair_action": "load_kernel_module",
                    "module_name": normalized_module_name,
                    "timeout_seconds": timeout_seconds,
                }
            },
        )
        logger.debug(
            "Runtime repair command details",
            extra={
                "context": {
                    "repair_action": "load_kernel_module",
                    "module_name": normalized_module_name,
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                }
            },
        )

        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "Runtime repair action command unavailable",
                extra={
                    "context": {
                        "repair_action": "load_kernel_module",
                        "module_name": normalized_module_name,
                        "failure_category": "runtime_repair_command_unavailable",
                    }
                },
            )
            logger.debug(
                "Runtime repair command unavailable details",
                extra={
                    "context": {
                        "repair_action": "load_kernel_module",
                        "module_name": normalized_module_name,
                        "command": command,
                        "raw_error": str(exc),
                    }
                },
            )
            raise RuntimeError("The host modprobe command is unavailable") from exc
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "Runtime repair action timed out",
                extra={
                    "context": {
                        "repair_action": "load_kernel_module",
                        "module_name": normalized_module_name,
                        "failure_category": "runtime_repair_timeout",
                    }
                },
            )
            logger.debug(
                "Runtime repair timeout details",
                extra={
                    "context": {
                        "repair_action": "load_kernel_module",
                        "module_name": normalized_module_name,
                        "command": command,
                        "timeout_seconds": timeout_seconds,
                        "raw_error": str(exc),
                    }
                },
            )
            raise RuntimeError(f"Kernel module load timed out after {timeout_seconds}s") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or b"").decode(errors="replace").strip()
            lowered_stderr = stderr.lower()
            if settings.use_sudo and (
                "a terminal is required" in lowered_stderr
                or "a password is required" in lowered_stderr
                or "no tty present" in lowered_stderr
                or "is not in the sudoers file" in lowered_stderr
            ):
                raise RuntimeError(
                    "The ECUBE service account is not allowed to run the host modprobe command non-interactively. "
                    "Install the ECUBE sudoers rules with modprobe enabled, then retry."
                ) from exc
            if "operation not permitted" in lowered_stderr:
                raise RuntimeError(
                    "The host rejected the kernel module load. Verify the ECUBE service is running with the required host privileges, then retry."
                ) from exc
            logger.warning(
                "Runtime repair action failed",
                extra={
                    "context": {
                        "repair_action": "load_kernel_module",
                        "module_name": normalized_module_name,
                        "failure_category": "runtime_repair_command_failed",
                        "reason": sanitize_error_message(stderr or "modprobe failed", "Kernel module load failed"),
                    }
                },
            )
            logger.debug(
                "Runtime repair failure details",
                extra={
                    "context": {
                        "repair_action": "load_kernel_module",
                        "module_name": normalized_module_name,
                        "command": command,
                        "returncode": exc.returncode,
                        "raw_error": stderr or str(exc),
                    }
                },
            )
            raise RuntimeError(stderr or "Kernel module load failed") from exc

        logger.info(
            "Runtime repair action completed",
            extra={
                "context": {
                    "repair_action": "load_kernel_module",
                    "module_name": normalized_module_name,
                }
            },
        )


def _with_sudo(cmd: list[str]) -> list[str]:
    if settings.use_sudo and os.geteuid() != 0:
        return ["sudo", "-n", *cmd]
    return cmd