# 6. REST API Specification — Design

**OpenAPI Documentation:** This API specification is also available interactively via OpenAPI (Swagger) when the ECUBE API server is running:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI Schema (JSON):** `http://localhost:8000/openapi.json`

For the complete role model and policy context, see [10-security-and-access-control.md](10-security-and-access-control.md).

## 1. API Authentication

### 1.1 Identity Sources

ECUBE supports three identity modes:

- **Local mode (default)**
  - Authenticates users via PAM (Pluggable Authentication Modules) on the host OS.
  - Reads OS group memberships and maps to ECUBE roles via `LOCAL_GROUP_ROLE_MAP`.

- **LDAP mode (optional)**
  - Authenticates users via PAM with an LDAP backend (SSSD, pam_ldap, etc.).
  - LDAP group membership maps to ECUBE roles via `LDAP_GROUP_ROLE_MAP`.

- **OIDC mode (optional)**
  - Accepts OIDC ID tokens (JWTs) issued by a third-party identity provider.
  - Validates token signature via JWKS; maps group claims to ECUBE roles.

### 1.2 Login Endpoint

#### `POST /auth/token`

Authenticate with OS credentials and receive a signed JWT.

**Roles:** None (unauthenticated — this is the login route)

**Request body (JSON):**

```json
{
    "username": "frank",
    "password": "secret"
}
```

**Response (200 OK):**

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
}
```

**Error responses:**

- `401 Unauthorized` — Invalid credentials
- `422 Unprocessable Entity` — Missing or empty username/password

**Behavior:**

1. Validates credentials against the host OS via PAM.
2. Checks the `user_roles` table for explicit role assignments for this user.
3. If DB roles exist, uses those. Otherwise, reads OS group memberships and maps groups to ECUBE roles using the configured role resolver (fallback).
4. Signs a JWT containing `sub`, `username`, `groups`, `roles`, `iat`, and `exp`.
5. Token expiration is configurable via `TOKEN_EXPIRE_MINUTES` (default: 60 minutes).

**Role resolution priority:**

1. `user_roles` table (DB) — explicit admin-managed assignments
2. OS group memberships + role resolver config — automatic fallback
3. No roles found — empty list — endpoints return 403

**Audit events:**

- `AUTH_SUCCESS` — Successful login; includes username, groups, roles
- `AUTH_FAILURE` — Failed login; includes username and reason

**Security notes:**

- Passwords are never logged or stored by ECUBE.
- The ECUBE service account must have PAM access on the host.
- For LDAP authentication, configure PAM on the host to use SSSD or pam_ldap.

### 1.3 Authentication Mechanism

- All endpoints except `/health`, `/auth/token`, `/setup/status`, `/setup/initialize`, and `/introspection/version` require a bearer token.
- `/setup/database/test-connection` and `/setup/database/provision` accept an **optional** bearer token: unauthenticated during initial setup (no admin exists), `admin` role required after.
- `/setup/database/test-connection`, `/setup/database/provision`, and `/setup/database/provision-status` accept an **optional** bearer token: unauthenticated during initial setup (no admin exists), `admin` role required after.
- `/setup/database/system-info` is always public — no bearer token is required or checked at any point.
- Token includes:
  - `sub` — user identifier (username)
  - `username` — display name
  - `groups` — OS group memberships
  - `roles` — ECUBE roles (resolved from groups)
  - `iat` — issued-at timestamp
  - `exp` — expiration timestamp

### 1.4 User Context

Every authenticated request resolves to:

```json
{
    "username": "frank",
    "roles": ["manager", "auditor"]
}
```

---

## 2. ECUBE Security Roles

### 2.1 Role Definitions

- **Administrator**
  - Full access to all ECUBE operations.
- **Manager**
  - Initialize drives.
  - Assign drives to projects.
  - Prepare drives for eject.
  - Manage mounts.
  - View jobs, drives, logs.
- **Processor**
  - Create jobs.
  - Start copy operations.
  - View job and drive status.
- **Auditor**
  - Read audit logs.
  - View job and file metadata.
  - Compute file hashes (MD5/SHA‑256).
  - Perform file comparisons.
  - No write operations.

### 2.2 Authorization Matrix

| API Area / Operation | Admin | Manager | Processor | Auditor |
| ---------------------- | :-----: | :-------: | :---------: | :-------: |
| Manage user roles | ✔ | ✖ | ✖ | ✖ |
| Manage OS users/groups (local only) | ✔ | ✖ | ✖ | ✖ |
| Add/remove mounts | ✔ | ✔ | ✖ | ✖ |
| List mounts | ✔ | ✔ | ✔ | ✔ |
| Initialize drives | ✔ | ✔ | ✖ | ✖ |
| Prepare drives for eject | ✔ | ✔ | ✖ | ✖ |
| Manage USB port enablement | ✔ | ✔ | ✖ | ✖ |
| List drives | ✔ | ✔ | ✔ | ✔ |
| Create jobs | ✔ | ✔ | ✔ | ✖ |
| Start copy jobs | ✔ | ✔ | ✔ | ✖ |
| View job status | ✔ | ✔ | ✔ | ✔ |
| Regenerate manifest | ✔ | ✔ | ✔ | ✖ |
| Verify job | ✔ | ✔ | ✔ | ✖ |
| Read audit logs | ✔ | ✔ | ✖ | ✔ |
| Introspection (read-only) | ✔ | ✔ | ✔ | ✔ |
| File hash/compare | ✔ | ✖ | ✖ | ✔ |

---

## 3. Updated REST API Endpoints with Security Requirements

Each endpoint now includes **required roles** and **error responses**.

### Standardized Error Response Format

All error responses use a uniform JSON payload:

```json
{
    "code": "CONFLICT",
    "message": "Drive is not in IN_USE state (current state: AVAILABLE)",
    "trace_id": "abc123"
}
```

| Field      | Type            | Description |
|------------|-----------------|-------------|
| `code`     | string          | Machine-readable error code (e.g. `CONFLICT`, `NOT_FOUND`, `UNAUTHORIZED`, `ENCODING_ERROR`) |
| `message`  | string          | Human-readable description of the error |
| `trace_id` | string          | Correlation ID for log tracing (always present; a UUID generated per error) |

The Pydantic schema for this payload is `ErrorResponse` in `app/schemas/errors.py`.

### Common Error Codes

All authenticated endpoints (except `/health`, `/auth/token`, `/setup/status`, `/setup/initialize`, and `/introspection/version`) return these error codes when applicable:

- `401 Unauthorized` — Missing, invalid, or expired authentication token
- `403 Forbidden` — Authenticated user lacks the required role
- `422 Unprocessable Entity` — Request body or query parameter validation error (Pydantic / FastAPI)

Additional error codes are documented per endpoint where applicable (e.g. `404`, `409`, `500`).

---

## 3.1 Mount Management

### `POST /mounts`

Add NFS/SMB mount.

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `DELETE /mounts/{id}`

Unmount and remove mount.

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Mount ID does not exist

### `GET /mounts`

List all mounts.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

---

## 3.2 Drive Management

### `GET /drives`

List all drives with state and project assignment.

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_id` | string | No | When provided, return only drives bound to this project. When omitted, return all drives. |

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `422 Unprocessable Entity` — Invalid query parameter (e.g. malformed Unicode)

