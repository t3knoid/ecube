from __future__ import annotations

import asyncio
import gc
import logging
import os
import threading
import time
from collections import defaultdict
from typing import Any, Callable, Optional

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import Pool
from starlette.routing import BaseRoute, Match

from app.infrastructure import get_drive_discovery
from app.models.hardware import DriveState, UsbDrive, UsbHub, UsbPort
from app.models.jobs import ExportJob, JobStatus
from app.models.network import MountStatus, MountType, NetworkShare

logger = logging.getLogger(__name__)

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUEST_DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
JOB_COPY_DURATION_BUCKETS = (1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200)
VERIFY_DURATION_BUCKETS = (0.1, 0.5, 1, 5, 10, 30, 60, 120, 300)
DB_QUERY_DURATION_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5)
RECONCILIATION_DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
SAMPLING_INTERVAL_SECONDS = 5.0

_METRICS_LOCK = threading.Lock()
_DB_EVENTS_INSTALLED = False
_PROCESS = None
_PROCESS_IMPORT_ERROR = None
_START_MONOTONIC = time.monotonic()
_UPTIME_SECONDS_RECORDED = 0.0
_GC_COLLECTIONS_RECORDED = 0
_SAMPLER_STATE: dict[str, Any] = {
    "last_run_monotonic": None,
    "last_job_samples": {},
}

try:
    import psutil as _psutil
except Exception as exc:  # pragma: no cover - depends on runtime environment
    _psutil = None
    _PROCESS_IMPORT_ERROR = exc


HTTP_REQUESTS_TOTAL = Counter(
    "ecube_http_requests_total",
    "Total HTTP requests by method, route template, and response status class.",
    labelnames=("method", "route", "status_class"),
    registry=REGISTRY,
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "ecube_http_request_duration_seconds",
    "HTTP request duration in seconds by method and route template.",
    labelnames=("method", "route"),
    buckets=HTTP_REQUEST_DURATION_BUCKETS,
    registry=REGISTRY,
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "ecube_http_requests_in_progress",
    "HTTP requests currently in progress by method and route template.",
    labelnames=("method", "route"),
    registry=REGISTRY,
)

AUTH_ATTEMPTS_TOTAL = Counter(
    "ecube_auth_attempts_total",
    "Authentication attempts by normalized result.",
    labelnames=("result",),
    registry=REGISTRY,
)
ROLE_DENIALS_TOTAL = Counter(
    "ecube_role_denials_total",
    "Requests denied because the authenticated user lacks a required role.",
    labelnames=("route",),
    registry=REGISTRY,
)

JOBS_CREATED_TOTAL = Counter(
    "ecube_jobs_created_total",
    "Jobs created since process start.",
    registry=REGISTRY,
)
JOBS_RUNNING = Gauge(
    "ecube_jobs_running",
    "Jobs currently in RUNNING state.",
    registry=REGISTRY,
)
JOBS_COMPLETED_TOTAL = Counter(
    "ecube_jobs_completed_total",
    "Jobs that reached COMPLETED since process start.",
    registry=REGISTRY,
)
JOBS_FAILED_TOTAL = Counter(
    "ecube_jobs_failed_total",
    "Jobs that reached FAILED since process start.",
    registry=REGISTRY,
)
JOB_COPY_DURATION_SECONDS = Histogram(
    "ecube_job_copy_duration_seconds",
    "Copy-phase duration in seconds for terminal job outcomes.",
    labelnames=("outcome", "thread_count_bucket"),
    buckets=JOB_COPY_DURATION_BUCKETS,
    registry=REGISTRY,
)
JOB_FILES_COPIED_TOTAL = Counter(
    "ecube_job_files_copied_total",
    "Files successfully copied across all jobs since process start.",
    registry=REGISTRY,
)
JOB_BYTES_COPIED_TOTAL = Counter(
    "ecube_job_bytes_copied_total",
    "Bytes successfully copied across all jobs since process start.",
    registry=REGISTRY,
)
JOB_COPY_ERRORS_TOTAL = Counter(
    "ecube_job_copy_errors_total",
    "Copy-engine errors by normalized outcome.",
    labelnames=("outcome",),
    registry=REGISTRY,
)
JOB_COPY_THROUGHPUT_BYTES_PER_SECOND = Gauge(
    "ecube_job_copy_throughput_bytes_per_second",
    "Aggregated instantaneous throughput for active jobs by thread-count bucket.",
    labelnames=("thread_count_bucket",),
    registry=REGISTRY,
)
JOB_COPY_SCHEDULER_CONTROL_POLLS_TOTAL = Counter(
    "ecube_job_copy_scheduler_control_polls_total",
    "Copy scheduler control-state polls by trigger reason.",
    labelnames=("reason",),
    registry=REGISTRY,
)
JOB_COPY_SCHEDULER_CONTROL_POLL_INTERVAL_SECONDS = Histogram(
    "ecube_job_copy_scheduler_control_poll_interval_seconds",
    "Elapsed seconds between copy scheduler control-state polls.",
    labelnames=("reason",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2),
    registry=REGISTRY,
)
JOB_COPY_SCHEDULER_COMPLETIONS_PER_CONTROL_POLL = Histogram(
    "ecube_job_copy_scheduler_completions_per_control_poll",
    "Worker completions observed between copy scheduler control-state polls.",
    buckets=(0, 1, 2, 4, 8, 16, 32),
    registry=REGISTRY,
)
JOB_COPY_SCHEDULER_REFILL_LATENCY_SECONDS = Histogram(
    "ecube_job_copy_scheduler_refill_latency_seconds",
    "Elapsed seconds between a worker completion and submission of replacement work.",
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25),
    registry=REGISTRY,
)
JOB_VERIFY_DURATION_SECONDS = Histogram(
    "ecube_job_verify_duration_seconds",
    "Verification duration in seconds by terminal verification outcome.",
    labelnames=("outcome",),
    buckets=VERIFY_DURATION_BUCKETS,
    registry=REGISTRY,
)

