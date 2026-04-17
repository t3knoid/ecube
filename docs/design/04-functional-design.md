# 4. Functional Design

| Field | Value |
|---|---|
| Title | Functional Design |
| Purpose | Describes how ECUBE functional behavior is implemented, covering lifecycle flows, state transitions, endpoint responsibilities, algorithms, and locking strategies. |
| Updated on | 04/11/26 |
| Audience | Engineers, implementers, maintainers, and technical reviewers. |

## 4.1 Drive Lifecycle Management

- Implement a finite-state machine for drive states and legal transitions.
- Gate all transitions through a single service module to ensure consistency.
- The recommended persisted drive states are `DISCONNECTED`, `AVAILABLE`, and `IN_USE`.

### 4.1.0 Recommended Drive State Semantics

- `DISCONNECTED` — drive record exists but hardware is not presently available for use.
- `AVAILABLE` — drive is present, writable, and eligible for initialization or job assignment.
- `IN_USE` — drive is actively assigned to a project/job workflow and may receive data writes.

Recommended legal transitions:

- `DISCONNECTED → AVAILABLE` on discovery of a usable drive.
- `AVAILABLE → IN_USE` on initialize or job assignment.
- `IN_USE → AVAILABLE` on prepare-eject.
- `AVAILABLE → DISCONNECTED` on removal or disabled-port reconciliation.
- `AVAILABLE → ARCHIVED` on custody handoff confirmation (via `POST /audit/chain-of-custody/handoff`).

Note: handoff confirmation accepts drives in any non-archived state so that drives that were not formally ejected before handoff can still be archived. The expected operational flow is `IN_USE → AVAILABLE` (prepare-eject) followed by `AVAILABLE → ARCHIVED` (handoff). `ARCHIVED` is a terminal state; no further transitions are permitted.

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
- No-op case: If device is not currently mounted, consider prepare-eject successful (return success)

### 4.2.1 Prepare-Eject Semantics

- `POST /drives/{drive_id}/prepare-eject` is the safe-removal endpoint.
- It flushes pending writes, unmounts all partitions, and transitions the drive from `IN_USE` to `AVAILABLE`.
- It does **not** imply legal handoff, write protection, or export completion.
- It does **not** clear `current_project_id`; the drive remains bound to its project after prepare-eject.
- After prepare-eject, the drive is immediately reusable within the current workflow and can be assigned back to `IN_USE` under existing project-isolation rules.

## 4.3 Project Isolation Design

Project isolation binds each USB drive to a single project and rejects any write from a different project.

### Storage

The binding is persisted as part of the drive's authoritative state. A drive with no active project binding remains unassigned.

### Binding Lifecycle

1. **Format** — The drive must have a recognized filesystem (`ext4`, `exfat`, etc.) before it can be bound. Drives with `filesystem_type` of `unformatted`, `unknown`, or `NULL` are rejected at initialization with HTTP 409. Formatting also clears the prior project binding so the drive can be safely reassigned.
2. **Initialize** — `POST /drives/{drive_id}/initialize` accepts a `project_id` in the request body. The service:
   - Normalizes the requested project identifier by trimming surrounding whitespace and converting it to uppercase.
   - Acquires an exclusive lock on the drive record to prevent concurrent mutations.
   - Verifies that the requested project already has at least one assigned share in the `MOUNTED` state and requests a fast-fail update lock on one eligible share.
   - Checks `current_project_id`: if the drive is already `IN_USE` for a different project, the request is denied with HTTP 403 and a `PROJECT_ISOLATION_VIOLATION` audit event is recorded; if the drive is `AVAILABLE` but still bound to a different project, the request is denied with HTTP 409 until the drive is formatted.
   - Rejects the request with HTTP 409 when no eligible mounted share exists or when the project source is being updated concurrently.
   - Sets `current_project_id = project_id` and transitions `current_state` from `AVAILABLE` to `IN_USE`.
   - Commits the change and emits a `DRIVE_INITIALIZED` audit event.
