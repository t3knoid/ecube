"""Startup state reconciliation — mounts, jobs, and USB drives.

After a service restart or host reboot, in-memory OS state (active mounts,
running processes, USB device presence) may diverge from the database.  This
module re-aligns persisted state with actual OS/hardware state.

All three passes are **idempotent** — running them multiple times produces
the same result without side-effects.
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Dict

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
    audit_repo = AuditRepository(db)
    mounts = (
        db.query(NetworkMount)
        .filter(NetworkMount.status == MountStatus.MOUNTED)
        .all()
    )

    checked = 0
    corrected = 0

    for mount in mounts:
        checked += 1
        result = mount_provider.check_mounted(mount.local_mount_point)

        if result is True:
            # Still mounted — no change needed.
            continue

        old_status = mount.status
        mount.status = MountStatus.UNMOUNTED if result is False else MountStatus.ERROR
        mount.last_checked_at = datetime.now(timezone.utc)

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "DB commit failed reconciling mount %s", mount.id,
            )
            continue
        db.refresh(mount)
        corrected += 1

        try:
            audit_repo.add(
                action="MOUNT_RECONCILED",
                user="system",
                details={
                    "mount_id": mount.id,
                    "local_mount_point": mount.local_mount_point,
                    "old_status": old_status.value,
                    "new_status": mount.status.value,
                    "reason": "startup reconciliation",
                },
            )
        except Exception:
            logger.exception(
                "Failed to write audit log for MOUNT_RECONCILED (mount %s)",
                mount.id,
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
    audit_repo = AuditRepository(db)
    jobs = (
        db.query(ExportJob)
        .filter(ExportJob.status.in_(_IN_PROGRESS_STATUSES))
        .all()
    )

    checked = len(jobs)
    corrected = 0

    for job in jobs:
        old_status = job.status
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "DB commit failed reconciling job %s", job.id,
            )
            continue
        db.refresh(job)
        corrected += 1

        try:
            audit_repo.add(
                action="JOB_RECONCILED",
                user="system",
                job_id=job.id,
                details={
                    "old_status": old_status.value,
                    "new_status": JobStatus.FAILED.value,
                    "reason": "interrupted by restart",
                },
            )
        except Exception:
            logger.exception(
                "Failed to write audit log for JOB_RECONCILED (job %s)",
                job.id,
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
) -> Dict[str, Dict]:
    """Execute all reconciliation passes during startup.

    Returns a nested summary keyed by domain (``mounts``, ``jobs``,
    ``drives``).
    """
    results: Dict[str, Dict] = {}

    logger.info("Startup reconciliation: checking mounts")
    try:
        results["mounts"] = reconcile_mounts(db, mount_provider)
    except Exception:
        logger.exception("Mount reconciliation failed")
        results["mounts"] = {"error": "mount reconciliation failed"}

    logger.info("Startup reconciliation: checking jobs")
    try:
        results["jobs"] = reconcile_jobs(db)
    except Exception:
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
        logger.exception("Drive reconciliation failed")
        results["drives"] = {"error": "drive reconciliation failed"}

    logger.info("Startup reconciliation complete: %s", results)
    return results
