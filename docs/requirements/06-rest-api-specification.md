# 6. REST API Specification

## 1. API Authentication

### 1.1 Identity Sources

ECUBE supports three identity modes.

- Local mode (default): users authenticate with host OS credentials through PAM; roles are resolved from `user_roles` first, then mapped from OS groups.
- LDAP mode (optional): users authenticate through PAM backed by LDAP/SSSD; LDAP-backed group memberships map to ECUBE roles.
- OIDC mode (optional): bearer tokens are validated against the configured identity provider and mapped to ECUBE roles from configured group claims.

### 1.2 Authentication Mechanism

- API uses bearer authentication with signed JWTs.
- Tokens carry at minimum `sub`, `username`, `groups`, `roles`, `iat`, and `exp` claims.
- Token lifetime is configurable (`TOKEN_EXPIRE_MINUTES`).
- Role enforcement must occur for every authenticated endpoint at the API boundary.

### 1.3 Login Endpoint Behavior

`POST /auth/token` is the local/LDAP login endpoint.

- In local and LDAP modes, valid credentials return a signed bearer token.
- In OIDC mode, this endpoint is not available for local login and returns `404 Not Found`.

### 1.4 Public and Conditional Authentication Endpoints

The following endpoints are intentionally unauthenticated or conditionally authenticated.

- Always public: `GET /health`, `GET /health/live`, `GET /health/ready`, `GET /introspection/version`, `GET /setup/status`, `GET /setup/database/system-info`.
- Deployment-controlled public access: `GET /metrics` may be public or restricted by deployment policy.
- Conditional admin gate (unauthenticated during initial setup, admin-required after initialization): `POST /setup/database/test-connection`, `POST /setup/database/provision`, `GET /setup/database/provision-status`.
- Admin-only after initialization: `GET /setup/database/status`, `PUT /setup/database/settings`.

### 1.5 Authorization Semantics

- Missing, invalid, or expired token: `401 Unauthorized`.
- Authenticated user lacking required role: `403 Forbidden`.
- Validation failures for path/query/body: `422 Unprocessable Entity`.
- Security-relevant denials and failures must be audit-logged.

---

## 2. ECUBE Security Roles

### 2.1 Role Definitions

- Admin: full access to ECUBE operations and configuration.
- Manager: mount and drive lifecycle operations, operational oversight.
- Processor: create and run jobs, monitor job and drive status.
- Auditor: read audit metadata and integrity operations (hash/compare), no write operations to jobs, drives, or mounts.

### 2.2 Authorization Matrix

| API Area / Operation | Admin | Manager | Processor | Auditor |
| -------------------- | :---: | :-----: | :-------: | :-----: |
| Manage user roles (`/users/*/roles`) | ✔ | ✖ | ✖ | ✖ |
| Manage OS users/groups (`/admin/os-*`) | ✔ | ✖ | ✖ | ✖ |
| Add/remove mounts | ✔ | ✔ | ✖ | ✖ |
| Validate mounts | ✔ | ✔ | ✖ | ✖ |
| List mounts | ✔ | ✔ | ✔ | ✔ |
| Initialize/format/prepare-eject drives | ✔ | ✔ | ✖ | ✖ |
| List drives | ✔ | ✔ | ✔ | ✔ |
| Trigger drive refresh discovery | ✔ | ✔ | ✖ | ✖ |
| Create/start/verify/manifest jobs | ✔ | ✔ | ✔ | ✖ |
| View jobs and job files | ✔ | ✔ | ✔ | ✔ |
| Read audit logs | ✔ | ✔ | ✖ | ✔ |
| File hash/compare | ✔ | ✖ | ✖ | ✔ |
| Introspection system endpoints | ✔ | ✔ | ✔ | ✔ |
| Introspection job debug | ✔ | ✖ | ✖ | ✔ |
| Admin configuration endpoints | ✔ | ✖ | ✖ | ✖ |
| Telemetry ingestion endpoint | ✔ | ✔ | ✔ | ✔ |
| Log file list/download endpoints | ✔ | ✔ | ✔ | ✔ |

---

## 3. Standard Error Response Requirements

All error responses must conform to a standardized `ErrorResponse` schema.

```json
{
  "code": "CONFLICT",
  "message": "Drive is not in IN_USE state",
  "trace_id": "abc123"
}
```

Minimum error coverage by authenticated endpoint family must include applicable combinations of `400`, `401`, `403`, `404`, `409`, `422`, `500`, `503`, and `504`.

---

## 4. Endpoint Families and Required Roles

### 4.1 Health and Version

- `GET /health` (public): service liveness/status endpoint.
- `GET /health/live` (public): lightweight process liveness endpoint.
- `GET /health/ready` (public): readiness endpoint with dependency checks.
- `GET /metrics` (public or deployment-restricted): Prometheus-compatible metrics endpoint.
- `GET /introspection/version` (public): API/application version endpoint.

### 4.2 Authentication

- `POST /auth/token` (public in local/LDAP modes): issue JWT bearer token.

### 4.3 Setup and Database Provisioning

