# 10. Third-Party Integration Guide

This document provides guidance for third-party applications that need to programmatically interface with the ECUBE system to submit evidence copy jobs using the existing REST API endpoints.

## 1. Overview

ECUBE exposes a REST API that external systems (case management platforms, eDiscovery tools, automation scripts) can call to submit copy jobs. The workflow involves calling a series of endpoints in sequence:

1. **Authenticate** — Obtain a Bearer JWT token.
2. **Select a drive** *(optional)* — Find an available USB drive and bind it to the project. If omitted, ECUBE auto-assigns a drive when the job is created.
3. **Mount the source** — Register the NFS or SMB share containing the evidence.
4. **Create and start the job** — Submit the copy job with source, optional drive, and parameters.
5. **Monitor, verify, manifest** — Poll for completion, verify integrity, and generate a chain-of-custody manifest.

> **Auto-Assignment:** Step 2 (Select/Initialize drive) can be skipped
> entirely. When `drive_id` is omitted from `POST /jobs`, ECUBE automatically
> selects a drive: it picks the single project-bound `AVAILABLE` drive, or
> falls back to an unbound drive and binds the project to it. This is the
> recommended approach for hands-off automation. See [Step 4](#step-4--create-the-copy-job)
> for details.

### 1.1 Minimum Required Information

| Field | Description |
|-------|-------------|
| `project_id` | Unique project/case identifier. Used for project isolation on USB drives. |
| `source_path` | NFS (or SMB) share path containing the evidence data (e.g., `server:/exports/case-2026-001`). |

### 1.2 Default Copy Parameters

If not overridden, jobs use these defaults:

| Parameter | Default | Range |
|-----------|---------|-------|
| `thread_count` | 4 | 1–8 |
| `max_file_retries` | 3 | 0+ |
| `retry_delay_seconds` | 1 | 0+ |

---

## 2. Authentication

All API calls (except login) require a Bearer JWT token.

```
POST /auth/token
Content-Type: application/json

{
    "username": "<service_account>",
    "password": "<password>"
}
```

**Response (200):**

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
}
```

Include the token in all subsequent requests:

```
Authorization: Bearer <access_token>
```

> **Recommendation:** Create a dedicated OS service account (e.g., `svc-casemgmt`) with the `processor` role for automated integrations. Do not share credentials with interactive users.

---

## 3. API Workflow

### Step 1 — Select an Available Drive

> **Note:** This step is optional. If you omit `drive_id` when creating the job
> (Step 4), ECUBE auto-assigns a drive. Skip to Step 3 for the simplified
> workflow.

```
GET /drives
```

Find a drive where `current_state` is `AVAILABLE`. Note its `id`.

To list only drives bound to a specific project:

```
GET /drives?project_id=CASE-2026-001
```

### Step 2 — Initialize the Drive for the Project

> **Note:** This step is only needed when you explicitly selected a drive in
> Step 1. Auto-assigned drives are automatically bound to the project.

```
POST /drives/{drive_id}/initialize
Content-Type: application/json

{
    "project_id": "CASE-2026-001"
}
```

This binds the drive to the project. Once bound, it only accepts data for that project (project isolation). Returns the updated drive object.

### Step 3 — Mount the Network Share

```
POST /mounts
Content-Type: application/json

{
    "type": "NFS",
    "remote_path": "fileserver:/exports/case-2026-001",
    "local_mount_point": "/mnt/evidence/case-2026-001"
}
```

For SMB shares, include credentials:

```json
{
    "type": "SMB",
    "remote_path": "//fileserver/evidence$/case-2026-001",
    "local_mount_point": "/mnt/evidence/case-2026-001",
    "username": "svc-reader",
    "password": "share-password"
}
```

Returns the mount object with its `id` and `status` (`MOUNTED` or `ERROR`). Verify `status` is `MOUNTED` before proceeding.

### Step 4 — Create the Copy Job

**With auto-assignment (recommended for automation):**

```
POST /jobs
Content-Type: application/json

