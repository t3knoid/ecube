"""Webhook callback delivery for job lifecycle events.

Sends an HTTPS POST with a JSON payload for terminal job outcomes and
selected persisted lifecycle actions such as creation, start, retry,
pause, manifest generation, chain-of-custody updates, archive, and
restart reconciliation. Retries up to 4 times with exponential backoff
on transient errors (5xx, network failures). Blocks private/reserved IP
addresses by default (SSRF protection).

Delivery runs on a bounded ``ThreadPoolExecutor`` (sized by
``settings.callback_max_workers``, default 4) with its own short-lived
DB session so it never blocks the copy/verify worker or ties up its
database connection.  A ``BoundedSemaphore`` (sized by
``settings.callback_max_pending``, default 100) caps the total number of
outstanding deliveries (queued + in-flight).  When the limit is reached,
new deliveries are dropped and an audit record is written, providing real
backpressure against slow or unreachable callback endpoints.
"""

import atexit
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from app.config import settings
from app.models.hardware import UsbDrive
from app.models.jobs import ExportJob, FileStatus, JobStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.job_repository import DriveAssignmentRepository, FileRepository
from app.utils.callback_payload_contract import (
    apply_callback_payload_contract,
    describe_callback_payload_contract,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_BACKOFF_BASE = 5  # exponential base; delay per retry attempt is 5**attempt seconds

# ---------------------------------------------------------------------------
# Bounded thread pool for callback delivery
# ---------------------------------------------------------------------------

_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()

_pending_semaphore: Optional[threading.BoundedSemaphore] = None
_semaphore_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    """Return (and lazily create) the module-level callback executor.

    The pool is sized by ``settings.callback_max_workers`` and registered
    for clean shutdown via ``atexit``.  Lazy creation avoids side effects
    at import time and lets tests override the pool size via settings.
    """
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:  # double-checked locking
                _executor = ThreadPoolExecutor(
                    max_workers=settings.callback_max_workers,
                    thread_name_prefix="callback",
                )
                atexit.register(_shutdown_executor)
    return _executor


def _get_pending_semaphore() -> threading.BoundedSemaphore:
    """Return (and lazily create) the module-level pending-delivery semaphore.

    The semaphore is sized by ``settings.callback_max_pending`` and caps the
    total number of outstanding deliveries (queued in the executor + actively
    executing).  When all permits are taken, ``deliver_callback`` drops the
    delivery instead of growing the queue without bound.
    """
    global _pending_semaphore
    if _pending_semaphore is None:
        with _semaphore_lock:
            if _pending_semaphore is None:
                _pending_semaphore = threading.BoundedSemaphore(
                    settings.callback_max_pending,
                )
    return _pending_semaphore


def _shutdown_executor() -> None:
    """Gracefully drain pending callbacks on interpreter shutdown."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None


def _sanitize_url_for_log(url: str) -> str:
    """Return *url* with userinfo, query string, and fragment stripped.

    Prevents credentials or signed tokens from being persisted to the
    audit log.  Falls back to ``<unparseable>`` on any parse failure.
    """
    try:
        p = urlparse(url)
        # Rebuild with only scheme, host, port, and path.
        host_part = p.hostname or ""
        if p.port:
            host_part = f"{host_part}:{p.port}"
        return f"{p.scheme}://{host_part}{p.path}"
    except Exception:
        return "<unparseable>"


def _resolve_safe(hostname: str) -> str:
    """Resolve *hostname* via DNS and return the first globally-routable IP.

    Performs a **single** resolution that is reused for the outbound
    connection, eliminating the DNS-rebinding / TOCTOU window that would
    exist if we resolved once to validate and let httpx resolve again.

    Raises ``ValueError`` when:
    * DNS resolution fails (unresolvable hostname).
    * *Any* resolved address is not globally routable (private, loopback,
      link-local, reserved, unspecified, or multicast).  Rejecting the
      entire set when even one address is unsafe prevents an attacker
      from mixing a routable record with a private one.
    """
    try:
        infos = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed: {exc}") from exc

    if not infos:
        raise ValueError("DNS returned no addresses")

    first_ip: Optional[str] = None
    for _family, _type, _proto, _canonname, sockaddr in infos:
        resolved_ip = sockaddr[0]
        if not isinstance(resolved_ip, str):
            continue
        addr = ipaddress.ip_address(resolved_ip)
        if not addr.is_global or addr.is_multicast:
            raise ValueError(
                f"Resolved to non-globally-routable address: {resolved_ip}"
            )
        if first_ip is None:
            first_ip = resolved_ip

    # first_ip is guaranteed non-None because infos is non-empty and we
    # would have raised on an unsafe address before reaching here.
    return first_ip  # type: ignore[return-value]


def _count_file_outcomes(job: ExportJob) -> tuple[int, int, int]:
    """Return ``(files_succeeded, files_failed, files_timed_out)`` for *job*."""
    try:
        session = object_session(job)
    except UnmappedInstanceError:
        session = None

    job_id = getattr(job, "id", None)
    if session is not None and isinstance(job_id, int):
        return FileRepository(session).count_done_errors_and_timeouts(job_id)

    files = list(getattr(job, "files", []) or [])
    return (
        sum(1 for export_file in files if export_file.status == FileStatus.DONE),
        sum(1 for export_file in files if export_file.status == FileStatus.ERROR),
        sum(1 for export_file in files if export_file.status == FileStatus.TIMEOUT),
    )


def _resolve_active_drive(job: ExportJob) -> UsbDrive | None:
    try:
        session = object_session(job)
    except UnmappedInstanceError:
        session = None

    job_id = getattr(job, "id", None)
    if session is not None and isinstance(job_id, int):
        active_assignment = DriveAssignmentRepository(session).get_active_for_job(job_id)
        return getattr(active_assignment, "drive", None)

    assignments = list(getattr(job, "assignments", []) or [])
    active_assignments = [
        assignment for assignment in assignments if getattr(assignment, "released_at", None) is None
    ]
    if not active_assignments:
        return None

    active_assignments.sort(
        key=lambda assignment: (
            getattr(assignment, "assigned_at", None) or 0,
            getattr(assignment, "id", 0) or 0,
        ),
        reverse=True,
    )
    return getattr(active_assignments[0], "drive", None)


def _serialize_timestamp(value: Any) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _resolve_event_name(job: ExportJob, event: str | None) -> str:
    if event is not None:
        return event
    job_status = getattr(job, "status", None)
    if not isinstance(job_status, JobStatus) or job_status not in _TERMINAL_STATUSES:
        raise ValueError(
            f"build_payload requires an explicit event for non-terminal status, got {job_status!r}"
        )
    return "JOB_COMPLETED" if job_status == JobStatus.COMPLETED else "JOB_FAILED"


def _resolve_completion_result(
    *,
    job: ExportJob,
    files_failed: int,
    files_timed_out: int,
) -> str | None:
    job_status = getattr(job, "status", None)
    if job_status == JobStatus.FAILED:
        return "failed"
    if job_status == JobStatus.COMPLETED:
        return "partial_success" if (files_failed or files_timed_out) else "success"
    return None


def _resolve_event_actor(job: ExportJob, event_actor: str | None) -> str | None:
    if event_actor:
        return event_actor
    return None


def _resolve_event_at(job: ExportJob, event_name: str, event_at: datetime | None) -> str | None:
    if event_at is not None:
        return _serialize_timestamp(event_at)

    if event_name == "JOB_CREATED":
        return _serialize_timestamp(getattr(job, "created_at", None))
    if event_name in {"JOB_STARTED", "JOB_RETRY_FAILED_FILES_STARTED"}:
        return _serialize_timestamp(getattr(job, "started_at", None))
    if event_name in {"JOB_COMPLETED", "JOB_FAILED", "JOB_COMPLETED_MANUALLY", "JOB_RECONCILED"}:
        return _serialize_timestamp(getattr(job, "completed_at", None))
    raise ValueError(f"build_payload requires an explicit event_at for lifecycle event {event_name!r}")


def build_payload(
    job: ExportJob,
    *,
    event: str | None = None,
    event_actor: str | None = None,
    event_at: datetime | None = None,
    event_details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Construct the JSON callback payload for a persisted lifecycle event.

    When *event* is omitted, the payload defaults to terminal completion
    semantics for ``COMPLETED`` and ``FAILED`` jobs to preserve the legacy
    contract used by existing callers.
    """
    event_name = _resolve_event_name(job, event)

    files_succeeded, files_failed, files_timed_out = _count_file_outcomes(job)
    completion_result = _resolve_completion_result(
        job=job,
        files_failed=files_failed,
        files_timed_out=files_timed_out,
    )

    payload: Dict[str, Any] = {
        "event": event_name,
        "job_id": job.id,
        "project_id": job.project_id,
        "evidence_number": job.evidence_number,
        "created_by": getattr(job, "created_by", None),
        "started_by": job.started_by,
        "status": job.status.value,
        "source_path": job.source_path,
        "total_bytes": job.total_bytes,
        "copied_bytes": job.copied_bytes,
        "file_count": job.file_count,
        "files_succeeded": files_succeeded,
        "files_failed": files_failed,
        "files_timed_out": files_timed_out,
        "active_duration_seconds": int(getattr(job, "active_duration_seconds", 0) or 0),
    }

    if completion_result is not None:
        payload["completion_result"] = completion_result

    active_drive = _resolve_active_drive(job)
    if active_drive is not None:
        payload["drive_id"] = active_drive.id
        payload["drive_manufacturer"] = active_drive.manufacturer
        payload["drive_model"] = active_drive.product_name
        payload["drive_serial_number"] = active_drive.serial_number

    created_at = _serialize_timestamp(getattr(job, "created_at", None))
    if created_at is not None:
        payload["created_at"] = created_at

    started_at = _serialize_timestamp(getattr(job, "started_at", None))
    if started_at is not None:
        payload["started_at"] = started_at

    completed_at = _serialize_timestamp(getattr(job, "completed_at", None))
    if completed_at is not None:
        payload["completed_at"] = completed_at

    resolved_event_actor = _resolve_event_actor(job, event_actor)
    if resolved_event_actor is not None:
        payload["event_actor"] = resolved_event_actor

    resolved_event_at = _resolve_event_at(job, event_name, event_at)
    if resolved_event_at is not None:
        payload["event_at"] = resolved_event_at

    if event_details:
        payload["event_details"] = dict(event_details)

    return payload


_TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


def _resolve_callback_url(job: ExportJob) -> Optional[str]:
    """Return the effective callback URL for *job*.

    Job-specific callback_url takes precedence. When it is absent, the
    system-wide callback_default_url is used if configured.
    """
    job_url = getattr(job, "callback_url", None)
    if isinstance(job_url, str):
        job_url = job_url.strip() or None
    if job_url:
        return job_url

    default_url = settings.callback_default_url
    if isinstance(default_url, str):
        default_url = default_url.strip() or None
    return default_url


def _resolve_callback_hmac_secret() -> Optional[str]:
    """Return the configured callback HMAC secret, if present."""
    secret = getattr(settings, "callback_hmac_secret", None)
    if not isinstance(secret, str):
        return None
    return secret.strip() or None


def _resolve_callback_proxy_url() -> Optional[str]:
    """Return the configured callback forward-proxy URL, if present."""
    proxy_url = getattr(settings, "callback_proxy_url", None)
    if not isinstance(proxy_url, str):
        return None
    return proxy_url.strip() or None


def _serialize_payload_bytes(payload: Dict[str, Any]) -> bytes:
    """Serialize *payload* into the exact JSON bytes delivered to receivers."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _build_signature_header(payload_bytes: bytes) -> Optional[str]:
    """Return the HMAC signature header value for *payload_bytes*."""
    secret = _resolve_callback_hmac_secret()
    if not secret:
        return None
    digest = hmac.new(
        secret.encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _resolve_callback_payload_fields() -> list[str] | None:
    payload_fields = getattr(settings, "callback_payload_fields", None)
    if payload_fields is None or not isinstance(payload_fields, list):
        return None
    return list(payload_fields)


def _resolve_callback_payload_field_map() -> dict[str, str] | None:
    payload_field_map = getattr(settings, "callback_payload_field_map", None)
    if payload_field_map is None or not isinstance(payload_field_map, dict):
        return None
    return dict(payload_field_map)


def build_callback_payload(
    job: ExportJob,
    *,
    event: str | None = None,
    event_actor: str | None = None,
    event_at: datetime | None = None,
    event_details: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build the effective outbound callback payload for *job*."""
    return apply_callback_payload_contract(
        build_payload(
            job,
            event=event,
            event_actor=event_actor,
            event_at=event_at,
            event_details=event_details,
        ),
        _resolve_callback_payload_fields(),
        _resolve_callback_payload_field_map(),
    )


def _callback_payload_audit_details() -> Dict[str, Any]:
    return describe_callback_payload_contract(
        _resolve_callback_payload_fields(),
        _resolve_callback_payload_field_map(),
    )


def deliver_callback(
    job: ExportJob,
    db: Any = None,
    *,
    event: str | None = None,
    event_actor: str | None = None,
    event_at: datetime | None = None,
    event_details: Dict[str, Any] | None = None,
) -> None:
    """Snapshot callback data from *job* and deliver the webhook callback.

    * **Production (db omitted):** submits delivery to a bounded
      ``ThreadPoolExecutor`` (capped at ``settings.callback_max_workers``).
      A ``BoundedSemaphore`` (capped at ``settings.callback_max_pending``)
      limits the total number of outstanding deliveries.  If the limit is
      reached the delivery is dropped and an audit record is written.
    * **Testing (db provided):** executes delivery synchronously in the
      caller's process using the supplied session, making audit-log assertions
      deterministic.

    If neither a job-specific callback_url nor a system-wide
    callback_default_url is configured, the call is a no-op. When *event*
    is omitted, only terminal job states (COMPLETED / FAILED) are eligible
    for delivery to preserve legacy behavior.
    """
    url = _resolve_callback_url(job)
    if not url:
        return

    if event is None and job.status not in _TERMINAL_STATUSES:
        logger.warning(
            "deliver_callback called for job %s in non-terminal status %s; ignoring",
            job.id, job.status,
        )
        return

    # Snapshot everything we need before leaving the caller's session scope.
    payload = build_callback_payload(
        job,
        event=event,
        event_actor=event_actor,
        event_at=event_at,
        event_details=event_details,
    )
    job_id: int = job.id  # type: ignore[assignment]

    if db is not None:
        # Synchronous path — used by tests for deterministic assertions.
        _do_deliver(job_id, url, payload, db)
        return

    # --- Backpressure: cap outstanding deliveries ---
    if not _get_pending_semaphore().acquire(blocking=False):
        safe_url = _sanitize_url_for_log(url)
        logger.warning(
            "Callback queue full for job %s; dropping delivery to %s",
            job_id, safe_url,
        )
        _audit_dropped_delivery(job_id, safe_url)
        return

    _get_executor().submit(_deliver_callback_sync, job_id, url, payload)


def _audit_dropped_delivery(job_id: int, safe_url: str) -> None:
    """Write an audit record for a delivery dropped due to backpressure.

    Opens a short-lived DB session so the caller does not need one.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        AuditRepository(db).add(
            action="CALLBACK_DELIVERY_DROPPED",
            job_id=job_id,
            details={
                "callback_url": safe_url,
                "reason": "Callback queue full: too many outstanding deliveries",
            },
        )
    except Exception:
        logger.exception(
            "Failed to write audit log for CALLBACK_DELIVERY_DROPPED"
        )
    finally:
        db.close()


def _deliver_callback_sync(
    job_id: int,
    url: str,
    payload: Dict[str, Any],
) -> None:
    """Perform the actual HTTP delivery with retries.

    Opens a **dedicated** DB session for audit writes and closes it before
    returning, so no external session is held during network I/O.
    Releases the pending-delivery semaphore on completion.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        _do_deliver(job_id, url, payload, db)
    finally:
        db.close()
        _get_pending_semaphore().release()


def _do_deliver(
    job_id: int,
    url: str,
    payload: Dict[str, Any],
    db: Any,
) -> None:
    """Core delivery logic (SSRF check ➜ HTTP POST ➜ retry loop ➜ audit)."""
    audit_repo = AuditRepository(db)

    safe_url = _sanitize_url_for_log(url)
    event_name = payload.get("event")
    payload_audit_details = _callback_payload_audit_details()

    logger.info(
        "Dispatching callback",
        {
            "job_id": job_id,
            "event": event_name,
            "callback_url": safe_url,
        },
    )

    # --- SSRF guard ---
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        logger.exception("Malformed callback_url for job %s", job_id)
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job_id,
                details={
                    "callback_url": safe_url,
                    "reason": "Malformed callback URL: unable to parse",
                    **payload_audit_details,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (malformed URL)")
        return

    if parsed.scheme.lower() != "https":
        logger.warning("Callback URL for job %s uses disallowed scheme: %s", job_id, parsed.scheme)
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job_id,
                details={
                    "callback_url": safe_url,
                    "reason": f"Callback URL uses disallowed scheme: {parsed.scheme}",
                    **payload_audit_details,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (scheme)")
        return

    if parsed.username or parsed.password:
        logger.warning("Callback URL for job %s contains embedded credentials", job_id)
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job_id,
                details={
                    "callback_url": safe_url,
                    "reason": "Callback URL contains embedded credentials (userinfo)",
                    **payload_audit_details,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (userinfo)")
        return

    if not hostname:
        logger.warning(
            "Callback URL for job %s blocked: empty hostname",
            job_id,
        )
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job_id,
                details={
                    "callback_url": safe_url,
                    "reason": "Empty hostname",
                    **payload_audit_details,
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (empty hostname)")
        return

    # --- DNS resolution + SSRF validation (single resolution, pinned) ---
    pinned_ip: Optional[str] = None
    if not settings.callback_allow_private_ips:
        try:
            pinned_ip = _resolve_safe(hostname)
        except ValueError as exc:
            reason = f"SSRF protection: {exc}"
            logger.warning(
                "Callback URL for job %s blocked: %s", job_id, reason,
            )
            try:
                audit_repo.add(
                    action="CALLBACK_DELIVERY_FAILED",
                    job_id=job_id,
                    details={
                        "callback_url": safe_url,
                        "reason": reason,
                        **payload_audit_details,
                    },
                )
            except Exception:
                logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (SSRF)")
            return

    timeout = settings.callback_timeout_seconds
    last_error: Optional[str] = None
    payload_bytes = _serialize_payload_bytes(payload)
    signature_header = _build_signature_header(payload_bytes)
    proxy_url = _resolve_callback_proxy_url()

    # Build a pinned URL that connects directly to the resolved IP,
    # preventing DNS rebinding between our safety check and the
    # actual TCP connection (TOCTOU elimination).
    if pinned_ip is not None:
        port = parsed.port or 443
        ip_host = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
        pinned_netloc = f"{ip_host}:{port}"
        pinned_url = urlunparse((
            parsed.scheme, pinned_netloc, parsed.path,
            parsed.params, parsed.query, "",
        ))
        # Include port in Host header when the URL uses a non-default port,
        # so virtual-host routing works on receivers listening on custom ports.
        host_header = f"{hostname}:{port}" if parsed.port else hostname
    else:
        pinned_url = url

    for attempt in range(_MAX_RETRIES):
        try:
            headers = {"Content-Type": "application/json"}
            if signature_header:
                headers["X-ECUBE-Signature"] = signature_header

            post_kwargs: Dict[str, Any] = {
                "content": payload_bytes,
                "headers": headers,
            }
            if pinned_ip is not None:
                # Override Host header and TLS SNI so the server sees the
                # original hostname despite connecting to the resolved IP.
                post_kwargs["headers"]["Host"] = host_header
                post_kwargs["extensions"] = {
                    "sni_hostname": hostname.encode("idna"),
                }

            client_kwargs: Dict[str, Any] = {
                "timeout": timeout,
                "follow_redirects": False,
                "trust_env": False,
            }
            if proxy_url:
                client_kwargs["proxy"] = proxy_url

            with httpx.Client(**client_kwargs) as client:
                response = client.post(pinned_url, **post_kwargs)

            if response.status_code < 300:
                # 2xx: successful delivery.
                logger.info(
                    "Callback delivered",
                    {
                        "job_id": job_id,
                        "event": event_name,
                        "callback_url": safe_url,
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                )
                try:
                    audit_repo.add(
                        action="CALLBACK_SENT",
                        job_id=job_id,
                        details={
                            "callback_url": safe_url,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                            **payload_audit_details,
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for CALLBACK_SENT")
                return

            if response.status_code < 400:
                # 3xx: redirect — treat as permanent failure.  httpx does
                # not follow redirects (and we must not, to avoid
                # redirect-based SSRF bypass).  A redirect means the
                # receiver did not process the payload.
                logger.warning(
                    "Callback for job %s redirected with %s (not followed)",
                    job_id, response.status_code,
                )
                try:
                    audit_repo.add(
                        action="CALLBACK_DELIVERY_FAILED",
                        job_id=job_id,
                        details={
                            "callback_url": safe_url,
                            "status_code": response.status_code,
                            "reason": f"HTTP {response.status_code}: redirect not followed (SSRF protection)",
                            "attempt": attempt + 1,
                            **payload_audit_details,
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (3xx)")
                return

            if response.status_code < 500:
                # 4xx: permanent failure — no retry.
                logger.warning(
                    "Callback for job %s rejected with %s (permanent failure)",
                    job_id, response.status_code,
                )
                try:
                    audit_repo.add(
                        action="CALLBACK_DELIVERY_FAILED",
                        job_id=job_id,
                        details={
                            "callback_url": safe_url,
                            "status_code": response.status_code,
                            "reason": f"HTTP {response.status_code}: receiver rejected the request",
                            "attempt": attempt + 1,
                            **payload_audit_details,
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (4xx)")
                return

            # 5xx: transient — retry after backoff.
            last_error = f"HTTP {response.status_code}"
            logger.warning(
                "Callback for job %s returned %s (attempt %d/%d)",
                job_id, response.status_code, attempt + 1, _MAX_RETRIES,
            )

        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)
            logger.warning(
                "Callback for job %s failed: %s (attempt %d/%d)",
                job_id, exc, attempt + 1, _MAX_RETRIES,
            )

        # Exponential backoff: 5^attempt → ~1 s, ~5 s, ~25 s
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_BACKOFF_BASE ** attempt)

    # All retries exhausted.
    try:
        audit_repo.add(
            action="CALLBACK_DELIVERY_FAILED",
            job_id=job_id,
            details={
                "callback_url": safe_url,
                "reason": last_error or "unknown",
                "attempts": _MAX_RETRIES,
                **payload_audit_details,
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED")
