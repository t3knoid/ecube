from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ECUBE_GROUP_ROLE_MAP, VALID_ROLES
from app.infrastructure import FilesystemDetector, get_filesystem_detector
from app.infrastructure.drive_mount import DriveMountProvider
from app.infrastructure.os_user_protocol import OsUserProvider
from app.infrastructure.usb_discovery import DiscoveredTopology
from app.models.hardware import DriveState, UsbDrive, UsbPort
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, FileStatus, JobStatus, Manifest
from app.models.network import MountStatus, MountType, NetworkMount
from app.models.users import UserRole
from app.repositories.audit_repository import AuditRepository
from app.repositories.drive_repository import DriveRepository
from app.services import discovery_service, drive_service
from app.utils.drive_identity import device_identifier_matches
from app.utils.sanitize import normalize_project_id

logger = logging.getLogger(__name__)

DEMO_SEED_MARKER = "ecube-demo-seed-v1"
_DEMO_MARKER_FILENAME = ".ecube-demo-seed.json"
_ROLE_TO_GROUP = {role: group for group, role in ECUBE_GROUP_ROLE_MAP.items()}

_DEFAULT_DEMO_ACCOUNTS: list[dict[str, Any]] = [
    {
        "username": "demo_admin",
        "label": "Admin demo",
        "description": "Full demo access for guided product walkthroughs.",
        "roles": ["admin"],
    },
    {
        "username": "demo_manager",
        "label": "Manager demo",
        "description": "Drive lifecycle, mounts, and job visibility.",
        "roles": ["manager"],
    },
    {
        "username": "demo_processor",
        "label": "Processor demo",
        "description": "Create and review sanitized export activity.",
        "roles": ["processor"],
    },
    {
        "username": "demo_auditor",
        "label": "Auditor demo",
        "description": "Read-only audit and verification review.",
        "roles": ["auditor"],
    },
]

_DEFAULT_SAMPLE_PROJECTS: list[dict[str, Any]] = [
    {
        "project_id": 1,
        "project_name": "DEMO-CASE-001",
        "evidence_number": "EVID-001",
        "folder": "demo-case-001",
        "files": {
            "incoming/mailbox-summary.txt": "Synthetic demo content only. Mailbox summary for internal training review. No real evidence is stored here.\n",
            "reports/collection-notes.txt": "Collection notes for a simulated matter. Dates, names, and file references are fictional and sanitized.\n",
        },
    },
    {
        "project_id": 2,
        "project_name": "DEMO-CASE-002",
        "evidence_number": "EVID-002",
        "folder": "demo-case-002",
        "files": {
            "incoming/chat-export.txt": "Synthetic chat export for product demonstration only. Do not use for real evidence or production decisions.\n",
            "reports/manifest-preview.txt": "Manifest preview generated from sanitized sample data. All content is fictional.\n",
        },
    },
]


@dataclass(frozen=True)
class DemoSeedResult:
    data_root: str
    users_seeded: int
    roles_seeded: int
    jobs_seeded: int
    files_staged: int
    usb_drives_seeded: int = 0
    usb_drives_mounted: int = 0
    network_mounts_seeded: int = 0
    network_mounts_mounted: int = 0


@dataclass(frozen=True)
class DemoResetResult:
    data_root: str
    roles_removed: int
    jobs_removed: int
    files_removed: int


