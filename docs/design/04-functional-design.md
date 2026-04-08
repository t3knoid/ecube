# 4. Functional Design

This document describes how ECUBE functional behavior is implemented. It is written for engineers, implementers, maintainers, and technical reviewers who need endpoint structure, flows, algorithms, state handling, and data-oriented design detail.

This document intentionally includes lifecycle flows, endpoint responsibilities, state transitions, algorithms, validation order, and implementation-oriented constraints. It intentionally excludes business justification, user stories, and product-level rationale except where a brief note is necessary to explain a resulting design choice.

## 4.1 Drive Lifecycle Management

- Implement a finite-state machine for drive states and legal transitions.
- Gate all transitions through a single service module to ensure consistency.
- The recommended persisted drive states are `EMPTY`, `AVAILABLE`, `IN_USE`, and `FINALIZED`.
- `FINALIZED` is distinct from `AVAILABLE`: it represents a drive that has completed export handling and is logically sealed against further writes until an explicit reopen action is performed.

### 4.1.0 Recommended Drive State Semantics

- `EMPTY` — drive record exists but hardware is not presently available for use.
- `AVAILABLE` — drive is present, writable, and eligible for initialization or job assignment.
- `IN_USE` — drive is actively assigned to a project/job workflow and may receive data writes.
- `FINALIZED` — drive has been explicitly finalized for handoff/custody; it remains project-bound but is not eligible for new writes, auto-assignment, or reinitialization until reopened.

Recommended legal transitions:

- `EMPTY → AVAILABLE` on discovery of a usable drive.
- `AVAILABLE → IN_USE` on initialize or job assignment.
- `IN_USE → AVAILABLE` on prepare-eject.
- `IN_USE → FINALIZED` on finalize.
- `AVAILABLE → FINALIZED` on finalize when the drive was already safely prepared and no additional OS-level unmount work is needed.
- `FINALIZED → AVAILABLE` on explicit reopen/unfinalize.
- `AVAILABLE → EMPTY` on removal or disabled-port reconciliation.

Illegal transitions should be rejected with `409 Conflict`.

### 4.1.1 Filesystem Detection Design

- On each discovery cycle (insertion or periodic refresh), probe the drive's filesystem type through the platform abstraction layer.
- Map detection results to canonical values:
  - Recognized filesystems: `ext4`, `exfat`, `ntfs`, `fat32`, `xfs` (and others as reported by the OS tool).
  - No filesystem signature found: `unformatted`.
  - Detection command failed (I/O error, permission denied): `unknown`.
- Persist the detected value as part of drive state.
- Update the value whenever a drive is reformatted or re-detected.

### 4.1.2 Drive Formatting Design

- Provide an API endpoint (`POST /drives/{drive_id}/format`) to format a drive.
- **Supported filesystem types:** `ext4`, `exfat`.
- The formatting operation is executed through the platform abstraction layer.
- **Preconditions (enforced by the service layer before calling the interface):**
  - Drive must be in `AVAILABLE` state (reject with `409` if not).
  - Drive must not be currently mounted (reject with `409` if mounted).
  - Drive must have a valid `filesystem_path` (reject with `400` if missing).
- **Formatting procedure:**
  1. Validate preconditions (state, mount status, device path).
  2. Invoke the formatter for the requested filesystem type.
  3. On success: update the persisted filesystem classification to the new value, audit-log `DRIVE_FORMATTED`.
  4. On failure: do not change drive state, audit-log `DRIVE_FORMAT_FAILED` with error details.
- **Security:**
  - Device path must be validated before any destructive operation.
  - Formatting commands run with bounded timeouts.
  - Only `admin` and `manager` roles may format drives.

## 4.2 Drive Prepare-Eject Procedure

