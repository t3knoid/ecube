# 6. REST API Specification — Design

**OpenAPI Documentation:** This API specification is also available interactively via OpenAPI (Swagger) when the ECUBE API server is running:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI Schema (JSON):** `http://localhost:8000/openapi.json`

For the complete role model and policy context, see [10-security-and-access-control.md](10-security-and-access-control.md).

## 1. API Authentication

### 1.1 Identity Sources

ECUBE supports two identity modes:

- **Local mode (default)**
  - Uses Linux system users and groups (`/etc/passwd`, `/etc/group`).
  - Group membership determines ECUBE roles.

- **LDAP mode (optional)**
  - Uses LDAP bind for authentication.
  - LDAP group membership maps to ECUBE roles.

### 1.2 Authentication Mechanism

- API uses **token-based authentication** (JWT or signed session token).
- Token includes:
  - `username`
  - `roles` (resolved from local groups or LDAP groups)
  - `issued_at`
  - `expires_at`

### 1.3 User Context

Every request resolves to:

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

Prepare drive for safe eject: flush filesystem writes, unmount all partitions, and transition to AVAILABLE.

**Precondition:** Drive must be in `IN_USE` state (required for this operation to proceed).

Performs the following steps in sequence:
1. Validates drive is in `IN_USE` state at request start
2. Issues `sync(1)` to flush all pending filesystem writes to block devices
3. Identifies and unmounts all partitions and mount points for the device
4. Re-validates that drive state and device path have not changed (see race condition protection below)
5. On success: transitions drive from `IN_USE` → `AVAILABLE`, logs `DRIVE_EJECT_PREPARED`
6. On failure: drive remains `IN_USE`, logs `DRIVE_EJECT_FAILED` with error details

**Behavior:**
- Returns `200` with updated drive state on success
- Returns `409` Conflict if drive is not in `IN_USE` state (precondition violation)
- Returns `409` Conflict if drive state changed during operation (detected race condition; operation aborted)
- Returns `409` Conflict if device path changed during operation (e.g., via concurrent discovery refresh; operation aborted to avoid stale OS operations)
- Returns `500` if sync or unmount operations fail (drive state unchanged, stays `IN_USE`)
- If device is not mounted, returns `200` immediately (no-op is success)
- If device has multiple partitions mounted, unmounts all; returns `500` only if any unmount fails

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
