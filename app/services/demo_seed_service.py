from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.constants import ECUBE_GROUP_ROLE_MAP, VALID_ROLES
from app.infrastructure.os_user_protocol import OsUserProvider
from app.models.jobs import DriveAssignment, ExportFile, ExportJob, Manifest
from app.models.users import UserRole
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)

DEMO_SEED_MARKER = "ecube-demo-seed-v1"
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

@dataclass(frozen=True)
class DemoSeedResult:
    users_seeded: int
    roles_seeded: int
    jobs_seeded: int


@dataclass(frozen=True)
class DemoResetResult:
    roles_removed: int
    jobs_removed: int


def seed_demo_environment(
    db: Session,
    *,
    metadata_path: str | Path | None = None,
    provider: OsUserProvider | None = None,
    shared_password: str | None = None,
    actor: str = "system",
) -> DemoSeedResult:
    """Seed demo-safe users from demo metadata only."""
    seed_metadata = _load_seed_metadata(metadata_path=metadata_path)
    accounts = _configured_demo_accounts(seed_metadata)
    effective_shared_password = (
        shared_password
        or _configured_shared_password(seed_metadata)
        or settings.get_demo_shared_password()
        or None
    )
    jobs_removed = _delete_seeded_jobs(db)
    if jobs_removed:
        db.commit()

    roles_removed = _delete_demo_roles(db, [account["username"] for account in accounts])
    if roles_removed:
        db.commit()

    roles_seeded = 0
    users_seeded = 0
    if provider is not None:
        provider.ensure_ecube_groups()

    for account in accounts:
        roles_seeded += _set_demo_roles(db, account["username"], account["roles"])
        if provider is not None:
            _reconcile_demo_os_user(provider, account, effective_shared_password)
            users_seeded += 1

    AuditRepository(db).add(
        action="DEMO_BOOTSTRAP_APPLIED",
        user=actor,
        details={
            "usernames": [account["username"] for account in accounts],
            "roles_removed": roles_removed,
            "jobs_removed": jobs_removed,
            "jobs_seeded": 0,
        },
    )

    return DemoSeedResult(
        users_seeded=users_seeded,
        roles_seeded=roles_seeded,
        jobs_seeded=0,
    )


def reset_demo_environment(
    db: Session,
    *,
    metadata_path: str | Path | None = None,
    actor: str = "system",
) -> DemoResetResult:
    """Remove demo-seeded jobs and role assignments for metadata-defined users."""
    seed_metadata = _load_seed_metadata(metadata_path=metadata_path)
    accounts = _configured_demo_accounts(seed_metadata)

    jobs_removed = _delete_seeded_jobs(db)
    roles_removed = _delete_demo_roles(db, [account["username"] for account in accounts])
    db.commit()

    AuditRepository(db).add(
        action="DEMO_BOOTSTRAP_RESET",
        user=actor,
        details={
            "usernames": [account["username"] for account in accounts],
            "jobs_removed": jobs_removed,
            "roles_removed": roles_removed,
        },
    )

    return DemoResetResult(
        roles_removed=roles_removed,
        jobs_removed=jobs_removed,
    )


def _load_seed_metadata(metadata_path: str | Path | None = None) -> dict[str, Any]:
    resolved_metadata_path: Path
    if metadata_path is not None:
        resolved_metadata_path = Path(metadata_path).expanduser().resolve()
    else:
        resolved_metadata_path = Path(__file__).resolve().parents[2] / "demo-metadata.json"

    if not resolved_metadata_path.is_file():
        return {}
    try:
        payload = json.loads(resolved_metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "Failed to read demo seed metadata template",
            {"failure_category": "demo_seed_metadata_unreadable"},
        )
        logger.debug(
            "Demo seed metadata load details",
            {"path": str(resolved_metadata_path), "error": str(exc)},
        )
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_seed_demo_config(seed_metadata: dict[str, Any]) -> dict[str, Any]:
    value = seed_metadata.get("demo_config")
    return value if isinstance(value, dict) else {}


def _configured_demo_accounts(seed_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    metadata_accounts = _extract_seed_demo_config(seed_metadata).get("accounts")
    if isinstance(metadata_accounts, list):
        return _normalized_demo_accounts(metadata_accounts, include_defaults=False)
    return []


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


def _normalized_demo_accounts(
    configured_accounts: Iterable[object] | None,
    *,
    include_defaults: bool = True,
) -> list[dict[str, Any]]:
    source = list(configured_accounts or ([] if not include_defaults else _DEFAULT_DEMO_ACCOUNTS))
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

    if normalized or not include_defaults:
        return normalized

    return [
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

    password_to_apply = shared_password or account_password
    if not password_to_apply:
        raise ValueError(
            "A shared password or per-account password is required to create missing demo accounts."
        )

    provider.create_user(username, password_to_apply, groups=groups)


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
