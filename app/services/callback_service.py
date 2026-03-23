"""Webhook callback delivery for terminal job states.

Sends an HTTPS POST with a JSON payload when a job reaches COMPLETED
or FAILED.  Retries up to 4 times with exponential backoff on transient
errors (5xx, network failures).  Blocks private/reserved IP addresses
by default (SSRF protection).

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
import ipaddress
import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx

from app.config import settings
from app.models.jobs import ExportJob, JobStatus
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_BACKOFF_BASE = 5  # seconds; delays: 1 s, 5 s, 25 s

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
        addr = ipaddress.ip_address(sockaddr[0])
        if not addr.is_global or addr.is_multicast:
            raise ValueError(
                f"Resolved to non-globally-routable address: {sockaddr[0]}"
            )
        if first_ip is None:
            first_ip = sockaddr[0]

    # first_ip is guaranteed non-None because infos is non-empty and we
    # would have raised on an unsafe address before reaching here.
    return first_ip  # type: ignore[return-value]


def build_payload(job: ExportJob) -> Dict[str, Any]:
    """Construct the JSON callback payload from a terminal job.

    Raises ``ValueError`` if *job.status* is not a terminal state.
    """
    if job.status not in _TERMINAL_STATUSES:
        raise ValueError(
            f"build_payload requires a terminal status (COMPLETED/FAILED), "
            f"got {job.status!r}"
        )
    event = "JOB_COMPLETED" if job.status == JobStatus.COMPLETED else "JOB_FAILED"
    payload: Dict[str, Any] = {
        "event": event,
        "job_id": job.id,
        "project_id": job.project_id,
        "evidence_number": job.evidence_number,
        "status": job.status.value,
        "source_path": job.source_path,
        "total_bytes": job.total_bytes,
        "copied_bytes": job.copied_bytes,
        "file_count": job.file_count,
    }
    if job.completed_at:
        payload["completed_at"] = job.completed_at.isoformat()
    return payload


_TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED})


def deliver_callback(job: ExportJob, db: Any = None) -> None:
    """Snapshot callback data from *job* and deliver the webhook callback.

    * **Production (db omitted):** submits delivery to a bounded
      ``ThreadPoolExecutor`` (capped at ``settings.callback_max_workers``).
      A ``BoundedSemaphore`` (capped at ``settings.callback_max_pending``)
      limits the total number of outstanding deliveries.  If the limit is
      reached the delivery is dropped and an audit record is written.
    * **Testing (db provided):** executes delivery synchronously in the
      caller's process using the supplied session, making audit-log assertions
      deterministic.

    If *job.callback_url* is falsy or the job is not in a terminal state
    (COMPLETED / FAILED) the call is a no-op.
    """
    url: Optional[str] = job.callback_url
    if not url:
        return

    if job.status not in _TERMINAL_STATUSES:
        logger.warning(
            "deliver_callback called for job %s in non-terminal status %s; ignoring",
            job.id, job.status,
        )
        return

    # Snapshot everything we need before leaving the caller's session scope.
    payload = build_payload(job)
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

    # --- SSRF guard ---
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        logger.warning("Malformed callback_url for job %s", job_id)
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job_id,
                details={
                    "callback_url": safe_url,
                    "reason": "Malformed callback URL: unable to parse",
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
                    },
                )
            except Exception:
                logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (SSRF)")
            return

    timeout = settings.callback_timeout_seconds
    last_error: Optional[str] = None

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
    else:
        pinned_url = url

    for attempt in range(_MAX_RETRIES):
        try:
            post_kwargs: Dict[str, Any] = {"json": payload}
            if pinned_ip is not None:
                # Override Host header and TLS SNI so the server sees the
                # original hostname despite connecting to the resolved IP.
                post_kwargs["headers"] = {"Host": hostname}
                post_kwargs["extensions"] = {
                    "sni_hostname": hostname.encode("ascii"),
                }

            with httpx.Client(timeout=timeout) as client:
                response = client.post(pinned_url, **post_kwargs)

            if response.status_code < 400:
                # 2xx/3xx: successful delivery.
                try:
                    audit_repo.add(
                        action="CALLBACK_SENT",
                        job_id=job_id,
                        details={
                            "callback_url": safe_url,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for CALLBACK_SENT")
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
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED")