{
    "project_id": "CASE-2026-001",
    "evidence_number": "EV-042",
    "source_path": "/mnt/evidence/case-2026-001"
}
```

When `drive_id` is omitted, ECUBE selects a drive automatically:

- If exactly one `AVAILABLE` drive is bound to the project, it is selected.
  If that drive is temporarily locked by a concurrent operation, the request
  fails with **409** — retry after a short delay.
- If no project-bound drives exist, an unbound `AVAILABLE` drive is selected and
  bound to the project.
- If multiple project-bound drives are `AVAILABLE`, the request fails with
  **409** — the caller must specify `drive_id` to disambiguate.
- If no usable drive exists (none bound to the project and none unbound), the
  request fails with **409**.

> **Drive Capacity Warning:** ECUBE does **not** validate free space on the
> target drive before or during copy operations. It is the caller's
> responsibility to ensure the target drive has sufficient space. When a project
> has multiple drives, specify `drive_id` to select the drive with available
> capacity.

**With explicit drive (when disambiguation is needed):**

```
POST /jobs
Content-Type: application/json

{
    "project_id": "CASE-2026-001",
    "evidence_number": "EV-042",
    "source_path": "/mnt/evidence/case-2026-001",
    "drive_id": 3
}
```

The `source_path` must be the `local_mount_point` from Step 3. When provided, `drive_id` is from Step 1.

Optional fields to override defaults:

```json
{
    "project_id": "CASE-2026-001",
    "evidence_number": "EV-042",
    "source_path": "/mnt/evidence/case-2026-001",
    "drive_id": 3,
    "thread_count": 6,
    "max_file_retries": 5,
    "retry_delay_seconds": 2
}
```

Returns the job object with its `id` and `status` (`PENDING`).

### Step 5 — Start the Copy Job

```
POST /jobs/{job_id}/start
```

Optionally override thread count:

```json
{
    "thread_count": 8
}
```

The job transitions to `RUNNING` and the copy engine begins in the background.

### Step 6 — Poll for Completion

```
GET /jobs/{job_id}
```

**Response fields of interest:**

| Field | Description |
|-------|-------------|
| `status` | `PENDING`, `RUNNING`, `VERIFYING`, `COMPLETED`, or `FAILED` |
| `total_bytes` | Total bytes to copy |
| `copied_bytes` | Bytes copied so far |
| `file_count` | Total file count |

Progress: `(copied_bytes / total_bytes) * 100`

> **Polling interval:** Every 5–10 seconds. Avoid polling faster than once per second.

### Step 7 — Verify Integrity

```
POST /jobs/{job_id}/verify
```

Compares SHA-256 hashes of source and destination files. Status transitions: `COMPLETED` → `VERIFYING` → `COMPLETED` (pass) or `FAILED`.

### Step 8 — Generate Manifest

```
POST /jobs/{job_id}/manifest
```

Writes a JSON manifest to the USB drive containing file paths, sizes, hashes, and copy metadata for chain-of-custody.

---

## 4. Error Handling

| Status | Condition | Action |
|--------|-----------|--------|
| `401 Unauthorized` | Token missing, invalid, or expired | Re-authenticate via `POST /auth/token` |
| `403 Forbidden` | Insufficient role or project isolation violation | Check role assignments; verify `project_id` matches the drive's bound project |
| `404 Not Found` | Resource does not exist | Verify drive/job/mount IDs |
| `409 Conflict` | Drive not in expected state, multiple project-bound drives (specify `drive_id`), or no usable drive for the requested project | Select a different drive, specify `drive_id` explicitly, or wait for a drive to become available |
| `422 Unprocessable Entity` | Invalid request body | Check field names, types, and constraints |
| `500 Internal Server Error` | Mount failure, copy engine error | Check mount connectivity; inspect job error details |

---

## 5. Complete Examples

### 5.1 Bash Script

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────
ECUBE_URL="http://ecube-host:8000"
USERNAME="svc-casemgmt"
PASSWORD="service-account-password"

PROJECT_ID="CASE-2026-001"
EVIDENCE_NUMBER="EV-042"
REMOTE_PATH="fileserver:/exports/case-2026-001"
MOUNT_POINT="/mnt/evidence/case-2026-001"
MOUNT_TYPE="NFS"         # NFS or SMB
THREAD_COUNT=4           # 1-8
MAX_RETRIES=3            # 0+
RETRY_DELAY=1            # seconds, 0+
POLL_INTERVAL=10         # seconds

# ── Step 1: Authenticate ──────────────────────────────────────
echo "Authenticating..."
TOKEN=$(curl -sf -X POST "$ECUBE_URL/auth/token" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$USERNAME\", \"password\": \"$PASSWORD\"}" \
  | jq -r '.access_token')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "ERROR: Authentication failed." >&2
  exit 1
fi
AUTH="Authorization: Bearer $TOKEN"
echo "  Authenticated."

# ── Step 2: Select an available drive ─────────────────────────
echo "Selecting available drive..."
DRIVE_ID=$(curl -sf -X GET "$ECUBE_URL/drives" \
  -H "$AUTH" \
  | jq -r '[.[] | select(.current_state == "AVAILABLE")][0].id')

if [ -z "$DRIVE_ID" ] || [ "$DRIVE_ID" = "null" ]; then
  echo "ERROR: No available drives." >&2
  exit 1
fi
echo "  Selected drive $DRIVE_ID."

# ── Step 3: Initialize drive for the project ──────────────────
echo "Initializing drive $DRIVE_ID for project $PROJECT_ID..."
curl -sf -X POST "$ECUBE_URL/drives/$DRIVE_ID/initialize" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\"}" > /dev/null
echo "  Drive initialized."

# ── Step 4: Mount the network share ───────────────────────────
echo "Mounting $REMOTE_PATH at $MOUNT_POINT..."
MOUNT_RESPONSE=$(curl -sf -X POST "$ECUBE_URL/mounts" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"type\": \"$MOUNT_TYPE\", \"remote_path\": \"$REMOTE_PATH\", \"local_mount_point\": \"$MOUNT_POINT\"}")

MOUNT_STATUS=$(echo "$MOUNT_RESPONSE" | jq -r '.status')
MOUNT_ID=$(echo "$MOUNT_RESPONSE" | jq -r '.id')

if [ "$MOUNT_STATUS" != "MOUNTED" ]; then
  echo "ERROR: Mount failed with status: $MOUNT_STATUS" >&2
  exit 1
fi
echo "  Mounted (mount_id=$MOUNT_ID)."

# ── Step 5: Create the copy job (auto-assign drive) ───────────
echo "Creating copy job..."
JOB_RESPONSE=$(curl -sf -X POST "$ECUBE_URL/jobs" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{
    \"project_id\": \"$PROJECT_ID\",
    \"evidence_number\": \"$EVIDENCE_NUMBER\",
    \"source_path\": \"$MOUNT_POINT\",
    \"thread_count\": $THREAD_COUNT,
    \"max_file_retries\": $MAX_RETRIES,
    \"retry_delay_seconds\": $RETRY_DELAY
  }")

JOB_ID=$(echo "$JOB_RESPONSE" | jq -r '.id')
echo "  Job created (job_id=$JOB_ID)."

# ── Step 6: Start the copy job ────────────────────────────────
echo "Starting job $JOB_ID..."
curl -sf -X POST "$ECUBE_URL/jobs/$JOB_ID/start" \
  -H "$AUTH" \
  -H "Content-Type: application/json" \
  -d "{\"thread_count\": $THREAD_COUNT}" > /dev/null
echo "  Job started."

# ── Step 7: Poll for completion ───────────────────────────────
echo "Waiting for job to complete..."
while true; do
  STATUS_RESPONSE=$(curl -sf -X GET "$ECUBE_URL/jobs/$JOB_ID" -H "$AUTH")
  STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status')
  COPIED=$(echo "$STATUS_RESPONSE" | jq -r '.copied_bytes')
  TOTAL=$(echo "$STATUS_RESPONSE" | jq -r '.total_bytes')

  if [ "$TOTAL" -gt 0 ] 2>/dev/null; then
    PCT=$(awk "BEGIN {printf \"%.1f\", ($COPIED/$TOTAL)*100}")
    echo "  $STATUS — $COPIED / $TOTAL bytes ($PCT%)"
  else
    echo "  $STATUS — scanning files..."
  fi

  case "$STATUS" in
    COMPLETED) break ;;
    FAILED)
      echo "ERROR: Job failed." >&2
      exit 1
      ;;
  esac
  sleep "$POLL_INTERVAL"
done

# ── Step 8: Verify ────────────────────────────────────────────
echo "Verifying job $JOB_ID..."
curl -sf -X POST "$ECUBE_URL/jobs/$JOB_ID/verify" -H "$AUTH" > /dev/null

# Wait for verification to finish
while true; do
  STATUS=$(curl -sf -X GET "$ECUBE_URL/jobs/$JOB_ID" -H "$AUTH" | jq -r '.status')
  echo "  Verification: $STATUS"
  case "$STATUS" in
    COMPLETED) break ;;
    FAILED)
      echo "ERROR: Verification failed." >&2
      exit 1
      ;;
  esac
  sleep "$POLL_INTERVAL"
done

# ── Step 9: Generate manifest ─────────────────────────────────
echo "Generating manifest..."
curl -sf -X POST "$ECUBE_URL/jobs/$JOB_ID/manifest" -H "$AUTH" > /dev/null
echo "  Manifest written to USB drive."

echo ""
echo "Done. Job $JOB_ID completed successfully."
echo "  Project:  $PROJECT_ID"
echo "  Evidence: $EVIDENCE_NUMBER"
echo "  Drive:    $DRIVE_ID"
```