- **Precondition:** Drive must be in `IN_USE` state; reject with 409 if not
- **Initial validation:** Capture drive state and filesystem path at request start
- **Fast-fail optimization:** Validate `IN_USE` precondition immediately, before any expensive OS operations (sync/unmount). Prevents wasted work on invalid requests.
- Filesystem sync: Issue `sync(1)` to flush pending writes before unmount
- Partition discovery: Parse `/proc/mounts` to find all mounted partitions and volumes belonging to the device
  - Supports traditional partition naming: `sdb`, `sdb1`, `sdb2` (etc.)
  - Supports NVMe partition naming: `nvme0n1`, `nvme0n1p1`, `nvme0n1p2` (etc.)
  - Supports MMC partition naming: `mmcblk0`, `mmcblk0p1`, `mmcblk0p2` (etc.)
  - Supports device-mapper (encrypted) volumes: `/dev/mapper/*` (LUKS) and `/dev/dm-*` (LVM)
    - Resolves symlinks via `os.path.realpath()` to actual `/dev/dm-N` device nodes
    - Traces parent block device via `/sys/block/dm-N/slaves/` sysfs interface
- Path normalization: Normalizes device paths to resolve symlinks (e.g., `/dev/disk/by-id/*` → actual device)
- Escape sequence handling: Decodes POSIX escape sequences in mount points from `/proc/mounts` (e.g., `\040` → space, `\011` → tab)
- Safe unmount ordering: Unmounts nested mount points in reverse depth order (deepest first) to prevent "target is busy" errors
- Unmount all partitions: Attempt to unmount each mount point, collecting errors
- **Transaction optimization:** OS operations (sync/unmount) execute without database row lock to reduce contention
- **Race condition detection:** After re-acquiring lock, validate that drive state and device path have not changed since initial read
  - If state changed: reject with 409 Conflict (another request changed drive state)
  - If device path changed: reject with 409 Conflict (discovery refresh changed path during operation)
  - This ensures audit trail records the device path actually used for OS operations
- Failure handling: If any operation fails, keep drive `IN_USE` and audit the failure with details
- Success: Transition drive to `AVAILABLE` only after all operations succeed
- No-op case: If device is not currently mounted, consider it successfully prepared (return success)

### 4.2.1 Relationship Between Prepare-Eject and Finalize

- `prepare-eject` remains the operational safe-removal endpoint.
- It does **not** imply legal handoff, write protection, or export completion.
- It does **not** clear `current_project_id`; the drive remains bound to its project after prepare-eject.
- A prepare-ejected drive remains reusable within the current workflow and can later be assigned back to `IN_USE` under existing project-isolation rules.
- Finalization, if implemented, must be a separate endpoint and separate persisted state, not an alias for prepare-eject.

### 4.2.2 Drive Finalization Design

- Provide an API endpoint (`POST /drives/{drive_id}/finalize`) to mark a drive as export-complete and logically sealed.
- Finalization is exposed as an explicit sealed-state transition after copy-oriented work is complete.
- Recommended allowed starting states:
  - `IN_USE` — perform safe-eject operations as part of finalization, then transition to `FINALIZED`.
  - `AVAILABLE` — permit finalization if the drive is already safely unmounted/prepared and remains project-bound to the intended export.
- Recommended preconditions:
  - Drive must be bound to a project (`current_project_id` is not `NULL`).
  - No active copy/verify/manifest job may still be operating against the drive.
  - If a job is associated with the drive, it should be in a terminal successful state before finalization is accepted.
  - If manifest completion is part of the deployment policy, manifest generation should already be complete.
- Finalization procedure:
  1. Validate state and project binding.
  2. Validate no active job is still using the drive.
  3. If state is `IN_USE`, reuse prepare-eject OS behavior (sync + unmount + race validation).
  4. Transition drive state to `FINALIZED`.
  5. Persist finalization metadata (`finalized_at`, `finalized_by`, and optional operator note/reason).
  6. Emit a dedicated audit event such as `DRIVE_FINALIZED`.
- Finalization effects:
  - Finalized drives must not be eligible for new job creation or auto-assignment.
  - Finalized drives must not be reinitialized, formatted, or returned to `IN_USE` implicitly.
  - Finalized drives remain associated with their existing `current_project_id` until explicitly reopened or reset.
- Failure handling:
  - If OS-level prepare-eject work fails, do not mark the drive finalized.
  - If database persistence of finalization fails after OS work succeeded, return `500` and require operator review; state must not silently degrade to `AVAILABLE` without an audit trail.

### 4.2.3 Drive Reopen / Unfinalize Design

