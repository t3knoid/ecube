"""Admin configuration management service.

Provides a controlled allowlist of runtime-editable settings for the
frontend Configuration page and a helper to request service restarts.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List

from app.config import settings
from app.logging_config import configure_logging
from app.services import database_service

logger = logging.getLogger(__name__)

_SERVICE_NAME = "ecube"


@dataclass(frozen=True)
class _FieldSpec:
    env_key: str
    requires_restart: bool
    serializer: Callable[[Any], str]


def _serialize_plain(value: Any) -> str:
    return str(value)


def _serialize_log_file(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


_EDITABLE_FIELDS: Dict[str, _FieldSpec] = {
    "log_level": _FieldSpec("LOG_LEVEL", False, _serialize_plain),
    "log_format": _FieldSpec("LOG_FORMAT", False, _serialize_plain),
    "log_file": _FieldSpec("LOG_FILE", False, _serialize_log_file),
    "log_file_max_bytes": _FieldSpec("LOG_FILE_MAX_BYTES", False, _serialize_plain),
    "log_file_backup_count": _FieldSpec("LOG_FILE_BACKUP_COUNT", False, _serialize_plain),
    "db_pool_size": _FieldSpec("DB_POOL_SIZE", False, _serialize_plain),
    "db_pool_max_overflow": _FieldSpec("DB_POOL_MAX_OVERFLOW", False, _serialize_plain),
    "db_pool_recycle_seconds": _FieldSpec("DB_POOL_RECYCLE_SECONDS", True, _serialize_plain),
}


def _normalized_value(field_name: str, value: Any) -> Any:
    if field_name == "log_file":
        if value is None:
            return None
        text = str(value).strip()
        return text or None
    return value


def get_configuration_fields() -> List[Dict[str, Any]]:
    """Return editable configuration fields and their current values."""
    fields: List[Dict[str, Any]] = []
    for key, spec in _EDITABLE_FIELDS.items():
        fields.append(
            {
                "key": key,
                "value": _normalized_value(key, getattr(settings, key)),
                "requires_restart": spec.requires_restart,
            }
        )
    return fields


def update_configuration(values: Dict[str, Any]) -> Dict[str, Any]:
    """Apply allowlisted configuration updates.

    Returns metadata describing immediate application and restart-required
    changes.
    """
    changed_settings: List[str] = []
    applied_immediately: List[str] = []
    restart_required_settings: List[str] = []
    env_updates: Dict[str, str] = {}

    pending_values: Dict[str, Any] = {}

    for key, new_value_raw in values.items():
        if key not in _EDITABLE_FIELDS:
            continue
        current_value = _normalized_value(key, getattr(settings, key))
        new_value = _normalized_value(key, new_value_raw)
        if current_value == new_value:
            continue

        spec = _EDITABLE_FIELDS[key]
        changed_settings.append(key)
        if spec.requires_restart:
            restart_required_settings.append(key)
        else:
            applied_immediately.append(key)

        env_updates[spec.env_key] = spec.serializer(new_value)
        pending_values[key] = new_value

    if not changed_settings:
        return {
            "status": "no_changes",
            "changed_settings": [],
            "applied_immediately": [],
            "restart_required_settings": [],
            "restart_required": False,
        }

    if "log_file" in pending_values:
        _validate_log_file_path(pending_values["log_file"])

    for key, new_value in pending_values.items():
        setattr(settings, key, new_value)

    database_service._write_env_settings(env_updates)

    _apply_runtime_changes(changed_settings)

    return {
        "status": "updated",
        "changed_settings": changed_settings,
        "applied_immediately": applied_immediately,
        "restart_required_settings": restart_required_settings,
        "restart_required": bool(restart_required_settings),
    }


def _validate_log_file_path(value: Any) -> None:
    normalized = _normalized_value("log_file", value)
    if normalized is None:
        return

    path = str(normalized)
    log_dir = os.path.dirname(path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    try:
        with open(path, "a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise ValueError(f"Unable to write log file at '{path}': {exc.strerror or str(exc)}") from exc


def _apply_runtime_changes(changed_settings: List[str]) -> None:
    log_fields = {
        "log_level",
        "log_format",
        "log_file",
        "log_file_max_bytes",
        "log_file_backup_count",
    }
    db_pool_hot_fields = {"db_pool_size", "db_pool_max_overflow"}

    if any(name in log_fields for name in changed_settings):
        configure_logging()

    if any(name in db_pool_hot_fields for name in changed_settings):
        if (settings.database_url or "").strip():
            database_service._reinitialize_engine(
                settings.database_url,
                settings.db_pool_size,
                settings.db_pool_max_overflow,
            )


def request_service_restart(*, confirm: bool) -> Dict[str, str]:
    """Request a non-blocking restart of the ECUBE systemd service."""
    if not confirm:
        raise ValueError("Restart confirmation is required")

    if not shutil.which("systemctl"):
        raise RuntimeError("systemctl is not available on this host")

    cmd = ["systemctl", "restart", _SERVICE_NAME, "--no-block"]
    if settings.use_sudo:
        cmd = ["sudo", "-n", *cmd]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=settings.subprocess_timeout_seconds,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "service restart command failed").strip()
        raise RuntimeError(msg)

    logger.info("Service restart requested via admin configuration API")
    return {"status": "restart_requested", "service": _SERVICE_NAME}