METRICS_SAMPLING_RUNS_TOTAL = Counter(
    "ecube_metrics_sampling_runs_total",
    "Metrics sampling loop executions by normalized outcome.",
    labelnames=("outcome",),
    registry=REGISTRY,
)
METRICS_SAMPLING_LAG_SECONDS = Gauge(
    "ecube_metrics_sampling_lag_seconds",
    "Current sampling lag relative to the target interval.",
    registry=REGISTRY,
)

USB_HUBS_TOTAL = Gauge(
    "ecube_usb_hubs_total",
    "USB hubs currently recorded in the discovery snapshot.",
    registry=REGISTRY,
)
USB_PORTS_TOTAL = Gauge(
    "ecube_usb_ports_total",
    "USB ports currently recorded in the discovery snapshot.",
    registry=REGISTRY,
)
USB_DRIVES_PRESENT = Gauge(
    "ecube_usb_drives_present",
    "Physically present USB drives.",
    registry=REGISTRY,
)
USB_DRIVES_STATE = Gauge(
    "ecube_usb_drives_state",
    "USB drives grouped by ECUBE runtime state bucket.",
    labelnames=("state",),
    registry=REGISTRY,
)
PORT_ENABLED_TOTAL = Gauge(
    "ecube_port_enabled_total",
    "USB ports that are administratively enabled.",
    registry=REGISTRY,
)
NETWORK_MOUNTS_STATE = Gauge(
    "ecube_network_mounts_state",
    "Network mounts grouped by state and mount type.",
    labelnames=("state", "mount_type"),
    registry=REGISTRY,
)
DRIVE_FORMAT_TOTAL = Counter(
    "ecube_drive_format_total",
    "Drive format operations by filesystem type and normalized outcome.",
    labelnames=("filesystem_type", "outcome"),
    registry=REGISTRY,
)
DRIVE_EJECT_TOTAL = Counter(
    "ecube_drive_eject_total",
    "Prepare-eject operations by normalized outcome.",
    labelnames=("outcome",),
    registry=REGISTRY,
)

