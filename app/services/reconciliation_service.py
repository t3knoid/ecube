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
from typing import Any, Callable, Dict

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.mount_protocol import MountProvider
from app.infrastructure.os_user_protocol import OsUserProvider
from app.infrastructure.usb_discovery import DiscoveredTopology
from app.infrastructure import FilesystemDetector
from app.models.jobs import ExportJob, JobStatus
from app.models.network import MountStatus, NetworkMount
from app.models.system import ReconciliationLock
from app.repositories.user_role_repository import UserRoleRepository
from app.repositories.audit_repository import AuditRepository
from app.constants import ECUBE_GROUP_ROLE_MAP

logger = logging.getLogger(__name__)

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

def reconcile_mounts(
    db: Session,
    mount_provider: MountProvider,
) -> Dict[str, int]:
    """Check all ``MOUNTED`` mounts against the OS and correct stale state.

    Every checked mount receives a ``last_checked_at`` timestamp update
    regardless of whether its status changed.  This is an observability
    side-effect (not a domain state mutation) and is expected on every run.

    Returns a summary dict with counts of mounts checked and corrected.
    """
    mounts = (
        db.query(NetworkMount)
        .filter(NetworkMount.status == MountStatus.MOUNTED)
        .all()
    )

    checked = 0
    corrected = 0
    audit_entries = []

    for mount in mounts:
        checked += 1
        try:
            result = mount_provider.check_mounted(mount.local_mount_point)
        except Exception:
            logger.exception(
                "OS check failed for mount %s (%s) — treating as ERROR",
                mount.id,
                mount.local_mount_point,
            )
            result = None
        mount.last_checked_at = datetime.now(timezone.utc)

        if result is True:
            # Still mounted — no status change needed.
            continue

        old_status = mount.status
        mount.status = MountStatus.UNMOUNTED if result is False else MountStatus.ERROR
        corrected += 1

        audit_entries.append({
            "mount_id": mount.id,
            "local_mount_point": mount.local_mount_point,
            "old_status": old_status.value,
            "new_status": mount.status.value,
            "reason": "startup reconciliation",
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

    return {"mounts_checked": checked, "mounts_corrected": corrected}


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
            logger.exception("DB commit failed during job reconciliation")
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
            logger.exception(
                "Failed to write audit logs for JOB_RECONCILED",
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
    ``EMPTY``), and preserving ``IN_USE`` drives (project-isolation
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
            except Exception:
                logger.exception("Identity group reconciliation failed")
                results["identity"]["groups"] = {"error": "identity group reconciliation failed"}

            _refresh_reconciliation_lock(db)

            logger.info("Startup reconciliation: reconciling DB users to OS users")
            try:
                results["identity"]["users"] = reconcile_identity_users(db, os_user_provider)
            except Exception:
                logger.exception("Identity user reconciliation failed")
                results["identity"]["users"] = {"error": "identity user reconciliation failed"}

            _refresh_reconciliation_lock(db)

        logger.info("Startup reconciliation: checking mounts")
        try:
            results["mounts"] = reconcile_mounts(db, mount_provider)
        except Exception:
            db.rollback()
            db.expire_all()
            logger.exception("Mount reconciliation failed")
            results["mounts"] = {"error": "mount reconciliation failed"}

        _refresh_reconciliation_lock(db)

        logger.info("Startup reconciliation: checking jobs")
        try:
            results["jobs"] = reconcile_jobs(db)
        except Exception:
            db.rollback()
            db.expire_all()
            logger.exception("Job reconciliation failed")
            results["jobs"] = {"error": "job reconciliation failed"}

        _refresh_reconciliation_lock(db)

        logger.info("Startup reconciliation: checking USB drives")
        try:
            results["drives"] = reconcile_drives(
                db,
                topology_source=topology_source,
                filesystem_detector=filesystem_detector,
            )
        except Exception:
            db.rollback()
            db.expire_all()
            logger.exception("Drive reconciliation failed")
            results["drives"] = {"error": "drive reconciliation failed"}

        logger.info("Startup reconciliation complete: %s", results)
        return results
    finally:
        _release_reconciliation_lock(db)
