from __future__ import annotations

from typing import Optional


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