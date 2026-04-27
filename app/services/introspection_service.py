"""Service helpers for system introspection and operator diagnostics."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.jobs import ExportJob, JobStatus
from app.services.copy_worker_runtime import list_active_copy_workers
from app.utils.sanitize import sanitize_error_message


logger = logging.getLogger(__name__)


def get_system_health(
    db: Session,
    *,
    psutil_available: bool,
    psutil_module: Any | None,
) -> dict[str, Any]:
    """Return host and ECUBE-owned runtime diagnostics for the System page."""

    db_status = "connected"
    db_error = None
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = "error"
        db_error = sanitize_error_message(exc, "Database connectivity check failed")

    active_jobs = 0
    if db_status == "connected":
        try:
            active_jobs = db.query(ExportJob).filter(ExportJob.status == JobStatus.RUNNING).count()
        except Exception:
            pass

    worker_queue_size: int | None = None
    if db_status == "connected":
        try:
            worker_queue_size = db.query(ExportJob).filter(ExportJob.status == JobStatus.PENDING).count()
        except Exception:
            pass

    cpu_percent: float | None = None
    memory_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    disk_read_bytes: int | None = None
    disk_write_bytes: int | None = None

    if psutil_available and psutil_module is not None:
        try:
            cpu_percent = psutil_module.cpu_percent(interval=None)
        except Exception:
            pass
        try:
            vm = psutil_module.virtual_memory()
            memory_percent = vm.percent
            memory_used_bytes = vm.used
            memory_total_bytes = vm.total
        except Exception:
            pass
        try:
            disk_counters = psutil_module.disk_io_counters()
            if disk_counters is not None:
                disk_read_bytes = disk_counters.read_bytes
                disk_write_bytes = disk_counters.write_bytes
        except Exception:
            pass

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "database_error": db_error,
        "active_jobs": active_jobs,
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "memory_used_bytes": memory_used_bytes,
        "memory_total_bytes": memory_total_bytes,
        "disk_read_bytes": disk_read_bytes,
        "disk_write_bytes": disk_write_bytes,
        "worker_queue_size": worker_queue_size,
        "ecube_process": _build_ecube_process_metrics(
            db,
            db_status=db_status,
            psutil_available=psutil_available,
            psutil_module=psutil_module,
        ),
    }


def _build_ecube_process_metrics(
    db: Session,
    *,
    db_status: str,
    psutil_available: bool,
    psutil_module: Any | None,
) -> dict[str, Any]:
    active_workers = list_active_copy_workers()
    process_cpu_percent: float | None = None
    process_cpu_time_seconds: float | None = None
    memory_rss_bytes: int | None = None
    memory_vms_bytes: int | None = None
    process_thread_count: int | None = None
    per_thread_cpu_times: dict[int, tuple[float, float]] = {}
    per_thread_metrics_reason = "Per-thread CPU metrics are currently unavailable."

    if psutil_available and psutil_module is not None:
        try:
            process = psutil_module.Process(os.getpid())
        except Exception:
            process = None

        if process is not None:
            try:
                process_cpu_percent = process.cpu_percent(interval=None)
            except Exception:
                pass
            try:
                cpu_times = process.cpu_times()
                process_cpu_time_seconds = float(cpu_times.user + cpu_times.system)
            except Exception:
                pass
            try:
                memory_info = process.memory_info()
                memory_rss_bytes = int(memory_info.rss)
                memory_vms_bytes = int(memory_info.vms)
            except Exception:
                pass
            try:
                process_thread_count = int(process.num_threads())
            except Exception:
                pass
            try:
                per_thread_cpu_times = {
                    int(thread.id): (float(thread.user_time), float(thread.system_time))
                    for thread in process.threads()
                }
                per_thread_metrics_reason = "Per-thread memory metrics are not available on this host."
            except Exception:
                per_thread_metrics_reason = "Per-thread metrics are not available on this host."

    job_context: dict[int, dict[str, Any]] = {}
    if db_status == "connected" and active_workers:
        job_ids = sorted({int(worker["job_id"]) for worker in active_workers if worker.get("job_id") is not None})
        if job_ids:
            try:
                for job in db.query(ExportJob).filter(ExportJob.id.in_(job_ids)).all():
                    job_context[int(job.id)] = {
                        "project_id": job.project_id,
                        "job_status": job.status.value if job.status else None,
                        "configured_thread_count": job.thread_count,
                    }
            except Exception:
                logger.info("System health could not correlate active copy workers to jobs")
                logger.debug(
                    "Active copy worker correlation query failed",
                    exc_info=True,
                )

    active_copy_threads: list[dict[str, Any]] = []
    now_monotonic = time.monotonic()
    for worker in active_workers:
        job_id = int(worker["job_id"])
        job_meta = job_context.get(job_id, {})
        native_thread_id = worker.get("native_thread_id")
        cpu_user_seconds: float | None = None
        cpu_system_seconds: float | None = None
        cpu_time_seconds: float | None = None
        metrics_available = False
        metrics_note = per_thread_metrics_reason
        if isinstance(native_thread_id, int) and native_thread_id in per_thread_cpu_times:
            cpu_user_seconds, cpu_system_seconds = per_thread_cpu_times[native_thread_id]
            cpu_time_seconds = cpu_user_seconds + cpu_system_seconds
            metrics_available = True
            metrics_note = "Per-thread memory metrics are not available on this host."

        started_monotonic = worker.get("started_monotonic")
        elapsed_seconds: float | None = None
        if isinstance(started_monotonic, (int, float)):
            elapsed_seconds = round(max(now_monotonic - float(started_monotonic), 0.0), 3)

        active_copy_threads.append(
            {
                "job_id": job_id,
                "project_id": job_meta.get("project_id"),
                "job_status": job_meta.get("job_status"),
                "configured_thread_count": job_meta.get("configured_thread_count"),
                "worker_label": str(worker.get("worker_label") or f"copy-job-{job_id}"),
                "started_at": str(worker.get("started_at") or ""),
                "elapsed_seconds": elapsed_seconds,
                "cpu_user_seconds": cpu_user_seconds,
                "cpu_system_seconds": cpu_system_seconds,
                "cpu_time_seconds": cpu_time_seconds,
                "memory_bytes": None,
                "metrics_available": metrics_available,
                "metrics_note": metrics_note,
            }
        )

    active_copy_threads.sort(key=lambda item: (item["job_id"], item["worker_label"]))

    return {
        "cpu_percent": process_cpu_percent,
        "cpu_time_seconds": process_cpu_time_seconds,
        "memory_rss_bytes": memory_rss_bytes,
        "memory_vms_bytes": memory_vms_bytes,
        "thread_count": process_thread_count,
        "active_copy_thread_count": len(active_copy_threads),
        "active_copy_threads": active_copy_threads,
    }