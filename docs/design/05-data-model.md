# 5. Data Model — Design

## Modeling Approach

- Use normalized relational tables for core entities.
- Keep mutable operational state explicit (`status`, timestamps, assignment fields).
- Store high-variability audit details as `JSONB`.

## Table Design Notes

### Hardware Domain

- `usb_hubs` and `usb_ports` define stable topology references.
  - `usb_hubs.vendor_id` (String, nullable) — USB vendor ID read from sysfs
    `idVendor` attribute during discovery (e.g. `"8086"` for Intel).
  - `usb_hubs.product_id` (String, nullable) — USB product ID read from sysfs
    `idProduct` attribute during discovery.
  - `usb_hubs.location_hint` (String, nullable) — Admin-assigned physical
    location label (e.g. `"back-left rack"`) managed via
    `PATCH /admin/hubs/{hub_id}`.
  - `usb_ports.vendor_id` (String, nullable) — USB vendor ID of the device
    currently plugged into this port, read from sysfs during discovery.
  - `usb_ports.product_id` (String, nullable) — USB product ID of the device
    currently plugged into this port, read from sysfs during discovery.
  - `usb_ports.speed` (String, nullable) — Negotiated link speed in Mbps
    (e.g. `"480"`, `"5000"`) read from the sysfs `speed` attribute during
    discovery.
  - `usb_ports.friendly_label` (String, nullable) — Admin-assigned label for
    the port, managed via `PATCH /admin/ports/{port_id}/label`.
  - `usb_ports.enabled` (Boolean, default `false`) — controls whether drives
    on this port are eligible to transition to `AVAILABLE` during discovery.
    Ports default to disabled; an admin or manager must explicitly enable a
    port via `PATCH /admin/ports/{port_id}` before its drives become available.
- `usb_drives` captures runtime device identity and current assignment/state.
  - `current_project_id` (nullable string) — set during initialization to
    bind the drive to a project for isolation enforcement. Remains `NULL`
    until the drive is initialized via `POST /drives/{id}/initialize`.
  - `current_state` — FSM column (`EMPTY`, `AVAILABLE`, `IN_USE`);
    transitions to `IN_USE` when `current_project_id` is bound.
- `usb_drives.filesystem_type` stores the detected filesystem label (e.g., `ext4`, `exfat`, `ntfs`, `fat32`, `unformatted`, `unknown`). Updated during discovery and after formatting operations. Nullable; `NULL` means detection has not yet been attempted.

### Mount Domain

- `network_mounts` tracks protocol type, remote path, local path, and health.
- Mount `status` can diverge from OS reality after an unclean shutdown (e.g. database says `MOUNTED` but the filesystem is no longer mounted). Startup reconciliation (§ 4.11) corrects this by verifying each `MOUNTED` row against the OS and transitioning stale entries to `UNMOUNTED` or `ERROR`.

### Job Domain

- `export_jobs` stores job-level lifecycle and throughput counters.
  - `callback_url` (nullable `String`) — optional HTTPS URL that receives a POST callback when the job reaches a terminal state (`COMPLETED` or `FAILED`). Added in migration `0011`. Only `https://` URLs are accepted; HTTP is rejected at schema validation (422).
- Jobs in `RUNNING` or `VERIFYING` state cannot survive a service restart (worker processes are ephemeral). Startup reconciliation (§ 4.11) transitions these to `FAILED` with `completed_at` set. Note: webhook callbacks are **not** issued for reconciliation-driven failures — only the `JOB_RECONCILED` audit event is emitted.
- `export_files` stores per-file status/checksum for retries and verification.
- `manifests` stores generated artifact pointers.
- `drive_assignments` preserves assignment history over time.

### Audit Domain

- `audit_logs` provides append-only operation history with actor and context.

### User & System Domain

- `user_roles` stores explicit username→role assignments managed through the admin API.
- `system_initialization` is a single-row table (constrained by `CHECK (id = 1)`) that records when and by whom the system was first initialized, providing a cross-process guard against concurrent initialization attempts.
- `reconciliation_lock` is a single-row table (constrained by `CHECK (id = 1)`) that prevents concurrent startup reconciliation across multiple Uvicorn workers.  The row records `locked_by` (worker PID) and `locked_at` (UTC timestamp for stale-lock detection).  Locks older than 5 minutes are automatically reclaimed.

## Integrity & Constraints

- Foreign keys enforce hub→port→drive and job→file relationships.
- `usb_hubs.system_identifier` and `usb_ports.system_path` carry **unique constraints**, ensuring each hub and port maps to exactly one row. The discovery upsert logic relies on these keys for stable identity across sync cycles.
- Enumerated statuses should be constrained by check/enum types.
- Index by `project_id`, `status`, and recent timestamps for UI queries.
