# 4. Functional Requirements — Design

## 4.1 Drive Lifecycle Management

- Implement a finite-state machine for drive states and legal transitions.
- Gate all transitions through a single service module to ensure consistency.

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

- Bind `current_project_id` on initialization and enforce at write time.
- Reject mismatched project writes before copy begins.
- Record denial in `audit_logs` with actor, drive, requested project, and reason.

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

## 4.8 Audit Logging Design

- Emit structured JSON payloads for all critical operations.
- Use append-only semantics and immutable timestamps.

## 4.9 USB Discovery and State Refresh Design

- Service reads sysfs topology (`/sys/bus/usb/devices`) and returns dataclass-based snapshot.
- Hub and Port records are upserted (identified by stable `system_identifier` and `system_path` keys).
- Drive state transitions follow FSM rules: `EMPTY → AVAILABLE` on reconnection, `AVAILABLE → EMPTY` on removal (unless `IN_USE` — project isolation preserved).
- Refresh operation is fully idempotent: running multiple times without hardware changes produces no mutations.
- **Operational note:** When a port is discovered but its parent hub is not present in the topology snapshot, a placeholder hub is automatically created with a default name. This prevents foreign-key violations in case of sysfs race conditions or partial enumeration. The placeholder hub name can be manually updated via hub management API when the hub is fully enumerated.
- Every sync emits a `USB_DISCOVERY_SYNC` audit log with actor and summary counts (hubs_upserted, ports_upserted, drives_inserted, drives_updated, drives_removed).