def seed_demo_environment(
    db: Session,
    *,
    data_root: str | Path | None = None,
    metadata_path: str | Path | None = None,
    provider: OsUserProvider | None = None,
    shared_password: str | None = None,
    actor: str = "system",
    topology_source: Callable[[], DiscoveredTopology] | None = None,
    filesystem_detector: FilesystemDetector | None = None,
    mount_provider: DriveMountProvider | None = None,
    network_mount_provider: Any | None = None,
) -> DemoSeedResult:
    """Seed a normal ECUBE install with demo-safe users, roles, sample data, and optional real USB and network mounts configured in demo-metadata.json."""
    root = _resolve_data_root(data_root)
    seed_metadata = _load_seed_metadata(root, metadata_path=metadata_path)
    projects = _normalized_projects(seed_metadata)
    accounts = _configured_demo_accounts(seed_metadata)
    effective_shared_password = (
        shared_password
        or _configured_shared_password(seed_metadata)
        or settings.get_demo_shared_password()
        or None
    )
    usb_seed_config = _normalized_usb_seed_config(seed_metadata.get("usb_seed"), projects=projects)
    mount_seed_config = _normalized_mount_seed_config(seed_metadata.get("mount_seed"), projects=projects)
    job_seed_config = _normalized_job_seed_config(seed_metadata.get("job_seed"), projects=projects)

    jobs_removed = _delete_seeded_jobs(db)
    if jobs_removed:
        db.commit()

    roles_removed = _delete_demo_roles(db, [account["username"] for account in accounts])
    if roles_removed:
        db.commit()

    _prepare_demo_root(root)
    files_staged = _stage_demo_files(
        root,
        accounts=accounts,
        projects=projects,
        shared_password=effective_shared_password,
        seed_metadata=seed_metadata,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
        job_seed_config=job_seed_config,
    )

    roles_seeded = 0
    users_seeded = 0
    if provider is not None:
        provider.ensure_ecube_groups()

    for account in accounts:
        roles_seeded += _set_demo_roles(db, account["username"], account["roles"])
        if provider is not None:
            _reconcile_demo_os_user(provider, account, effective_shared_password)
            users_seeded += 1

    usb_drives_seeded = 0
    usb_drives_mounted = 0
    if usb_seed_config["enabled"]:
        usb_drives_seeded, usb_drives_mounted = _seed_connected_usb_drives(
            db,
            actor=actor,
            usb_seed_config=usb_seed_config,
            topology_source=topology_source,
            filesystem_detector=filesystem_detector,
            mount_provider=mount_provider,
        )

    network_mounts_seeded = 0
    network_mounts_mounted = 0
    if mount_seed_config["enabled"]:
        network_mounts_seeded, network_mounts_mounted = _seed_configured_network_mounts(
            db,
            actor=actor,
            mount_seed_config=mount_seed_config,
            provider=network_mount_provider,
        )

    _synchronize_runtime_seed_ids(
        db,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
        job_seed_config=job_seed_config,
    )

    jobs_seeded = _seed_demo_jobs(
        db,
        actor=actor,
        job_seed_config=job_seed_config,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
    )
    _write_demo_metadata(
        root,
        accounts=accounts,
        projects=projects,
        shared_password=effective_shared_password,
        seed_metadata=seed_metadata,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
        job_seed_config=job_seed_config,
    )

    AuditRepository(db).add(
        action="DEMO_BOOTSTRAP_APPLIED",
        user=actor,
        details={
            "data_root": str(root),
            "usernames": [account["username"] for account in accounts],
            "project_ids": [project["project_name"] for project in projects],
            "roles_removed": roles_removed,
            "jobs_removed": jobs_removed,
            "jobs_seeded": jobs_seeded,
            "files_staged": files_staged,
            "usb_drives_seeded": usb_drives_seeded,
            "usb_drives_mounted": usb_drives_mounted,
            "network_mounts_seeded": network_mounts_seeded,
            "network_mounts_mounted": network_mounts_mounted,
            "usb_project_ids": [entry["project_name"] for entry in usb_seed_config.get("drives", [])] if usb_seed_config["enabled"] else [],
            "mount_project_ids": [entry["project_name"] for entry in mount_seed_config.get("mounts", [])] if mount_seed_config["enabled"] else [],
            "job_project_ids": [entry["project_name"] for entry in job_seed_config.get("jobs", [])],
        },
    )

    return DemoSeedResult(
        data_root=str(root),
        users_seeded=users_seeded,
        roles_seeded=roles_seeded,
        jobs_seeded=jobs_seeded,
        files_staged=files_staged,
        usb_drives_seeded=usb_drives_seeded,
        usb_drives_mounted=usb_drives_mounted,
        network_mounts_seeded=network_mounts_seeded,
        network_mounts_mounted=network_mounts_mounted,
    )


def reset_demo_environment(
    db: Session,
    *,
    data_root: str | Path | None = None,
    actor: str = "system",
) -> DemoResetResult:
    """Remove demo-seeded jobs, roles, and staged sample files."""
    accounts = _normalized_demo_accounts(settings.get_demo_accounts())
    root = _resolve_data_root(data_root)

    jobs_removed = _delete_seeded_jobs(db)
    roles_removed = _delete_demo_roles(db, [account["username"] for account in accounts])
    db.commit()
    files_removed = _remove_demo_root(root)

    AuditRepository(db).add(
        action="DEMO_BOOTSTRAP_RESET",
        user=actor,
        details={
            "data_root": str(root),
            "usernames": [account["username"] for account in accounts],
            "jobs_removed": jobs_removed,
            "roles_removed": roles_removed,
            "files_removed": files_removed,
        },
    )

    return DemoResetResult(
        data_root=str(root),
        roles_removed=roles_removed,
        jobs_removed=jobs_removed,
        files_removed=files_removed,
    )


def _resolve_data_root(data_root: str | Path | None) -> Path:
    raw_path = data_root or settings.demo_data_root
    return Path(raw_path).expanduser().resolve()