### `POST /drives/{id}/initialize`

Initialize drive for a project.

Enforces project isolation.

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `422 Unprocessable Entity` — Invalid request body (e.g. malformed Unicode in project_id)

### `POST /drives/{id}/format`

Format a drive with a specified filesystem type.

**Precondition:** Drive must be in `AVAILABLE` state and not currently mounted.

**Body:** `{ "filesystem_type": "ext4" }`

**Supported types:** `ext4`, `exfat`

Performs the following steps:

1. Validates drive is in `AVAILABLE` state (rejects with `409` if not).
2. Validates `filesystem_type` is a supported value (rejects with `400` if not).
3. Verifies the drive is not mounted by checking `/proc/mounts` (rejects with `409` if mounted).
4. Validates the drive has a valid `filesystem_path` (rejects with `400` if missing).
5. Executes `mkfs.<type> <device_path>` to format the drive.
6. On success: updates `usb_drives.filesystem_type`, logs `DRIVE_FORMATTED`.
7. On failure: drive state unchanged, logs `DRIVE_FORMAT_FAILED` with error details.

**Behavior:**

- Returns `200` with the updated drive record on success.
- Returns `400` if the filesystem type is unsupported or the device path is missing.
- Returns `409` Conflict if the drive is not in `AVAILABLE` state or is currently mounted.
- Returns `500` if the `mkfs` command fails.

**Security:**

- Device path is validated against the same allowlist pattern used by unmount operations.
- Format commands use absolute binary paths from configuration to prevent PATH manipulation.
- Commands execute with bounded subprocess timeouts.

**Audit events:**

- `DRIVE_FORMATTED`: Drive successfully formatted; includes `drive_id`, `filesystem_path`, `filesystem_type`.
- `DRIVE_FORMAT_FAILED`: Format operation failed; includes `drive_id`, `filesystem_path`, `filesystem_type`, `error`.

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `409 Conflict` — Drive not in `AVAILABLE` state or currently mounted
- `500 Internal Server Error` — Format command (`mkfs`) failed

### `POST /drives/{id}/prepare-eject`

Prepare drive for safe eject: flush filesystem writes, unmount all partitions and encrypted volumes, and transition to AVAILABLE.

**Precondition:** Drive must be in `IN_USE` state (required for this operation to proceed).

Performs the following steps in sequence:

