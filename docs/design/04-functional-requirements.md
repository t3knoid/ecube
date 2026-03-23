# 4. Functional Requirements — Design

## 4.1 Drive Lifecycle Management

- Implement a finite-state machine for drive states and legal transitions.
- Gate all transitions through a single service module to ensure consistency.

### 4.1.1 Filesystem Detection Design

- On each discovery cycle (insertion or periodic refresh), probe the drive's filesystem type through the `FilesystemDetector` interface.
- The interface contract:

  ```python
  class FilesystemDetector(Protocol):
      def detect(self, device_path: str) -> str:
          """Return the canonical filesystem label for the given block device.

          Returns one of:
          - A recognized filesystem name (e.g. 'ext4', 'exfat', 'ntfs', 'fat32', 'xfs').
          - 'unformatted' when no filesystem signature is found.
          - 'unknown' when the detection command fails.
          """
          ...
  ```

- **Linux reference implementation:** Use `blkid -o value -s TYPE <device>` as the primary detection tool; fall back to `lsblk --json` if `blkid` returns no result.
- Map detection results to canonical values:
  - Recognized filesystems: `ext4`, `exfat`, `ntfs`, `fat32`, `xfs` (and others as reported by the OS tool).
  - No filesystem signature found: `unformatted`.
  - Detection command failed (I/O error, permission denied): `unknown`.
- Store the result in `usb_drives.filesystem_type`.
- Update the field whenever a drive is reformatted or re-detected.

### 4.1.2 Drive Formatting Design

- Provide an API endpoint (`POST /drives/{id}/format`) to format a drive.
- **Supported filesystem types:** `ext4`, `exfat`.
- The formatting operation is executed through the `DriveFormatter` interface.
- The interface contract:

  ```python
  class DriveFormatter(Protocol):
      def format(self, device_path: str, filesystem_type: str) -> None:
          """Format the block device with the specified filesystem.

          Raises RuntimeError with a descriptive message on failure.
          Implementations must validate the device path before executing
          any destructive operation.
          """
          ...

      def is_mounted(self, device_path: str) -> bool:
          """Return True if the device (or any of its partitions) is currently mounted."""
          ...
  ```

- **Linux reference implementation:** `mkfs.ext4`, `mkfs.exfat`; mount check via `/proc/mounts`.
- **Preconditions (enforced by the service layer before calling the interface):**
  - Drive must be in `AVAILABLE` state (reject with `409` if not).
  - Drive must not be currently mounted — checked via `DriveFormatter.is_mounted()` (reject with `409` if mounted).
  - Drive must have a valid `filesystem_path` (reject with `400` if missing).
- **Formatting procedure:**
  1. Validate preconditions (state, mount status, device path).
  2. Call `DriveFormatter.format(device_path, filesystem_type)`. Implementations use absolute binary paths from settings to prevent PATH manipulation.
  3. On success: update `usb_drives.filesystem_type` to the new value, audit-log `DRIVE_FORMATTED`.
  4. On failure: do not change drive state, audit-log `DRIVE_FORMAT_FAILED` with error details.
- **Security:**
  - Device path must pass validation (e.g. `_DEVICE_PATH_RE`) before any destructive operation — enforced within each concrete implementation.
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

## 4.3 Project Isolation Design (Critical)

Project isolation prevents evidence contamination by binding each USB drive
to a single project and rejecting any write from a different project.

### Storage

The binding is stored in the `usb_drives` database table in the
`current_project_id` column (a nullable string). When a drive has no
project binding the column is `NULL`.

### Binding Lifecycle

1. **Format** — The drive must have a recognized filesystem (`ext4`,
   `exfat`, etc.) before it can be bound. Drives with `filesystem_type`
   of `unformatted`, `unknown`, or `NULL` are rejected at initialization
   with HTTP 409.
2. **Initialize** — `POST /drives/{id}/initialize` accepts a `project_id`
   in the request body. The service:
   - Acquires a row-level lock on the drive (`SELECT … FOR UPDATE NOWAIT`)
     to prevent concurrent mutations.
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

### Concurrency

Row-level locking (`FOR UPDATE NOWAIT`) ensures that two concurrent
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

- Up to **3 attempts** with exponential backoff (1 s, 5 s between retries).
- **5xx** responses and network errors trigger retries.
- **4xx** responses are treated as permanent failures (logged as `CALLBACK_DELIVERY_FAILED`, no retry).
- **2xx/3xx** responses are treated as successful delivery (logged as `CALLBACK_SENT`).

