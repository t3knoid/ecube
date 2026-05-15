"""Service helpers for system introspection and operator diagnostics."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import ConflictError, NotFoundError
from app.infrastructure import get_drive_discovery
from app.models.jobs import ExportJob, JobStatus
from app.repositories.audit_repository import AuditRepository
from app.services.copy_worker_runtime import list_active_copy_workers
from app.utils.drive_identity import extract_usb_serial_number
from app.utils.sanitize import sanitize_error_message


logger = logging.getLogger(__name__)

_EXFAT_RUNTIME_WARNING_CODE = "exfat_runtime_kernel_mismatch"
_EXFAT_RUNTIME_WARNING_MESSAGE = (
    "exFAT formatting tools are available, but runtime mount support for exFAT is unavailable on this host. "
    "After a kernel change, the matching runtime package can be missing even though formatting still works."
)
_EXFAT_RUNTIME_WARNING_REMEDIATION = (
    "Verify exFAT runtime support for the current kernel, including the documented exfatprogs and linux-modules-extra-$(uname -r) prerequisites, then retry the mount."
)
_EXFAT_LOAD_MODULE_ACTION_CODE = "load_exfat_kernel_module"

_PROCESS_CPU_SAMPLER: Any | None = None
_PROCESS_CPU_SAMPLER_PID: int | None = None
_PROCESS_CPU_SAMPLER_PRIMED = False


def get_usb_topology() -> dict[str, Any]:
    """Return sanitized USB topology details for the System page."""

    topology = get_drive_discovery().discover_topology()
    devices = []

    for port in topology.ports:
        matching_drive = next(
            (drive for drive in topology.drives if drive.port_system_path == port.system_path),
            None,
        )
        devices.append({
            "device": port.system_path,
            "serial": extract_usb_serial_number(
                matching_drive.device_identifier,
                port_system_path=port.system_path,
            ) if matching_drive else None,
            "idVendor": port.vendor_id,
            "idProduct": port.product_id,
            "product": matching_drive.product_name if matching_drive else None,
            "manufacturer": matching_drive.manufacturer if matching_drive else None,
            "speed": matching_drive.speed or port.speed if matching_drive else port.speed,
        })

    return {"devices": devices}


@dataclass(frozen=True)
class _SystemHealthRepairActionDefinition:
    code: str
    warning_code: str
    severity: str
    component: str
    warning_message: str
    warning_remediation: str
    label: str
    description: str
    confirm_title: str
    confirm_message: str
    success_message: str
    not_needed_message: str
    failure_message: str
    is_active: Callable[[Any | None], bool]
    execute: Callable[[Any], None]


def _exfat_runtime_warning_is_active(filesystem_runtime_inspector: Any | None) -> bool:
    if filesystem_runtime_inspector is None:
        return False

    try:
        formatting_available = bool(filesystem_runtime_inspector.exfat_formatting_available())
        mount_runtime_available = filesystem_runtime_inspector.exfat_mount_runtime_available()
    except Exception:
        logger.info(
            "System health repair-action availability unavailable",
            extra={"failure_class": "filesystem_runtime_diagnostics_unavailable"},
        )
        logger.debug("Filesystem runtime repair-action probe failed", exc_info=True)
        return False

    return formatting_available and mount_runtime_available is False


_SYSTEM_HEALTH_REPAIR_ACTIONS: dict[str, _SystemHealthRepairActionDefinition] = {
    _EXFAT_LOAD_MODULE_ACTION_CODE: _SystemHealthRepairActionDefinition(
        code=_EXFAT_LOAD_MODULE_ACTION_CODE,
        warning_code=_EXFAT_RUNTIME_WARNING_CODE,
        severity="warning",
        component="filesystem_runtime",
        warning_message=_EXFAT_RUNTIME_WARNING_MESSAGE,
        warning_remediation=_EXFAT_RUNTIME_WARNING_REMEDIATION,
        label="Load exFAT runtime support",
        description="Run the host repair step that loads the exFAT kernel module for the current running kernel.",
        confirm_title="Load exFAT runtime support?",
        confirm_message="This will run an explicit host repair action to load the exFAT kernel module for the current kernel. Use this only when runtime warnings show exFAT mount support is missing.",
        success_message="exFAT runtime support reload requested. Refreshing health should now clear the warning if the host accepted the module load.",
        not_needed_message="exFAT runtime support is already available on this host.",
        failure_message="The host could not load exFAT runtime support.",
        is_active=_exfat_runtime_warning_is_active,
        execute=lambda runtime_repair_provider: runtime_repair_provider.load_kernel_module("exfat"),
    ),
}


def _build_cross_process_copy_worker_fallback(job: ExportJob) -> list[dict[str, Any]]:
    configured_thread_count = int(job.thread_count or settings.copy_default_thread_count)
    started_at = job.started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if job.started_at else ""
    elapsed_seconds: float | None = None
    if job.started_at is not None:
        started_at_utc = job.started_at.astimezone(timezone.utc)
        elapsed_seconds = round(max((datetime.now(timezone.utc) - started_at_utc).total_seconds(), 0.0), 3)

    return [
        {
            "job_id": int(job.id),
            "project_id": job.project_id,
            "job_status": job.status.value if job.status else None,
            "configured_thread_count": configured_thread_count,
            "worker_label": f"copy-job-{int(job.id)}_{index}",
            "started_at": started_at,
            "elapsed_seconds": elapsed_seconds,
            "cpu_user_seconds": None,
            "cpu_system_seconds": None,
            "cpu_time_seconds": None,
            "memory_bytes": None,
            "metrics_available": False,
            "metrics_note": "Active copy worker is running in another ECUBE worker process; showing configured copy threads from the running job.",
        }
        for index in range(configured_thread_count)
    ]


def _get_process_cpu_sampler(psutil_module: Any) -> Any | None:
    global _PROCESS_CPU_SAMPLER
    global _PROCESS_CPU_SAMPLER_PID
    global _PROCESS_CPU_SAMPLER_PRIMED

    current_pid = os.getpid()
    if _PROCESS_CPU_SAMPLER is not None and _PROCESS_CPU_SAMPLER_PID == current_pid:
        return _PROCESS_CPU_SAMPLER

    try:
        _PROCESS_CPU_SAMPLER = psutil_module.Process(current_pid)
    except Exception:
        _PROCESS_CPU_SAMPLER = None
        _PROCESS_CPU_SAMPLER_PID = None
        _PROCESS_CPU_SAMPLER_PRIMED = False
        return None

    _PROCESS_CPU_SAMPLER_PID = current_pid
    _PROCESS_CPU_SAMPLER_PRIMED = False
    return _PROCESS_CPU_SAMPLER


def prime_process_cpu_sampler(*, psutil_module: Any) -> None:
    global _PROCESS_CPU_SAMPLER_PRIMED

    process = _get_process_cpu_sampler(psutil_module)
    if process is None:
        return

    try:
        process.cpu_percent(interval=None)
        _PROCESS_CPU_SAMPLER_PRIMED = True
    except Exception:
        logger.debug("Failed to prime ECUBE process CPU sampler", exc_info=True)


def get_system_health(
    db: Session,
    *,
    psutil_available: bool,
    psutil_module: Any | None,
    filesystem_runtime_inspector: Any | None = None,
    runtime_repair_provider: Any | None = None,
    include_repair_actions: bool = False,
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
            active_jobs = db.query(ExportJob).filter(ExportJob.status.in_((JobStatus.PREPARING, JobStatus.RUNNING))).count()
        except Exception:
            pass

    worker_queue_size: int | None = None
    if db_status == "connected":
        try:
            worker_queue_size = db.query(ExportJob).filter(ExportJob.status == JobStatus.PENDING).count()
        except Exception:
            pass

    cpu_percent: float | None = None
    physical_cores: int | None = None
    logical_cpus: int | None = None
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
            detected_physical_cores = psutil_module.cpu_count(logical=False)
            if isinstance(detected_physical_cores, int) and detected_physical_cores > 0:
                physical_cores = detected_physical_cores
        except Exception:
            logger.info(
                "System health metric unavailable",
                extra={"failure_class": "cpu_topology_metric_unavailable", "metric": "physical_cores"},
            )
            logger.debug("Physical core count sampling failed", exc_info=True)
        try:
            detected_logical_cpus = psutil_module.cpu_count(logical=True)
            if isinstance(detected_logical_cpus, int) and detected_logical_cpus > 0:
                logical_cpus = detected_logical_cpus
        except Exception:
            logger.info(
                "System health metric unavailable",
                extra={"failure_class": "cpu_topology_metric_unavailable", "metric": "logical_cpus"},
            )
            logger.debug("Logical CPU count sampling failed", exc_info=True)
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

    warnings = _build_runtime_warnings(
        filesystem_runtime_inspector,
        runtime_repair_provider=runtime_repair_provider,
        include_repair_actions=include_repair_actions,
    )

    return {
        "status": "ok" if db_status == "connected" and not warnings else "degraded",
        "database": db_status,
        "database_error": db_error,
        "active_jobs": active_jobs,
        "cpu_percent": cpu_percent,
        "physical_cores": physical_cores,
        "logical_cpus": logical_cpus,
        "memory_percent": memory_percent,
        "memory_used_bytes": memory_used_bytes,
        "memory_total_bytes": memory_total_bytes,
        "disk_read_bytes": disk_read_bytes,
        "disk_write_bytes": disk_write_bytes,
        "worker_queue_size": worker_queue_size,
        "warnings": warnings,
        "ecube_process": _build_ecube_process_metrics(
            db,
            db_status=db_status,
            psutil_available=psutil_available,
            psutil_module=psutil_module,
        ),
    }


def _build_runtime_warnings(
    filesystem_runtime_inspector: Any | None,
    *,
    runtime_repair_provider: Any | None = None,
    include_repair_actions: bool = False,
) -> list[dict[str, Any]]:
    if filesystem_runtime_inspector is None:
        return []

    warnings_by_code: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for action in _SYSTEM_HEALTH_REPAIR_ACTIONS.values():
        if not action.is_active(filesystem_runtime_inspector):
            continue

        warning = warnings_by_code.setdefault(
            action.warning_code,
            {
                "code": action.warning_code,
                "severity": action.severity,
                "component": action.component,
                "message": action.warning_message,
                "remediation": action.warning_remediation,
                "actions": [],
            },
        )

        if runtime_repair_provider is not None and include_repair_actions:
            warning["actions"].append(
                {
                    "code": action.code,
                    "label": action.label,
                    "description": action.description,
                    "confirm_title": action.confirm_title,
                    "confirm_message": action.confirm_message,
                }
            )

    return list(warnings_by_code.values())


def run_system_health_repair_action(
    db: Session,
    *,
    action_code: str,
    actor: str,
    filesystem_runtime_inspector: Any | None,
    runtime_repair_provider: Any | None,
) -> dict[str, str]:
    action = _SYSTEM_HEALTH_REPAIR_ACTIONS.get(action_code)
    if action is None:
        raise NotFoundError(
            message="Unknown system repair action.",
            code="SYSTEM_REPAIR_ACTION_NOT_FOUND",
        )

    if runtime_repair_provider is None:
        raise ConflictError(
            message="System repair actions are unavailable on this host.",
            code="SYSTEM_REPAIR_ACTION_UNAVAILABLE",
        )

    if not _is_system_health_repair_action_needed(action.code, filesystem_runtime_inspector):
        result = {
            "code": action.code,
            "status": "not_needed",
            "message": action.not_needed_message,
        }
        _write_system_repair_audit(db, actor=actor, action=action, status="not_needed")
        return result

    logger.info(
        "System repair action requested",
        extra={
            "action_code": action.code,
            "warning_code": action.warning_code,
            "actor_username": actor,
        },
    )

    try:
        _execute_system_health_repair_action(action.code, runtime_repair_provider)
    except RuntimeError as exc:
        safe_message = sanitize_error_message(str(exc), action.failure_message)
        logger.info(
            "System repair action failed",
            extra={
                "action_code": action.code,
                "warning_code": action.warning_code,
                "actor_username": actor,
                "failure_class": "system_repair_action_failed",
            },
        )
        logger.debug(
            "System repair action raw failure",
            extra={
                "action_code": action.code,
                "warning_code": action.warning_code,
                "actor_username": actor,
                "raw_error": str(exc),
            },
        )
        _write_system_repair_audit(db, actor=actor, action=action, status="failed", reason=safe_message)
        raise ConflictError(
            message=safe_message,
            code="SYSTEM_REPAIR_ACTION_FAILED",
        ) from exc

    if _is_system_health_repair_action_needed(action.code, filesystem_runtime_inspector):
        logger.info(
            "System repair action completed without clearing warning",
            extra={
                "action_code": action.code,
                "warning_code": action.warning_code,
                "actor_username": actor,
                "failure_class": "system_repair_action_not_effective",
            },
        )
        _write_system_repair_audit(
            db,
            actor=actor,
            action=action,
            status="failed",
            reason="warning_persisted_after_action",
        )
        raise ConflictError(
            message="The repair action completed, but the runtime warning is still active.",
            code="SYSTEM_REPAIR_ACTION_NOT_EFFECTIVE",
        )

    result = {
        "code": action.code,
        "status": "ok",
        "message": action.success_message,
    }
    _write_system_repair_audit(db, actor=actor, action=action, status="ok")
    return result


def _is_system_health_repair_action_needed(action_code: str, filesystem_runtime_inspector: Any | None) -> bool:
    action = _SYSTEM_HEALTH_REPAIR_ACTIONS.get(action_code)
    if action is None:
        return False
    return action.is_active(filesystem_runtime_inspector)


def _execute_system_health_repair_action(action_code: str, runtime_repair_provider: Any) -> None:
    action = _SYSTEM_HEALTH_REPAIR_ACTIONS.get(action_code)
    if action is None:
        raise RuntimeError("Unsupported system repair action")
    action.execute(runtime_repair_provider)


def _write_system_repair_audit(
    db: Session,
    *,
    actor: str,
    action: _SystemHealthRepairActionDefinition,
    status: str,
    reason: str | None = None,
) -> None:
    details: dict[str, str] = {
        "action_code": action.code,
        "warning_code": action.warning_code,
        "status": status,
    }
    if reason:
        details["reason"] = reason

    try:
        AuditRepository(db).add(
            action="SYSTEM_REPAIR_ACTION",
            user=actor,
            details=details,
        )
    except Exception as exc:
        logger.info(
            "System repair action audit write failed",
            extra={
                "action_code": action.code,
                "warning_code": action.warning_code,
                "actor_username": actor,
                "failure_class": "system_repair_action_audit_write_failed",
            },
        )
        logger.debug(
            "System repair action audit write raw failure",
            extra={
                "action_code": action.code,
                "warning_code": action.warning_code,
                "actor_username": actor,
                "raw_error": str(exc),
            },
        )
        raise ConflictError(
            message="The repair action could not be recorded in the audit log.",
            code="SYSTEM_REPAIR_ACTION_AUDIT_FAILED",
        ) from exc


def _build_ecube_process_metrics(
    db: Session,
    *,
    db_status: str,
    psutil_available: bool,
    psutil_module: Any | None,
) -> dict[str, Any]:
    global _PROCESS_CPU_SAMPLER_PRIMED

    active_workers = list_active_copy_workers()
    running_jobs: list[ExportJob] = []
    process_cpu_percent: float | None = None
    process_cpu_time_seconds: float | None = None
    memory_rss_bytes: int | None = None
    memory_vms_bytes: int | None = None
    process_thread_count: int | None = None
    per_thread_cpu_times: dict[int, tuple[float, float]] = {}
    per_thread_metrics_reason = "Per-thread CPU metrics are currently unavailable."

    if psutil_available and psutil_module is not None:
        process = _get_process_cpu_sampler(psutil_module)

        if process is not None:
            if _PROCESS_CPU_SAMPLER_PRIMED:
                try:
                    process_cpu_percent = process.cpu_percent(interval=None)
                except Exception:
                    pass
            else:
                try:
                    process.cpu_percent(interval=None)
                    _PROCESS_CPU_SAMPLER_PRIMED = True
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

    if db_status == "connected" and not active_workers:
        try:
            running_jobs = (
                db.query(ExportJob)
                .filter(ExportJob.status.in_((JobStatus.PREPARING, JobStatus.RUNNING)))
                .order_by(ExportJob.id.asc())
                .all()
            )
        except Exception:
            logger.info("System health could not load running jobs for cross-process copy worker fallback")
            logger.debug(
                "Cross-process active copy worker fallback query failed",
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

    if not active_copy_threads and running_jobs:
        for job in running_jobs:
            active_copy_threads.extend(_build_cross_process_copy_worker_fallback(job))

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