### 5.2 Python Script

```python
#!/usr/bin/env python3
"""ECUBE copy job submission script.

Usage:
    python ecube_submit_job.py

Configure the variables in the CONFIGURATION section below,
or adapt this script into your application's integration module.
"""

import sys
import time
import requests

# ── Configuration ──────────────────────────────────────────────
ECUBE_URL = "http://ecube-host:8000"
USERNAME = "svc-casemgmt"
PASSWORD = "service-account-password"

PROJECT_ID = "CASE-2026-001"
EVIDENCE_NUMBER = "EV-042"
REMOTE_PATH = "fileserver:/exports/case-2026-001"
MOUNT_POINT = "/mnt/evidence/case-2026-001"
MOUNT_TYPE = "NFS"        # "NFS" or "SMB"
THREAD_COUNT = 4          # 1-8
MAX_RETRIES = 3           # 0+
RETRY_DELAY = 1           # seconds, 0+
POLL_INTERVAL = 10        # seconds


def main():
    session = requests.Session()

    # ── Step 1: Authenticate ──────────────────────────────────
    print("Authenticating...")
    resp = session.post(f"{ECUBE_URL}/auth/token", json={
        "username": USERNAME,
        "password": PASSWORD,
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    session.headers["Authorization"] = f"Bearer {token}"
    print("  Authenticated.")

    # ── Step 2: Select an available drive ─────────────────────
    print("Selecting available drive...")
    resp = session.get(f"{ECUBE_URL}/drives")
    resp.raise_for_status()
    drives = resp.json()

    available = [d for d in drives if d["current_state"] == "AVAILABLE"]
    if not available:
        print("ERROR: No available drives.", file=sys.stderr)
        sys.exit(1)

    drive_id = available[0]["id"]
    print(f"  Selected drive {drive_id}.")

    # ── Step 3: Initialize drive for the project ──────────────
    print(f"Initializing drive {drive_id} for project {PROJECT_ID}...")
    resp = session.post(
        f"{ECUBE_URL}/drives/{drive_id}/initialize",
        json={"project_id": PROJECT_ID},
    )
    resp.raise_for_status()
    print("  Drive initialized.")

    # ── Step 4: Mount the network share ───────────────────────
    print(f"Mounting {REMOTE_PATH} at {MOUNT_POINT}...")
    resp = session.post(f"{ECUBE_URL}/mounts", json={
        "type": MOUNT_TYPE,
        "remote_path": REMOTE_PATH,
        "local_mount_point": MOUNT_POINT,
    })
    resp.raise_for_status()
    mount = resp.json()

    if mount["status"] != "MOUNTED":
        print(f"ERROR: Mount failed with status: {mount['status']}", file=sys.stderr)
        sys.exit(1)
    print(f"  Mounted (mount_id={mount['id']}).")

    # ── Step 5: Create the copy job (auto-assign drive) ───────
    print("Creating copy job...")
    resp = session.post(f"{ECUBE_URL}/jobs", json={
        "project_id": PROJECT_ID,
        "evidence_number": EVIDENCE_NUMBER,
        "source_path": MOUNT_POINT,
        "thread_count": THREAD_COUNT,
        "max_file_retries": MAX_RETRIES,
        "retry_delay_seconds": RETRY_DELAY,
    })
    resp.raise_for_status()
    job = resp.json()
    job_id = job["id"]
    print(f"  Job created (job_id={job_id}).")

    # ── Step 6: Start the copy job ────────────────────────────
    print(f"Starting job {job_id}...")
    resp = session.post(f"{ECUBE_URL}/jobs/{job_id}/start", json={
        "thread_count": THREAD_COUNT,
    })
    resp.raise_for_status()
    print("  Job started.")

    # ── Step 7: Poll for completion ───────────────────────────
    print("Waiting for job to complete...")
    while True:
        resp = session.get(f"{ECUBE_URL}/jobs/{job_id}")
        resp.raise_for_status()
        status = resp.json()

        total = status["total_bytes"]
        copied = status["copied_bytes"]
        if total > 0:
            pct = (copied / total) * 100
            print(f"  {status['status']} — {copied:,} / {total:,} bytes ({pct:.1f}%)")
        else:
            print(f"  {status['status']} — scanning files...")

        if status["status"] == "COMPLETED":
            break
        if status["status"] == "FAILED":
            print("ERROR: Job failed.", file=sys.stderr)
            sys.exit(1)

        time.sleep(POLL_INTERVAL)

    # ── Step 8: Verify ────────────────────────────────────────
    print(f"Verifying job {job_id}...")
    session.post(f"{ECUBE_URL}/jobs/{job_id}/verify").raise_for_status()

    while True:
        resp = session.get(f"{ECUBE_URL}/jobs/{job_id}")
        resp.raise_for_status()
        s = resp.json()["status"]
        print(f"  Verification: {s}")
        if s == "COMPLETED":
            break
        if s == "FAILED":
            print("ERROR: Verification failed.", file=sys.stderr)
            sys.exit(1)
        time.sleep(POLL_INTERVAL)

    # ── Step 9: Generate manifest ─────────────────────────────
    print("Generating manifest...")
    session.post(f"{ECUBE_URL}/jobs/{job_id}/manifest").raise_for_status()
    print("  Manifest written to USB drive.")

    print()
    print(f"Done. Job {job_id} completed successfully.")
    print(f"  Project:  {PROJECT_ID}")
    print(f"  Evidence: {EVIDENCE_NUMBER}")
    print(f"  Drive:    {drive_id}")


if __name__ == "__main__":
    main()
```