### SSRF Protection

- The callback URL's hostname is resolved via DNS before the request is sent.
- If any resolved address is private, loopback, link-local, or reserved, delivery is **blocked** (configurable via `CALLBACK_ALLOW_PRIVATE_IPS`).
- Unresolvable hostnames are also blocked.

### Schema Enforcement

- Only `https://` URLs are accepted. HTTP URLs are rejected with 422 at job creation time.

### Audit Events

- `CALLBACK_SENT` — Successful delivery; includes `callback_url`, `status_code`, `attempt`.
- `CALLBACK_DELIVERY_FAILED` — All retries exhausted or SSRF blocked; includes `callback_url`, `reason`, `attempts`.

---

## 4.9 Audit Logging Design

- Emit structured JSON payloads for all critical operations.
- Use append-only semantics and immutable timestamps.
- Port enablement changes emit dedicated audit events:
  - `PORT_ENABLED` — Port enabled for ECUBE use; includes `port_id`, `system_path`, `hub_id`, `enabled`, `path`.
  - `PORT_DISABLED` — Port disabled; includes `port_id`, `system_path`, `hub_id`, `enabled`, `path`.

## 4.10 USB Discovery and State Refresh Design

- Service reads sysfs topology (`/sys/bus/usb/devices`) and returns dataclass-based snapshot.
- Hub and Port records are upserted (identified by stable `system_identifier` and `system_path` keys).
- **Hardware enrichment:** During discovery, the service reads additional sysfs
  attributes for each hub and port device:
  - `idVendor` → `vendor_id` (hubs and ports)
  - `idProduct` → `product_id` (hubs and ports)
  - `speed` → `speed` (ports only, in Mbps)
  These fields are updated on every sync cycle when present in sysfs; `NULL`
  values in sysfs do not overwrite previously stored values. Empty sysfs
  attribute files (zero-length or whitespace-only) are normalized to `None`
  by the discovery adapter and therefore also do not overwrite stored values.
- **Label preservation:** Admin-assigned labels (`location_hint` on hubs,
  `friendly_label` on ports) are never overwritten by the discovery sync.
  Labels can only be changed through the admin API
  (`PATCH /admin/hubs/{hub_id}`, `PATCH /admin/ports/{port_id}/label`).
- Drive state transitions follow FSM rules: `EMPTY → AVAILABLE` on reconnection, `AVAILABLE → EMPTY` on removal (unless `IN_USE` — project isolation preserved).
- **Port enablement filtering:** Each USB port has an `enabled` flag (default `false`). Discovery uses this flag to gate drive availability:
  - A newly discovered drive on a **disabled** port is inserted in `EMPTY` state (not `AVAILABLE`).
  - A reconnecting drive (previously `EMPTY`) on a **disabled** port remains `EMPTY`.
  - An `AVAILABLE` drive whose port is subsequently **disabled** is demoted to `EMPTY` on the next discovery sync.
  - Drives with no associated port (`port_id = NULL`) are treated as **disabled** — they remain in `EMPTY` state.
  - Drives already in `IN_USE` state are **never** changed by the enablement filter — project isolation takes priority.
  - Admins and managers toggle port enablement via `PATCH /admin/ports/{port_id}`. The change takes effect on the next discovery sync.
- Refresh operation is fully idempotent: running multiple times without hardware changes produces no mutations.
- **Concurrency safety:** `usb_ports.system_path` carries a database-level
  unique constraint. If two concurrent discovery syncs both attempt to insert
  the same port, the second insert raises an `IntegrityError` which is caught,
  rolled back, and retried as an update against the already-committed row.
  The same mechanism applies to `usb_hubs.system_identifier`. This ensures
  discovery remains idempotent under multi-worker deployments.
- **Operational note:** When a port is discovered but its parent hub is not present in the topology snapshot, a placeholder hub is automatically created with a default name. This prevents foreign-key violations in case of sysfs race conditions or partial enumeration. The placeholder hub name can be manually updated via hub management API when the hub is fully enumerated.
- Every sync emits a `USB_DISCOVERY_SYNC` audit log with actor and summary counts (hubs_upserted, ports_upserted, drives_inserted, drives_updated, drives_removed).