DB_CONNECTION_POOL_SIZE = Gauge(
    "ecube_db_connection_pool_size",
    "Configured or effective database connection pool size when available.",
    registry=REGISTRY,
)
DB_CONNECTION_POOL_IN_USE = Gauge(
    "ecube_db_connection_pool_in_use",
    "Database connections currently checked out when available.",
    registry=REGISTRY,
)
DB_CONNECTION_POOL_IDLE = Gauge(
    "ecube_db_connection_pool_idle",
    "Database connections currently idle in the pool when available.",
    registry=REGISTRY,
)
DB_CONNECTION_POOL_OVERFLOW = Gauge(
    "ecube_db_connection_pool_overflow",
    "Database pool overflow connections currently in use when available.",
    registry=REGISTRY,
)
DB_QUERY_DURATION_SECONDS = Histogram(
    "ecube_db_query_duration_seconds",
    "Database query duration in seconds by normalized operation type.",
    labelnames=("operation",),
    buckets=DB_QUERY_DURATION_BUCKETS,
    registry=REGISTRY,
)
DB_CONNECTIONS_CREATED_TOTAL = Counter(
    "ecube_db_connections_created_total",
    "Database connections created since process start.",
    registry=REGISTRY,
)
DB_CONNECTIONS_CLOSED_TOTAL = Counter(
    "ecube_db_connections_closed_total",
    "Database connections closed since process start.",
    registry=REGISTRY,
)

RECONCILIATION_RUNS_TOTAL = Counter(
    "ecube_reconciliation_runs_total",
    "Startup reconciliation pass executions by pass and outcome.",
    labelnames=("pass", "outcome"),
    registry=REGISTRY,
)
RECONCILIATION_DURATION_SECONDS = Histogram(
    "ecube_reconciliation_duration_seconds",
    "Startup reconciliation pass duration in seconds by pass and outcome.",
    labelnames=("pass", "outcome"),
    buckets=RECONCILIATION_DURATION_BUCKETS,
    registry=REGISTRY,
)

UPTIME_SECONDS = Counter(
    "ecube_uptime_seconds",
    "Process uptime in seconds since start, exported as a monotonic counter.",
    registry=REGISTRY,
)
PROCESS_RESIDENT_MEMORY_BYTES = Gauge(
    "process_resident_memory_bytes",
    "Resident memory used by the ECUBE process.",
    registry=REGISTRY,
)
PROCESS_VIRTUAL_MEMORY_BYTES = Gauge(
    "process_virtual_memory_bytes",
    "Virtual memory used by the ECUBE process.",
    registry=REGISTRY,
)
PYTHON_GC_COLLECTIONS_TOTAL = Counter(
    "ecube_python_gc_collections_total",
    "Python garbage-collection cycles since process start.",
    registry=REGISTRY,
)


def _normalize_status_class(status_code: int) -> str:
    return f"{max(1, int(status_code)) // 100}xx"


def _thread_count_bucket(thread_count: Optional[int]) -> str:
    value = int(thread_count or 0)
    if value <= 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 4:
        return "3_4"
    if value <= 8:
        return "5_8"
    if value <= 16:
        return "9_16"
    return "17_plus"


def _db_operation_for_statement(statement: str) -> Optional[str]:
    normalized = str(statement or "").lstrip().split(None, 1)
    if not normalized:
        return None
    token = normalized[0].lower()
    if token in {"select", "insert", "update", "delete"}:
        return token
    return None


def route_template_from_request(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path

    for candidate in request.app.routes:
        if not isinstance(candidate, BaseRoute):
            continue
        match, _ = candidate.matches(request.scope)
        candidate_path = getattr(candidate, "path", None)
        if match != Match.NONE and isinstance(candidate_path, str) and candidate_path:
            return candidate_path

    return "unmatched"


def install_sqlalchemy_metrics_hooks() -> None:
    global _DB_EVENTS_INSTALLED

    with _METRICS_LOCK:
        if _DB_EVENTS_INSTALLED:
            return

        @event.listens_for(Engine, "before_cursor_execute")
        def _before_cursor_execute(_conn, _cursor, statement, _parameters, context, _executemany):
            context._ecube_metrics_query_started_at = time.perf_counter()
            context._ecube_metrics_query_operation = _db_operation_for_statement(statement)

        @event.listens_for(Engine, "after_cursor_execute")
        def _after_cursor_execute(_conn, _cursor, _statement, _parameters, context, _executemany):
            operation = getattr(context, "_ecube_metrics_query_operation", None)
            started_at = getattr(context, "_ecube_metrics_query_started_at", None)
            if operation is None or started_at is None:
                return
            DB_QUERY_DURATION_SECONDS.labels(operation=operation).observe(max(time.perf_counter() - started_at, 0.0))

        @event.listens_for(Pool, "connect")
        def _on_pool_connect(_dbapi_connection, _connection_record):
            DB_CONNECTIONS_CREATED_TOTAL.inc()

        @event.listens_for(Pool, "close")
        def _on_pool_close(_dbapi_connection, _connection_record):
            DB_CONNECTIONS_CLOSED_TOTAL.inc()

        _DB_EVENTS_INSTALLED = True


def record_http_request_start(*, method: str, route: str) -> None:
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method, route=route).inc()


