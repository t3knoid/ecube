from __future__ import annotations

from typing import Optional


def _normalize_identifier_component(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized.replace("|", "_").replace("=", "_")


def build_persistent_device_identifier(
    usb_vendor_id: Optional[str],
    usb_product_id: Optional[str],
    usb_serial_number: Optional[str],
    usb_bus_path: Optional[str],
    *,
    disk_serial_number: Optional[str] = None,
) -> str:
    parts: list[str] = ["usb"]
    component_map = {
        "vid": _normalize_identifier_component(usb_vendor_id),
        "pid": _normalize_identifier_component(usb_product_id),
        "serial": _normalize_identifier_component(usb_serial_number),
        "disk": _normalize_identifier_component(disk_serial_number),
        "bus": _normalize_identifier_component(usb_bus_path),
    }

    for key in ("vid", "pid", "serial", "disk", "bus"):
        value = component_map[key]
        if value:
            parts.append(f"{key}={value}")

    if len(parts) > 1:
        return "|".join(parts)

    return _normalize_identifier_component(usb_bus_path) or "-"


def parse_persistent_device_identifier(device_identifier: Optional[str]) -> dict[str, str]:
    identifier = str(device_identifier or "").strip()
    if not identifier.startswith("usb|"):
        return {}

    parsed: dict[str, str] = {}
    for token in identifier.split("|")[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            parsed[key] = value
    return parsed


def is_persistent_device_identifier(device_identifier: Optional[str]) -> bool:
    return bool(parse_persistent_device_identifier(device_identifier))


def extract_usb_serial_number(
    device_identifier: Optional[str],
    *,
    port_system_path: Optional[str] = None,
) -> Optional[str]:
    parsed = parse_persistent_device_identifier(device_identifier)
    if parsed.get("serial"):
        return parsed["serial"]

    identifier = str(device_identifier or "").strip()
    if not identifier:
        return None
    if port_system_path and identifier == port_system_path:
        return None
    return identifier


def device_identifier_matches(
    device_identifier: Optional[str],
    candidate: Optional[str],
    *,
    port_system_path: Optional[str] = None,
) -> bool:
    normalized_candidate = str(candidate or "").strip()
    normalized_identifier = str(device_identifier or "").strip()
    if not normalized_candidate or not normalized_identifier:
        return False
    if normalized_identifier == normalized_candidate:
        return True

    parsed = parse_persistent_device_identifier(normalized_identifier)
    if not parsed:
        return False

    return normalized_candidate in {
        parsed.get("serial"),
        parsed.get("disk"),
        None if port_system_path is not None else parsed.get("bus"),
    }


def _format_drive_capacity_label(capacity_bytes: Optional[int]) -> Optional[str]:
    capacity = capacity_bytes if isinstance(capacity_bytes, int) else None
    if capacity is None or capacity <= 0:
        return None

    units = (
        (1024 ** 4, "TB"),
        (1024 ** 3, "GB"),
        (1024 ** 2, "MB"),
    )

    for unit_bytes, suffix in units:
        if capacity >= unit_bytes:
            scaled_value = round(capacity / unit_bytes)
            return f"{max(scaled_value, 1)}{suffix}"

    return "1MB"


def build_readable_device_label(
    manufacturer: Optional[str],
    product_name: Optional[str],
    port_number: Optional[int],
    *,
    capacity_bytes: Optional[int] = None,
    fallback_label: Optional[str] = None,
) -> str:
    parts: list[str] = []
    for value in (manufacturer, product_name):
        normalized = str(value or "").strip()
        if normalized and normalized not in parts:
            parts.append(normalized)

    base_label = " ".join(parts).strip()
    if port_number is not None:
        if base_label:
            label = f"{base_label} - Port {port_number}"
        else:
            label = f"USB Drive - Port {port_number}"

        capacity_label = _format_drive_capacity_label(capacity_bytes)
        if capacity_label:
            return f"{label} ({capacity_label})"
        return label

    if base_label:
        return base_label

    fallback = str(fallback_label or "").strip()
    return fallback or "-"


def mask_serial_number(serial_number: Optional[str]) -> Optional[str]:
    serial = str(serial_number or "").strip()
    if not serial:
        return None
    if len(serial) <= 4:
        return "[redacted]"
    return f"[redacted]-{serial[-4:]}"