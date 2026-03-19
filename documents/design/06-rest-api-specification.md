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

- All endpoints except `/health` and `/auth/token` require a bearer token.
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

Each endpoint now includes **required roles**.

---

## 3.1 Mount Management

### `POST /mounts`

Add NFS/SMB mount.

**Roles:** `admin`, `manager`

### `DELETE /mounts/{id}`

Unmount and remove mount.

**Roles:** `admin`, `manager`

### `GET /mounts`

List all mounts.

**Roles:** `admin`, `manager`, `processor`, `auditor`

---

## 3.2 Drive Management

### `GET /drives`

List all drives with state and project assignment.

**Roles:** `admin`, `manager`, `processor`, `auditor`

### `POST /drives/{id}/initialize`

Initialize drive for a project.

Enforces project isolation.

**Roles:** `admin`, `manager`

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

---

## 3.2a Port Management

### `GET /admin/ports`

List all USB ports with their current enablement state.

**Roles:** `admin`, `manager`

**Response (200 OK):**

```json
[
    {
        "id": 1,
        "hub_id": 1,
        "port_number": 1,
        "system_path": "/sys/bus/usb/devices/1-1",
        "friendly_label": null,
        "enabled": false
    }
]
```

### `PATCH /admin/ports/{port_id}`

Enable or disable a USB port for ECUBE use. Disabled ports cause newly discovered or reconnecting drives to remain in `EMPTY` state instead of transitioning to `AVAILABLE`.

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
    "system_path": "/sys/bus/usb/devices/1-1",
    "friendly_label": null,
    "enabled": true
}
```

**Error responses:**

- `401 Unauthorized` — Missing/invalid token
- `403 Forbidden` — Insufficient role (processor, auditor)
- `404 Not Found` — Port ID does not exist

**Behavior:**

- The enablement change takes effect on the next discovery sync.
- Drives already in `IN_USE` state on a disabled port are **not** affected — project isolation takes priority.
- Drives with no associated port (`port_id = NULL`) are unaffected by the enablement filter.

**Audit events:**

- `PORT_ENABLED` — Port enabled; includes `port_id`, `system_path`, `hub_id`.
- `PORT_DISABLED` — Port disabled; includes `port_id`, `system_path`, `hub_id`.

---

## 3.3 Job Management

### `POST /jobs`

Create a new job.

**Roles:** `admin`, `manager`, `processor`

### `POST /jobs/{id}/start`

Start job with thread count.

**Roles:** `admin`, `manager`, `processor`

### `GET /jobs/{id}`

Return job status and progress.

**Roles:** `admin`, `manager`, `processor`, `auditor`

### `POST /jobs/{id}/verify`

Re-verify checksums.

**Roles:** `admin`, `manager`, `processor`

### `POST /jobs/{id}/manifest`

Regenerate manifest.

**Roles:** `admin`, `manager`, `processor`

---

## 3.4 Audit Log Access

### `GET /audit`

Return audit logs with filters.

**Roles:** `admin`, `manager`, `auditor`

---

## 3.5 File Audit Operations

### `GET /files/{file_id}/hashes`

Compute MD5/SHA‑256 for a file.

**Roles:** `admin`, `auditor`

### `POST /files/compare`

Compare two files by hash/size/path.

**Roles:** `admin`, `auditor`

---

## 3.6 User Role Management

All user role management endpoints require the `admin` role. These endpoints manage authorization (role assignments) only — they do not create or delete OS/LDAP user accounts.

### `GET /users`

List all users with their ECUBE role assignments.

**Roles:** `admin`

**Response (200 OK):**

```json
{
    "users": [
        { "username": "frank", "roles": ["admin"] },
        { "username": "alice", "roles": ["processor", "auditor"] }
    ]
}
```

### `GET /users/{username}/roles`

Get role assignments for a specific user.

**Roles:** `admin`

**Response (200 OK):**

```json
{
    "username": "alice",
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
    "username": "alice",
    "roles": ["auditor", "processor"]
}
```

**Error responses:**

- `422 Unprocessable Entity` — Invalid role name or empty list

**Valid roles:** `admin`, `manager`, `processor`, `auditor`

Duplicate roles in the request are deduplicated. Roles are returned sorted alphabetically.

**Audit events:**

- `ROLE_ASSIGNED` — Includes actor, target user, and new roles

### `DELETE /users/{username}/roles`

Remove all role assignments for a user. The user will fall back to OS group-based role resolution on next login.

**Roles:** `admin`

**Response (200 OK):**

```json
{
    "username": "alice",
    "roles": []
}
```

**Audit events:**

- `ROLE_REMOVED` — Includes actor and target user

---

## 3.7 OS User & Group Management API

All endpoints require `admin` role and are only available when `role_resolver = "local"` (returns `404` otherwise).

### `POST /admin/os-users`

Create an OS user, set password, and add to groups and optionally assign DB roles. At least one `ecube-*` group is required so the account remains manageable through the API.

**Roles:** `admin`

**Request body (JSON):**

```json
{
    "username": "alice",
    "password": "s3cret",
    "groups": ["ecube-processors"],
    "roles": ["processor"]
}
```

**Response (201 Created):** `OSUserResponse` with `username`, `uid`, `gid`, `home`, `shell`, `groups`.

**Error responses:**

- `409 Conflict` — User already exists
- `422 Unprocessable Entity` — Invalid username, empty password, reserved username, or no `ecube-*` group provided

**Audit events:** `OS_USER_CREATED`

### `GET /admin/os-users`

List OS users filtered to ECUBE-relevant groups.

**Roles:** `admin`

**Response (200 OK):** `OSUserListResponse` with array of `OSUserResponse`.

### `DELETE /admin/os-users/{username}`

Delete an OS user and remove their DB role assignments.

**Roles:** `admin`

**Error responses:**

- `404 Not Found` — User does not exist
- `422 Unprocessable Entity` — Invalid or reserved username, or user is not a member of any `ecube-*` group (see [ECUBE-managed user guard](#ecube-managed-user-guard))

**Audit events:** `OS_USER_DELETED`

### `PUT /admin/os-users/{username}/password`

Reset an OS user's password via `chpasswd`.

**Roles:** `admin`

**Request body:** `{"password": "newpass"}`

**Error responses:**

- `404 Not Found` — User does not exist
- `422 Unprocessable Entity` — Invalid/reserved username, empty password, or user is not ECUBE-managed (see [ECUBE-managed user guard](#ecube-managed-user-guard))

**Audit events:** `OS_PASSWORD_RESET` (password never appears in audit details)

### `PUT /admin/os-users/{username}/groups`

Replace an OS user's `ecube-*` supplementary group memberships. Only group names starting with the `ecube-` prefix are accepted; non-ECUBE supplementary groups are preserved automatically. At least one `ecube-*` group is required.

**Roles:** `admin`

**Request body:** `{"groups": ["ecube-admins", "ecube-processors"]}`

**Response (200 OK):** `OSUserResponse` with updated group list.

**Error responses:**

- `422 Unprocessable Entity` — Empty group list, non-`ecube-*` group name, or user is not ECUBE-managed (see [ECUBE-managed user guard](#ecube-managed-user-guard))

**Audit events:** `OS_USER_GROUPS_MODIFIED`

### `POST /admin/os-users/{username}/groups`

Add supplementary groups to an OS user without removing existing memberships.

**Roles:** `admin`

**Request body:** `{"groups": ["ecube-managers"]}`

**Response (200 OK):** `OSUserResponse` with updated group list.

**Error responses:**

- `422 Unprocessable Entity` — User is not ECUBE-managed (see [ECUBE-managed user guard](#ecube-managed-user-guard))

**Audit events:** `OS_USER_GROUPS_APPENDED`

### `POST /admin/os-groups`

Create an OS group. The group name **must** start with the `ecube-` prefix.

**Roles:** `admin`

**Request body:** `{"name": "ecube-custom"}`

**Response (201 Created):** `OSGroupResponse` with `name`, `gid`, `members`.

**Error responses:**

- `422 Unprocessable Entity` — Group name does not start with `ecube-`

**Audit events:** `OS_GROUP_CREATED`

### `GET /admin/os-groups`

List OS groups filtered to the `ecube-` prefix.

**Roles:** `admin`

### `DELETE /admin/os-groups/{name}`

Delete an OS group. The group name **must** start with the `ecube-` prefix.

**Roles:** `admin`

**Error responses:**

- `422 Unprocessable Entity` — Group name does not start with `ecube-`

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

## 3.9 Introspection API (Read‑Only)

### `GET /introspection/usb/topology`

USB hub/port/device mapping.

**Roles:** `admin`, `manager`, `processor`, `auditor`

### `GET /introspection/block-devices`

Block device metadata.

**Roles:** `admin`, `manager`, `processor`, `auditor`

### `GET /introspection/mounts`

Mounted filesystems.

**Roles:** `admin`, `manager`, `processor`, `auditor`

### `GET /introspection/system-health`

CPU, memory, disk I/O, worker queue.

**Roles:** `admin`, `manager`, `processor`, `auditor`

### `GET /introspection/jobs/{id}/debug`

Internal worker state.

**Roles:** `admin`, `manager`, `processor`, `auditor`

---

## 4. Error Handling for Security

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

### 4.3 Audit Logging

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