3. **Copy enforcement** — When a copy job targets a drive, the job's `project_id` is compared against the drive's `current_project_id`. Mismatched writes are rejected **before** any data is copied.
4. **Release** — The project binding persists until the drive is explicitly reformatted or re-initialized for the same project. Removing a drive physically does not clear its `current_project_id` in the database.

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

### 4.6.1 Project Source Binding Design

Project source binding defines which source locations are valid for each project,
so project isolation covers both destination drives and source-path selection.

#### Configuration Model

- Add a project source-binding entity keyed by project identifier.
- Each binding row references:
  - project identifier
  - mount identifier
  - optional subfolder path under the mount's local mount point
  - active flag
  - created/updated metadata
- Multiple bindings per project are allowed.
- A binding without subfolder means the whole mount root is allowed for that project.

#### Path Resolution Model

- Job creation resolves an effective source path as an absolute path visible to ECUBE.
- If the caller provides a relative source component, the service resolves it under
  the selected mount root before validation.
- If the caller provides an absolute source path, it is normalized and validated
  against allowed binding boundaries.
- Normalization must remove redundant path segments and reject unsafe traversal
  semantics (for example, attempts to escape via `..`).

#### Job Creation Enforcement Flow

1. Load active source bindings for the requested project.
2. If bindings exist, require the effective source path to be contained by at
   least one allowed binding boundary (`mount_root[/subfolder]`).
3. If bindings are required by policy and none exist, reject job creation.
4. If the source path is outside all allowed boundaries, reject job creation
   before drive assignment or copy scheduling.
5. If source binding passes, continue existing drive/project isolation and job
   lifecycle validation.

#### Shared-Share / Subfolder Pattern

- One mount may be shared across many projects.
- Per-project segregation is achieved by binding distinct subfolders on the
  same mount root (for example `/mnt/evidence/PROJECT-A`, `/mnt/evidence/PROJECT-B`).
- Boundary checks are path-prefix-safe and segment-aware so `PROJECT-A`
  does not match `PROJECT-A-ARCHIVE` unless explicitly configured.

#### UI / Workflow Model

- Add a project settings screen for admin/manager roles.
- The screen allows create/update/delete of project source bindings and displays
  effective allowed source boundaries.
- Job creation UI should present project-allowed source options first; free-text
  source entry, if retained, must still pass server-side binding validation.

#### Authorization Model

- Admin/manager: can manage project source bindings.
- Processor: can create jobs using allowed bindings but cannot modify binding policy.
- Auditor: read-only visibility where policy permits, no mutation capability.

#### Audit Model

- Emit audit events for source-binding create/update/delete operations.
- Emit a dedicated denial audit event when job creation is rejected due to
  source-binding policy mismatch.
- Denial details include actor, project identifier, submitted source path,
  and evaluated binding boundary identifiers.

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

### 4.9.1 Chain-of-Custody Report Design

- Provide chain-of-custody report retrieval by `drive_id` and by `project_id`.
- Default query mode to drive-based retrieval.
- When both `drive_id` and `project_id` are provided, drive-based retrieval takes precedence.
- Restrict CoC report access to the same role set that can read audit logs (`admin`, `manager`, `auditor`).
- Support UI print/save workflows for authorized users using the same CoC report data model.
- Ensure printed/saved CoC outputs include custody actors and custody timestamps required for legal review.
- Define `delivery_time` as the timestamp of physical custody transfer confirmation.
- Do not infer delivery from `POST /drives/{drive_id}/prepare-eject`; prepare-eject only confirms safe-removal readiness.
- Capture custody handoff through a dedicated confirmation step in the UI/API that records `possessor` and `delivery_time` as a distinct CoC event.

## 4.10 USB Discovery and State Refresh Design

