"""Linux password policy and password-expiration inspection service."""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import date, datetime
from pathlib import Path

from app.config import settings
from app.infrastructure.password_policy_protocol import (
    PasswordExpirationInfo,
    PasswordPolicyError,
)
from app.utils.password_policy import (
    WRITABLE_PASSWORD_POLICY_KEYS,
    parse_pwquality_policy_values,
)

logger = logging.getLogger(__name__)

_SUBPROCESS_TIMEOUT = settings.subprocess_timeout_seconds
_ENFORCE_FOR_ROOT_LINE = "enforce_for_root = 1"


def _run_root_command(cmd: list[str], *, stdin_data: str | None = None) -> subprocess.CompletedProcess[str]:
    full_cmd = ["sudo", "-n", *cmd] if settings.use_sudo else cmd
    try:
        result = subprocess.run(
            full_cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PasswordPolicyError("Password policy command timed out") from exc

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "Password policy command failed").strip()
        raise PasswordPolicyError(stderr)
    return result


def _read_pwquality_text() -> str:
    path = Path(settings.pwquality_conf_path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _render_updated_policy(existing_text: str, values: dict[str, int]) -> str:
    remaining_keys = set(WRITABLE_PASSWORD_POLICY_KEYS)
    enforce_written = False
    rendered_lines: list[str] = []

    for raw_line in existing_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rendered_lines.append(raw_line)
            continue

        key, _ = [part.strip() for part in stripped.split("=", 1)]
        if key in remaining_keys:
            rendered_lines.append(f"{key} = {values[key]}")
            remaining_keys.remove(key)
            continue
        if key == "enforce_for_root":
            rendered_lines.append(_ENFORCE_FOR_ROOT_LINE)
            enforce_written = True
            continue
        rendered_lines.append(raw_line)

    if rendered_lines and rendered_lines[-1].strip():
        rendered_lines.append("")

    for key in WRITABLE_PASSWORD_POLICY_KEYS:
        if key in remaining_keys:
            rendered_lines.append(f"{key} = {values[key]}")

    if not enforce_written:
        rendered_lines.append(_ENFORCE_FOR_ROOT_LINE)

    return "\n".join(rendered_lines).rstrip() + "\n"


def _write_policy_text(text: str) -> None:
    target_path = Path(settings.pwquality_conf_path)

    if settings.use_sudo:
        helper_path = str(settings.password_policy_writer_path).strip()
        if not helper_path:
            raise PasswordPolicyError("Password policy writer helper is not configured")
        _run_root_command([helper_path], stdin_data=text)
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, target_path)


def _parse_chage_list(stdout: str) -> PasswordExpirationInfo | None:
    fields: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        fields[key.strip().lower()] = value.strip()

    expires_text = fields.get("password expires")
    warning_text = fields.get("number of days of warning before password expires")
    if not expires_text:
        return None

    try:
        warning_days = int(warning_text) if warning_text else 14
    except ValueError:
        warning_days = 14

    if expires_text.lower() == "never":
        return PasswordExpirationInfo(days_until_expiration=None, warning_days=warning_days, warning_active=False)

    try:
        expires_on = datetime.strptime(expires_text, "%b %d, %Y").date()
    except ValueError:
        logger.debug(
            "Unable to parse password expiration date",
            extra={"expires_text": expires_text},
        )
        return None

    days_until = (expires_on - date.today()).days
    return PasswordExpirationInfo(
        days_until_expiration=days_until,
        warning_days=warning_days,
        warning_active=days_until >= 0 and days_until <= warning_days,
    )


class LinuxPasswordPolicyProvider:
    """Linux implementation for PAM password policy and expiry inspection."""

    def get_policy_settings(self) -> dict[str, int]:
        return parse_pwquality_policy_values(_read_pwquality_text())

    def update_policy_settings(self, updates: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
        unknown_keys = sorted(set(updates) - set(WRITABLE_PASSWORD_POLICY_KEYS))
        if unknown_keys:
            raise ValueError(f"Unknown password policy key(s): {', '.join(unknown_keys)}")

        existing_text = _read_pwquality_text()
        previous_values = parse_pwquality_policy_values(existing_text)
        next_values = dict(previous_values)
        next_values.update(updates)

        _write_policy_text(_render_updated_policy(existing_text, next_values))
        return previous_values, next_values

    def get_password_expiration_info(self, username: str) -> PasswordExpirationInfo | None:
        try:
            result = _run_root_command([settings.chage_binary_path, "-l", username])
        except PasswordPolicyError as exc:
            logger.info(
                "Password expiration inspection unavailable",
                extra={"operation_surface": "auth.login", "failure_category": "expiration_check_unavailable"},
            )
            logger.debug(
                "Password expiration inspection diagnostic",
                extra={"username": username, "detail": exc.message},
            )
            return None
        return _parse_chage_list(result.stdout)