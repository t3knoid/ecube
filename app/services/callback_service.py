"""Webhook callback delivery for terminal job states.

Sends an HTTPS POST with a JSON payload when a job reaches COMPLETED
or FAILED.  Retries up to 4 times with exponential backoff on transient
errors (5xx, network failures).  Blocks private/reserved IP addresses
by default (SSRF protection).

Delivery runs in a dedicated daemon thread with its own short-lived DB
session so it never blocks the copy/verify worker or ties up its
database connection.
"""

import ipaddress
import logging
import socket
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.models.jobs import ExportJob, JobStatus
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_BACKOFF_BASE = 5  # seconds; delays: 1 s, 5 s, 25 s


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


def _is_private_ip(hostname: str) -> bool:
    """Resolve *hostname* and return ``True`` if any resolved address is
    not globally routable (private, loopback, link-local, reserved,
    unspecified, multicast, etc.)."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        # Unresolvable hostnames are rejected as unsafe.
        return True
    for family, _type, _proto, _canonname, sockaddr in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        if not addr.is_global or addr.is_multicast:
            return True
    return False


def build_payload(job: ExportJob) -> Dict[str, Any]:
    """Construct the JSON callback payload from a terminal job."""
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


def deliver_callback(job: ExportJob, db: Any = None) -> None:
    """Snapshot callback data from *job* and deliver the webhook callback.

    * **Production (db omitted):** dispatches delivery on a background daemon
      thread with its own short-lived DB session.  Returns immediately so the
      caller's worker thread is not blocked by HTTP I/O or retry sleeps.
    * **Testing (db provided):** executes delivery synchronously in the
      caller's process using the supplied session, making audit-log assertions
      deterministic.

    If *job.callback_url* is falsy the call is a no-op.
    """
    url: Optional[str] = job.callback_url
    if not url:
        return

    # Snapshot everything we need before leaving the caller's session scope.
    payload = build_payload(job)
    job_id: int = job.id  # type: ignore[assignment]

    if db is not None:
        # Synchronous path — used by tests for deterministic assertions.
        _do_deliver(job_id, url, payload, db)
        return

    thread = threading.Thread(
        target=_deliver_callback_sync,
        args=(job_id, url, payload),
        daemon=True,
        name=f"callback-job-{job_id}",
    )
    thread.start()


def _deliver_callback_sync(
    job_id: int,
    url: str,
    payload: Dict[str, Any],
) -> None:
    """Perform the actual HTTP delivery with retries.

    Opens a **dedicated** DB session for audit writes and closes it before
    returning, so no external session is held during network I/O.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        _do_deliver(job_id, url, payload, db)
    finally:
        db.close()


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

    if not settings.callback_allow_private_ips and (not hostname or _is_private_ip(hostname)):
        reason = (
            "SSRF protection: empty hostname"
            if not hostname
            else "SSRF protection: non-globally-routable IP"
        )
        logger.warning(
            "Callback URL for job %s blocked: %s",
            job_id, reason,
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

    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload)

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
