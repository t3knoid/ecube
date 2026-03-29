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

#### User/Group/Role Reconciliation Model

ECUBE separates authentication from authorization:

- **Authentication source:** host identity provider via PAM (local accounts, LDAP-backed PAM, etc.).
- **Authorization sources:**
  - `user_roles` table (explicit DB assignments)
  - OS group memberships mapped through configuration (`LOCAL_GROUP_ROLE_MAP`, `LDAP_GROUP_ROLE_MAP`, or OIDC group mapping when OIDC mode is used)

At login (`POST /auth/token`), role resolution follows strict precedence:

1. Resolve username via successful authentication.
2. Query `user_roles` for that username.
3. If one or more DB roles exist, **use DB roles only**.
4. If no DB roles exist, compute roles from mapped group memberships.
5. If still empty, issue token with no effective roles; guarded endpoints return `403`.

This makes `user_roles` the day-to-day control plane while preserving OS-group fallback for first-run and recovery operations.

#### Role Reconciliation Scenarios

| Scenario | `user_roles` rows | OS groups | Effective roles at login |
| --- | --- | --- | --- |
| Fresh system after setup | none for most users | `ecube-*` groups present | Mapped roles from OS groups |
| Admin override applied | one or more rows | any | DB roles (override group mapping) |
| DB roles removed | none | `ecube-*` groups present | Fallback mapped roles |
| No DB roles and no mapped groups | none | unmapped/none | Empty role set (authorization denied) |

#### Data Ownership and Lifecycle

- `user_roles` is intentionally lightweight and stores only `(username, role)` tuples; it does **not** store passwords, UID/GID, or group membership.
- OS user/group membership remains owned by the host OS (and local admin endpoints in local mode).
- ECUBE snapshots the resolved roles into JWT claims at login time; role/group changes require re-authentication to take effect.
- The unique constraint on (`username`, `role`) guarantees idempotent assignment semantics and prevents duplicate role rows.

## Integrity & Constraints

- Foreign keys enforce hub→port→drive and job→file relationships.
- `usb_hubs.system_identifier` and `usb_ports.system_path` carry **unique constraints**, ensuring each hub and port maps to exactly one row. The discovery upsert logic relies on these keys for stable identity across sync cycles.
- Enumerated statuses should be constrained by check/enum types.
- Index by `project_id`, `status`, and recent timestamps for UI queries.

## Physical Schema Reference (Current ORM)

This section documents the concrete table layout represented by the SQLAlchemy models.

### Hardware Tables

#### `usb_hubs`

- `id` (Integer, PK)
- `name` (String, required)
- `system_identifier` (String, required, unique)
- `location_hint` (String, nullable)
- `vendor_id` (String, nullable)
- `product_id` (String, nullable)

#### `usb_ports`

- `id` (Integer, PK)
- `hub_id` (Integer, FK → `usb_hubs.id`, required)
- `port_number` (Integer, required)
- `system_path` (String, required, unique)
- `friendly_label` (String, nullable)
- `enabled` (Boolean, required, default `false`)
- `vendor_id` (String, nullable)
- `product_id` (String, nullable)
- `speed` (String, nullable)

#### `usb_drives`

- `id` (Integer, PK)
- `port_id` (Integer, FK → `usb_ports.id`, nullable)
- `device_identifier` (String, required, unique)
- `filesystem_path` (String, nullable)
- `capacity_bytes` (BigInteger, nullable)
- `encryption_status` (String, nullable)
- `filesystem_type` (String, nullable)
- `current_state` (Enum `DriveState`, `native_enum=False`, default `AVAILABLE`)
- `current_project_id` (String, nullable)
- `last_seen_at` (DateTime with timezone, auto-updated on change)

### Mount Table

#### `network_mounts`

- `id` (Integer, PK)
- `type` (Enum `MountType`, required, `native_enum=False`)
- `remote_path` (String, required)
- `local_mount_point` (String, required, unique)
- `status` (Enum `MountStatus`, `native_enum=False`, default `UNMOUNTED`)
- `last_checked_at` (DateTime with timezone, default `now()`)

