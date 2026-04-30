"""Validation and rendering helpers for callback payload customization."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping


ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELDS = (
    "event",
    "job_id",
    "project_id",
    "evidence_number",
    "started_by",
    "status",
    "source_path",
    "total_bytes",
    "copied_bytes",
    "file_count",
    "files_succeeded",
    "files_failed",
    "files_timed_out",
    "completion_result",
    "active_duration_seconds",
    "drive_id",
    "drive_manufacturer",
    "drive_model",
    "drive_serial_number",
    "started_at",
    "completed_at",
)

_ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELD_SET = frozenset(ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELDS)
_OUTBOUND_FIELD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_TEMPLATE_TOKEN_RE = re.compile(r"\$\{([a-z_][a-z0-9_]*)\}")


def validate_callback_payload_contract(
    payload_fields: Iterable[str] | None,
    payload_field_map: Mapping[str, str] | None,
) -> tuple[list[str] | None, dict[str, str] | None]:
    """Validate and normalize callback payload customization settings."""
    normalized_fields = _normalize_payload_fields(payload_fields)
    normalized_field_map = _normalize_payload_field_map(payload_field_map, normalized_fields)
    return normalized_fields, normalized_field_map


def apply_callback_payload_contract(
    payload: Dict[str, Any],
    payload_fields: Iterable[str] | None,
    payload_field_map: Mapping[str, str] | None,
) -> Dict[str, Any]:
    """Return the outbound callback payload after allowlist/mapping rules."""
    normalized_fields, normalized_field_map = validate_callback_payload_contract(
        payload_fields,
        payload_field_map,
    )

    source_payload = dict(payload)
    if normalized_fields is not None:
        source_payload = {
            field_name: source_payload[field_name]
            for field_name in normalized_fields
            if field_name in source_payload
        }

    if not normalized_field_map:
        return source_payload

    rendered: Dict[str, Any] = {}
    for outbound_field_name, source_spec in normalized_field_map.items():
        if source_spec in _ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELD_SET:
            rendered[outbound_field_name] = source_payload.get(source_spec)
            continue
        rendered[outbound_field_name] = _render_template_value(source_spec, source_payload)
    return rendered


def describe_callback_payload_contract(
    payload_fields: Iterable[str] | None,
    payload_field_map: Mapping[str, str] | None,
) -> Dict[str, Any]:
    """Return safe audit metadata describing the configured payload contract."""
    normalized_fields, normalized_field_map = validate_callback_payload_contract(
        payload_fields,
        payload_field_map,
    )
    details: Dict[str, Any] = {}
    if normalized_fields is not None:
        details["payload_fields"] = list(normalized_fields)
    if normalized_field_map is not None:
        details["payload_mapping_keys"] = list(normalized_field_map.keys())
    return details


def _normalize_payload_fields(payload_fields: Iterable[str] | None) -> list[str] | None:
    if payload_fields is None:
        return None
    if isinstance(payload_fields, (str, bytes)):
        raise ValueError("callback_payload_fields must be a JSON array of allowlisted field names")

    normalized_fields: list[str] = []
    seen_fields: set[str] = set()
    for raw_field in payload_fields:
        if not isinstance(raw_field, str):
            raise ValueError("callback_payload_fields entries must be strings")
        field_name = raw_field.strip()
        if not field_name:
            raise ValueError("callback_payload_fields entries must not be blank")
        if field_name not in _ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELD_SET:
            raise ValueError(f"callback_payload_fields contains unknown field: {field_name}")
        if field_name in seen_fields:
            raise ValueError(f"callback_payload_fields contains duplicate field: {field_name}")
        seen_fields.add(field_name)
        normalized_fields.append(field_name)

    if not normalized_fields:
        raise ValueError("callback_payload_fields must not be empty")
    return normalized_fields


def _normalize_payload_field_map(
    payload_field_map: Mapping[str, str] | None,
    payload_fields: list[str] | None,
) -> dict[str, str] | None:
    if payload_field_map is None:
        return None
    if not isinstance(payload_field_map, Mapping):
        raise ValueError("callback_payload_field_map must be a JSON object")
    if not payload_field_map:
        raise ValueError("callback_payload_field_map must not be empty")
    if payload_fields is None:
        raise ValueError(
            "callback_payload_field_map requires callback_payload_fields so the source allowlist is explicit"
        )

    allowed_field_set = frozenset(payload_fields)
    normalized_map: dict[str, str] = {}

    for raw_outbound_field_name, raw_source_spec in payload_field_map.items():
        if not isinstance(raw_outbound_field_name, str):
            raise ValueError("callback_payload_field_map keys must be strings")
        outbound_field_name = raw_outbound_field_name.strip()
        if not outbound_field_name:
            raise ValueError("callback_payload_field_map keys must not be blank")
        if not _OUTBOUND_FIELD_NAME_RE.fullmatch(outbound_field_name):
            raise ValueError(
                "callback_payload_field_map keys must start with a letter and contain only letters, digits, underscores, or hyphens"
            )
        if not isinstance(raw_source_spec, str):
            raise ValueError("callback_payload_field_map values must be strings")

        source_spec = raw_source_spec.strip()
        if not source_spec:
            raise ValueError(
                f"callback_payload_field_map[{outbound_field_name!r}] must not be blank"
            )

        if source_spec in _ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELD_SET:
            if source_spec not in allowed_field_set:
                raise ValueError(
                    f"callback_payload_field_map[{outbound_field_name!r}] references {source_spec!r} outside callback_payload_fields"
                )
            normalized_map[outbound_field_name] = source_spec
            continue

        tokens = _TEMPLATE_TOKEN_RE.findall(source_spec)
        if not tokens:
            raise ValueError(
                f"callback_payload_field_map[{outbound_field_name!r}] must reference an allowlisted field name or contain template tokens like ${{project_id}}"
            )
        if "${" in _TEMPLATE_TOKEN_RE.sub("", source_spec):
            raise ValueError(
                f"callback_payload_field_map[{outbound_field_name!r}] contains malformed template syntax"
            )
        for token in tokens:
            if token not in _ALLOWED_CALLBACK_PAYLOAD_SOURCE_FIELD_SET:
                raise ValueError(
                    f"callback_payload_field_map[{outbound_field_name!r}] references unknown field: {token}"
                )
            if token not in allowed_field_set:
                raise ValueError(
                    f"callback_payload_field_map[{outbound_field_name!r}] references {token!r} outside callback_payload_fields"
                )
        normalized_map[outbound_field_name] = source_spec

    return normalized_map


def _render_template_value(template: str, source_payload: Mapping[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        field_name = match.group(1)
        value = source_payload.get(field_name)
        return "" if value is None else str(value)

    return _TEMPLATE_TOKEN_RE.sub(_replace, template)