- Provide an API endpoint (`POST /drives/{drive_id}/reopen`) or equivalent to reverse finalization when additional data must be exported.
- Reopen is intentionally explicit because it breaks the sealed-handoff assumption established by finalization.
- Recommended preconditions:
  - Drive must currently be in `FINALIZED` state.
  - Caller must have elevated privileges (`admin`, or stricter if policy requires).
  - Request body should include a mandatory human-readable reason.
- Reopen procedure:
  1. Validate the drive is `FINALIZED`.
  2. Record the operator-supplied reason.
  3. Transition drive state from `FINALIZED` to `AVAILABLE`.
  4. Preserve `current_project_id` by default so additional exports remain constrained to the same case/project.
  5. Emit a dedicated audit event such as `DRIVE_REOPENED` or `DRIVE_UNFINALIZED` containing actor, reason, prior finalization metadata, and drive/project identifiers.
- Reopen effects:
  - The drive becomes eligible for explicit reuse.
  - Subsequent writes must still respect project isolation.
  - Operators may then assign/start an additional job and later finalize the drive again.
- Reopen must never happen implicitly as a side effect of discovery, job creation, or initialize.

## 4.3 Project Isolation Design

Project isolation binds each USB drive to a single project and rejects any write from a different project.

### Storage

The binding is persisted as part of the drive's authoritative state. A drive with no active project binding remains unassigned.

### Binding Lifecycle

1. **Format** — The drive must have a recognized filesystem (`ext4`,
   `exfat`, etc.) before it can be bound. Drives with `filesystem_type`
   of `unformatted`, `unknown`, or `NULL` are rejected at initialization
   with HTTP 409.
2. **Initialize** — `POST /drives/{drive_id}/initialize` accepts a `project_id`
   in the request body. The service:
   - Acquires an exclusive lock on the drive record to prevent concurrent mutations.
   - Checks `current_project_id`: if already set **and** different from
     the requested project, the request is denied with HTTP 403 and a
     `PROJECT_ISOLATION_VIOLATION` audit event is recorded (including
     actor, drive ID, existing project, and requested project).
   - Sets `current_project_id = project_id` and transitions
     `current_state` from `AVAILABLE` to `IN_USE`.
   - Commits the change and emits a `DRIVE_INITIALIZED` audit event.
3. **Copy enforcement** — When a copy job targets a drive, the job's
   `project_id` is compared against the drive's `current_project_id`.
   Mismatched writes are rejected **before** any data is copied.
4. **Release** — The project binding persists until the drive is explicitly
   re-initialized for a different project or reset. Removing a drive
   physically does not clear its `current_project_id` in the database.
5. **Finalization interaction** — Finalization does not clear project binding.
  A finalized drive remains bound to its project but is write-ineligible
  until explicitly reopened.

### Concurrency

Exclusive record locking ensures that two concurrent
initialize or format requests for the same drive are serialized. If a
lock cannot be acquired immediately, the request fails with HTTP 409
rather than waiting.

### Audit Trail

Every project-isolation decision is recorded:

| Event | When |
|-------|------|
| `DRIVE_INITIALIZED` | Drive successfully bound to a project |
| `PROJECT_ISOLATION_VIOLATION` | Request attempted to bind a drive already assigned to a different project |
| `INIT_REJECTED_FILESYSTEM` | Initialization rejected because drive has no recognized filesystem |

## 4.4 Job Management Design

- Job entity stores immutable creation metadata plus mutable progress fields.
- File-level records enable resume and per-file retry semantics.

## 4.5 Multi-threaded Copy Engine Design

- Queue file units to worker pool sized by `thread_count`.
- Use atomic progress updates (`copied_bytes`, file status transitions).
- Verify checksums post-copy and mark verification status.

## 4.6 Network Mount Support Design

- Mount manager validates connectivity before exposing paths to job creation.
- Reference counting prevents unmount while active jobs still depend on a mount.

## 4.7 Manifest Generation Design

- Generate deterministic manifest per job completion (or on-demand regeneration).
- Include source metadata, checksums, byte totals, and generation timestamp.

## 4.8 Webhook Callback Delivery

When a job includes a `callback_url`, the system sends an HTTPS POST request with a JSON payload to the specified URL when the job reaches a terminal state (`COMPLETED` or `FAILED`). This applies to all three terminal-state paths: copy completion, copy timeout, and post-copy verification.