1. **Fast-fail validation:** Checks that drive is in `IN_USE` state before performing expensive OS operations
2. Issues `sync(1)` to flush all pending filesystem writes to block devices
3. Identifies and unmounts all partitions, volumes, and encrypted devices:
   - Discovers mount points via `/proc/mounts` parsing
   - Supports traditional partition naming: `sdb`, `sdb1`, `sdb2` (etc.)
   - Supports NVMe naming: `nvme0n1`, `nvme0n1p1`, `nvme0n1p2` (etc.)
   - Supports MMC naming: `mmcblk0`, `mmcblk0p1`, `mmcblk0p2` (etc.)
   - **Encrypted volume support:** Discovers and unmounts LUKS (`/dev/mapper/*`) and LVM (`/dev/dm-*`) volumes by:
     - Resolving symlinks to actual device nodes via `os.path.realpath()`
     - Tracing parent block device via `/sys/block/dm-N/slaves/` sysfs interface
     - Validating encrypted volume is backed by the target device before including in unmount list
   - **Safe unmount ordering:** Unmounts nested mount points in reverse depth order (deepest first) to prevent "umount: target is busy" errors when multiple levels of mounts exist
   - **Path normalization:** Resolves device path symlinks (e.g., `/dev/disk/by-id/*` references)
   - **Escape sequence handling:** Decodes POSIX escape sequences in mount points (e.g., `\040` for space, `\011` for tab) so actual paths are passed to `umount`
4. Re-validates that drive state and device path have not changed (see race condition protection below)
5. On success: transitions drive from `IN_USE` → `AVAILABLE`, logs `DRIVE_EJECT_PREPARED`
6. On failure: drive remains `IN_USE`, logs `DRIVE_EJECT_FAILED` with error details

**Behavior:**

- Returns `200` with updated drive state on success
- Returns `409` Conflict if drive is not in `IN_USE` state (precondition violation); error message includes current state value (e.g., `current state: AVAILABLE`)
- Returns `409` Conflict if drive state changed during operation (detected race condition; operation aborted); error message includes initial and final state values
- Returns `409` Conflict if device path changed during operation (e.g., via concurrent discovery refresh; operation aborted to avoid stale OS operations)
- Returns `500` if sync or unmount operations fail (drive state unchanged, stays `IN_USE`)
- If device is not mounted, returns `200` immediately (no-op is success)
- If device has multiple partitions or encrypted volumes mounted, unmounts all; returns `500` only if any unmount fails

**Race Condition Protection:**
The endpoint captures the drive state and device path at the start, performs potentially slow OS operations without holding the database lock (to avoid contention), then re-acquires the lock to validate preconditions before committing the state transition. If another request or discovery process changes the drive's state or device path, this operation fails with 409 Conflict, ensuring audit consistency and preventing operations against stale or unintended device paths.

**Audit events:**

- `DRIVE_EJECT_PREPARED`: Drive successfully prepared for eject; includes `drive_id`, `filesystem_path`, `flush_ok`, `unmount_ok`
- `DRIVE_EJECT_FAILED`: Sync or unmount failed; includes `drive_id`, `filesystem_path`, `flush_ok`, `flush_error`, `unmount_ok`, `unmount_error`

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `409 Conflict` — Drive not in `IN_USE` state, or state/device path changed during operation
- `500 Internal Server Error` — Sync or unmount operations failed

---

## 3.2a Port Management

### `GET /admin/ports`

List all USB ports with their current enablement state and hardware metadata.

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

**Response (200 OK):**

```json
[
    {
        "id": 1,
        "hub_id": 1,
        "port_number": 1,
        "system_path": "1-1",
        "friendly_label": null,
        "enabled": false,
        "vendor_id": "0781",
        "product_id": "5583",
        "speed": "480"
    }
]
```

### `PATCH /admin/ports/{port_id}`

Enable or disable a USB port for ECUBE use. Disabled ports cause newly discovered or reconnecting drives to remain in `EMPTY` state instead of transitioning to `AVAILABLE`. Drives already in `AVAILABLE` state on a disabled port are demoted to `EMPTY` on the next discovery sync.

**Roles:** `admin`, `manager`

**Request body (JSON):**

```json
{
    "enabled": true
}
```

**Response (200 OK):**

```json
{
    "id": 1,
    "hub_id": 1,
    "port_number": 1,
    "system_path": "1-1",
    "friendly_label": null,
    "enabled": true,
    "vendor_id": "0781",
    "product_id": "5583",
    "speed": "480"
}
```

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (processor, auditor)
- `404 Not Found` — Port ID does not exist

**Behavior:**

- The enablement change takes effect on the next discovery sync.
- Drives already in `IN_USE` state on a disabled port are **not** affected — project isolation takes priority.
- Drives with no associated port (`port_id = NULL`) are treated as disabled — they remain in `EMPTY` state.

**Audit events:**

- `PORT_ENABLED` — Port enabled; includes `port_id`, `system_path`, `hub_id`, `enabled`, `path`.
- `PORT_DISABLED` — Port disabled; includes `port_id`, `system_path`, `hub_id`, `enabled`, `path`.

### `PATCH /admin/ports/{port_id}/label`

Set or update the human-readable `friendly_label` on a USB port.

**Roles:** `admin`, `manager`

**Request body (JSON):**

```json
{
    "friendly_label": "Bay 3 – Top Left"
}
```

**Response (200 OK):**

Returns the updated port object (same schema as `GET /admin/ports` elements).

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Port ID does not exist

**Audit events:**

- `PORT_LABEL_UPDATED` — Includes `port_id`, `system_path`, `field`, `old_value`, `new_value`, `path`.

---

## 3.2b Hub Management

### `GET /admin/hubs`