def record_http_request_finish(*, method: str, route: str, status_code: int, duration_seconds: float) -> None:
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method, route=route).dec()
    HTTP_REQUESTS_TOTAL.labels(
        method=method,
        route=route,
        status_class=_normalize_status_class(status_code),
    ).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(max(duration_seconds, 0.0))


def record_auth_attempt(result: str) -> None:
    if result not in {"success", "invalid_credentials", "token_invalid", "token_expired"}:
        return
    AUTH_ATTEMPTS_TOTAL.labels(result=result).inc()


def record_role_denial(route: str) -> None:
    ROLE_DENIALS_TOTAL.labels(route=route or "unmatched").inc()


def record_job_created() -> None:
    JOBS_CREATED_TOTAL.inc()


def record_job_terminal_status(outcome: str) -> None:
    if outcome == "completed":
        JOBS_COMPLETED_TOTAL.inc()
    elif outcome == "failed":
        JOBS_FAILED_TOTAL.inc()


def record_job_copy_terminal(*, outcome: str, thread_count: Optional[int], duration_seconds: float) -> None:
    if outcome not in {"completed", "failed"}:
        return
    record_job_terminal_status(outcome)
    JOB_COPY_DURATION_SECONDS.labels(
        outcome=outcome,
        thread_count_bucket=_thread_count_bucket(thread_count),
    ).observe(max(duration_seconds, 0.0))


def record_job_file_copied(*, bytes_copied: int) -> None:
    JOB_FILES_COPIED_TOTAL.inc()
    JOB_BYTES_COPIED_TOTAL.inc(max(int(bytes_copied), 0))


def record_job_copy_error(outcome: str) -> None:
    if outcome not in {"retry", "failed"}:
        return
    JOB_COPY_ERRORS_TOTAL.labels(outcome=outcome).inc()


def record_copy_scheduler_control_poll(*, reason: str, interval_seconds: float, completions_since_last: int) -> None:
    if reason not in {"startup", "interval", "completion_budget", "worker_exception"}:
        return
    JOB_COPY_SCHEDULER_CONTROL_POLLS_TOTAL.labels(reason=reason).inc()
    JOB_COPY_SCHEDULER_CONTROL_POLL_INTERVAL_SECONDS.labels(reason=reason).observe(max(interval_seconds, 0.0))
    JOB_COPY_SCHEDULER_COMPLETIONS_PER_CONTROL_POLL.observe(max(float(completions_since_last), 0.0))


def record_copy_scheduler_refill_latency(*, latency_seconds: float) -> None:
    JOB_COPY_SCHEDULER_REFILL_LATENCY_SECONDS.observe(max(latency_seconds, 0.0))


def record_job_verify_terminal(*, outcome: str, duration_seconds: float) -> None:
    if outcome not in {"completed", "failed"}:
        return
    JOB_VERIFY_DURATION_SECONDS.labels(outcome=outcome).observe(max(duration_seconds, 0.0))


def record_drive_format(*, filesystem_type: Optional[str], outcome: str) -> None:
    if outcome not in {"success", "error"}:
        return
    DRIVE_FORMAT_TOTAL.labels(
        filesystem_type=(filesystem_type or "unknown").lower(),
        outcome=outcome,
    ).inc()


def record_drive_eject(outcome: str) -> None:
    if outcome not in {"prepared", "failed"}:
        return
    DRIVE_EJECT_TOTAL.labels(outcome=outcome).inc()


def record_reconciliation_pass(*, pass_name: str, outcome: str, duration_seconds: float) -> None:
    if pass_name not in {"mounts", "jobs", "drives"}:
        return
    if outcome not in {"success", "error", "skipped"}:
        return
    labels = {"pass": pass_name, "outcome": outcome}
    RECONCILIATION_RUNS_TOTAL.labels(**labels).inc()
    RECONCILIATION_DURATION_SECONDS.labels(**labels).observe(max(duration_seconds, 0.0))