- `GET /setup/status` (public): initialization status.
- `POST /setup/initialize` (public, first-run guarded): initial admin/bootstrap flow.
- `GET /setup/database/system-info` (public): setup hints for DB host defaults.
- `POST /setup/database/test-connection` (conditional admin gate): test PostgreSQL connectivity.
- `POST /setup/database/provision` (conditional admin gate): create app DB/user and run migrations.
- `GET /setup/database/provision-status` (conditional admin gate): report DB provisioned state.
- `GET /setup/database/status` (`admin`): DB health/migration status.
- `PUT /setup/database/settings` (`admin`): update DB settings.

### 4.4 Mount Management

- `POST /mounts` (`admin`, `manager`): add mount.
- `GET /mounts` (all roles): list mounts.
- `POST /mounts/validate` (`admin`, `manager`): validate all mounts.
- `POST /mounts/{mount_id}/validate` (`admin`, `manager`): validate one mount.
- `DELETE /mounts/{mount_id}` (`admin`, `manager`): remove mount.

### 4.5 Drive Management

- `GET /drives` (all roles): list drives.
- `POST /drives/{drive_id}/initialize` (`admin`, `manager`): bind drive to project.
- `POST /drives/{drive_id}/format` (`admin`, `manager`): format drive (`ext4`, `exfat`).
- `POST /drives/{drive_id}/prepare-eject` (`admin`, `manager`): safe eject preparation.
- `POST /drives/{drive_id}/finalize` (`admin`, `manager`): finalize drive for export completion and safe handoff.
- `POST /drives/refresh` (`admin`, `manager`): trigger discovery sync.

### 4.6 Job Management

- `POST /jobs` (`admin`, `manager`, `processor`): create job.
- `GET /jobs/{job_id}` (all roles): job status and metadata.
- `GET /jobs/{job_id}/files` (all roles): operator-safe per-file status.
- `POST /jobs/{job_id}/start` (`admin`, `manager`, `processor`): start copy job.
- `POST /jobs/{job_id}/verify` (`admin`, `manager`, `processor`): verify copy.
- `POST /jobs/{job_id}/manifest` (`admin`, `manager`, `processor`): generate manifest.

### 4.7 Audit and File Integrity

- `GET /audit` (`admin`, `manager`, `auditor`): list audit logs with filters.
- `GET /audit/chain-of-custody` (`admin`, `manager`, `auditor`): export chain-of-custody timeline for a job.
  Query parameter: `job_id` (required)
- `GET /files/{file_id}/hashes` (`admin`, `auditor`): file hash endpoint.
- `POST /files/compare` (`admin`, `auditor`): compare files by integrity metadata.

### 4.8 Introspection

- `GET /introspection/drives` (all roles): diagnostic drive inventory.
- `GET /introspection/usb/topology` (all roles): USB topology diagnostics.
- `GET /introspection/block-devices` (all roles): block device diagnostics.
- `GET /introspection/mounts` (all roles): mount diagnostics.
- `GET /introspection/system-health` (all roles): system health diagnostics.
- `GET /introspection/jobs/{job_id}/debug` (`admin`, `auditor`): deep job debug details.

### 4.9 User Role Administration

- `GET /users` (`admin`): list users and role assignments.
- `GET /users/{username}/roles` (`admin`): read user roles.
- `PUT /users/{username}/roles` (`admin`): replace user role set.
- `DELETE /users/{username}/roles` (`admin`): remove role assignments.

### 4.10 Admin Operations

- `GET /admin/logs` (all authenticated roles): list available log files.
- `GET /admin/logs/{filename}` (all authenticated roles): download log file.
- `GET /admin/ports` (`admin`, `manager`): list ports.
- `PATCH /admin/ports/{port_id}` (`admin`, `manager`): update port state.
- `PATCH /admin/ports/{port_id}/label` (`admin`, `manager`): update port label.
- `GET /admin/hubs` (`admin`, `manager`): list hubs.
- `PATCH /admin/hubs/{hub_id}` (`admin`, `manager`): update hub metadata.
- `POST /admin/os-users` (`admin`): create OS user.
- `GET /admin/os-users` (`admin`): list OS users.
- `DELETE /admin/os-users/{username}` (`admin`): delete OS user.
- `PUT /admin/os-users/{username}/password` (`admin`): reset OS user password.
- `PUT /admin/os-users/{username}/groups` (`admin`): replace OS group membership.
- `POST /admin/os-users/{username}/groups` (`admin`): add OS group membership.
- `POST /admin/os-groups` (`admin`): create OS group.
- `GET /admin/os-groups` (`admin`): list OS groups.
- `DELETE /admin/os-groups/{name}` (`admin`): delete OS group.

### 4.11 Runtime Configuration

- `GET /admin/configuration` (`admin`): retrieve editable runtime configuration.
- `PUT /admin/configuration` (`admin`): update runtime configuration values.
- `POST /admin/configuration/restart` (`admin`): request service restart after config changes.

### 4.12 Frontend Telemetry Ingestion

- `POST /telemetry/ui-navigation` (all roles): ingest UI navigation telemetry events for diagnostics.

---

## 5. Operational and Security Requirements for API Behavior

- Security-relevant events must be audit-logged, including authentication outcomes, authorization denials, and privileged mutations.
- Role enforcement must be explicit in route dependencies and must fail closed.
- Path/query/body validation must reject malformed values with `422`.
- Administrative endpoints that mutate OS resources must remain local-only when deployment mode requires local host guarantees.
- API contracts and OpenAPI documentation must remain synchronized for endpoint paths, roles, and response semantics.

---