def _load_seed_metadata(root: Path, metadata_path: str | Path | None = None) -> dict[str, Any]:
    resolved_metadata_path: Path
    if metadata_path is not None:
        resolved_metadata_path = Path(metadata_path).expanduser().resolve()
    else:
        install_root_metadata = Path(__file__).resolve().parents[2] / "demo-metadata.json"
        resolved_metadata_path = install_root_metadata if install_root_metadata.is_file() else root / "demo-metadata.json"

    if not resolved_metadata_path.is_file():
        return {}
    try:
        payload = json.loads(resolved_metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to read demo seed metadata template", extra={"path": str(resolved_metadata_path)})
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_seed_demo_config(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    value = seed_metadata.get("demo_config")
    return value if isinstance(value, dict) else {}


def _configured_demo_accounts(seed_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    metadata_accounts = _extract_seed_demo_config(seed_metadata).get("accounts")
    if isinstance(metadata_accounts, list):
        return _normalized_demo_accounts(metadata_accounts)
    return _normalized_demo_accounts(settings.get_demo_accounts())


def _configured_shared_password(seed_metadata: dict[str, Any]) -> str | None:
    value = _extract_seed_demo_config(seed_metadata).get("shared_password")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_seed_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    return text


def _optional_positive_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = _optional_seed_string(value)
    if text is None or not text.isdigit():
        return None
    parsed = int(text)
    return parsed if parsed > 0 else None


def _normalized_seed_identifier(value: object, *, prefix: str, fallback: object = None, index: int = 1) -> int | str:
    explicit_int = _optional_positive_int(value)
    if explicit_int is not None:
        return explicit_int

    explicit = _optional_seed_string(value)
    if explicit:
        return explicit

    raw_fallback = _optional_seed_string(fallback)
    if raw_fallback:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", raw_fallback).strip("-").lower()
        if slug:
            return f"{prefix}-{slug}"

    return f"{prefix}-{index}"


def _normalized_projects(seed_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_projects = seed_metadata.get("projects")
    if not isinstance(raw_projects, list) or not raw_projects:
        return [dict(project) for project in _DEFAULT_SAMPLE_PROJECTS]

    defaults_by_name = {str(project["project_name"]): project for project in _DEFAULT_SAMPLE_PROJECTS}
    normalized_projects: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()

    for index, raw in enumerate(raw_projects, start=1):
        if not isinstance(raw, dict):
            continue

        requested_project_id = _optional_positive_int(raw.get("project_id"))
        requested_project_name = _optional_seed_string(raw.get("project_name"))
        if requested_project_name is None:
            legacy_project_id = _optional_seed_string(raw.get("project_id"))
            if legacy_project_id and not legacy_project_id.isdigit():
                requested_project_name = legacy_project_id

        if requested_project_name is None and requested_project_id is not None:
            default_project = next((project for project in _DEFAULT_SAMPLE_PROJECTS if project["project_id"] == requested_project_id), None)
            if default_project is not None:
                requested_project_name = str(default_project["project_name"])

        normalized_name = normalize_project_id(requested_project_name)
        if not isinstance(normalized_name, str) or not normalized_name:
            raise ValueError("projects[] requires a non-empty project_name")

        default_project = defaults_by_name.get(normalized_name)
        numeric_project_id = requested_project_id or (default_project["project_id"] if default_project is not None else index)
        if numeric_project_id in seen_ids or normalized_name in seen_names:
            continue

        seen_ids.add(numeric_project_id)
        seen_names.add(normalized_name)
        normalized_projects.append(
            {
                "project_id": numeric_project_id,
                "project_name": normalized_name,
                "evidence_number": _optional_seed_string(raw.get("evidence_number"))
                or (default_project.get("evidence_number") if default_project is not None else f"EVID-{numeric_project_id:03d}"),
                "folder": _optional_seed_string(raw.get("folder"))
                or (default_project.get("folder") if default_project is not None else f"project-{numeric_project_id}"),
                "files": dict(default_project.get("files", {})) if default_project is not None else {},
            }
        )

    return normalized_projects or [dict(project) for project in _DEFAULT_SAMPLE_PROJECTS]


def _resolve_seed_project_reference(project_id: object, *, projects: list[dict[str, Any]]) -> tuple[int, str]:
    if not projects:
        raise ValueError("At least one demo project is required")

    if project_id is None:
        default_project = projects[0]
        return int(default_project["project_id"]), str(default_project["project_name"])

    numeric_project_id = _optional_positive_int(project_id)
    if numeric_project_id is not None:
        for project in projects:
            if int(project["project_id"]) == numeric_project_id:
                return numeric_project_id, str(project["project_name"])
        raise ValueError(f"Unknown demo project_id reference: {numeric_project_id}")

    normalized_name = normalize_project_id(project_id)
    if not isinstance(normalized_name, str) or not normalized_name:
        raise ValueError("project_id must not be empty")

    for project in projects:
        if str(project["project_name"]) == normalized_name:
            return int(project["project_id"]), normalized_name

    next_project_id = max((int(project["project_id"]) for project in projects), default=0) + 1
    projects.append(
        {
            "project_id": next_project_id,
            "project_name": normalized_name,
            "evidence_number": f"EVID-{next_project_id:03d}",
            "folder": f"project-{next_project_id}",
            "files": {},
        }
    )
    return next_project_id, normalized_name


def _normalized_job_seed_config(value: object, *, projects: list[dict[str, Any]]) -> dict[str, Any]:
    config = value if isinstance(value, dict) else {}
    entries: list[dict[str, Any]] = []
    seen_jobs: set[str] = set()

    raw_entries = config.get("jobs")
    if isinstance(raw_entries, list):
        for index, raw in enumerate(raw_entries, start=1):
            if not isinstance(raw, dict):
                continue
            project_ref, project_name = _resolve_seed_project_reference(raw.get("project_id"), projects=projects)
            evidence_number = _optional_seed_string(raw.get("evidence_number"))
            source_path = _optional_seed_string(raw.get("source_path"))

            mount_id = _optional_positive_int(raw.get("mount_id"))
            drive_id = _optional_positive_int(raw.get("drive_id"))
            mount_source_id = None if mount_id is not None else _optional_seed_string(raw.get("mount_source_id") or raw.get("mount_source"))
            destination_usb_id = None if drive_id is not None else _optional_seed_string(raw.get("destination_usb_id") or raw.get("destination_usb") or raw.get("usb_id"))

            if not evidence_number or not source_path or (mount_id is None and not mount_source_id) or (drive_id is None and not destination_usb_id):
                raise ValueError(
                    "job_seed.jobs[] requires project_id, evidence_number, mount_id or mount_source_id, drive_id or destination_usb_id, and source_path"
                )
            job_id = _normalized_seed_identifier(raw.get("id"), prefix="job", fallback=evidence_number, index=index)
            job_id_key = str(job_id)
            if job_id_key in seen_jobs:
                continue
            seen_jobs.add(job_id_key)
            entry = {
                "id": job_id,
                "project_id": project_ref,
                "project_name": project_name,
                "evidence_number": evidence_number,
                "mount_id": mount_id,
                "drive_id": drive_id,
                "source_path": source_path,
                "status": _optional_seed_string(raw.get("status")) or JobStatus.PENDING.value,
            }
            if mount_source_id is not None:
                entry["mount_source_id"] = mount_source_id
            if destination_usb_id is not None:
                entry["destination_usb_id"] = destination_usb_id
            entries.append(entry)

    return {"jobs": entries}


def _normalized_mount_seed_config(value: object, *, projects: list[dict[str, Any]]) -> dict[str, Any]:
    config = value if isinstance(value, dict) else {}
    enabled = bool(config.get("enabled", False))
    entries: list[dict[str, Any]] = []
    seen_mounts: set[tuple[str, str, str]] = set()

    raw_entries = config.get("mounts")
    if isinstance(raw_entries, list):
        for index, raw in enumerate(raw_entries, start=1):
            if not isinstance(raw, dict):
                continue
            mount_type = _resolve_mount_type(raw.get("type"))
            remote_path = _optional_seed_string(raw.get("remote_path")) or ""
            if mount_type is None or not remote_path:
                continue
            project_ref, project_name = _resolve_seed_project_reference(raw.get("project_id"), projects=projects)
            key = (mount_type.value, remote_path, project_name)
            if key in seen_mounts:
                continue
            seen_mounts.add(key)
            entries.append(
                {
                    "id": _normalized_seed_identifier(raw.get("id"), prefix="mount", fallback=project_name, index=index),
                    "type": mount_type,
                    "remote_path": remote_path,
                    "project_id": project_ref,
                    "project_name": project_name,
                    "username": _optional_seed_string(raw.get("username")),
                    "password": _optional_seed_string(raw.get("password")),
                    "credentials_file": _optional_seed_string(raw.get("credentials_file")),
                }
            )

    return {
        "enabled": enabled,
        "mounts": entries,
    }


def _normalized_usb_seed_config(value: object, *, projects: list[dict[str, Any]]) -> dict[str, Any]:
    config = value if isinstance(value, dict) else {}
    enabled = bool(config.get("enabled", False))
    entries: list[dict[str, Any]] = []
    seen_ports: set[str] = set()

    raw_entries = config.get("drives")
    if isinstance(raw_entries, list):
        for index, raw in enumerate(raw_entries, start=1):
            if not isinstance(raw, dict):
                continue
            port_system_path = str(raw.get("port_system_path", "")).strip()
            if not port_system_path or port_system_path in seen_ports:
                continue
            seen_ports.add(port_system_path)
            device_identifier = str(raw.get("device_identifier", "")).strip() or None
            project_ref, project_name = _resolve_seed_project_reference(raw.get("project_id"), projects=projects)
            entries.append(
                {
                    "id": _normalized_seed_identifier(raw.get("id"), prefix="usb", fallback=port_system_path, index=index),
                    "port_system_path": port_system_path,
                    "project_id": project_ref,
                    "project_name": project_name,
                    "device_identifier": device_identifier,
                }
            )

    legacy_port = str(config.get("port_system_path", "")).strip()
    if enabled and legacy_port and legacy_port not in seen_ports:
        project_ref, project_name = _resolve_seed_project_reference(config.get("project_id"), projects=projects)
        entries.append(
            {
                "id": _normalized_seed_identifier(config.get("id"), prefix="usb", fallback=legacy_port, index=len(entries) + 1),
                "port_system_path": legacy_port,
                "project_id": project_ref,
                "project_name": project_name,
                "device_identifier": str(config.get("device_identifier", "")).strip() or None,
            }
        )

    return {
        "enabled": enabled,
        "drives": entries,
    }


def _resolve_mount_type(value: object) -> MountType | None:
    if isinstance(value, MountType):
        return value
    try:
        normalized = str(value).strip().upper()
    except Exception:
        return None
    if not normalized:
        return None
    try:
        return MountType(normalized)
    except ValueError:
        return None


def _select_seed_drive_for_port(
    db: Session,
    *,
    port_id: int,
    expected_device_identifier: str | None = None,
) -> UsbDrive | None:
    candidates = db.query(UsbDrive).filter(UsbDrive.port_id == port_id).all()
    if not candidates:
        return None

    normalized_expected_identifier = _optional_seed_string(expected_device_identifier)
    if normalized_expected_identifier is not None:
        for drive in candidates:
            if device_identifier_matches(
                drive.device_identifier,
                normalized_expected_identifier,
                port_system_path=drive.port_system_path,
            ):
                return drive

    return max(
        candidates,
        key=lambda drive: (
            drive.current_state == DriveState.IN_USE,
            drive.current_state == DriveState.AVAILABLE,
            bool(drive.mount_path),
            bool(drive.filesystem_path),
            drive.last_seen_at or datetime.min.replace(tzinfo=timezone.utc),
            drive.id,
        ),
    )


def _seed_connected_usb_drives(
    db: Session,
    *,
    actor: str,
    usb_seed_config: dict[str, Any],
    topology_source: Callable[[], DiscoveredTopology] | None = None,
    filesystem_detector: FilesystemDetector | None = None,
    mount_provider: DriveMountProvider | None = None,
) -> tuple[int, int]:
    """Discover and mount real connected USB drives for demo use.

    This path is opt-in and only acts on USB devices the host actually reports.
    It never formats or fabricates drives.
    """
    configured_entries = list(usb_seed_config.get("drives") or [])
    if not configured_entries:
        return 0, 0

    detector = filesystem_detector or get_filesystem_detector()

    discovery_kwargs: dict[str, Any] = {
        "db": db,
        "actor": actor,
        "filesystem_detector": detector,
    }
    if topology_source is not None:
        discovery_kwargs["topology_source"] = topology_source

    discovery_service.run_discovery_sync(**discovery_kwargs)

    configured_paths = {
        str(entry.get("port_system_path", "")).strip()
        for entry in configured_entries
        if str(entry.get("port_system_path", "")).strip()
    }

    changed_ports = False
    if configured_paths:
        for port in db.query(UsbPort).filter(UsbPort.system_path.in_(configured_paths)).all():
            if not port.enabled:
                port.enabled = True
                changed_ports = True

    if changed_ports:
        db.commit()
        discovery_service.run_discovery_sync(**discovery_kwargs)

    seeded = 0
    mounted = 0
    processed_drive_ids: set[int] = set()
    drive_repo = DriveRepository(db)

    for entry in configured_entries:
        port_system_path = str(entry.get("port_system_path", "")).strip()
        if not port_system_path:
            continue

        port = db.query(UsbPort).filter(UsbPort.system_path == port_system_path).one_or_none()
        if port is None:
            logger.info("Configured demo USB port was not discovered", extra={"port_system_path": port_system_path})
            continue

        expected_device_identifier = entry.get("device_identifier")
        drive = _select_seed_drive_for_port(
            db,
            port_id=port.id,
            expected_device_identifier=expected_device_identifier,
        )
        if drive is None:
            logger.info("No connected USB drive found on configured demo port", extra={"port_system_path": port_system_path})
            continue
        if drive.id in processed_drive_ids:
            continue

        if expected_device_identifier and not device_identifier_matches(
            drive.device_identifier,
            expected_device_identifier,
            port_system_path=drive.port_system_path,
        ):
            logger.info(
                "Configured demo USB device mismatch",
                extra={
                    "port_system_path": port_system_path,
                    "expected_device_identifier": expected_device_identifier,
                    "actual_device_identifier": drive.device_identifier,
                },
            )
            continue

        project_id = str(entry.get("project_name") or "").strip()
        if not drive.filesystem_path:
            continue
        if drive.filesystem_type in {None, "unknown", "unformatted"}:
            logger.info(
                "Skipping demo USB seed for drive without recognized filesystem",
                extra={"drive_id": drive.id, "device_identifier": drive.device_identifier},
            )
            continue
        if drive.current_project_id not in (None, project_id):
            logger.info(
                "Skipping demo USB seed for project-bound drive",
                extra={
                    "drive_id": drive.id,
                    "device_identifier": drive.device_identifier,
                    "current_project_id": drive.current_project_id,
                },
            )
            continue

        if drive.current_project_id is None or drive.current_state != DriveState.IN_USE:
            drive.current_project_id = project_id
            drive.current_state = DriveState.IN_USE
            drive_repo.save(drive)

        processed_drive_ids.add(drive.id)
        seeded += 1
        if drive.mount_path:
            mounted += 1
            continue

        try:
            mounted_drive = drive_service.mount_drive(
                drive.id,
                db,
                actor=actor,
                mount_provider=mount_provider,
            )
        except HTTPException as exc:
            logger.warning(
                "Demo USB mount skipped",
                extra={
                    "drive_id": drive.id,
                    "device_identifier": drive.device_identifier,
                    "reason": str(exc.detail),
                },
            )
            continue

        if mounted_drive.mount_path:
            mounted += 1

    return seeded, mounted


def _seed_configured_network_mounts(
    db: Session,
    *,
    actor: str,
    mount_seed_config: dict[str, Any],
    provider: Any | None = None,
) -> tuple[int, int]:
    from app.schemas.network import MountCreate
    from app.services import mount_service

    configured_entries = list(mount_seed_config.get("mounts") or [])
    if not configured_entries:
        return 0, 0

    seeded = 0
    mounted = 0

    for entry in configured_entries:
        mount_type = entry.get("type")
        remote_path = str(entry.get("remote_path", "")).strip()
        project_id = str(entry.get("project_name") or "").strip()
        if not isinstance(mount_type, MountType) or not remote_path or not project_id:
            continue

        existing = (
            db.query(NetworkMount)
            .filter(
                NetworkMount.type == mount_type,
                NetworkMount.remote_path == remote_path,
                NetworkMount.project_id == project_id,
            )
            .order_by(NetworkMount.id)
            .first()
        )
        if existing is not None and existing.status == MountStatus.MOUNTED:
            seeded += 1
            mounted += 1
            continue
        if existing is not None:
            mount_service.remove_mount(existing.id, db, actor=actor, provider=provider)

        created = mount_service.add_mount(
            MountCreate(
                type=mount_type,
                remote_path=remote_path,
                project_id=project_id,
                username=entry.get("username"),
                password=entry.get("password"),
                credentials_file=entry.get("credentials_file"),
            ),
            db,
            actor=actor,
            provider=provider,
        )
        seeded += 1
        if created.status == MountStatus.MOUNTED:
            mounted += 1

    return seeded, mounted


def _normalized_demo_accounts(configured_accounts: Iterable[object] | None) -> list[dict[str, Any]]:
    source = list(configured_accounts or _DEFAULT_DEMO_ACCOUNTS)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in source:
        if not isinstance(raw, dict):
            continue
        username = str(raw.get("username", "")).strip()
        if not username or username in seen:
            continue
        seen.add(username)
        roles = _normalized_roles(raw.get("roles"), username=username)
        normalized.append(
            {
                "username": username,
                "label": str(raw.get("label", "")).strip() or username.replace("_", " ").title(),
                "description": str(raw.get("description", "")).strip(),
                "roles": roles,
                "password": str(raw.get("password", "")).strip() or None,
            }
        )

    return normalized or [
        {
            "username": entry["username"],
            "label": entry["label"],
            "description": entry["description"],
            "roles": list(entry["roles"]),
            "password": None,
        }
        for entry in _DEFAULT_DEMO_ACCOUNTS
    ]


def _normalized_roles(value: object, *, username: str) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        roles = [str(role).strip() for role in value if str(role).strip() in VALID_ROLES]
    else:
        roles = []

    if roles:
        return sorted(set(roles))

    if "admin" in username:
        return ["admin"]
    if "manager" in username:
        return ["manager"]
    if "auditor" in username:
        return ["auditor"]
    return ["processor"]


def _set_demo_roles(db: Session, username: str, roles: list[str]) -> int:
    db.query(UserRole).filter(UserRole.username == username).delete(synchronize_session=False)
    for role in roles:
        db.add(UserRole(username=username, role=role))
    db.commit()
    return len(roles)


def _reconcile_demo_os_user(provider: OsUserProvider, account: dict[str, Any], shared_password: str | None) -> None:
    username = account["username"]
    account_password = account.get("password")
    groups = sorted({_ROLE_TO_GROUP[role] for role in account["roles"] if role in _ROLE_TO_GROUP})

    if provider.user_exists(username):
        password_to_apply = shared_password or account_password
        if password_to_apply:
            provider.reset_password(username, password_to_apply, _skip_managed_check=True)
        if groups:
            provider.add_user_to_groups(username, groups, _skip_managed_check=True)
        return

    password_to_apply = account_password or shared_password
    if not password_to_apply:
        raise ValueError(
            "A shared password or per-account password is required to create missing demo accounts."
        )

    provider.create_user(username, password_to_apply, groups=groups)


def _prepare_demo_root(root: Path) -> None:
    marker = root / _DEMO_MARKER_FILENAME
    if root.exists():
        contents = {path.name for path in root.iterdir()}
        if contents and not marker.exists():
            if not contents.issubset({"demo-metadata.json"}):
                raise ValueError(
                    f"Refusing to overwrite non-demo content at {root}. Create an empty directory or reuse a seeded demo root."
                )
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _build_demo_metadata(
    *,
    accounts: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    shared_password: str | None,
    seed_metadata: dict[str, Any],
    usb_seed_config: dict[str, Any],
    mount_seed_config: dict[str, Any],
    job_seed_config: dict[str, Any],
) -> dict[str, Any]:
    seed_demo_config = _extract_seed_demo_config(seed_metadata)
    configured_login_message = seed_demo_config.get("login_message")
    configured_shared_password = seed_demo_config.get("shared_password")

    if "demo_disable_password_change" in seed_demo_config:
        disable_password_change = bool(seed_demo_config.get("demo_disable_password_change"))
    elif "password_change_allowed" in seed_demo_config:
        disable_password_change = not bool(seed_demo_config.get("password_change_allowed"))
    else:
        disable_password_change = settings.get_demo_disable_password_change()

    return {
        "managed_by": DEMO_SEED_MARKER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo_config": {
            "demo_mode": True,
            "login_message": (
                str(configured_login_message).strip()
                if isinstance(configured_login_message, str) and str(configured_login_message).strip()
                else settings.get_demo_login_message() or "Use the shared demo accounts below."
            ),
            "shared_password": (
                shared_password
                or (str(configured_shared_password).strip() if isinstance(configured_shared_password, str) and str(configured_shared_password).strip() else None)
                or settings.get_demo_shared_password()
                or None
            ),
            "demo_disable_password_change": disable_password_change,
            "password_change_allowed": not disable_password_change,
            "accounts": [
                {
                    "username": account["username"],
                    "label": account["label"],
                    "description": account["description"],
                    "roles": list(account["roles"]),
                    "password": account.get("password") or shared_password or None,
                }
                for account in accounts
            ],
        },
        "usb_seed": {
            "enabled": bool(usb_seed_config.get("enabled", False)),
            "drives": [
                {
                    "id": entry.get("id"),
                    "port_system_path": entry.get("port_system_path"),
                    "project_id": entry.get("project_id"),
                    "device_identifier": entry.get("device_identifier"),
                }
                for entry in usb_seed_config.get("drives", [])
            ],
        },
        "mount_seed": {
            "enabled": bool(mount_seed_config.get("enabled", False)),
            "mounts": [
                {
                    "id": entry.get("id"),
                    "type": entry.get("type").value if isinstance(entry.get("type"), MountType) else entry.get("type"),
                    "remote_path": entry.get("remote_path"),
                    "project_id": entry.get("project_id"),
                    "username": entry.get("username"),
                    "password": entry.get("password"),
                    "credentials_file": entry.get("credentials_file"),
                }
                for entry in mount_seed_config.get("mounts", [])
            ],
        },
        "job_seed": {
            "jobs": [
                {
                    "id": entry.get("id"),
                    "project_id": entry.get("project_id"),
                    "evidence_number": entry.get("evidence_number"),
                    "mount_id": entry.get("mount_id"),
                    "drive_id": entry.get("drive_id"),
                    "source_path": entry.get("source_path"),
                    "status": entry.get("status"),
                    **({"mount_source_id": entry.get("mount_source_id")} if entry.get("mount_source_id") is not None else {}),
                    **({"destination_usb_id": entry.get("destination_usb_id")} if entry.get("destination_usb_id") is not None else {}),
                    **({"ui_job_id": entry.get("ui_job_id")} if entry.get("ui_job_id") is not None else {}),
                }
                for entry in job_seed_config.get("jobs", [])
            ],
        },
        "projects": [
            {
                "project_id": project["project_id"],
                "project_name": project["project_name"],
                "folder": project["folder"],
                "sanitized": True,
            }
            for project in projects
        ],
    }


def _write_demo_metadata(
    root: Path,
    *,
    accounts: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    shared_password: str | None,
    seed_metadata: dict[str, Any],
    usb_seed_config: dict[str, Any],
    mount_seed_config: dict[str, Any],
    job_seed_config: dict[str, Any],
) -> None:
    metadata = _build_demo_metadata(
        accounts=accounts,
        projects=projects,
        shared_password=shared_password,
        seed_metadata=seed_metadata,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
        job_seed_config=job_seed_config,
    )
    (root / "demo-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def _stage_demo_files(
    root: Path,
    *,
    accounts: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    shared_password: str | None,
    seed_metadata: dict[str, Any],
    usb_seed_config: dict[str, Any],
    mount_seed_config: dict[str, Any],
    job_seed_config: dict[str, Any],
) -> int:
    files_staged = 0
    marker_payload = {
        "marker": DEMO_SEED_MARKER,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "warning": "Synthetic demo content only. Do not use for real evidence.",
    }
    (root / _DEMO_MARKER_FILENAME).write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")
    files_staged += 1

    readme = (
        "ECUBE synthetic demo data\n\n"
        "This directory contains sanitized sample content for product demonstrations only. "
        "Do not use for real evidence, production exports, or customer data.\n"
    )
    (root / "README.txt").write_text(readme, encoding="utf-8")
    files_staged += 1

    _write_demo_metadata(
        root,
        accounts=accounts,
        projects=projects,
        shared_password=shared_password,
        seed_metadata=seed_metadata,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
        job_seed_config=job_seed_config,
    )
    files_staged += 1

    for project in projects:
        project_root = root / str(project["folder"])
        for relative_path, contents in project.get("files", {}).items():
            target = project_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
            files_staged += 1

    return files_staged


def _seed_demo_jobs(
    db: Session,
    *,
    actor: str,
    job_seed_config: dict[str, Any],
    usb_seed_config: dict[str, Any],
    mount_seed_config: dict[str, Any],
) -> int:
    configured_jobs = list(job_seed_config.get("jobs") or [])
    if not configured_jobs:
        return 0
    return _seed_configured_demo_jobs(
        db,
        actor=actor,
        configured_jobs=configured_jobs,
        usb_seed_config=usb_seed_config,
        mount_seed_config=mount_seed_config,
    )


def _synchronize_runtime_seed_ids(
    db: Session,
    *,
    usb_seed_config: dict[str, Any],
    mount_seed_config: dict[str, Any],
    job_seed_config: dict[str, Any],
) -> None:
    drive_ids_by_project: dict[str, int] = {}
    drive_ids_by_previous_id: dict[int, int] = {}
    for entry in usb_seed_config.get("drives", []):
        port_system_path = str(entry.get("port_system_path", "")).strip()
        if not port_system_path:
            continue
        previous_drive_id = _optional_positive_int(entry.get("id"))
        port = db.query(UsbPort).filter(UsbPort.system_path == port_system_path).one_or_none()
        if port is None:
            continue
        drive = _select_seed_drive_for_port(
            db,
            port_id=port.id,
            expected_device_identifier=_optional_seed_string(entry.get("device_identifier")),
        )
        if drive is None:
            continue
        entry["id"] = drive.id
        if previous_drive_id is not None:
            drive_ids_by_previous_id[previous_drive_id] = drive.id
        project_name = _optional_seed_string(entry.get("project_name"))
        if project_name is not None:
            drive_ids_by_project[project_name] = drive.id

    mount_ids_by_project: dict[str, int] = {}
    mount_ids_by_previous_id: dict[int, int] = {}
    for entry in mount_seed_config.get("mounts", []):
        previous_mount_id = _optional_positive_int(entry.get("id"))
        mount = (
            db.query(NetworkMount)
            .filter(
                NetworkMount.type == entry.get("type"),
                NetworkMount.remote_path == entry.get("remote_path"),
                NetworkMount.project_id == entry.get("project_name"),
            )
            .order_by(NetworkMount.id)
            .first()
        )
        if mount is None:
            continue
        entry["id"] = mount.id
        if previous_mount_id is not None:
            mount_ids_by_previous_id[previous_mount_id] = mount.id
        project_name = _optional_seed_string(entry.get("project_name"))
        if project_name is not None:
            mount_ids_by_project[project_name] = mount.id

    for entry in job_seed_config.get("jobs", []):
        project_id = _optional_seed_string(entry.get("project_name"))
        requested_mount_id = _optional_positive_int(entry.get("mount_id"))
        requested_drive_id = _optional_positive_int(entry.get("drive_id"))

        if requested_mount_id in mount_ids_by_previous_id:
            entry["mount_id"] = mount_ids_by_previous_id[requested_mount_id]
        elif project_id in mount_ids_by_project:
            entry["mount_id"] = mount_ids_by_project[project_id]

        if requested_drive_id in drive_ids_by_previous_id:
            entry["drive_id"] = drive_ids_by_previous_id[requested_drive_id]
        elif project_id in drive_ids_by_project:
            entry["drive_id"] = drive_ids_by_project[project_id]

        if entry.get("mount_id") is not None:
            entry.pop("mount_source_id", None)
        if entry.get("drive_id") is not None:
            entry.pop("destination_usb_id", None)


def _seed_configured_demo_jobs(
    db: Session,
    *,
    actor: str,
    configured_jobs: list[dict[str, Any]],
    usb_seed_config: dict[str, Any],
    mount_seed_config: dict[str, Any],
) -> int:
    from app.schemas.jobs import JobCreate
    from app.services import job_service

    drive_by_seed_id: dict[str, UsbDrive] = {}
    drive_by_ui_id: dict[int, UsbDrive] = {}
    for entry in usb_seed_config.get("drives", []):
        port_system_path = str(entry.get("port_system_path", "")).strip()
        if not port_system_path:
            continue
        port = db.query(UsbPort).filter(UsbPort.system_path == port_system_path).one_or_none()
        if port is None:
            continue
        drive = _select_seed_drive_for_port(
            db,
            port_id=port.id,
            expected_device_identifier=_optional_seed_string(entry.get("device_identifier")),
        )
        if drive is not None:
            drive_by_seed_id[str(entry.get("id"))] = drive
            drive_by_ui_id[drive.id] = drive

    mount_by_seed_id: dict[str, NetworkMount] = {}
    mount_by_ui_id: dict[int, NetworkMount] = {}
    for entry in mount_seed_config.get("mounts", []):
        mount = (
            db.query(NetworkMount)
            .filter(
                NetworkMount.type == entry.get("type"),
                NetworkMount.remote_path == entry.get("remote_path"),
                NetworkMount.project_id == entry.get("project_name"),
            )
            .order_by(NetworkMount.id)
            .first()
        )
        if mount is not None:
            mount_by_seed_id[str(entry.get("id"))] = mount
            mount_by_ui_id[mount.id] = mount

    seeded_count = 0
    for entry in configured_jobs:
        requested_mount_id = _optional_positive_int(entry.get("mount_id"))
        requested_drive_id = _optional_positive_int(entry.get("drive_id"))
        mount_source_id = _optional_seed_string(entry.get("mount_source_id"))
        destination_usb_id = _optional_seed_string(entry.get("destination_usb_id"))

        mount = mount_by_ui_id.get(requested_mount_id) if requested_mount_id is not None else None
        if mount is None and mount_source_id is not None:
            mount = mount_by_seed_id.get(mount_source_id)
        if mount is None:
            detail = f"mount_id={requested_mount_id}" if requested_mount_id is not None else f"mount_source_id={mount_source_id}"
            raise ValueError(f"Configured demo job references unknown mount: {detail}")

        drive = drive_by_ui_id.get(requested_drive_id) if requested_drive_id is not None else None
        if drive is None and destination_usb_id is not None:
            drive = drive_by_seed_id.get(destination_usb_id)
        if drive is None:
            detail = f"drive_id={requested_drive_id}" if requested_drive_id is not None else f"destination_usb_id={destination_usb_id}"
            raise ValueError(f"Configured demo job references unknown drive: {detail}")

        desired_job_id = _optional_positive_int(entry.get("id"))
        created = job_service.create_job(
            JobCreate(
                project_id=entry["project_name"],
                evidence_number=entry["evidence_number"],
                source_path=entry["source_path"],
                mount_id=mount.id,
                drive_id=drive.id,
            ),
            db,
            actor=DEMO_SEED_MARKER,
            seeded_job_id=desired_job_id,
        )
        entry["id"] = created.id
        entry["ui_job_id"] = created.id

        requested_status = _optional_seed_string(entry.get("status")) or JobStatus.PENDING.value
        try:
            normalized_status = JobStatus(str(requested_status).upper())
        except ValueError:
            normalized_status = JobStatus.PENDING
        if created.status != normalized_status:
            created.status = normalized_status
            if normalized_status in {JobStatus.RUNNING, JobStatus.VERIFYING, JobStatus.COMPLETED, JobStatus.FAILED}:
                created.started_at = created.started_at or datetime.now(timezone.utc)
                created.started_by = created.started_by or DEMO_SEED_MARKER
            if normalized_status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                created.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(created)

        seeded_count += 1

    return seeded_count


def _delete_seeded_jobs(db: Session) -> int:
    job_ids = [
        row[0]
        for row in db.query(ExportJob.id)
        .filter(ExportJob.created_by == DEMO_SEED_MARKER)
        .all()
    ]
    if not job_ids:
        return 0

    db.query(DriveAssignment).filter(DriveAssignment.job_id.in_(job_ids)).delete(synchronize_session=False)
    db.query(Manifest).filter(Manifest.job_id.in_(job_ids)).delete(synchronize_session=False)
    db.query(ExportFile).filter(ExportFile.job_id.in_(job_ids)).delete(synchronize_session=False)
    db.query(ExportJob).filter(ExportJob.id.in_(job_ids)).delete(synchronize_session=False)
    return len(job_ids)


def _delete_demo_roles(db: Session, usernames: list[str]) -> int:
    if not usernames:
        return 0
    return (
        db.query(UserRole)
        .filter(UserRole.username.in_(usernames))
        .delete(synchronize_session=False)
    )


def _remove_demo_root(root: Path) -> int:
    if not root.exists():
        return 0
    marker = root / _DEMO_MARKER_FILENAME
    if not marker.exists():
        raise ValueError(f"Refusing to delete unmanaged directory: {root}")
    file_count = sum(1 for path in root.rglob("*") if path.is_file())
    shutil.rmtree(root)
    return file_count
