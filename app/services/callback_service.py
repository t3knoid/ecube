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
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

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

    * **Production (db omitted):** dispatches delivery on a background daemon
      thread with its own short-lived DB session.  Returns immediately so the
      caller's worker thread is not blocked by HTTP I/O or retry sleeps.
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

    if not settings.callback_allow_private_ips and not hostname:
        logger.warning(
            "Callback URL for job %s blocked: SSRF protection: empty hostname",
            job_id,
        )
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job_id,
                details={
                    "callback_url": safe_url,
                    "reason": "SSRF protection: empty hostname",
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (SSRF)")
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