List all USB hubs with enriched hardware metadata and admin-assigned labels.

**Roles:** `admin`, `manager`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

**Response (200 OK):**

```json
[
    {
        "id": 1,
        "name": "usb1",
        "system_identifier": "usb1",
        "location_hint": "back-left rack",
        "vendor_id": "1d6b",
        "product_id": "0002"
    }
]
```

### `PATCH /admin/hubs/{hub_id}`

Set or update the `location_hint` label on a USB hub.

**Roles:** `admin`, `manager`

**Request body (JSON):**

```json
{
    "location_hint": "back-left rack"
}
```

**Response (200 OK):**

Returns the updated hub object (same schema as `GET /admin/hubs` elements).

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Hub ID does not exist

**Audit events:**

- `HUB_LABEL_UPDATED` — Includes `hub_id`, `system_identifier`, `field`, `old_value`, `new_value`, `path`.

---

## 3.3 Job Management

All job endpoints that return a single job use the `ExportJobSchema` response, which includes timestamps, user attribution, file counts, an optional nested drive object, and an error summary.

#### `ExportJobSchema` response fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique job identifier |
| `project_id` | string | Project ID for audit and isolation |
| `evidence_number` | string | Evidence case number |
| `source_path` | string | Source path of evidence data |
| `target_mount_path` | string or null | Target mount path for copied data |
| `status` | string | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `VERIFYING` |
| `total_bytes` | integer | Total bytes to copy |
| `copied_bytes` | integer | Bytes copied so far |
| `file_count` | integer | Total number of files to copy |
| `files_succeeded` | integer | Number of files successfully copied (status `DONE`) |
| `files_failed` | integer | Number of files that failed (status `ERROR`) |
| `thread_count` | integer | Number of parallel threads used (1–8) |
| `max_file_retries` | integer | Maximum retries per failed file |
| `retry_delay_seconds` | integer | Delay between retries in seconds |
| `created_by` | string or null | Username of the job creator |
| `started_by` | string or null | Username of the user who started the job |
| `created_at` | datetime or null | When the job was created |
| `started_at` | datetime or null | When the copy was started |
| `completed_at` | datetime or null | When the job reached a terminal state. Reset to `null` if the job is restarted from `FAILED` |
| `drive` | object or null | Nested `DriveInfoSchema` for the assigned drive (see below) |
| `error_summary` | string or null | Brief summary of file failures; `null` when no files failed. Returns count-only fallback (e.g. "2 files failed") when errors lack messages |
| `callback_url` | string or null | HTTPS callback URL (null if none was provided) |
| `client_ip` | string or null | Client IP (redacted for non-admin/auditor roles) |

#### Nested `DriveInfoSchema`

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique drive identifier |
| `device_identifier` | string | Stable hardware identifier |
| `filesystem_path` | string or null | OS block device node (e.g. `/dev/sdb`) |
| `capacity_bytes` | integer or null | Total storage capacity in bytes |
| `filesystem_type` | string or null | Detected filesystem label |
| `current_state` | string | `EMPTY`, `AVAILABLE`, `IN_USE` |
| `current_project_id` | string or null | Bound project ID |

#### Example response (completed job)

```json
{
  "id": 1,
  "project_id": "PROJECT-42",
  "evidence_number": "EV-2026-001",
  "source_path": "/mnt/evidence/case-001",
  "target_mount_path": "/media/usb0",
  "status": "COMPLETED",
  "total_bytes": 5368709120,
  "copied_bytes": 5368709120,
  "file_count": 342,
  "files_succeeded": 342,
  "files_failed": 0,
  "thread_count": 4,
  "max_file_retries": 3,
  "retry_delay_seconds": 1,
  "created_by": "ecube-admin",
  "started_by": "ecube-admin",
  "created_at": "2026-03-18T14:00:00Z",
  "started_at": "2026-03-18T14:01:00Z",
  "completed_at": "2026-03-18T14:45:00Z",
  "drive": {
    "id": 3,
    "device_identifier": "usb-Generic_Flash_Disk_12345-0:0",
    "filesystem_path": "/dev/sdb1",
    "capacity_bytes": 64023257088,
    "filesystem_type": "exfat",
    "current_state": "IN_USE",
    "current_project_id": "PROJECT-42"
  },
  "error_summary": null,
  "callback_url": null,
  "client_ip": "192.168.1.50"
}
```

### `POST /jobs`

Create a new job.

**Roles:** `admin`, `manager`, `processor`