def _update_uptime_metric() -> None:
    global _UPTIME_SECONDS_RECORDED

    elapsed = max(time.monotonic() - _START_MONOTONIC, 0.0)
    delta = max(elapsed - _UPTIME_SECONDS_RECORDED, 0.0)
    if delta > 0:
        UPTIME_SECONDS.inc(delta)
        _UPTIME_SECONDS_RECORDED = elapsed


def _update_gc_metric() -> None:
    global _GC_COLLECTIONS_RECORDED

    try:
        total_collections = int(sum(int(item.get("collections", 0)) for item in gc.get_stats()))
    except Exception:
        return
    delta = total_collections - _GC_COLLECTIONS_RECORDED
    if delta > 0:
        PYTHON_GC_COLLECTIONS_TOTAL.inc(delta)
        _GC_COLLECTIONS_RECORDED = total_collections


def _update_process_metrics() -> None:
    global _PROCESS

    if _psutil is None:
        if _PROCESS_IMPORT_ERROR is not None:
            logger.debug("psutil unavailable for metrics", extra={"raw_error": str(_PROCESS_IMPORT_ERROR)})
        PROCESS_RESIDENT_MEMORY_BYTES.set(0)
        PROCESS_VIRTUAL_MEMORY_BYTES.set(0)
        return

    if _PROCESS is None:
        _PROCESS = _psutil.Process(os.getpid())

    try:
        memory = _PROCESS.memory_info()
    except Exception as exc:
        logger.debug("Process metrics unavailable", extra={"raw_error": str(exc)})
        return

    PROCESS_RESIDENT_MEMORY_BYTES.set(int(memory.rss))
    PROCESS_VIRTUAL_MEMORY_BYTES.set(int(memory.vms))


def _set_pool_metric(metric: Gauge, value: Optional[int | float]) -> None:
    metric.set(float(value or 0))


def _update_db_pool_metrics(db: Session | None) -> None:
    bind = None
    try:
        bind = db.get_bind() if db is not None else None
    except Exception:
        bind = None

    pool = getattr(bind, "pool", None)
    if pool is None:
        _set_pool_metric(DB_CONNECTION_POOL_SIZE, 0)
        _set_pool_metric(DB_CONNECTION_POOL_IN_USE, 0)
        _set_pool_metric(DB_CONNECTION_POOL_IDLE, 0)
        _set_pool_metric(DB_CONNECTION_POOL_OVERFLOW, 0)
        return

    size = pool.size() if callable(getattr(pool, "size", None)) else 0
    checked_out = pool.checkedout() if callable(getattr(pool, "checkedout", None)) else 0
    checked_in = pool.checkedin() if callable(getattr(pool, "checkedin", None)) else 0
    overflow = pool.overflow() if callable(getattr(pool, "overflow", None)) else 0
    _set_pool_metric(DB_CONNECTION_POOL_SIZE, size)
    _set_pool_metric(DB_CONNECTION_POOL_IN_USE, checked_out)
    _set_pool_metric(DB_CONNECTION_POOL_IDLE, checked_in)
    _set_pool_metric(DB_CONNECTION_POOL_OVERFLOW, overflow)


def _update_job_metrics(db: Session | None) -> None:
    if db is None:
        JOBS_RUNNING.set(0)
        return
    try:
        running_jobs = db.query(ExportJob).filter(ExportJob.status == JobStatus.RUNNING).count()
    except Exception as exc:
        logger.debug("Job metrics snapshot failed", extra={"raw_error": str(exc)})
        return
    JOBS_RUNNING.set(int(running_jobs))