### Job Tables

#### `export_jobs`

- `id` (Integer, PK)
- `project_id` (String, required)
- `evidence_number` (String, required)
- `source_path` (String, required)
- `target_mount_path` (String, nullable)
- `status` (Enum `JobStatus`, `native_enum=False`, default `PENDING`)
- `total_bytes` (BigInteger, default `0`)
- `copied_bytes` (BigInteger, default `0`)
- `file_count` (Integer, default `0`)
- `thread_count` (Integer, default `4`)
- `max_file_retries` (Integer, default `3`)
- `retry_delay_seconds` (Integer, default `1`)
- `started_at` (DateTime with timezone, nullable)
- `completed_at` (DateTime with timezone, nullable)
- `created_by` (String, nullable)
- `started_by` (String, nullable)
- `client_ip` (String(45), nullable)
- `callback_url` (String, nullable)
- `created_at` (DateTime with timezone, default `now()`)

#### `export_files`

- `id` (Integer, PK)
- `job_id` (Integer, FK → `export_jobs.id`, required)
- `relative_path` (String, required)
- `size_bytes` (BigInteger, nullable)
- `checksum` (String, nullable)
- `status` (Enum `FileStatus`, `native_enum=False`, default `PENDING`)
- `error_message` (Text, nullable)
- `retry_attempts` (Integer, default `0`)

#### `manifests`

- `id` (Integer, PK)
- `job_id` (Integer, FK → `export_jobs.id`, required)
- `manifest_path` (String, nullable)
- `format` (String, default `JSON`)
- `created_at` (DateTime with timezone, default `now()`)

#### `drive_assignments`

- `id` (Integer, PK)
- `drive_id` (Integer, FK → `usb_drives.id`, required)
- `job_id` (Integer, FK → `export_jobs.id`, required)
- `assigned_at` (DateTime with timezone, default `now()`)
- `released_at` (DateTime with timezone, nullable)

### Audit Table

#### `audit_logs`

- `id` (Integer, PK)
- `timestamp` (DateTime with timezone, default `now()`)
- `user` (String, nullable actor identity)
- `action` (String, required)
- `job_id` (Integer, FK → `export_jobs.id`, nullable, `ON DELETE SET NULL`)
- `details` (JSON in ORM, PostgreSQL variant JSONB)
- `client_ip` (String(45), nullable)

### User/System Tables

#### `user_roles`

- `id` (Integer, PK)
- `username` (String, required, indexed)
- `role` (Enum `admin|manager|processor|auditor`, required, `native_enum=False`)

Unique constraint: (`username`, `role`) (`uq_user_role`).

#### `system_initialization`

- `id` (Integer, PK, fixed single-row ID)
- `initialized_by` (String, required)
- `initialized_at` (DateTime with timezone, required)

Check constraint: `id = 1` (`ck_single_initialization_row`).

#### `reconciliation_lock`

- `id` (Integer, PK, fixed single-row ID)
- `locked_by` (String, required)
- `locked_at` (DateTime with timezone, required)

Check constraint: `id = 1` (`ck_single_reconciliation_lock`).

## Relationship Map (ER-Style, Text)

```text
usb_hubs (1) --------< (N) usb_ports
usb_ports (1) -------< (N) usb_drives

usb_drives (1) ------< (N) drive_assignments >------ (N) export_jobs

export_jobs (1) -----< (N) export_files
export_jobs (1) -----< (N) manifests
export_jobs (1) -----< (N) audit_logs (job_id is nullable; ON DELETE SET NULL)

network_mounts (standalone)
user_roles (standalone; authorization mapping table)
system_initialization (single-row guard table)
reconciliation_lock (single-row guard table)
```

Notes:

- `drive_assignments` is the junction/history table between drives and jobs.
- `audit_logs` can exist without a job association (for non-job events).
- `user_roles` is not FK-linked to OS users because identities are PAM/IdP-backed, not DB-owned.