- Service reads host USB topology through the platform abstraction layer and produces a normalized snapshot for persistence.
- Hub and port records are upserted using stable hardware identity keys.
- **Hardware enrichment:** Discovery should capture vendor, product, and negotiated-speed metadata when available, without erasing previously known values with empty readings.
- **Label preservation:** Admin-assigned hub and port labels are never overwritten by discovery.
- Drive state transitions follow FSM rules: `DISCONNECTED → AVAILABLE` on reconnection, `AVAILABLE → DISCONNECTED` on removal (unless `IN_USE` — project isolation takes priority).
- **Port enablement filtering:** Each USB port has an `enabled` flag (default `false`). Discovery uses this flag to gate drive availability:
  - A newly discovered drive on a **disabled** port is inserted in `DISCONNECTED` state (not `AVAILABLE`).
  - A reconnecting drive (previously `DISCONNECTED`) on a **disabled** port remains `DISCONNECTED`.
  - An `AVAILABLE` drive whose port is subsequently **disabled** is demoted to `DISCONNECTED` on the next discovery sync.
  - Drives with no associated port (`port_id = NULL`) are treated as **disabled** — they remain in `DISCONNECTED` state.
  - Drives already in `IN_USE` state are **never** changed by the enablement filter — project isolation takes priority.
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
- This re-reads the USB topology and applies the standard drive FSM transitions (DISCONNECTED ↔ AVAILABLE, IN_USE preserved).
- Drives that are no longer physically present and were `AVAILABLE` are transitioned to `DISCONNECTED`.

### Failure Isolation

Each reconciliation pass is wrapped in an independent `try/except` block. A failure in one pass (e.g. mount provider raises an OS error) does not prevent the remaining passes from executing.

### Idempotency Guarantee

All three passes are fully idempotent — running them multiple times without underlying state changes produces no additional **state mutations**. Mount and job reconciliation emit audit records (`MOUNT_RECONCILED`, `JOB_RECONCILED`) only when a state correction occurs; repeated runs with no new corrections produce no duplicate audit rows. Observability side-effects that **do** occur on every invocation (and are not considered state mutations) include: mount `last_checked_at` timestamp updates, and the `USB_DISCOVERY_SYNC` summary audit entry emitted by the drive pass.

### Multi-Worker Safety

The cross-process lock guarantees that exactly one worker runs reconciliation per startup cycle. Workers that do not acquire the lock skip reconciliation, which prevents duplicate correction audit events and conflicting writes during startup.

## 4.12 In-App Help System Design

The Help system is generated from user-facing documentation and rendered in-app through a modal UX.

### 4.12.1 Source of Truth and Curation

- Canonical source: `docs/operations/13-user-manual.md`.
- A generation step extracts and curates end-user-relevant sections for in-app usage.
- Operator-only installation/deployment internals are excluded from in-app help output.

### 4.12.2 Help Generation Pipeline

- A dedicated script (for example `scripts/build-help.mjs` or `scripts/build-help.sh`) reads the source manual and emits static HTML.
- Generated output is deterministic for identical source input and generation options.
- Output target is a frontend-shipped location (for example `frontend/public/help/manual.html` or equivalent generated path consumed by frontend build).

### 4.12.3 QA and CI Parity Model

- Local QA runs the same dedicated help-generation script before packaging.
- CI packaging invokes the identical script entrypoint; CI must not maintain a separate help-generation path.
- This guarantees packaged help content is produced by the same process used for QA validation.

### 4.12.4 Frontend Integration Design

- Authenticated shell exposes a Help trigger (header/footer/sidebar placement per UI design).
- Trigger opens a modal-style help container without hard navigation away from active workflow.
- Recommended rendering model is an iframe or isolated container targeting generated static help HTML to minimize style/script interference.

### 4.12.5 Error and Fallback Behavior

- If generated help asset is missing, UI displays a non-fatal error state with retry and operator-facing guidance.
- Missing-help events are surfaced through frontend diagnostics/logging pathways used for operational troubleshooting.

## References

- [docs/requirements/04-functional-requirements.md](../requirements/04-functional-requirements.md)
