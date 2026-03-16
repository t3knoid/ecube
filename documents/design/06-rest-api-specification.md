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
2. Reads the authenticated user's OS group memberships.
3. Maps groups to ECUBE roles using the configured role resolver.
4. Signs a JWT containing `sub`, `username`, `groups`, `roles`, `iat`, and `exp`.
5. Token expiration is configurable via `TOKEN_EXPIRE_MINUTES` (default: 60 minutes).

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
| Add/remove mounts | ✔ | ✔ | ✖ | ✖ |
| List mounts | ✔ | ✔ | ✔ | ✔ |
| Initialize drives | ✔ | ✔ | ✖ | ✖ |
| Prepare drives for eject | ✔ | ✔ | ✖ | ✖ |
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

## 3.6 Introspection API (Read‑Only)

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
- Role resolution
- Access denied events
- Drive initialization attempts
- File hash/compare operations