def _update_drive_and_mount_metrics(db: Session | None) -> None:
    USB_DRIVES_STATE.clear()
    NETWORK_MOUNTS_STATE.clear()

    if db is None:
        USB_HUBS_TOTAL.set(0)
        USB_PORTS_TOTAL.set(0)
        USB_DRIVES_PRESENT.set(0)
        PORT_ENABLED_TOTAL.set(0)
        for state in ("empty", "available", "in_use"):
            USB_DRIVES_STATE.labels(state=state).set(0)
        return

    try:
        USB_HUBS_TOTAL.set(int(db.query(UsbHub).count()))
        USB_PORTS_TOTAL.set(int(db.query(UsbPort).count()))
        PORT_ENABLED_TOTAL.set(int(db.query(UsbPort).filter(UsbPort.enabled.is_(True)).count()))

        empty_count = int(db.query(UsbDrive).filter(UsbDrive.current_state == DriveState.DISABLED).count())
        available_count = int(db.query(UsbDrive).filter(UsbDrive.current_state == DriveState.AVAILABLE).count())
        in_use_count = int(db.query(UsbDrive).filter(UsbDrive.current_state == DriveState.IN_USE).count())
        present_count = empty_count + available_count + in_use_count

        USB_DRIVES_PRESENT.set(present_count)
        USB_DRIVES_STATE.labels(state="empty").set(empty_count)
        USB_DRIVES_STATE.labels(state="available").set(available_count)
        USB_DRIVES_STATE.labels(state="in_use").set(in_use_count)

        for mount_type in MountType:
            mount_type_label = mount_type.value.lower()
            for state_label, mount_state in (("mounted", MountStatus.MOUNTED), ("unmounted", MountStatus.UNMOUNTED), ("error", MountStatus.ERROR)):
                count = int(
                    db.query(NetworkShare)
                    .filter(NetworkShare.type == mount_type, NetworkShare.status == mount_state)
                    .count()
                )
                NETWORK_MOUNTS_STATE.labels(state=state_label, mount_type=mount_type_label).set(count)
    except Exception as exc:
        logger.debug("Drive or mount metrics snapshot failed", extra={"raw_error": str(exc)})
        try:
            topology = get_drive_discovery().discover_topology()
        except Exception:
            return
        USB_HUBS_TOTAL.set(len(getattr(topology, "hubs", []) or []))
        USB_PORTS_TOTAL.set(len(getattr(topology, "ports", []) or []))


def update_scrape_time_metrics(db: Session | None) -> None:
    _update_uptime_metric()
    _update_gc_metric()
    _update_process_metrics()
    _update_db_pool_metrics(db)
    _update_job_metrics(db)
    _update_drive_and_mount_metrics(db)


def render_metrics(db: Session | None) -> bytes:
    update_scrape_time_metrics(db)
    return generate_latest(REGISTRY)


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


def sample_active_job_throughput(
    *,
    db_factory: Callable[[], Session],
    sampled_at_monotonic: Optional[float] = None,
) -> str:
    if sampled_at_monotonic is None:
        sampled_at_monotonic = time.monotonic()

    last_run = _SAMPLER_STATE.get("last_run_monotonic")
    lag = max(float(sampled_at_monotonic) - float(last_run) - SAMPLING_INTERVAL_SECONDS, 0.0) if last_run is not None else 0.0
    METRICS_SAMPLING_LAG_SECONDS.set(lag)
    _SAMPLER_STATE["last_run_monotonic"] = float(sampled_at_monotonic)

    db = None
    try:
        db = db_factory()
        active_jobs = (
            db.query(ExportJob)
            .filter(ExportJob.status == JobStatus.RUNNING)
            .order_by(ExportJob.id.asc())
            .all()
        )
        if not active_jobs:
            JOB_COPY_THROUGHPUT_BYTES_PER_SECOND.clear()
            METRICS_SAMPLING_RUNS_TOTAL.labels(outcome="skipped").inc()
            _SAMPLER_STATE["last_job_samples"] = {}
            return "skipped"

        aggregated: dict[str, float] = defaultdict(float)
        previous_samples: dict[int, tuple[int, float]] = dict(_SAMPLER_STATE.get("last_job_samples") or {})
        next_samples: dict[int, tuple[int, float]] = {}

        for job in active_jobs:
            job_id = int(job.id)
            copied_bytes = int(job.copied_bytes or 0)
            previous = previous_samples.get(job_id)
            bucket = _thread_count_bucket(getattr(job, "thread_count", None))
            if previous is not None:
                previous_bytes, previous_at = previous
                delta_bytes = copied_bytes - previous_bytes
                delta_seconds = float(sampled_at_monotonic) - float(previous_at)
                if delta_bytes >= 0 and delta_seconds > 0:
                    aggregated[bucket] += float(delta_bytes) / delta_seconds
            next_samples[job_id] = (copied_bytes, float(sampled_at_monotonic))

        JOB_COPY_THROUGHPUT_BYTES_PER_SECOND.clear()
        for bucket, throughput in aggregated.items():
            JOB_COPY_THROUGHPUT_BYTES_PER_SECOND.labels(thread_count_bucket=bucket).set(max(throughput, 0.0))

        _SAMPLER_STATE["last_job_samples"] = next_samples
        METRICS_SAMPLING_RUNS_TOTAL.labels(outcome="ok").inc()
        return "ok"
    except Exception as exc:
        logger.info(
            "Metrics throughput sampling failed",
            extra={"failure_class": "metrics_sampling_failed"},
        )
        logger.debug("Metrics throughput sampling raw failure", extra={"raw_error": str(exc)}, exc_info=True)
        METRICS_SAMPLING_RUNS_TOTAL.labels(outcome="error").inc()
        return "error"
    finally:
        if db is not None:
            db.close()