**Optional fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `callback_url` | string or null | `null` | HTTPS URL to receive a POST callback on job completion or failure. HTTP URLs are rejected (422). See [§ 4.8 Webhook Callback Delivery](04-functional-requirements.md#48-webhook-callback-delivery) for payload format, retry policy, and SSRF protection. |

**Error responses:**

- `401 Unauthorized` — Missing/invalid credentials
- `403 Forbidden` — Insufficient role or project isolation violation
- `404 Not Found` — Drive not found
- `409 Conflict` — Drive already in use
- `422 Validation Error` — Invalid request body (includes non-HTTPS `callback_url`)
- `500 Internal Server Error` — Database error

### `POST /jobs/{id}/start`

Start job with thread count. Sets `started_by` to the authenticated user and `started_at` to the current timestamp. Resets `completed_at` to `null`. Accepts jobs in `PENDING` or `FAILED` status (allowing restart of failed jobs).

**Roles:** `admin`, `manager`, `processor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid credentials
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Job not found
- `409 Conflict` — Job cannot be started from its current status
- `422 Validation Error` — Invalid path/body parameters
- `500 Internal Server Error` — Database error

### `GET /jobs/{id}`

Return job status, progress, file counts, timestamps, drive info, and error summary.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid credentials
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Job not found
- `422 Validation Error` — Invalid path parameter

### `POST /jobs/{id}/verify`

Re-verify checksums.

**Roles:** `admin`, `manager`, `processor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid credentials
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Job not found
- `422 Validation Error` — Invalid path parameter
- `500 Internal Server Error` — Database error

### `POST /jobs/{id}/manifest`

Regenerate manifest.

**Roles:** `admin`, `manager`, `processor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid credentials
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Job not found
- `422 Validation Error` — Invalid path parameter
- `500 Internal Server Error` — Database error

---

## 3.4 Audit Log Access

### `GET /audit`

Return audit logs with filters.

**Roles:** `admin`, `manager`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

---

## 3.5 File Audit Operations

### `GET /files/{file_id}/hashes`

Compute MD5/SHA‑256 for a file.

**Roles:** `admin`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `POST /files/compare`

Compare two files by hash/size/path.

**Roles:** `admin`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

---

## 3.6 User Role Management

All user role management endpoints require the `admin` role. These endpoints manage authorization (role assignments) only — they do not create or delete OS/LDAP user accounts.

The `{username}` path parameter must match the POSIX username pattern: `^[a-z_][a-z0-9_-]{0,31}$` (lowercase letter or underscore start, 1–32 characters, lowercase alphanumeric/hyphen/underscore only). Requests with non-matching values are rejected with `422 Unprocessable Entity`.

### `GET /users`

List all users with their ECUBE role assignments.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)

**Response (200 OK):**

```json
{
    "users": [
        { "username": "frank", "roles": ["admin"] },
        { "username": "griffin", "roles": ["processor", "auditor"] }
    ]
}
```

### `GET /users/{username}/roles`

Get role assignments for a specific user.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `422 Unprocessable Entity` — Invalid username

**Response (200 OK):**

```json
{
    "username": "griffin",
    "roles": ["processor", "auditor"]
}
```

Returns an empty `roles` list if the user has no DB-managed role assignments (OS group fallback still applies at login time).

### `PUT /users/{username}/roles`

Set roles for a user. Replaces all existing role assignments.

**Roles:** `admin`

**Request body (JSON):**

```json
{
    "roles": ["processor", "auditor"]
}
```

**Response (200 OK):**

```json
{
    "username": "griffin",
    "roles": ["auditor", "processor"]
}
```

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `422 Unprocessable Entity` — Invalid role name or empty list
- `500 Internal Server Error` — Database error during role update

**Valid roles:** `admin`, `manager`, `processor`, `auditor`

Duplicate roles in the request are deduplicated. Roles are returned sorted alphabetically.

**Audit events:**

- `ROLE_ASSIGNED` — Includes actor, target user, and new roles

### `DELETE /users/{username}/roles`

Remove all role assignments for a user. The user will fall back to OS group-based role resolution on next login.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `422 Unprocessable Entity` — Invalid username
- `500 Internal Server Error` — Database error during role removal

**Response (200 OK):**

```json
{
    "username": "griffin",
    "roles": []
}
```

**Audit events:**

- `ROLE_REMOVED` — Includes actor and target user

---

## 3.7 OS User & Group Management API

All endpoints require `admin` role and are only available when `role_resolver = "local"` (returns `404` otherwise).

Path parameter constraints:

- `{username}` must match the POSIX username pattern: `^[a-z_][a-z0-9_-]{0,31}$`
- `{name}` (group name) must match the same pattern: `^[a-z_][a-z0-9_-]{0,31}$`

Requests with non-matching values are rejected with `422 Unprocessable Entity` at the framework level (before reaching service logic). These patterns are declared in the OpenAPI schema.

### `POST /admin/os-users`

Create an OS user, set password, and add to groups and optionally assign DB roles. At least one `ecube-*` group is required so the account remains manageable through the API.

**Roles:** `admin`

**Request body (JSON):**

```json
{
    "username": "griffin",
    "password": "s3cret",
    "groups": ["ecube-processors"],
    "roles": ["processor"]
}
```

**Response (201 Created):** `OSUserResponse` with `username`, `uid`, `gid`, `home`, `shell`, `groups`.

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `409 Conflict` — User already exists
- `422 Unprocessable Entity` — Invalid username, empty password, reserved username, or no `ecube-*` group provided
- `500 Internal Server Error` — OS command failed
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_USER_CREATED`

### `GET /admin/os-users`

List OS users filtered to ECUBE-relevant groups.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)

**Response (200 OK):** `OSUserListResponse` with array of `OSUserResponse`.

### `DELETE /admin/os-users/{username}`

