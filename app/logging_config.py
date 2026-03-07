"""Structured logging configuration for ECUBE.

This module provides:

* **configure_logging()**  – one-time setup called from ``app/main.py`` at
  startup.  Reads settings from :pydata:`app.config.settings` and installs
  the appropriate handlers and formatters on the root logger.

* **JsonFormatter**  – a :class:`logging.Formatter` subclass that emits each
  record as a single-line JSON object with the fields required for audit
  trail ingestion (``timestamp``, ``level``, ``module``, ``message``,
  ``trace_id``, ``user_id``, ``extra``).

* **TextFormatter** – a human-readable formatter with timestamp, level,
  module, and message.

Environment-controlled behaviour (via ``.env`` or environment variables):

    LOG_LEVEL            DEBUG | INFO | WARNING | ERROR   (default: INFO)
    LOG_FORMAT           text  | json                     (default: text)
    LOG_FILE             /var/log/ecube/app.log            (default: None)
    LOG_FILE_MAX_BYTES   10485760                          (default: 10 MB)
    LOG_FILE_BACKUP_COUNT  5                               (default: 5)

Usage in other modules
======================

.. code-block:: python

    import logging

    logger = logging.getLogger(__name__)

    # Example: log a state transition
    logger.info(
        "drive_state_transition",
        extra={
            "drive_id": drive_id,
            "old_state": old_state,
            "new_state": new_state,
        },
    )

    # Example: log an authorization denial
    logger.warning(
        "authorization_denied",
        extra={
            "actor_id": user_id,
            "reason": "insufficient_role",
            "required_roles": required_roles,
            "user_roles": user_roles,
        },
    )

Audit integration
=================

Security-relevant events that *must* be persisted in the ``audit_logs`` table
should additionally be written via
:func:`app.services.audit_service.log_and_audit`.  That helper writes the
event both to the Python logger **and** to the database-backed audit trail in
a single call, ensuring that the two records remain consistent.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Optional

from app.config import settings

# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

# Fields that are added by the standard LogRecord and are *not* user-supplied
# extras.  We use this set to filter them out when building the ``extra`` dict
# for the JSON formatter.
_BUILTIN_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object.

    Fields:
        timestamp  – ISO 8601 with timezone (UTC)
        level      – DEBUG / INFO / WARNING / ERROR / CRITICAL
        module     – logger name (usually ``__name__``)
        message    – formatted message string
        trace_id   – if present in the record's extra dict
        user_id    – if present in the record's extra dict
        extra      – dict of all remaining extra key/value pairs
    """

    def format(self, record: logging.LogRecord) -> str:
        # Build the extra dict from anything the caller passed that is not a
        # standard LogRecord attribute.
        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _BUILTIN_ATTRS and k not in ("message", "trace_id", "user_id")
        }

        obj = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }

        # Promote well-known context fields to top level.
        if getattr(record, "trace_id", None) is not None:
            obj["trace_id"] = record.trace_id  # type: ignore[attr-defined]
        if getattr(record, "user_id", None) is not None:
            obj["user_id"] = record.user_id  # type: ignore[attr-defined]

        if extra:
            obj["extra"] = extra

        return json.dumps(obj, default=str)


_TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


class TextFormatter(logging.Formatter):
    """Human-readable log format with timestamp, level, module, and message."""

    def __init__(self) -> None:
        super().__init__(fmt=_TEXT_FORMAT, datefmt="%Y-%m-%dT%H:%M:%S%z")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def configure_logging(
    *,
    level: Optional[str] = None,
    log_format: Optional[str] = None,
    log_file: Optional[str] = None,
    log_file_max_bytes: Optional[int] = None,
    log_file_backup_count: Optional[int] = None,
) -> None:
    """Initialise the root logger with the configured handlers/formatters.

    Parameters default to the values in :pydata:`app.config.settings` but can
    be overridden for testing.
    """
    effective_level = (level or settings.log_level).upper()
    effective_format = log_format or settings.log_format
    effective_file = log_file if log_file is not None else settings.log_file
    effective_max_bytes = log_file_max_bytes if log_file_max_bytes is not None else settings.log_file_max_bytes
    effective_backup_count = (
        log_file_backup_count if log_file_backup_count is not None else settings.log_file_backup_count
    )

    formatter: logging.Formatter
    if effective_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = TextFormatter()

    root = logging.getLogger()
    root.setLevel(effective_level)

    # Remove any pre-existing handlers (allows safe re-init in tests).
    root.handlers.clear()

    # Console handler – always active.
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler – optional, controlled by LOG_FILE.
    if effective_file:
        log_dir = os.path.dirname(effective_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            effective_file,
            maxBytes=effective_max_bytes,
            backupCount=effective_backup_count,
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Emit a brief configuration summary at startup.
    startup_logger = logging.getLogger("app.logging_config")
    startup_logger.info(
        "Logging configured: level=%s format=%s file=%s",
        effective_level,
        effective_format,
        effective_file or "(console only)",
    )