async def run_sampling_loop(*, db_factory: Callable[[], Session], stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        started_at = time.monotonic()
        sample_active_job_throughput(db_factory=db_factory, sampled_at_monotonic=started_at)
        remaining = max(SAMPLING_INTERVAL_SECONDS - (time.monotonic() - started_at), 0.0)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            continue


def reset_for_tests() -> None:
    global _UPTIME_SECONDS_RECORDED, _GC_COLLECTIONS_RECORDED, _PROCESS

    for collector in (
        HTTP_REQUESTS_TOTAL,
        HTTP_REQUEST_DURATION_SECONDS,
        HTTP_REQUESTS_IN_PROGRESS,
        AUTH_ATTEMPTS_TOTAL,
        ROLE_DENIALS_TOTAL,
        JOBS_CREATED_TOTAL,
        JOBS_COMPLETED_TOTAL,
        JOBS_FAILED_TOTAL,
        JOB_COPY_DURATION_SECONDS,
        JOB_FILES_COPIED_TOTAL,
        JOB_BYTES_COPIED_TOTAL,
        JOB_COPY_ERRORS_TOTAL,
        JOB_COPY_THROUGHPUT_BYTES_PER_SECOND,
        JOB_VERIFY_DURATION_SECONDS,
        METRICS_SAMPLING_RUNS_TOTAL,
        METRICS_SAMPLING_LAG_SECONDS,
        USB_HUBS_TOTAL,
        USB_PORTS_TOTAL,
        USB_DRIVES_PRESENT,
        USB_DRIVES_STATE,
        PORT_ENABLED_TOTAL,
        NETWORK_MOUNTS_STATE,
        DRIVE_FORMAT_TOTAL,
        DRIVE_EJECT_TOTAL,
        DB_CONNECTION_POOL_SIZE,
        DB_CONNECTION_POOL_IN_USE,
        DB_CONNECTION_POOL_IDLE,
        DB_CONNECTION_POOL_OVERFLOW,
        DB_QUERY_DURATION_SECONDS,
        DB_CONNECTIONS_CREATED_TOTAL,
        DB_CONNECTIONS_CLOSED_TOTAL,
        RECONCILIATION_RUNS_TOTAL,
        RECONCILIATION_DURATION_SECONDS,
        UPTIME_SECONDS,
        PROCESS_RESIDENT_MEMORY_BYTES,
        PROCESS_VIRTUAL_MEMORY_BYTES,
        PYTHON_GC_COLLECTIONS_TOTAL,
        JOBS_RUNNING,
    ):
        if getattr(collector, "_labelnames", ()):  # pragma: no branch - test helper
            metrics = getattr(collector, "_metrics", None)
            if metrics is not None:
                metrics.clear()
        elif hasattr(collector, "_value"):
            collector._value.set(0)  # type: ignore[attr-defined]
        elif hasattr(collector, "_sum") and hasattr(collector, "_buckets") and hasattr(collector, "_count"):
            collector._sum.set(0)  # type: ignore[attr-defined]
            for bucket in collector._buckets:  # type: ignore[attr-defined]
                bucket.set(0)
            collector._count.set(0)  # type: ignore[attr-defined]

    _UPTIME_SECONDS_RECORDED = 0.0
    _GC_COLLECTIONS_RECORDED = 0
    _PROCESS = None
    _SAMPLER_STATE["last_run_monotonic"] = None
    _SAMPLER_STATE["last_job_samples"] = {}
