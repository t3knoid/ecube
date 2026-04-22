from __future__ import annotations

from typing import Optional


def build_readable_device_label(
    manufacturer: Optional[str],
    product_name: Optional[str],
    port_number: Optional[int],
    *,
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
            return f"{base_label} - Port {port_number}"
        return f"USB Drive - Port {port_number}"

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