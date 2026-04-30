"""Startup state reconciliation — identity groups, mounts, jobs, and USB drives.

After a service restart or host reboot, in-memory OS state (active mounts,
running processes, USB device presence) may diverge from the database.  This
module re-aligns persisted state with actual OS/hardware state.

All three passes are **idempotent** — running them multiple times without
underlying state changes produces no additional state mutations.  Observability
side-effects (e.g. ``USB_DISCOVERY_SYNC`` audit entries from the drive pass,
``last_checked_at`` timestamp updates on verified mounts) may still be written
on each invocation.

A single-row ``reconciliation_lock`` guard table prevents concurrent
reconciliation when multiple uvicorn workers start simultaneously.  Only the
first worker to acquire the lock runs reconciliation; the others skip it.

Before reclaiming a stale lock, a **PID liveness check** verifies that the
holding process is no longer running.  This prevents a slow-but-alive worker
from having its lock stolen.  Additionally, ``locked_at`` is refreshed
between reconciliation passes so that long-running startups never appear
stale to other workers.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, Optional

from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from app.config import settings
from app.infrastructure.drive_mount import DriveMountProvider
from app.infrastructure.mount_info import find_device_mount_point, read_mount_table
from app.infrastructure.mount_protocol import MountProvider
from app.infrastructure.os_user_protocol import OsUserProvider
from app.infrastructure.usb_discovery import DiscoveredTopology
from app.infrastructure import FilesystemDetector
from app.exceptions import ConflictError
from app.models.hardware import DriveState, UsbDrive
from app.models.jobs import DriveAssignment, ExportJob, JobStatus
from app.models.network import MountStatus, NetworkMount
from app.models.system import ReconciliationLock
from app.repositories.user_role_repository import UserRoleRepository
from app.repositories.audit_repository import AuditRepository
from app.services.callback_service import deliver_callback
from app.services.mount_check_utils import check_mounted_with_configured_timeout
from app.constants import ECUBE_GROUP_ROLE_MAP
from app.utils.sanitize import normalize_project_id

logger = logging.getLogger(__name__)


class ManualReconciliationInProgressError(ConflictError):
    """Raised when a manual managed-mount reconciliation run is already in progress."""

    default_code = "MANUAL_RECONCILIATION_IN_PROGRESS"
    default_message = "A manual mount reconciliation run is already in progress."


def _schema_mismatch_hint(exc: Exception) -> Optional[str]:
    """Return a human-readable hint if *exc* is a DB schema mismatch.

    Catches ``ProgrammingError`` (missing column/table) and
    ``OperationalError`` (SQLite equivalent) so the reconciliation log
    clearly tells the operator to run migrations instead of burying the
    cause in a traceback.
    """
    if isinstance(exc, (ProgrammingError, OperationalError)):
        msg = str(exc.orig) if hasattr(exc, "orig") else str(exc)
        msg_lower = msg.lower()
        if "column" in msg_lower or "relation" in msg_lower or "table" in msg_lower or "no such" in msg_lower:
            return (
                f"Database schema mismatch: {msg.strip()}. "
                "Run 'alembic upgrade head' to apply pending migrations."
            )
    return None

# A lock older than this is considered stale (worker crashed mid-reconciliation)
# and will be reclaimed by the next startup attempt.
STALE_LOCK_SECONDS = 300  # 5 minutes


# -----------------------------------------------------------------------
# Identity reconciliation
# -----------------------------------------------------------------------

def reconcile_identity_groups(
    os_user_provider: OsUserProvider,
) -> Dict[str, Any]:
    """Ensure default ``ecube-*`` OS groups exist.

    This operation is idempotent. Existing groups are left unchanged,
    and only missing default groups are created.
    """
    created_groups = os_user_provider.ensure_ecube_groups()
    return {
        "groups_created": len(created_groups),
        "created_group_names": created_groups,
    }


_ROLE_TO_GROUP = {role: group for group, role in ECUBE_GROUP_ROLE_MAP.items()}


def reconcile_identity_users(
    db: Session,
    os_user_provider: OsUserProvider,
) -> Dict[str, Any]:
    """Reconcile DB role assignments with OS users/group memberships.

    For each user present in ``user_roles``:
    - Ensures mapped ``ecube-*`` groups are assigned on existing OS accounts.
    - Does **not** create missing OS users during startup reconciliation.

    Missing OS accounts are reported in the summary and logs for operator
    action, but no user-creation side effects occur at startup.
    """
    repo = UserRoleRepository(db)
    assignments = repo.list_users()

    checked = 0
    with_mapped_roles = 0
    created_users = 0
    missing_os_accounts = 0
    groups_updated = 0
    errors: list[dict[str, str]] = []

    for row in assignments:
        username = row.get("username")
        roles = row.get("roles", [])
        if not username:
            continue

        checked += 1
        required_groups = sorted({_ROLE_TO_GROUP[r] for r in roles if r in _ROLE_TO_GROUP})
        if not required_groups:
            continue

        with_mapped_roles += 1

        try:
            if not os_user_provider.user_exists(username):
                missing_os_accounts += 1
                logger.warning(
                    "Startup reconciliation found DB user '%s' with roles %s (groups %s) but no OS account. "
                    "Skipping OS user creation.",
                    username,
                    roles,
                    required_groups,
                )
                continue

            # Treat add_user_to_groups as idempotent and avoid scanning all OS users.
            os_user_provider.add_user_to_groups(
                username,
                required_groups,
                _skip_managed_check=True,
            )
            groups_updated += 1
        except Exception as exc:
            logger.exception("Identity user reconciliation failed for '%s'", username)
            errors.append({"username": username, "error": str(exc)})

    return {
        "users_checked": checked,
        "users_with_mapped_roles": with_mapped_roles,
        "users_created": created_users,
        "users_missing_os_account": missing_os_accounts,
        "users_groups_updated": groups_updated,
        "users_created_password_reset_required": created_users,
        "users_with_errors": len(errors),
        "errors": errors,
    }


# -----------------------------------------------------------------------
# Mount reconciliation
# -----------------------------------------------------------------------

def _cleanup_managed_mount_directory(path: str, managed_root: str) -> None:
    try:
        real_root = os.path.realpath(managed_root)
        real_path = os.path.realpath(path)
    except (OSError, ValueError):
        return

    if os.path.dirname(real_path) != real_root:
        return

    try:
        os.rmdir(real_path)
    except FileNotFoundError:
        return
    except OSError:
        return


def _is_direct_child_of(path: str, managed_root: str) -> bool:
    try:
        return os.path.dirname(os.path.realpath(path)) == os.path.realpath(managed_root)
    except (OSError, ValueError):
        return False


def _cleanup_generated_network_mount_directory(path: str) -> None:
    if _is_direct_child_of(path, "/nfs"):
        _cleanup_managed_mount_directory(path, "/nfs")
    elif _is_direct_child_of(path, "/smb"):
        _cleanup_managed_mount_directory(path, "/smb")


def _normalized_usb_mount_candidates(*paths: object) -> set[str]:
    normalized: set[str] = set()
    for path in paths:
        if not isinstance(path, str):
            continue
        stripped = path.strip()
        if not stripped:
            continue
        normalized.add(os.path.normpath(stripped))
    return normalized


def _missing_project_binding(project_id: object) -> bool:
    normalized = normalize_project_id(project_id)
    return not isinstance(normalized, str) or normalized == ""


def _resolve_usb_drive_owner(
    db: Session,
    *,
    drive_id: int,
    candidate_mount_paths: set[str],
) -> tuple[Optional[str], str]:
    assignment_rows = (
        db.query(DriveAssignment)
        .join(ExportJob, ExportJob.id == DriveAssignment.job_id)
        .filter(DriveAssignment.drive_id == drive_id)
        .all()
    )

    candidate_jobs: dict[int, ExportJob] = {}
    active_assignment_job_ids = {
        int(row.job_id)
        for row in assignment_rows
        if row.released_at is None and row.job is not None
    }
    released_assignment_job_ids = {
        int(row.job_id)
        for row in assignment_rows
        if row.released_at is not None
    }

    for row in assignment_rows:
        if row.released_at is None and row.job is not None:
            job_target = row.job.target_mount_path
            if candidate_mount_paths and os.path.normpath(str(job_target)) not in candidate_mount_paths:
                continue
            candidate_jobs[int(row.job.id)] = row.job

    if candidate_mount_paths:
        path_jobs = (
            db.query(ExportJob)
            .filter(ExportJob.target_mount_path.in_(sorted(candidate_mount_paths)))
            .all()
        )
        for job in path_jobs:
            job_id = int(job.id)
            if job_id in released_assignment_job_ids and job_id not in active_assignment_job_ids:
                continue
            candidate_jobs[job_id] = job

    candidate_projects = {
        normalized_project
        for normalized_project in (
            normalize_project_id(job.project_id) for job in candidate_jobs.values()
        )
        if isinstance(normalized_project, str) and normalized_project != ""
    }

    if not candidate_projects:
        return None, "no_relevant_owner"
    if len(candidate_projects) == 1:
        return next(iter(candidate_projects)), "binding_restored"
    return None, "ambiguous_owner"


def _release_usb_drive_without_owner(
    drive: UsbDrive,
    *,
    actual_target: Optional[str],
    drive_mount_provider: DriveMountProvider,
    managed_root: str,
) -> tuple[bool, str, Optional[str]]:
    if actual_target:
        unmount_ok, unmount_error = drive_mount_provider.unmount_drive(actual_target)
        if not unmount_ok:
            return False, "owner_release_failed", unmount_error
        if _is_direct_child_of(actual_target, managed_root):
            _cleanup_managed_mount_directory(actual_target, managed_root)

    drive.current_state = DriveState.AVAILABLE
    drive.current_project_id = None
    drive.mount_path = None
    return True, "owner_released", None


def _reconcile_usb_mounts(
    db: Session,
    drive_mount_provider: DriveMountProvider,
    *,
    audit_repo: AuditRepository,
) -> Dict[str, int]:
    checked = 0
    corrected = 0
    failures = 0
    audit_entries = []
    managed_root = settings.usb_mount_base_path

    drives = (
        db.query(UsbDrive)
        .filter(UsbDrive.filesystem_path.isnot(None))
        .filter(UsbDrive.current_state.in_((DriveState.AVAILABLE, DriveState.IN_USE)))
        .all()
    )

    expected_targets = {
        os.path.normpath(os.path.join(settings.usb_mount_base_path, str(drive.id))): drive.id
        for drive in drives
    }

    for drive in drives:
        checked += 1
        corrected_this_drive = False
        expected_target = os.path.normpath(os.path.join(settings.usb_mount_base_path, str(drive.id)))
        actual_target = find_device_mount_point(str(drive.filesystem_path)) if drive.filesystem_path else None
        missing_binding = drive.current_state == DriveState.IN_USE and _missing_project_binding(drive.current_project_id)

        if missing_binding:
            resolved_project_id, owner_reason = _resolve_usb_drive_owner(
                db,
                drive_id=int(drive.id),
                candidate_mount_paths=_normalized_usb_mount_candidates(
                    actual_target,
                    expected_target,
                    drive.mount_path,
                ),
            )
            if resolved_project_id is not None:
                drive.current_project_id = resolved_project_id
                drive.current_state = DriveState.IN_USE
                corrected += 1
                corrected_this_drive = True
                audit_entries.append({
                    "action": "DRIVE_MOUNT_RECONCILED",
                    "user": "system",
                    "drive_id": drive.id,
                    "project_id": resolved_project_id,
                    "details": {
                        "drive_id": drive.id,
                        "project_id": resolved_project_id,
                        "status": "IN_USE",
                        "reason": owner_reason,
                    },
                })
            else:
                released, release_reason, raw_error = _release_usb_drive_without_owner(
                    drive,
                    actual_target=actual_target,
                    drive_mount_provider=drive_mount_provider,
                    managed_root=managed_root,
                )
                if not released:
                    failures += 1
                    logger.info(
                        "Startup USB owner release failed",
                        extra={"drive_id": drive.id, "reason": release_reason},
                    )
                    logger.debug(
                        "Startup USB owner release raw error",
                        extra={"drive_id": drive.id, "mount_point": actual_target, "raw_error": raw_error},
                    )
                    audit_entries.append({
                        "action": "DRIVE_MOUNT_RECONCILED",
                        "user": "system",
                        "drive_id": drive.id,
                        "details": {
                            "drive_id": drive.id,
                            "status": "ERROR",
                            "reason": release_reason,
                        },
                    })
                    continue

                corrected += 1
                corrected_this_drive = True
                audit_entries.append({
                    "action": "DRIVE_MOUNT_RECONCILED",
                    "user": "system",
                    "drive_id": drive.id,
                    "details": {
                        "drive_id": drive.id,
                        "status": "AVAILABLE",
                        "reason": owner_reason,
                    },
                })
                continue

        if actual_target == expected_target:
            if drive.mount_path != expected_target:
                drive.mount_path = expected_target
                if not corrected_this_drive:
                    corrected += 1
                audit_entries.append({
                    "action": "DRIVE_MOUNT_RECONCILED",
                    "user": "system",
                    "drive_id": drive.id,
                    "details": {"drive_id": drive.id, "status": "MOUNTED", "reason": "startup_reconciled"},
                })
            continue

        if actual_target and actual_target != expected_target:
            unmount_ok, unmount_error = drive_mount_provider.unmount_drive(actual_target)
            if not unmount_ok:
                failures += 1
                logger.info(
                    "Startup USB mount cleanup failed",
                    extra={"drive_id": drive.id, "reason": "cleanup_failed"},
                )
                logger.debug(
                    "Startup USB mount cleanup raw error",
                    extra={"drive_id": drive.id, "mount_point": actual_target, "raw_error": unmount_error},
                )
                audit_entries.append({
                    "action": "DRIVE_MOUNT_RECONCILED",
                    "user": "system",
                    "drive_id": drive.id,
                    "details": {"drive_id": drive.id, "status": "ERROR", "reason": "cleanup_failed"},
                })
                continue
            if _is_direct_child_of(actual_target, managed_root):
                _cleanup_managed_mount_directory(actual_target, managed_root)
            corrected += 1
            corrected_this_drive = True

        if not drive.filesystem_path:
            audit_entries.append({
                "action": "DRIVE_MOUNT_RECONCILED",
                "user": "system",
                "drive_id": drive.id,
                "details": {"drive_id": drive.id, "status": "SKIPPED", "reason": "missing_filesystem_path"},
            })
            continue

        success, error = drive_mount_provider.mount_drive(str(drive.filesystem_path), expected_target)
        if success:
            drive.mount_path = expected_target
            if not corrected_this_drive:
                corrected += 1
            audit_entries.append({
                "action": "DRIVE_MOUNT_RECONCILED",
                "user": "system",
                "drive_id": drive.id,
                "details": {"drive_id": drive.id, "status": "MOUNTED", "reason": "startup_remount"},
            })
        else:
            failures += 1
            logger.info(
                "Startup USB remount failed",
                extra={"drive_id": drive.id, "reason": "remount_failed"},
            )
            logger.debug(
                "Startup USB remount raw error",
                extra={"drive_id": drive.id, "mount_point": expected_target, "raw_error": error},
            )
            audit_entries.append({
                "action": "DRIVE_MOUNT_RECONCILED",
                "user": "system",
                "drive_id": drive.id,
                "details": {"drive_id": drive.id, "status": "ERROR", "reason": "remount_failed"},
            })

    live_mounts = read_mount_table()
    for target in list(live_mounts.keys()):
        normalized_target = os.path.normpath(target)
        if not _is_direct_child_of(normalized_target, managed_root):
            continue
        if normalized_target in expected_targets:
            continue

        checked += 1
        unmount_ok, unmount_error = drive_mount_provider.unmount_drive(normalized_target)
        if not unmount_ok:
            failures += 1
            logger.info(
                "Startup orphan USB mount cleanup failed",
                extra={"reason": "cleanup_failed"},
            )
            logger.debug(
                "Startup orphan USB mount cleanup raw error",
                extra={"mount_point": normalized_target, "raw_error": unmount_error},
            )
            continue

        corrected += 1
        _cleanup_managed_mount_directory(normalized_target, managed_root)
        audit_entries.append({
            "action": "DRIVE_MOUNT_RECONCILED",
            "user": "system",
            "details": {"status": "UNMOUNTED", "reason": "orphan_managed_mount_removed"},
        })

    if checked:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("DB commit failed during USB mount reconciliation")
            raise

    if audit_entries:
        try:
            audit_repo.add_many(audit_entries)
        except Exception:
            db.rollback()
            db.expire_all()
            logger.exception("Failed to write audit logs for DRIVE_MOUNT_RECONCILED")

    return {
        "usb_mounts_checked": checked,
        "usb_mounts_corrected": corrected,
        "usb_mount_failures": failures,
    }

def reconcile_mounts(
    db: Session,
    mount_provider: MountProvider,
    drive_mount_provider: DriveMountProvider | None = None,
) -> Dict[str, int]:
    """Converge managed network and USB mounts toward ECUBE's expected state.

    For persisted network mounts, startup reconciliation restores expected
    ``MOUNTED`` entries, removes unexpected managed mounts for unmounted/error
    records, and cleans up orphan managed paths under ECUBE-controlled roots.

    For USB drives, persisted mounted drives are re-mounted to their managed
    ECUBE mount slots when possible, and orphan managed USB mounts are removed.
    """
    from app.services.mount_service import validate_mount

    mounts = db.query(NetworkMount).all()
    live_mounts = read_mount_table()
    persisted_targets = {os.path.normpath(str(m.local_mount_point)) for m in mounts}

    checked = 0
    corrected = 0
    failures = 0
    audit_entries = []

    for mount in mounts:
        target = os.path.normpath(str(mount.local_mount_point))
        live_source = live_mounts.get(target)
        corrected_this_mount = False
        previous_status = mount.status
        mount.last_checked_at = datetime.now(timezone.utc)
        checked += 1

        if live_source == str(mount.remote_path):
            if mount.status != MountStatus.MOUNTED:
                mount.status = MountStatus.MOUNTED
                corrected += 1
                audit_entries.append({
                    "mount_id": mount.id,
                    "old_status": previous_status.value,
                    "new_status": mount.status.value,
                    "reason": "startup reconciliation",
                })
            continue

        if live_source is None:
            try:
                result = check_mounted_with_configured_timeout(mount_provider, mount.local_mount_point)
            except Exception:
                logger.exception(
                    "OS check failed for mount %s during startup reconciliation",
                    mount.id,
                )
                result = None

            if result is True:
                if mount.status != MountStatus.MOUNTED:
                    mount.status = MountStatus.MOUNTED
                    corrected += 1
                    audit_entries.append({
                        "mount_id": mount.id,
                        "old_status": previous_status.value,
                        "new_status": mount.status.value,
                        "reason": "startup reconciliation",
                    })
                continue

            corrected_this_mount = True

        if live_source is not None and live_source != str(mount.remote_path):
            unmount_ok, unmount_error = mount_provider.os_unmount(str(mount.local_mount_point))
            if not unmount_ok:
                failures += 1
                mount.status = MountStatus.ERROR
                corrected += 1
                audit_entries.append({
                    "mount_id": mount.id,
                    "old_status": previous_status.value,
                    "new_status": mount.status.value,
                    "reason": "startup cleanup failed",
                })
                logger.debug(
                    "Startup mount cleanup raw error",
                    extra={"mount_id": mount.id, "mount_point": target, "raw_error": unmount_error},
                )
                continue
            corrected_this_mount = True
            _cleanup_generated_network_mount_directory(str(mount.local_mount_point))

        try:
            validate_mount(mount.id, db, actor="system", provider=mount_provider)
        except Exception:
            failures += 1
            logger.exception(
                "Startup network remount failed unexpectedly",
                extra={"mount_id": mount.id},
            )
            mount.status = MountStatus.ERROR
            if corrected_this_mount or mount.status != previous_status:
                corrected += 1
            audit_entries.append({
                "mount_id": mount.id,
                "old_status": previous_status.value,
                "new_status": mount.status.value,
                "reason": "startup reconciliation",
            })
            continue
        db.refresh(mount)
        if corrected_this_mount or mount.status != previous_status:
            corrected += 1
            audit_entries.append({
                "mount_id": mount.id,
                "old_status": previous_status.value,
                "new_status": mount.status.value,
                "reason": "startup reconciliation",
            })

    for target, source in live_mounts.items():
        normalized_target = os.path.normpath(target)
        if normalized_target in persisted_targets:
            continue
        managed_root = "/nfs" if _is_direct_child_of(normalized_target, "/nfs") else "/smb" if _is_direct_child_of(normalized_target, "/smb") else None
        if managed_root is None:
            continue

        checked += 1
        unmount_ok, unmount_error = mount_provider.os_unmount(normalized_target)
        if not unmount_ok:
            failures += 1
            logger.debug(
                "Startup orphan network mount cleanup raw error",
                extra={"mount_point": normalized_target, "raw_error": unmount_error},
            )
            continue
        corrected += 1
        _cleanup_managed_mount_directory(normalized_target, managed_root)
        audit_entries.append({
            "old_status": MountStatus.MOUNTED.value,
            "new_status": MountStatus.UNMOUNTED.value,
            "reason": "orphan_managed_mount_removed",
            "managed_area": managed_root.lstrip("/"),
        })

    if checked:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("DB commit failed during mount reconciliation")
            raise

    # Best-effort audit — failures are logged but must not roll back
    # the state corrections committed above.
    if audit_entries:
        audit_repo = AuditRepository(db)
        try:
            audit_repo.add_many([
                {"action": "MOUNT_RECONCILED", "user": "system", "details": d}
                for d in audit_entries
            ])
        except Exception:
            db.rollback()
            db.expire_all()
            logger.exception(
                "Failed to write audit logs for MOUNT_RECONCILED",
            )

    summary = {
        "mounts_checked": checked,
        "mounts_corrected": corrected,
        "mount_failures": failures,
    }
    if drive_mount_provider is not None:
        summary.update(_reconcile_usb_mounts(db, drive_mount_provider, audit_repo=AuditRepository(db)))
    return summary


def run_manual_managed_mount_reconciliation(
    db: Session,
    mount_provider: MountProvider,
    *,
    drive_mount_provider: DriveMountProvider,
    actor: str,
) -> Dict[str, Any]:
    """Run a live-safe, mount-only reconciliation pass for manual invocation.

    This path intentionally excludes identity, job, and drive discovery/state
    reconciliation. It only converges managed network mounts and managed USB
    mount slots.
    """
    if not _acquire_reconciliation_lock(db):
        raise ManualReconciliationInProgressError()

    logger.info(
        "Manual managed-mount reconciliation requested",
        extra={"actor": actor, "scope": "managed_mounts_only"},
    )

    try:
        summary = reconcile_mounts(db, mount_provider, drive_mount_provider)
        network_checked = int(summary.get("mounts_checked", 0))
        network_corrected = int(summary.get("mounts_corrected", 0))
        usb_checked = int(summary.get("usb_mounts_checked", 0))
        usb_corrected = int(summary.get("usb_mounts_corrected", 0))
        failures = int(summary.get("mount_failures", 0)) + int(summary.get("usb_mount_failures", 0))

        status = "partial" if failures > 0 else "ok"
        details = {
            "status": status,
            "scope": "managed_mounts_only",
            "network_mounts_checked": network_checked,
            "network_mounts_corrected": network_corrected,
            "usb_mounts_checked": usb_checked,
            "usb_mounts_corrected": usb_corrected,
            "failure_count": failures,
        }
        AuditRepository(db).add(
            action="MANUAL_MOUNT_RECONCILIATION",
            user=actor,
            details=details,
        )

        logger.info(
            "Manual managed-mount reconciliation finished",
            extra=details,
        )
        return details
    except Exception as exc:
        logger.info(
            "Manual managed-mount reconciliation failed",
            extra={
                "actor": actor,
                "scope": "managed_mounts_only",
                "status": "failed",
                "reason": "manual_reconciliation_failed",
            },
        )
        logger.debug(
            "Manual managed-mount reconciliation raw failure",
            extra={"actor": actor, "raw_error": str(exc)},
        )
        try:
            AuditRepository(db).add(
                action="MANUAL_MOUNT_RECONCILIATION",
                user=actor,
                details={
                    "status": "failed",
                    "scope": "managed_mounts_only",
                    "reason": "manual_reconciliation_failed",
                },
            )
        except Exception:
            logger.debug("Manual reconciliation failure audit write failed", exc_info=True)
        raise
    finally:
        _release_reconciliation_lock(db)


# -----------------------------------------------------------------------
# Job reconciliation
# -----------------------------------------------------------------------

_IN_PROGRESS_STATUSES = (JobStatus.RUNNING, JobStatus.VERIFYING)


def reconcile_jobs(db: Session) -> Dict[str, int]:
    """Fail any ``RUNNING`` or ``VERIFYING`` jobs that lost their worker.

    After a restart no worker processes exist, so these jobs are
    unconditionally transitioned to ``FAILED``.

    Returns a summary dict with counts of jobs checked and corrected.
    """
    jobs = (
        db.query(ExportJob)
        .filter(ExportJob.status.in_(_IN_PROGRESS_STATUSES))
        .all()
    )

    checked = len(jobs)
    corrected = 0
    audit_entries = []

    for job in jobs:
        old_status = job.status
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)
        job.failure_reason = "Job interrupted by service restart before completion"
        corrected += 1

        audit_entries.append({
            "job_id": job.id,
            "old_status": old_status.value,
            "new_status": JobStatus.FAILED.value,
            "reason": "interrupted by restart",
        })

    if corrected:
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("DB commit failed during job reconciliation")
            raise

    # Best-effort audit — failures are logged but must not roll back
    # the state corrections committed above.
    if audit_entries:
        audit_repo = AuditRepository(db)
        try:
            audit_repo.add_many([
                {
                    "action": "JOB_RECONCILED",
                    "user": "system",
                    "job_id": e["job_id"],
                    "details": e,
                }
                for e in audit_entries
            ])
        except Exception:
            db.rollback()
            db.expire_all()
            logger.error(
                "Failed to write audit logs for JOB_RECONCILED",
            )

    for job, audit_entry in zip(jobs, audit_entries):
        try:
            deliver_callback(
                job,
                event="JOB_RECONCILED",
                event_actor="system",
                event_at=getattr(job, "completed_at", None),
                event_details={
                    "old_status": audit_entry["old_status"],
                    "new_status": audit_entry["new_status"],
                    "reason": audit_entry["reason"],
                },
            )
        except Exception:
            logger.exception(
                "Failed to dispatch lifecycle callback",
                extra={"job_id": job.id, "event": "JOB_RECONCILED"},
            )

    return {"jobs_checked": checked, "jobs_corrected": corrected}


# -----------------------------------------------------------------------
# USB drive reconciliation
# -----------------------------------------------------------------------

def reconcile_drives(
    db: Session,
    *,
    topology_source: Callable[[], DiscoveredTopology],
    filesystem_detector: FilesystemDetector,
) -> Dict[str, int]:
    """Run USB discovery and reconcile DB drive state with hardware.

    Delegates entirely to
    :func:`~app.services.discovery_service.run_discovery_sync`, which
    handles topology detection, FSM transitions (including demoting
    ``AVAILABLE`` drives that are no longer physically present to
    ``DISCONNECTED``), and preserving ``IN_USE`` drives (project-isolation
    guarantee).  No additional logic is applied here.

    Returns a summary dict with counts from the discovery sync.
    """
    from app.services.discovery_service import run_discovery_sync

    summary = run_discovery_sync(
        db,
        actor="system",
        topology_source=topology_source,
        filesystem_detector=filesystem_detector,
    )

    return summary


# -----------------------------------------------------------------------
# Cross-process reconciliation lock
# -----------------------------------------------------------------------

def _is_holder_alive(locked_by: str) -> bool:
    """Check whether the process that holds the lock is still running.

    Extracts the PID from the ``"pid-<N>"`` format used by
    :func:`_acquire_reconciliation_lock`.  Returns ``True`` (assume alive)
    if the format is unrecognised or the check is inconclusive.

    On Windows, signal 0 maps to ``CTRL_C_EVENT`` and cannot be used for
    existence checks, so this function conservatively returns ``True``.
    The production target is Linux.
    """
    if not locked_by or not locked_by.startswith("pid-"):
        return True  # Cannot determine — assume alive
    try:
        pid = int(locked_by[4:])
    except (ValueError, IndexError):
        return True  # Malformed — assume alive
    if os.name == "nt":
        # On Windows, os.kill(pid, 0) sends CTRL_C_EVENT to the process
        # group — unusable for existence checks.  Assume alive.
        return True
    try:
        os.kill(pid, 0)  # Signal 0: existence check, no actual signal sent
        return True
    except ProcessLookupError:
        return False  # Process does not exist
    except (PermissionError, OSError):
        return True  # Process exists but we lack permission — assume alive


def _acquire_reconciliation_lock(db: Session) -> bool:
    """Try to acquire the single-row reconciliation lock.

    Returns ``True`` if the lock was acquired.  Returns ``False`` if
    another worker already holds it (and it is not stale).

    A stale lock (older than :data:`STALE_LOCK_SECONDS`) is reclaimed
    automatically so that a crashed worker does not block future startups.
    """
    worker_id = f"pid-{os.getpid()}"
    now = datetime.now(timezone.utc)

    db.add(ReconciliationLock(id=1, locked_by=worker_id, locked_at=now))
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()

    # Lock row already exists — check for staleness.
    existing = db.query(ReconciliationLock).filter_by(id=1).first()
    if existing is None:
        # Row disappeared between our failed INSERT and this SELECT
        # (another worker released it).  Retry the insert once.
        db.add(ReconciliationLock(id=1, locked_by=worker_id, locked_at=now))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False

    cutoff = now - timedelta(seconds=STALE_LOCK_SECONDS)
    # SQLite returns naive datetimes; normalise both sides for comparison.
    locked_at = existing.locked_at
    if locked_at is not None:
        if locked_at.tzinfo is not None:
            locked_at = locked_at.replace(tzinfo=None)
        cutoff_naive = cutoff.replace(tzinfo=None)
        is_stale = locked_at < cutoff_naive
    else:
        is_stale = False

    if is_stale and not _is_holder_alive(existing.locked_by):
        logger.warning(
            "Reclaiming stale reconciliation lock held by %s since %s"
            " (holder PID is no longer running)",
            existing.locked_by,
            existing.locked_at,
        )
        db.delete(existing)
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to delete stale reconciliation lock")
            return False
        db.add(ReconciliationLock(id=1, locked_by=worker_id, locked_at=now))
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            return False

    if is_stale:
        logger.info(
            "Reconciliation lock held by %s since %s is old but holder is"
            " still alive — skipping reconciliation",
            existing.locked_by,
            existing.locked_at,
        )
    else:
        logger.info(
            "Reconciliation lock held by %s since %s — skipping reconciliation",
            existing.locked_by,
            existing.locked_at,
        )
    return False


def _refresh_reconciliation_lock(db: Session) -> None:
    """Update ``locked_at`` to prevent stale-lock reclaim during long runs.

    Called between reconciliation passes so that a slow startup never
    appears stale to a later-starting worker.
    """
    try:
        row = db.query(ReconciliationLock).filter_by(id=1).first()
        if row is not None:
            row.locked_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
        logger.warning("Failed to refresh reconciliation lock timestamp")


def _release_reconciliation_lock(db: Session) -> bool:
    """Delete the reconciliation lock row.

    Returns ``True`` if the row was deleted, ``False`` if it was already
    gone (harmless).
    """
    try:
        row = db.query(ReconciliationLock).filter_by(id=1).first()
        if row is not None:
            db.delete(row)
            db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("Failed to release reconciliation lock")
        return False


# -----------------------------------------------------------------------
# Orchestrator — runs all three passes
# -----------------------------------------------------------------------

def run_startup_reconciliation(
    db: Session,
    mount_provider: MountProvider,
    *,
    drive_mount_provider: DriveMountProvider | None = None,
    os_user_provider: OsUserProvider | None = None,
    topology_source: Callable[[], DiscoveredTopology],
    filesystem_detector: FilesystemDetector,
) -> Dict[str, Any]:
    """Execute all reconciliation passes during startup.

    Acquires a cross-process lock before running.  If another worker
    already holds the lock, reconciliation is skipped and the return
    dict contains ``{"skipped": True}``.

    Returns a nested summary keyed by domain (``identity``, ``mounts``,
    ``jobs``, ``drives``).  Each value is either a counts dict on success or an
    ``{"error": "..."}`` dict on failure.
    """
    if not _acquire_reconciliation_lock(db):
        logger.info("Another worker is running startup reconciliation — skipping")
        return {"skipped": True}

    try:
        results: Dict[str, Any] = {}

        if os_user_provider is not None:
            results["identity"] = {}

            logger.info("Startup reconciliation: ensuring default ECUBE OS groups")
            try:
                results["identity"]["groups"] = reconcile_identity_groups(os_user_provider)
            except Exception as exc:
                hint = _schema_mismatch_hint(exc)
                if hint:
                    logger.error("Identity group reconciliation failed: %s", hint)
                else:
                    logger.exception("Identity group reconciliation failed")
                results["identity"]["groups"] = {"error": hint or "identity group reconciliation failed"}

            _refresh_reconciliation_lock(db)

            logger.info("Startup reconciliation: reconciling DB users to OS users")
            try:
                results["identity"]["users"] = reconcile_identity_users(db, os_user_provider)
            except Exception as exc:
                hint = _schema_mismatch_hint(exc)
                if hint:
                    logger.error("Identity user reconciliation failed: %s", hint)
                else:
                    logger.exception("Identity user reconciliation failed")
                results["identity"]["users"] = {"error": hint or "identity user reconciliation failed"}

            _refresh_reconciliation_lock(db)

        logger.info("Startup reconciliation: checking mounts")
        try:
            results["mounts"] = reconcile_mounts(db, mount_provider, drive_mount_provider)
        except Exception as exc:
            db.rollback()
            db.expire_all()
            hint = _schema_mismatch_hint(exc)
            if hint:
                logger.error("Mount reconciliation failed: %s", hint)
            else:
                logger.exception("Mount reconciliation failed")
            results["mounts"] = {"error": hint or "mount reconciliation failed"}

        _refresh_reconciliation_lock(db)

        logger.info("Startup reconciliation: checking jobs")
        try:
            results["jobs"] = reconcile_jobs(db)
        except Exception as exc:
            db.rollback()
            db.expire_all()
            hint = _schema_mismatch_hint(exc)
            if hint:
                logger.error("Job reconciliation failed: %s", hint)
            else:
                logger.exception("Job reconciliation failed")
            results["jobs"] = {"error": hint or "job reconciliation failed"}
        if "error" in results["jobs"]:
            logger.info(
                "Startup reconciliation: jobs result",
                extra={
                    "status": "failed",
                    "reason": "job_reconciliation_failed",
                },
            )
        else:
            logger.info(
                "Startup reconciliation: jobs result",
                extra={
                    "status": "ok",
                    "jobs_checked": results["jobs"].get("jobs_checked", 0),
                    "jobs_corrected": results["jobs"].get("jobs_corrected", 0),
                },
            )

        _refresh_reconciliation_lock(db)

        logger.info("Startup reconciliation: checking USB drives")
        try:
            results["drives"] = reconcile_drives(
                db,
                topology_source=topology_source,
                filesystem_detector=filesystem_detector,
            )
        except Exception as exc:
            db.rollback()
            db.expire_all()
            hint = _schema_mismatch_hint(exc)
            if hint:
                logger.error("Drive reconciliation failed: %s", hint)
            else:
                logger.exception("Drive reconciliation failed")
            results["drives"] = {"error": hint or "drive reconciliation failed"}

        logger.info("Startup reconciliation complete: %s", results)
        return results
    finally:
        _release_reconciliation_lock(db)