### Payload

The callback body is a JSON object containing:

| Field | Type | Description |
|-------|------|-------------|
| `event` | string | `JOB_COMPLETED` or `JOB_FAILED` |
| `job_id` | integer | Job identifier |
| `project_id` | string | Bound project ID |
| `evidence_number` | string | Evidence case number |
| `status` | string | Terminal status value |
| `source_path` | string | Source data path |
| `total_bytes` | integer | Total bytes to copy |
| `copied_bytes` | integer | Bytes actually copied |
| `file_count` | integer | Total file count |
| `completed_at` | string or null | ISO 8601 timestamp (present when `completed_at` is set) |

### Retry & Backoff

- Up to **4 attempts** with exponential backoff (1 s, 5 s, 25 s between retries).
- **5xx** responses and network errors trigger retries.
- **4xx** responses are treated as permanent failures (logged as `CALLBACK_DELIVERY_FAILED`, no retry).
- **3xx** redirects are treated as permanent failures (not followed, to prevent redirect-based SSRF bypass).
- **2xx** responses are treated as successful delivery (logged as `CALLBACK_SENT`).

### Backpressure

- A bounded semaphore (`CALLBACK_MAX_PENDING`, default 100) caps the total number of outstanding deliveries (queued + in-flight).
- When the limit is reached, new deliveries are dropped and logged as `CALLBACK_DELIVERY_DROPPED`.

### SSRF Protection

- The callback URL's hostname is resolved via DNS before the request is sent.
- If any resolved address is private, loopback, link-local, or reserved, delivery is **blocked** (configurable via `CALLBACK_ALLOW_PRIVATE_IPS`).
- Unresolvable hostnames are also blocked.

### Schema Enforcement

- Only `https://` URLs are accepted. HTTP URLs are rejected with 422 at job creation time.

### Audit Events

- `CALLBACK_SENT` — Successful delivery; includes `callback_url`, `status_code`, `attempt`.
- `CALLBACK_DELIVERY_FAILED` — All retries exhausted, SSRF blocked, redirect received, or permanent failure; includes `callback_url`, `reason`, `attempts`.
- `CALLBACK_DELIVERY_DROPPED` — Delivery dropped due to backpressure (queue full); includes `callback_url`, `reason`.

---

## 4.9 Audit Logging Design

- Emit structured JSON payloads for all critical operations.
- Use append-only semantics and immutable timestamps.
- Port enablement changes emit dedicated audit events:
  - `PORT_ENABLED` — Port enabled for ECUBE use; includes `port_id`, `system_path`, `hub_id`, `enabled`, `path`.
  - `PORT_DISABLED` — Port disabled; includes `port_id`, `system_path`, `hub_id`, `enabled`, `path`.
- Startup reconciliation events:
  - `MOUNT_RECONCILED` — Mount state corrected after restart; includes `mount_id`, `local_mount_point`, `old_status`, `new_status`, `reason`.
  - `JOB_RECONCILED` — In-progress job failed after restart; includes `job_id`, `old_status`, `new_status`, `reason`.

## 4.10 USB Discovery and State Refresh Design

- Service reads host USB topology through the platform abstraction layer and produces a normalized snapshot for persistence.
- Hub and port records are upserted using stable hardware identity keys.
- **Hardware enrichment:** Discovery should capture vendor, product, and negotiated-speed metadata when available, without erasing previously known values with empty readings.
- **Label preservation:** Admin-assigned hub and port labels are never overwritten by discovery.
- Drive state transitions follow FSM rules: `EMPTY → AVAILABLE` on reconnection, `AVAILABLE → EMPTY` on removal (unless `IN_USE` or `FINALIZED` — project isolation and custody state are preserved).
- **Port enablement filtering:** Each USB port has an `enabled` flag (default `false`). Discovery uses this flag to gate drive availability:
  - A newly discovered drive on a **disabled** port is inserted in `EMPTY` state (not `AVAILABLE`).
  - A reconnecting drive (previously `EMPTY`) on a **disabled** port remains `EMPTY`.
  - An `AVAILABLE` drive whose port is subsequently **disabled** is demoted to `EMPTY` on the next discovery sync.
  - Drives with no associated port (`port_id = NULL`) are treated as **disabled** — they remain in `EMPTY` state.
  - Drives already in `IN_USE` or `FINALIZED` state are **never** changed by the enablement filter — project isolation and custody state take priority.
  - Port enablement changes take effect on the next discovery sync.