Delete an OS user and remove their DB role assignments.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `404 Not Found` — User does not exist
- `422 Unprocessable Entity` — Invalid or reserved username, or user is not a member of any `ecube-*` group (see [ECUBE-managed user guard](#ecube-managed-user-guard))
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_USER_DELETED`

### `PUT /admin/os-users/{username}/password`

Reset an OS user's password via `chpasswd`.

**Roles:** `admin`

**Request body:** `{"password": "newpass"}`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `404 Not Found` — User does not exist
- `422 Unprocessable Entity` — Invalid/reserved username, empty password, or user is not ECUBE-managed (see [ECUBE-managed user guard](#ecube-managed-user-guard))
- `500 Internal Server Error` — Password change command failed
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_PASSWORD_RESET` (password never appears in audit details)

### `PUT /admin/os-users/{username}/groups`

Replace an OS user's `ecube-*` supplementary group memberships. Only group names starting with the `ecube-` prefix are accepted; non-ECUBE supplementary groups are preserved automatically. At least one `ecube-*` group is required.

**Roles:** `admin`

**Request body:** `{"groups": ["ecube-admins", "ecube-processors"]}`

**Response (200 OK):** `OSUserResponse` with updated group list.

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `404 Not Found` — User does not exist
- `422 Unprocessable Entity` — Empty group list, non-`ecube-*` group name, or user is not ECUBE-managed (see [ECUBE-managed user guard](#ecube-managed-user-guard))
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_USER_GROUPS_MODIFIED`

### `POST /admin/os-users/{username}/groups`

Add supplementary groups to an OS user without removing existing memberships.

**Roles:** `admin`

**Request body:** `{"groups": ["ecube-managers"]}`

**Response (200 OK):** `OSUserResponse` with updated group list.

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `404 Not Found` — User does not exist
- `422 Unprocessable Entity` — User is not ECUBE-managed (see [ECUBE-managed user guard](#ecube-managed-user-guard))
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_USER_GROUPS_APPENDED`

### `POST /admin/os-groups`

Create an OS group. The group name **must** start with the `ecube-` prefix.

**Roles:** `admin`

**Request body:** `{"name": "ecube-custom"}`

**Response (201 Created):** `OSGroupResponse` with `name`, `gid`, `members`.

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `409 Conflict` — Group already exists
- `422 Unprocessable Entity` — Group name does not start with `ecube-`
- `500 Internal Server Error` — OS command failed
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_GROUP_CREATED`

### `GET /admin/os-groups`

List OS groups filtered to the `ecube-` prefix.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)

### `DELETE /admin/os-groups/{name}`

Delete an OS group. The group name **must** start with the `ecube-` prefix.

**Roles:** `admin`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (non-admin)
- `404 Not Found` — Group does not exist
- `422 Unprocessable Entity` — Group name does not start with `ecube-`
- `500 Internal Server Error` — OS command failed
- `504 Gateway Timeout` — OS command timed out

**Audit events:** `OS_GROUP_DELETED`

### ECUBE-Managed User Guard

Mutative user operations (`DELETE`, `PUT /password`, `PUT /groups`, `POST /groups`) enforce that the target user is **ECUBE-managed** before proceeding. A user is considered ECUBE-managed if they belong to at least one OS group whose name starts with `ecube-`. This prevents accidental modification or deletion of host system accounts (e.g., `postgres`, `www-data`). Reserved system usernames (`root`, `nobody`, `daemon`, etc.) are also rejected regardless of group membership.

Operations that fail this check return `422 Unprocessable Entity` with a descriptive message. The check is bypassed for internal compensation paths (e.g., setup recovery) where the user may not yet be in an `ecube-*` group.

---

## 3.8 First-Run Setup API

These endpoints are **unauthenticated** and guarded by a first-run check.

### `GET /setup/status`

Check whether the system has been initialized.

**Authentication:** None required.

**Response (200 OK):**

```json
{"initialized": false}
```

### `POST /setup/initialize`

Perform first-run system initialization: create OS groups, create admin user, set password, seed DB role, and mark system as initialized.

**Authentication:** None required. Can only succeed once.

**Request body:**

```json
{
    "username": "ecube-admin",
    "password": "s3cret"
}
```

**Response (200 OK):** `SetupInitializeResponse` with `message`, `username`, `groups_created`.

**Error responses:**

- `409 Conflict` — System already initialized, or initialization is in progress by another worker. If a previous attempt failed and left the lock row stuck, the response detail includes manual remediation steps.
- `422 Unprocessable Entity` — Invalid username, empty password, or password containing unsafe characters (newlines, colons)
- `500 Internal Server Error` — OS group/user creation or DB role seeding failed. The response detail describes what succeeded, what failed, and whether the initialization lock was released for a safe retry. See the Operational Guide troubleshooting section for resolution steps.

**Cross-process guard:** Uses a `system_initialization` single-row table with a uniqueness constraint to ensure only one worker can complete initialization, even in multi-worker deployments.

**Audit events:** `SYSTEM_INITIALIZED`

### 3.8.1 Database Provisioning API

These endpoints support the setup wizard's database configuration step.  They live under `/setup/database/`.

| Endpoint | Auth |
|----------|------|
| `POST /setup/database/test-connection` | Optional bearer token (open during setup, admin required after) |
| `POST /setup/database/provision` | Optional bearer token (open during setup, admin required after) |
| `GET /setup/database/provision-status` | Optional bearer token (open during setup, admin required after) |
| `GET /setup/database/system-info` | Always public |
| `GET /setup/database/status` | `admin` role required |
| `PUT /setup/database/settings` | `admin` role required |

#### `POST /setup/database/test-connection`

Test connectivity to a PostgreSQL server.

**Authentication:** Unauthenticated during initial setup (no admin exists); `admin` role required after.  **Fail-closed:** if the database is unreachable and no valid admin JWT is provided, returns `503`.

**Request body:**

```json
{
    "host": "localhost",
    "port": 5432,
    "admin_username": "postgres",
    "admin_password": "secret"
}
```

**Validation:**

- `host` must be a valid hostname or IPv4 address (SSRF-safe — no URLs, schemes, or paths).
- `port` must be 1–65535.

**Response (200 OK):**

```json
{"status": "ok", "server_version": "16.2"}
```

**Error responses:**

- `400 Bad Request` — Connection failed (timeout, auth error, host unreachable)
- `401 Unauthorized` — Missing token (after setup)
- `403 Forbidden` — Non-admin role (after setup)
- `422 Unprocessable Entity` — Invalid host or port
- `503 Service Unavailable` — Database unreachable and no valid admin JWT provided (fail-closed)

**Audit events:** `DATABASE_CONNECTION_TEST` (best-effort; may not persist if the database doesn't exist yet)

#### `POST /setup/database/provision`

Create the application database user, database, and run Alembic migrations.

**Authentication:** Unauthenticated during initial setup; `admin` role required after.  **Fail-closed:** if the database is unreachable and no valid admin JWT is provided, returns `503`.

**Request body:**

```json
{
    "host": "localhost",
    "port": 5432,
    "admin_username": "postgres",
    "admin_password": "secret",
    "app_database": "ecube",
    "app_username": "ecube",
    "app_password": "app-secret"
}
```

**Validation:**

- `host`: same as test-connection.
- `app_database`, `app_username`: valid PostgreSQL identifiers (letters, digits, underscores; max 63 chars).

**Response (200 OK):**

```json
{
    "status": "provisioned",
    "database": "ecube",
    "user": "ecube",
    "migrations_applied": 4
}
```

**Side effects:** Writes `DATABASE_URL` to `.env`, reinitializes the database engine and in-memory settings.

**Error responses:**

- `400 Bad Request` — Connection to PostgreSQL failed
- `401 Unauthorized` — Missing token (after setup)
- `403 Forbidden` — Non-admin role (after setup)
- `409 Conflict` — Database already provisioned (use `"force": true` to override)
- `500 Internal Server Error` — Provisioning or migration failed
- `422 Unprocessable Entity` — Invalid identifiers
- `503 Service Unavailable` — Database unreachable and no valid admin JWT provided (fail-closed)

**Audit events:** `DATABASE_PROVISIONED`

#### `GET /setup/database/status`
#### `GET /setup/database/provision-status`

Report whether the application database has already been provisioned.

**Authentication:** Unauthenticated during initial setup (no admin exists); `admin` role required after.  **Fail-closed:** if the database is unreachable and no valid admin JWT is provided, returns `503`.

**Response (200 OK):**

```json
{"provisioned": true}
```

**Error responses:**

- `401 Unauthorized` — Missing token (after setup)
- `403 Forbidden` — Non-admin role (after setup)
- `503 Service Unavailable` — Database unreachable and no valid admin JWT provided (fail-closed)

**Use:** The setup wizard calls this on load to disable the Provision button when the database is already provisioned, preventing accidental re-provisioning.

#### `GET /setup/database/system-info`

Return runtime environment hints for the setup wizard.

**Authentication:** Always public — no credentials required at any point.

**Response (200 OK):**

```json
{"in_docker": true, "suggested_db_host": "postgres"}
```

| Field | Type | Description |
|-------|------|-------------|
| `in_docker` | `boolean` | Whether the server process is running inside a Docker container |
| `suggested_db_host` | `string` | Recommended PostgreSQL hostname to pre-fill in the setup wizard (`"postgres"` in Docker, `"localhost"` otherwise; overridable via `SETUP_DOCKER_DB_HOST`) |

**Use:** The setup wizard fetches this on load to pre-fill the database host field.  When `in_docker` is `true`, a contextual hint is displayed below the host input reminding the operator to use the Docker Compose service name.

#### `GET /setup/database/status`

Report the current database connection health and migration state.

**Authentication:** `admin` role required.

**Response (200 OK):**

```json
{
    "connected": true,
    "database": "ecube",
    "host": "localhost",
    "port": 5432,
    "current_migration": "0004_system_initialization",
    "pending_migrations": 0
}
```

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Non-admin role

#### `PUT /setup/database/settings`

Partially update database connection settings.  All fields are optional — only supplied fields are changed.

**Authentication:** `admin` role required.

**Request body (all fields optional):**

```json
{
    "host": "db.example.com",
    "port": 5432,
    "app_database": "ecube",
    "app_username": "ecube",
    "app_password": "new-password",
    "pool_size": 10,
    "pool_max_overflow": 20
}
```

**Validation:**

- `pool_size`: 1–100
- `pool_max_overflow`: 0–200

**Response (200 OK):**

```json
{
    "status": "updated",
    "host": "db.example.com",
    "port": 5432,
    "database": "ecube",
    "connected": true
}
```

**Side effects:** Tests the new settings before committing, writes `.env`, reinitializes the connection pool, and updates in-memory settings.

**Error responses:**

- `400 Bad Request` — New settings fail connection test
- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Non-admin role
- `422 Unprocessable Entity` — Invalid field values or empty body

**Audit events:** `DATABASE_SETTINGS_UPDATED`

**Security notes:**

- Passwords are redacted from all responses and audit log metadata.
- The `admin_password` (for test-connection and provision) is transient — used only for the PostgreSQL operation and never persisted.

---

## 3.8a Startup Behavior

ECUBE performs **startup state reconciliation** during application startup (inside the FastAPI lifespan context manager), before the server begins accepting HTTP requests. A cross-process `reconciliation_lock` guard table ensures only one worker runs reconciliation in multi-worker deployments. This reconciliation:

- Verifies all `MOUNTED` network mounts against the OS and corrects stale entries (audit action: `MOUNT_RECONCILED`).
- Fails any `RUNNING` or `VERIFYING` export jobs that lost their worker process (audit action: `JOB_RECONCILED`). Webhook callbacks are **not** issued for these reconciliation-driven failures.
- Re-runs USB discovery to sync physical device presence with the database.

API clients should be aware that after a service restart, previously `RUNNING` jobs may appear as `FAILED` and previously `MOUNTED` mounts may appear as `UNMOUNTED` or `ERROR`. The audit log contains the corresponding `MOUNT_RECONCILED` and `JOB_RECONCILED` records explaining the transitions.

See [§ 4.11 Startup State Reconciliation](04-functional-requirements.md#411-startup-state-reconciliation) for the full specification.

---

## 3.9 Introspection API (Read‑Only)

All introspection endpoints are read-only. Authenticated endpoints return `401`/`403` for authentication/authorization failures; `/introspection/version` is unauthenticated and therefore does not return `401`/`403`.

### `GET /introspection/drives`

Drive summary for UI display.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `GET /introspection/usb/topology`

USB hub/port/device mapping.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `GET /introspection/block-devices`

Block device metadata.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `GET /introspection/mounts`

Mounted filesystems.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `GET /introspection/system-health`

CPU, memory, disk I/O, worker queue.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role

### `GET /introspection/jobs/{id}/debug`

Internal worker state.

**Roles:** `admin`, `manager`, `processor`, `auditor`

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role
- `404 Not Found` — Job ID does not exist

---

## 4. Error Handling for Security

All error responses use the standardized `ErrorResponse` JSON format described in [Section 3](#standardized-error-response-format). Every endpoint declares its possible error responses in the OpenAPI schema via `responses=` on the route decorator, sourced from reusable declarations in `app/schemas/errors.py`.

### 4.1 Unauthorized (401)

Returned when:

- Token missing
- Token invalid
- Token expired

### 4.2 Forbidden (403)

Returned when:

- User lacks required role
- User attempts cross‑project access
- User attempts restricted operation (for example, processor initializing drive)

### 4.3 Not Found (404)

Returned when:

- Referenced resource (drive, mount, job, user, port, hub) does not exist

### 4.4 Conflict (409)

Returned when:

- Resource already exists (duplicate initialization, provisioning)
- Operation conflicts with current state (e.g. drive not in expected state)
- Concurrent operation detected (initialization lock, race condition)

### 4.5 Validation Error (422)

Returned when:

- Request body or query parameter fails Pydantic validation
- Malformed Unicode (null bytes, surrogate characters) in path fields
- Invalid enum values, out-of-range numbers, or empty required fields

### 4.6 Server Error (500) / Timeout (504)

Returned when:

- OS-level commands fail (format, mount, user/group management)
- Database operations fail unexpectedly
- Subprocess execution exceeds timeout bounds

### 4.7 Audit Logging

Every security‑relevant event is logged:

- Authentication success/failure
- Role assignment/removal (`ROLE_ASSIGNED`, `ROLE_REMOVED`)
- Role resolution
- Access denied events
- Drive initialization attempts
- File hash/compare operations
- OS user/group management (`OS_USER_CREATED`, `OS_USER_DELETED`, `OS_PASSWORD_RESET`, `OS_USER_GROUPS_MODIFIED`, `OS_USER_GROUPS_APPENDED`, `OS_GROUP_CREATED`, `OS_GROUP_DELETED`)
- Port enablement changes (`PORT_ENABLED`, `PORT_DISABLED`)
- System initialization (`SYSTEM_INITIALIZED`)
- Webhook callback delivery (`CALLBACK_SENT`, `CALLBACK_DELIVERY_FAILED`, `CALLBACK_DELIVERY_DROPPED`)