### 5.3 PowerShell Script

```powershell
# ECUBE copy job submission script

# ── Configuration ──────────────────────────────────────────────
$EcubeUrl      = "http://ecube-host:8000"
$Username      = "svc-casemgmt"
$Password      = "service-account-password"

$ProjectId     = "CASE-2026-001"
$EvidenceNum   = "EV-042"
$RemotePath    = "fileserver:/exports/case-2026-001"
$MountPoint    = "/mnt/evidence/case-2026-001"
$MountType     = "NFS"       # NFS or SMB
$ThreadCount   = 4           # 1-8
$MaxRetries    = 3           # 0+
$RetryDelay    = 1           # seconds
$PollInterval  = 10          # seconds

$ErrorActionPreference = "Stop"

# ── Step 1: Authenticate ──────────────────────────────────────
Write-Host "Authenticating..."
$auth = Invoke-RestMethod -Uri "$EcubeUrl/auth/token" -Method Post `
    -ContentType "application/json" `
    -Body (@{ username = $Username; password = $Password } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($auth.access_token)" }
Write-Host "  Authenticated."

# ── Step 2: Select an available drive ─────────────────────────
Write-Host "Selecting available drive..."
$drives = Invoke-RestMethod -Uri "$EcubeUrl/drives" -Headers $headers
$available = $drives | Where-Object { $_.current_state -eq "AVAILABLE" } | Select-Object -First 1

if (-not $available) {
    Write-Error "No available drives."
    exit 1
}
$driveId = $available.id
Write-Host "  Selected drive $driveId."

# ── Step 3: Initialize drive for the project ──────────────────
Write-Host "Initializing drive $driveId for project $ProjectId..."
Invoke-RestMethod -Uri "$EcubeUrl/drives/$driveId/initialize" -Method Post `
    -ContentType "application/json" -Headers $headers `
    -Body (@{ project_id = $ProjectId } | ConvertTo-Json) | Out-Null
Write-Host "  Drive initialized."

# ── Step 4: Mount the network share ───────────────────────────
Write-Host "Mounting $RemotePath at $MountPoint..."
$mount = Invoke-RestMethod -Uri "$EcubeUrl/mounts" -Method Post `
    -ContentType "application/json" -Headers $headers `
    -Body (@{
        type             = $MountType
        remote_path      = $RemotePath
        local_mount_point = $MountPoint
    } | ConvertTo-Json)

if ($mount.status -ne "MOUNTED") {
    Write-Error "Mount failed with status: $($mount.status)"
    exit 1
}
Write-Host "  Mounted (mount_id=$($mount.id))."

# ── Step 5: Create the copy job (auto-assign drive) ───────────
Write-Host "Creating copy job..."
$job = Invoke-RestMethod -Uri "$EcubeUrl/jobs" -Method Post `
    -ContentType "application/json" -Headers $headers `
    -Body (@{
        project_id         = $ProjectId
        evidence_number    = $EvidenceNum
        source_path        = $MountPoint
        thread_count       = $ThreadCount
        max_file_retries   = $MaxRetries
        retry_delay_seconds = $RetryDelay
    } | ConvertTo-Json)
$jobId = $job.id
Write-Host "  Job created (job_id=$jobId)."

# ── Step 6: Start the copy job ────────────────────────────────
Write-Host "Starting job $jobId..."
Invoke-RestMethod -Uri "$EcubeUrl/jobs/$jobId/start" -Method Post `
    -ContentType "application/json" -Headers $headers `
    -Body (@{ thread_count = $ThreadCount } | ConvertTo-Json) | Out-Null
Write-Host "  Job started."

# ── Step 7: Poll for completion ───────────────────────────────
Write-Host "Waiting for job to complete..."
do {
    Start-Sleep -Seconds $PollInterval
    $status = Invoke-RestMethod -Uri "$EcubeUrl/jobs/$jobId" -Headers $headers

    if ($status.total_bytes -gt 0) {
        $pct = [math]::Round(($status.copied_bytes / $status.total_bytes) * 100, 1)
        Write-Host "  $($status.status) - $($status.copied_bytes) / $($status.total_bytes) bytes ($pct%)"
    } else {
        Write-Host "  $($status.status) - scanning files..."
    }
} while ($status.status -notin @("COMPLETED", "FAILED"))

if ($status.status -eq "FAILED") {
    Write-Error "Job failed."
    exit 1
}

# ── Step 8: Verify ────────────────────────────────────────────
Write-Host "Verifying job $jobId..."
Invoke-RestMethod -Uri "$EcubeUrl/jobs/$jobId/verify" -Method Post -Headers $headers | Out-Null

do {
    Start-Sleep -Seconds $PollInterval
    $s = (Invoke-RestMethod -Uri "$EcubeUrl/jobs/$jobId" -Headers $headers).status
    Write-Host "  Verification: $s"
} while ($s -notin @("COMPLETED", "FAILED"))

if ($s -eq "FAILED") {
    Write-Error "Verification failed."
    exit 1
}

# ── Step 9: Generate manifest ─────────────────────────────────
Write-Host "Generating manifest..."
Invoke-RestMethod -Uri "$EcubeUrl/jobs/$jobId/manifest" -Method Post -Headers $headers | Out-Null
Write-Host "  Manifest written to USB drive."

Write-Host ""
Write-Host "Done. Job $jobId completed successfully."
Write-Host "  Project:  $ProjectId"
Write-Host "  Evidence: $EvidenceNum"
Write-Host "  Drive:    $driveId"
```

---

## 6. Security Considerations

- **Service accounts:** Use dedicated OS accounts with the minimum required role (`processor`).
- **Token lifetime:** Tokens expire after the configured TTL. Re-authenticate before expiry for long-running integrations.
- **Project isolation:** ECUBE enforces that a USB drive, once bound to a project, cannot receive data from other projects. This is enforced server-side and cannot be bypassed by the caller.
- **Credential handling:** SMB credentials (`username`, `password`) are stored server-side and never returned in API responses or logs. Prefer NFS with host-based access control when possible.
- **Network security:** All API communication should use HTTPS in production. The `http://` examples in this document are for development only.
- **Rate limiting:** Avoid submitting jobs faster than the system can allocate drives. Check drive availability via `GET /drives` before bulk submissions.
