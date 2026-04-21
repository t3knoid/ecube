"""Helpers for comparing export-job source path overlap."""

import os


def _normalize_path(path: str) -> str:
    """Return a stable normalized path for overlap comparison."""
    return os.path.normpath(path.strip())


def _path_parts(path: str) -> tuple[str, ...]:
    normalized = _normalize_path(path)
    return tuple(part for part in normalized.split(os.sep) if part)


def classify_source_path_overlap(existing_path: str, new_path: str) -> str:
    """Classify overlap between an existing and newly requested source path.

    The returned overlap type is relative to *new_path*:

    - ``exact``: same path
    - ``ancestor``: new path is a parent of the existing path
    - ``descendant``: new path is nested under the existing path
    - ``none``: no overlap
    """
    normalized_existing = _normalize_path(existing_path)
    normalized_new = _normalize_path(new_path)

    if normalized_existing == normalized_new:
        return "exact"

    existing_parts = _path_parts(normalized_existing)
    new_parts = _path_parts(normalized_new)

    if len(new_parts) < len(existing_parts) and new_parts == existing_parts[:len(new_parts)]:
        return "ancestor"
    if len(existing_parts) < len(new_parts) and existing_parts == new_parts[:len(existing_parts)]:
        return "descendant"
    return "none"