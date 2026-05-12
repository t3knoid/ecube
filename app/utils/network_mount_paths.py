import os

from app.config import settings


def managed_network_mount_root() -> str:
    return os.path.normpath(str(settings.network_mount_base_path).strip())


def is_within_managed_network_mount_root(local_mount_point: str) -> bool:
    normalized = os.path.normpath(local_mount_point)
    root = managed_network_mount_root()
    return normalized == root or normalized.startswith(root.rstrip("/") + "/")


def cleanup_target_for_generated_network_mount_point(local_mount_point: str) -> str | None:
    normalized = os.path.normpath(local_mount_point)
    root = managed_network_mount_root()

    if not normalized.startswith(root.rstrip("/") + "/"):
        return None

    rel = os.path.relpath(normalized, root)
    if rel in (".", "..") or rel.startswith("../") or "/" in rel:
        return None

    return os.path.join(root, rel)


def is_generated_network_mount_point(local_mount_point: str) -> bool:
    return cleanup_target_for_generated_network_mount_point(local_mount_point) is not None
