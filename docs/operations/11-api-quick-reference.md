# ECUBE API Quick Reference

| Field | Value |
|---|---|
| Title | API Quick Reference |
| Purpose | Provides a quick-reference guide to ECUBE API endpoints, authentication, and common request examples for operators and developers. |
| Updated on | 04/09/26 |
| Audience | Developers, operators, IT staff. |

## Table of Contents

1. [Interactive API Documentation](#interactive-api-documentation)
2. [Authentication](#authentication)
3. [Drives (`/drives`)](#drivesdrives)
4. [Mounts (`/mounts`)](#mountsmounts)
5. [Project Source Bindings (`/projects/{project_id}/source-bindings`)](#project-source-bindings-projectsproject_idsource-bindings)
6. [Jobs (`/jobs`)](#jobsjobs)
7. [Audit (`/audit`)](#auditaudit)
8. [Admin Users (`/admin/os-users`)](#admin-users-adminos-users)
9. [Admin Logs (`/admin/logs`)](#admin-logs-adminlogs)
10. [Introspection (`/introspection`)](#introspectionintrospection)
11. [Telemetry (`/telemetry`)](#telemetrytelemetry)
12. [Support and Resources](#support-and-resources)

---

## Interactive API Documentation

ECUBE provides **interactive API documentation** via OpenAPI/Swagger that allows
you to explore and test all endpoints directly from your browser. In **local
development**, when the API server is running on port `8000`, access:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc (Alternative):** `http://localhost:8000/redoc`
- **OpenAPI JSON Schema:** `http://localhost:8000/openapi.json`

In **production**, use the same paths on your deployed HTTPS endpoint (for
example, `https://localhost:8443/docs` or `https://ecube-api.example.com/docs`),
replacing `localhost:8000` with the actual host and port configured for the
ECUBE API.

Use the Swagger UI to:

- View all available endpoints with detailed descriptions
- Understand request/response schemas for each endpoint
- See required authentication and role requirements
- Test endpoints interactively with test data
- Copy curl commands
- View HTTP request/response examples

---

## Authentication

The following endpoints are publicly accessible and do **not** require
authentication:

- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /introspection/version`
- `POST /auth/token` (login / token issuance)
- `GET /setup/status`
- `POST /setup/initialize`
- `GET /setup/database/system-info`
- API documentation: `GET /docs`, `GET /redoc`, `GET /openapi.json`

All other API endpoints require a bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer $JWT_TOKEN" https://localhost:8443/endpoint
```

During initial setup, `POST /setup/database/test-connection`, `POST /setup/database/provision`, and `GET /setup/database/provision-status` also accept unauthenticated access. After setup is complete, these endpoints require an `admin` token.

---

## Drives (`/drives`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/drives` | admin/manager/processor/auditor | List drives (excludes `DISCONNECTED` drives by default). Optional `?project_id=`, repeatable `?state=`, and `?include_disconnected=true` filters |
| POST | `/drives/refresh` | admin/manager | Force rescan of attached drives |
| POST | `/drives/{drive_id}/initialize` | admin/manager | Initialize drive for project (requires a recognized filesystem and a mounted share assigned to that project; returns `409` if the source is missing or temporarily busy) |
| POST | `/drives/{drive_id}/format` | admin/manager | Format drive with `ext4` or `exfat`; drive must be AVAILABLE and unmounted |
| POST | `/drives/{drive_id}/prepare-eject` | admin/manager | Flush filesystem + unmount all partitions; transitions drive to AVAILABLE on success, stays IN_USE on failure |

---

## Mounts (`/mounts`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/mounts` | manager+ | List network mounts |
| POST | `/mounts` | manager | Add new mount with required project assignment |
| POST | `/mounts/{mount_id}/validate` | admin/manager | Validate mount connectivity |
| POST | `/mounts/validate` | admin/manager | Validate all mounts |
| DELETE | `/mounts/{mount_id}` | admin/manager | Remove mount |

Project identifiers are canonicalized by trimming surrounding whitespace and converting the value to uppercase before storage and comparison. The mount-create endpoint also rejects exact duplicate remote sources and cross-project parent or child overlaps with `409 Conflict`; same-project nested sources remain allowed. A temporary `409 Conflict` can also be returned when another mount update is already in progress and holds the serialization lock.

---

## Project Source Bindings (`/projects/{project_id}/source-bindings`)

Compatibility note: To support project-to-source-path policy, use project source bindings alongside mounts and jobs. Mounts still define connectivity, while bindings define which mount root and optional subfolder are valid for each project.

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/projects/{project_id}/source-bindings` | manager+ | List source bindings for a project |
| POST | `/projects/{project_id}/source-bindings` | admin/manager | Add a project source binding (mount + optional subfolder) |
| PATCH | `/projects/{project_id}/source-bindings/{binding_id}` | admin/manager | Update an existing binding |
| DELETE | `/projects/{project_id}/source-bindings/{binding_id}` | admin/manager | Remove a binding |

**Job compatibility:** `POST /jobs` may reject source paths that are outside active bindings for the job project (for example `403` policy violation or `409` configuration conflict), so processors should select source paths from configured project bindings.

---

## Jobs (`/jobs`)

| Method | Endpoint | Role | Description |
| ------ | -------- | -------- | ----------- |
| POST | `/jobs` | processor+ | Create new export job (omit `drive_id` for auto-assignment) |
| GET | `/jobs/{job_id}` | admin/manager/processor/auditor | Get job detail (status, progress) |
| GET | `/jobs/{job_id}/files` | admin/manager/processor/auditor | List operator-safe file status rows for the job |
| POST | `/jobs/{job_id}/start` | processor | Start copy operation |
| POST | `/jobs/{job_id}/verify` | processor+ | Verify data integrity |
| POST | `/jobs/{job_id}/manifest` | processor+ | Generate manifest document |

**Automatic Drive Assignment:** When `drive_id` is omitted from `POST /jobs`, the system auto-selects a drive: picks the single project-bound `AVAILABLE` drive, or falls back to an unbound drive. Returns **409** if the drive is temporarily unavailable (retry), if multiple project-bound drives exist (caller must specify `drive_id`), or if no usable drive can be acquired for the requested project. In both auto-assign and explicit `drive_id` paths, unbound drives are automatically bound to the requested project.

**Webhook Callbacks:** Include `callback_url` (HTTPS only) when creating a job to receive a POST notification when the job reaches `COMPLETED` or `FAILED`. Makes up to 4 attempts on server errors with exponential backoff. Private/reserved IPs are blocked by default (SSRF protection). See the [Third-Party Integration Guide](09-third-party-integration.md) for payload details.

---

## Audit (`/audit`)

| Method | Endpoint | Role | Description |
| ------ | -------- | -------- | ----------------------- |
| GET | `/audit` | auditor+ | Query audit logs with filters |

**Filters:**

- `user=griffin` — Filter by user
- `action=JOB_CREATED` — Filter by action
- `job_id=5` — Filter by job
- `since=2026-03-01T00:00:00Z` — Start timestamp (ISO 8601)
- `until=2026-03-06T23:59:59Z` — End timestamp (ISO 8601)
- `limit=100` — Max results (default 100, max 1000)
- `offset=0` — Skip N results

**Example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  'https://localhost:8443/audit?action=JOB_STARTED&user=griffin&limit=50&offset=0'
```

---

## Admin Users (`/admin/os-users`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| POST | `/admin/os-users` | admin | Create a new OS user or link an existing OS/directory user into ECUBE role assignments (decision-based flow). |
| GET | `/admin/os-users` | admin | List ECUBE-relevant users (ecube-group users plus DB role-assigned users). |
| DELETE | `/admin/os-users/{username}` | admin | Delete OS user and clean up DB role assignments. |
| PUT | `/admin/os-users/{username}/password` | admin | Reset OS user password. |

`POST /admin/os-users` supports existing-user decision outcomes:

- `200 confirmation_required` when target user exists and no decision was supplied
- `200 canceled` when `confirm_existing_os_user=false`
- `200 synced_existing_user` when `confirm_existing_os_user=true`
- `201 Created` for brand-new OS account creation

`GET /admin/os-users` visibility behavior:

- includes users in `ecube-*` OS groups
- includes usernames with DB role assignments in `user_roles`
- may return placeholder host fields (`uid=-1`, `gid=-1`, empty `home`/`shell`/`groups`) for directory-backed users that are role-assigned but not returned by host enumeration

---

## Admin Logs (`/admin/logs`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/admin/logs/view` | admin | View redacted log lines with pagination/filtering (source allowlist) |
| GET | `/admin/logs` | admin | List downloadable log files with metadata and aggregate size |
| GET | `/admin/logs/{filename}` | admin | Download raw log file content |

### `GET /admin/logs/view` (quick params)

- `source=app` — Allowlisted log source key (currently `app` only)
- `limit=200` — Max matching lines to return (min 1, max 1000)
- `offset=0` — Number of newest matching lines to skip
- `search=` — Optional case-insensitive substring filter
- `reverse=false` — `false`: oldest→newest in selected window, `true`: newest→oldest

**Response highlights:**

- Returns an object with `source`, `fetched_at`, `file_modified_at`, `offset`, `limit`, `returned`, `has_more`, `lines`
- `source.path` is basename-only (for example `app.log`), not an absolute host path
- `lines[].content` is automatically redacted for sensitive values

**Example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  'https://localhost:8443/admin/logs/view?source=app&limit=100&offset=0&search=error&reverse=true'
```

### `GET /admin/logs` (response shape)

Returns an object envelope (not a bare array):

```json
{
  "log_files": [
    {
      "name": "app.log",
      "size": 2097152,
      "created": "2026-04-08T14:00:00.000000Z",
      "modified": "2026-04-08T14:31:22.654321Z"
    }
  ],
  "total_size": 2097152
}
```

Common errors for admin log endpoints: `401` (missing/invalid token), `403` (non-admin), `404` (source/file not found or file logging unavailable), `422` (invalid query params on `/admin/logs/view`), `503` (log I/O/permission issues).

---

## Introspection (`/introspection`)

| Method | Endpoint | Role | Description |
| ------ | ----------------------- | ------ | ----------------------- |
| GET | `/introspection/version` | public | Application and API version |
| GET | `/introspection/drives` | all | Registered USB drive inventory |
| GET | `/introspection/usb/topology` | all | USB hub and device topology |
| GET | `/introspection/block-devices` | all | Kernel block device inventory |
| GET | `/introspection/mounts` | all | Mount inventory and status |
| GET | `/introspection/system-health` | all | Database and job engine health |
| GET | `/introspection/jobs/{job_id}/debug` | admin,auditor | Debug info for specific job |

---

## Telemetry (`/telemetry`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| POST | `/telemetry/ui-navigation` | admin/manager/processor/auditor | Internal troubleshooting endpoint for selected frontend navigation events |

**Notes:**

- This endpoint is for operational troubleshooting only.
- It records selected UI navigation events in the application log at `DEBUG` level.
- It does not create audit-log records and should not be treated as a compliance trail.
- Typical payload fields include `event_type`, `source`, `destination`, `route_name`, `action`, `label`, and `reason`.

---

## Support and Resources

### Documentation

- **Design Docs:** `docs/design/` — Technical design and architecture
- **API Spec:** `docs/design/06-rest-api-design.md` — Detailed API endpoints
- **Security:** `docs/design/10-security-and-access-control.md` — Authentication, RBAC
- **Configuration:** [04-configuration-reference.md](04-configuration-reference.md) — All environment variables

### Logging and Debugging

- **Service Logs:** `journalctl -u ecube -f`
- **Database Logs:** PostgreSQL log file (check postgresql.conf)
- **API Errors:** Check response JSON for `code`, `message`, and `trace_id` fields
- **UI navigation telemetry:** Set `LOG_LEVEL=DEBUG` to see `UI_NAVIGATION_TELEMETRY` lines from the frontend telemetry endpoint in the service log

### Contacting Support

- **GitHub Issues:** <https://github.com/t3knoid/ecube/issues>
- **Documentation:** <https://github.com/t3knoid/ecube/tree/main/documents>
- **Code Examples:** `README.md` in repository root

### Quick Command Reference

```bash
# Service management
sudo systemctl start|stop|restart|status ecube

# View logs
sudo journalctl -u ecube -f

# Check database
psql -U ecube -d ecube

# Verify API
curl -k https://localhost:8443/introspection/version

# Query audit logs (requires token)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/audit?limit=50
```

## References

- [docs/design/06-rest-api-design.md](../design/06-rest-api-design.md)
