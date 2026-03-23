"""Startup state reconciliation — mounts, jobs, and USB drives.

After a service restart or host reboot, in-memory OS state (active mounts,
running processes, USB device presence) may diverge from the database.  This
module re-aligns persisted state with actual OS/hardware state.

All three passes are **idempotent** — running them multiple times without
underlying state changes produces no additional state mutations.  Observability
side-effects (e.g. ``USB_DISCOVERY_SYNC`` audit entries from the drive pass)
may still be emitted on each invocation.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict

from sqlalchemy.orm import Session

from app.infrastructure.mount_protocol import MountProvider
from app.infrastructure.usb_discovery import DiscoveredTopology
from app.infrastructure import FilesystemDetector
from app.models.jobs import ExportJob, JobStatus
from app.models.network import MountStatus, NetworkMount
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Mount reconciliation
# -----------------------------------------------------------------------

def reconcile_mounts(
    db: Session,
    mount_provider: MountProvider,
) -> Dict[str, int]:
    """Check all ``MOUNTED`` mounts against the OS and correct stale state.

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
        result = mount_provider.check_mounted(mount.local_mount_point)
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
# Orchestrator — runs all three passes
# -----------------------------------------------------------------------

def run_startup_reconciliation(
    db: Session,
    mount_provider: MountProvider,
    *,
    topology_source: Callable[[], DiscoveredTopology],
    filesystem_detector: FilesystemDetector,
) -> Dict[str, Any]:
    """Execute all reconciliation passes during startup.

    Returns a nested summary keyed by domain (``mounts``, ``jobs``,
    ``drives``).  Each value is either a counts dict on success or an
    ``{"error": "..."}`` dict on failure.
    """
    results: Dict[str, Any] = {}

    logger.info("Startup reconciliation: checking mounts")
    try:
        results["mounts"] = reconcile_mounts(db, mount_provider)
    except Exception:
        db.rollback()
        db.expire_all()
        logger.exception("Mount reconciliation failed")
        results["mounts"] = {"error": "mount reconciliation failed"}

    logger.info("Startup reconciliation: checking jobs")
    try:
        results["jobs"] = reconcile_jobs(db)
    except Exception:
        db.rollback()
        db.expire_all()
        logger.exception("Job reconciliation failed")
        results["jobs"] = {"error": "job reconciliation failed"}

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