- Refresh operation is fully idempotent: running multiple times without hardware changes produces no mutations.
- **Concurrency safety:** Discovery must remain idempotent under multi-worker execution and tolerate concurrent upsert attempts against the same hardware identities.
- **Partial-topology tolerance:** If a port is observed before its parent hub is fully enumerated, discovery must still preserve referential consistency and recover cleanly on later syncs.
- Every sync emits a `USB_DISCOVERY_SYNC` audit log with actor and summary counts (hubs_upserted, ports_upserted, drives_inserted, drives_updated, drives_removed).

## 4.11 Startup State Reconciliation

After a service restart or host reboot, in-memory OS state (active mounts, running processes, USB device presence) may diverge from the database. The reconciliation service realigns persisted state with actual OS/hardware state during application startup.

### Cross-Process Lock

In multi-worker deployments, only one worker must run reconciliation. A cross-process guard prevents concurrent execution, allows non-owning workers to skip reconciliation safely, and supports stale-lock recovery so a crashed worker does not block future startups.

### Execution Order

Reconciliation runs during application startup, before the service begins normal steady-state discovery behavior. Once the cross-process lock is acquired, the three passes execute in fixed order:

1. **Mounts** — verify OS mount state
2. **Jobs** — fail interrupted jobs
3. **Drives** — re-run USB discovery

### 4.11.1 Mount Reconciliation

- Query all `network_mounts` rows with `status = MOUNTED`.
- For each, query the mount provider for actual OS mount state:
  - Returns `True` → mount is still active; no status change.  `last_checked_at` is updated.
  - Returns `False` → mount is no longer active; transition to `UNMOUNTED`.
  - Returns `None` (OS error) → transition to `ERROR`.
- Every checked mount receives a `last_checked_at` timestamp update regardless of whether its status changed.  This is an observability side-effect, not a domain state mutation.
- Each correction emits a `MOUNT_RECONCILED` audit event with `mount_id`, `local_mount_point`, `old_status`, `new_status`, and `reason: "startup reconciliation"`.
- Mounts already in `UNMOUNTED` or `ERROR` state are not checked.

### 4.11.2 Job Reconciliation

- Query all `export_jobs` rows with `status IN (RUNNING, VERIFYING)`.
- After a restart no worker processes exist, so these jobs are unconditionally transitioned to `FAILED` with `completed_at` set to the current UTC time.
- Each correction emits a `JOB_RECONCILED` audit event with `job_id`, `old_status`, `new_status`, and `reason: "interrupted by restart"`.
- Jobs in `PENDING`, `COMPLETED`, or `FAILED` state are not affected.

### 4.11.3 Drive Reconciliation

- Delegates to the normal discovery refresh path (see § 4.10) with `actor="system"`.
- This re-reads the USB topology and applies the standard drive FSM transitions (EMPTY ↔ AVAILABLE, IN_USE preserved).
- Drives that are no longer physically present and were `AVAILABLE` are transitioned to `EMPTY`.

### Failure Isolation

Each reconciliation pass is wrapped in an independent `try/except` block. A failure in one pass (e.g. mount provider raises an OS error) does not prevent the remaining passes from executing.

### Idempotency Guarantee

All three passes are fully idempotent — running them multiple times without underlying state changes produces no additional **state mutations**. Mount and job reconciliation emit audit records (`MOUNT_RECONCILED`, `JOB_RECONCILED`) only when a state correction occurs; repeated runs with no new corrections produce no duplicate audit rows. Observability side-effects that **do** occur on every invocation (and are not considered state mutations) include: mount `last_checked_at` timestamp updates, and the `USB_DISCOVERY_SYNC` summary audit entry emitted by the drive pass.

### Multi-Worker Safety

The cross-process lock guarantees that exactly one worker runs reconciliation per startup cycle. Workers that do not acquire the lock skip reconciliation, which prevents duplicate correction audit events and conflicting writes during startup.
