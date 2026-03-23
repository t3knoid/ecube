"""Webhook callback delivery for terminal job states.

Sends an HTTPS POST with a JSON payload when a job reaches COMPLETED
or FAILED.  Retries up to 3 times with exponential backoff on transient
errors (5xx, network failures).  Blocks private/reserved IP addresses
by default (SSRF protection).
"""

import ipaddress
import logging
import socket
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.jobs import ExportJob, JobStatus
from app.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 5  # seconds; delays: 1, 5, 25


def _is_private_ip(hostname: str) -> bool:
    """Resolve *hostname* and return ``True`` if any resolved address is
    private, loopback, link-local, or otherwise reserved."""
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        # Unresolvable hostnames are rejected as unsafe.
        return True
    for family, _type, _proto, _canonname, sockaddr in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
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


def deliver_callback(job: ExportJob, db: Session) -> None:
    """Send the webhook callback for *job*, retrying on transient failures.

    This function is designed to be called from the copy engine's background
    thread after the job has been committed to a terminal state.  It uses
    its own ``httpx`` client per invocation and performs synchronous I/O
    so it integrates naturally with the thread-based copy engine.
    """
    url: Optional[str] = job.callback_url
    if not url:
        return

    audit_repo = AuditRepository(db)

    # --- SSRF guard ---
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        logger.warning("Malformed callback_url for job %s", job.id)
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job.id,
                details={
                    "callback_url": url,
                    "reason": "Malformed callback URL: unable to parse",
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (malformed URL)")
        return

    if not settings.callback_allow_private_ips and _is_private_ip(hostname):
        logger.warning(
            "Callback URL for job %s resolves to a private/reserved address; "
            "delivery blocked (SSRF protection)",
            job.id,
        )
        try:
            audit_repo.add(
                action="CALLBACK_DELIVERY_FAILED",
                job_id=job.id,
                details={
                    "callback_url": url,
                    "reason": "SSRF protection: private/reserved IP",
                },
            )
        except Exception:
            logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED (SSRF)")
        return

    payload = build_payload(job)
    timeout = settings.callback_timeout_seconds
    last_error: Optional[str] = None

    for attempt in range(_MAX_RETRIES):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload)

            if response.status_code < 500:
                # 2xx–4xx: non-transient — accept or give up.
                try:
                    audit_repo.add(
                        action="CALLBACK_SENT",
                        job_id=job.id,
                        details={
                            "callback_url": url,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )
                except Exception:
                    logger.exception("Failed to write audit log for CALLBACK_SENT")
                return

            # 5xx: transient — retry after backoff.
            last_error = f"HTTP {response.status_code}"
            logger.warning(
                "Callback for job %s returned %s (attempt %d/%d)",
                job.id, response.status_code, attempt + 1, _MAX_RETRIES,
            )

        except (httpx.HTTPError, OSError) as exc:
            last_error = str(exc)
            logger.warning(
                "Callback for job %s failed: %s (attempt %d/%d)",
                job.id, exc, attempt + 1, _MAX_RETRIES,
            )

        # Exponential backoff: 1s, 5s, 25s
        if attempt < _MAX_RETRIES - 1:
            time.sleep(_BACKOFF_BASE ** attempt)

    # All retries exhausted.
    try:
        audit_repo.add(
            action="CALLBACK_DELIVERY_FAILED",
            job_id=job.id,
            details={
                "callback_url": url,
                "reason": last_error or "unknown",
                "attempts": _MAX_RETRIES,
            },
        )
    except Exception:
        logger.exception("Failed to write audit log for CALLBACK_DELIVERY_FAILED")
