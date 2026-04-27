# ECUBE API Quick Reference

| Field | Value |
|---|---|
| Title | API Quick Reference |
| Purpose | Provides a quick-reference guide to ECUBE API endpoints, authentication, and common request examples for operators and developers. |
| Updated on | 04/25/26 |
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

Setup initialize behavior:

- `POST /setup/initialize` accepts `trust_proxy_headers` (boolean, default `false`) in addition to admin username/password.
- If setup is already initialized, `POST /setup/initialize` returns `200` with `status="already_initialized"` and an informational message instead of returning `409`.
- Once setup is already initialized, the call returns informational success but does not persist runtime setting changes; post-setup configuration updates require authenticated admin workflows.

---

## Drives (`/drives`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/drives` | admin/manager/processor/auditor | List drives (excludes `DISCONNECTED` drives by default). Optional `?project_id=`, repeatable `?state=`, and `?include_disconnected=true` filters |
| POST | `/drives/refresh` | admin/manager | Force rescan of attached drives |
| POST | `/drives/{drive_id}/initialize` | admin/manager | Initialize drive for project (requires a recognized filesystem, a mounted destination drive, and a mounted share assigned to that project; returns `409` if the drive or source is not ready or is temporarily busy) |
| POST | `/drives/{drive_id}/format` | admin/manager | Format drive with `ext4` or `exfat`; drive must be AVAILABLE and unmounted |
| POST | `/drives/{drive_id}/prepare-eject` | admin/manager | Flush filesystem + unmount all partitions; transitions drive to AVAILABLE on success, stays IN_USE on failure. When active assignments contain timed-out or failed files, the first call returns `409` confirmation-required; retry with `?confirm_incomplete=true` to proceed. |

Drive responses include both the stable `device_identifier` and the port-based `port_system_path` used as the UI `Device` value. When available, `serial_number` is exposed separately so operator views can show the physical port-based label and the device serial at the same time.

---

## Mounts (`/mounts`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/mounts` | admin/manager/processor/auditor | List network mounts |
| POST | `/mounts` | admin/manager | Add new mount with required project assignment |
| PATCH | `/mounts/{mount_id}` | admin/manager | Update an existing mount in place while preserving the generated local mount point |
| POST | `/mounts/discover` | admin/manager | Discover SMB shares or NFS exports from the Add Mount dialog using the submitted server seed and optional credentials |
| POST | `/mounts/{mount_id}/validate` | admin/manager | Validate mount connectivity |
| POST | `/mounts/validate` | admin/manager | Validate all mounts |
| DELETE | `/mounts/{mount_id}` | admin/manager | Remove mount |

Project identifiers are canonicalized by trimming surrounding whitespace and converting the value to uppercase before storage and comparison. The mount-create endpoint also rejects exact duplicate remote sources and cross-project parent or child overlaps with `409 Conflict`; same-project nested sources remain allowed. A temporary `409 Conflict` can also be returned when another mount update is already in progress and holds the serialization lock.

`POST /mounts/discover` is a trusted helper for the Add Mount dialog. It accepts the selected mount type plus the entered server seed and optional credentials, returns sanitized remote paths suitable for populating the dialog, hides the feature in demo mode, and can return actionable `500` guidance when the ECUBE host is missing required discovery tools such as `smbclient` or `showmount`.

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
| PUT | `/jobs/{job_id}` | processor+ | Update a pending, paused, or failed job from the Job Detail page |
| DELETE | `/jobs/{job_id}` | processor+ | Delete a pending job and release its current drive assignment |
| GET | `/jobs/{job_id}` | admin/manager/processor/auditor | Get job detail, including progress, cumulative active duration that excludes paused time, and sanitized failure summaries |
| GET | `/jobs/{job_id}/files` | admin/manager/processor/auditor | List operator-safe file status rows for the job with `page` and optional `limit` pagination, including safe per-file `error_message` text when available |
| POST | `/jobs/{job_id}/analyze` | processor+ | Run manual startup analysis without starting copy so operators can review scan results first |
| POST | `/jobs/{job_id}/start` | processor+ | Start a new job or resume a paused job |
| POST | `/jobs/{job_id}/retry-failed` | processor+ | Re-queue only `ERROR` and `TIMEOUT` file rows on a partially successful `COMPLETED` job |
| POST | `/jobs/{job_id}/pause` | processor+ | Request a safe pause for a running job; returns `PAUSING` until in-flight work drains |
| POST | `/jobs/{job_id}/complete` | processor+ | Manually mark a pending, paused, or failed job as completed |
| POST | `/jobs/{job_id}/startup-analysis/clear` | admin/manager | Clear the persisted startup-analysis cache after explicit `{ "confirm": true }` confirmation |
| POST | `/jobs/{job_id}/verify` | processor+ | Verify copied data only after a clean completed job with no failed or timed-out files |
| POST | `/jobs/{job_id}/manifest` | processor+ | Write or refresh `manifest.json` only after a clean completed job with no failed or timed-out files |
| GET | `/jobs/{job_id}/manifest/download` | processor+ | Download the most recently generated manifest JSON as an attachment |

**Pause, Resume, and Retry Semantics:** `POST /jobs/{job_id}/pause` moves a running job into `PAUSING` immediately and into `PAUSED` once the active copy threads finish their current work. `POST /jobs/{job_id}/start` can then resume the job from `PAUSED`; attempts to start while a job is still `PAUSING` return **409 Conflict**. `POST /jobs/{job_id}/retry-failed` is the follow-up path for a partial-success `COMPLETED` job and returns **409 Conflict** if the job is not completed or no failed files remain.

**Job File Pagination:** `GET /jobs/{job_id}/files` accepts `page` (default `1`, minimum `1`) and optional `limit`. When `limit` is omitted, ECUBE uses the configured `JOB_DETAIL_FILES_PAGE_SIZE` default. Explicit `limit` values must stay between **20** and **100**. Responses include `page`, `page_size`, `total_files`, and `returned_files` in addition to the file rows. Each file row can also include a sanitized `error_message` value so Job Detail can open per-file failure details without using the privileged introspection API.

**Active Duration Semantics:** `GET /jobs/{job_id}` returns cumulative active runtime for the job. The value increases while the job is actively running, excludes time spent paused, and after a later resume continues from the previously stored active duration instead of resetting to zero.

**Job Detail Lifecycle Controls:** Analyze is available for eligible pending or restartable jobs and runs startup analysis without moving the job into `RUNNING`. Edit and Complete are limited to `PENDING`, `PAUSED`, and `FAILED` jobs. `Retry Failed Files` is limited to `COMPLETED` jobs that still contain `ERROR` or `TIMEOUT` file rows and re-queues only those failed terminal files while leaving successful copies unchanged. Delete is limited to `PENDING` jobs only, and the project binding on an existing job cannot be changed during edit. Startup-analysis cache cleanup is limited to `admin` and `manager`, requires explicit confirmation, and removes only the persisted startup-analysis snapshot rather than file-level copy history.

**Startup Analysis Locking:** While `startup_analysis_status` is `ANALYZING`, the backend rejects Edit, Analyze, Start, Retry Failed Files, Complete, Delete, and `POST /jobs/{job_id}/startup-analysis/clear` with **409 Conflict** so UI-disabled controls are enforced server-side.

**Manifest and Compare Semantics:** Verify and Manifest remain disabled in the UI until the job is truly complete at 100% and has no failed or timed-out files. A partial-success `COMPLETED` job can use `POST /jobs/{job_id}/retry-failed` to re-queue failed files before those clean-completion actions become eligible again. Manifest generation overwrites the same `manifest.json` file on the destination drive, shows its location in the UI, and can immediately be followed by `GET /jobs/{job_id}/manifest/download` so Job Detail can offer the same generated JSON as a browser download. When the same exported record is selected for file comparison, ECUBE compares the original source file against the copied destination version and returns a sanitized **409 Conflict** if either side is unavailable.

**Automatic Drive Assignment:** When `drive_id` is omitted from `POST /jobs`, the system auto-selects a drive: picks the single project-bound `AVAILABLE` drive, or falls back to an unbound drive. Returns **409** if the drive is temporarily unavailable (retry), if multiple project-bound drives exist (caller must specify `drive_id`), or if no usable drive can be acquired for the requested project. In both auto-assign and explicit `drive_id` paths, unbound drives are automatically bound to the requested project.

**Explicit Drive Selection:** When `drive_id` is provided, the destination drive must be project-compatible and currently mounted. A mounted drive already associated with the requested project remains valid when its state is `AVAILABLE` or `IN_USE`; unmounted or stale selections still return **409 Conflict**.

**Device Display Semantics:** Job responses may include `drive.port_system_path`, which is the port-based value shown in the Jobs list and the Create/Edit Job destination selector. The stable `device_identifier` remains available in the payload as a separate hardware identifier.

**Mounted Source Resolution:** Current job creation also includes the selected mounted share identifier. The API resolves the final source path on the trusted backend, treats / as the selected share root, rejects traversal outside that share with **422**, and returns **404** or **409** if the selected mount is missing, unmounted, or assigned to a different project.

**Progress Semantics:** Job list, dashboard, and detail views all use `copied_bytes` together with completed-file counters so active jobs do not appear 100% complete before file completion has caught up.

**File Outcome Counters:** Job payloads include `files_succeeded`, `files_failed`, and `files_timed_out`. `files_timed_out` tracks per-file timeout outcomes (for example, `File copy timed out after 3600s`) and is reported separately from whole-job failure classification.

**Failed Job Evidence Fallback:** When `GET /jobs/{job_id}` cannot correlate a failed-job application log line, ECUBE can synthesize a sanitized failure entry from recent audit evidence (`JOB_FAILED`, `JOB_TIMEOUT`, or `JOB_RECONCILED`) so operators still receive actionable context.

**Startup Analysis Semantics:** Job responses can include `startup_analysis_status`, `startup_analysis_ready`, `startup_analysis_last_analyzed_at`, `startup_analysis_failure_reason`, `startup_analysis_file_count`, and `startup_analysis_total_bytes` in addition to `startup_analysis_cached`. Manual analyze requests move the startup-analysis lifecycle through `NOT_ANALYZED`, `ANALYZING`, `READY`, `STALE`, or `FAILED` while the job itself can remain `PENDING`.

**Startup Analysis Cache Semantics:** `startup_analysis_cached` indicates whether a persisted startup-analysis snapshot is available for restart reuse. ECUBE may reuse that snapshot on a later start when the source tree is still current, refresh it if the source changed, clear it automatically after successful completion, and clear it on explicit `POST /jobs/{job_id}/startup-analysis/clear` or manual completion paths. Summary fields such as discovered files, estimated total bytes, last analyzed time, and the safe failure reason can remain available after the reusable per-file snapshot has been discarded.

**Webhook Callbacks:** Include `callback_url` (HTTPS only) when creating a job to receive a POST notification when the job reaches `COMPLETED` or `FAILED`. Callback payloads now include `files_succeeded`, `files_failed`, `files_timed_out`, and `completion_result` so integrations can distinguish clean success from partial-success completion. Makes up to 4 attempts on server errors with exponential backoff. Private/reserved IPs are blocked by default (SSRF protection). See the [Third-Party Integration Guide](12-third-party-integration.md) for payload details.

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

- `source=app` — View the configured application log family as a merged newest-first source
- `source=app.log.1` — View a specific rotated file from the same allowlisted log family
- `limit=200` — Max matching lines to return (min 1, max 1000)
- `offset=0` — Number of newest matching lines to skip
- `search=` — Optional case-insensitive substring filter
- `reverse=false` — `false`: oldest→newest in selected window, `true`: newest→oldest

**Response highlights:**

- Returns an object with `source`, `fetched_at`, `file_modified_at`, `offset`, `limit`, `returned`, `has_more`, `lines`
- `source.path` is basename-only (for example `app.log`, `app.log*`, or `app.log.1`), not an absolute host path
- `lines[].content` is automatically redacted for sensitive values

**Example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  'https://localhost:8443/admin/logs/view?source=app&limit=100&offset=0&search=error&reverse=true'
```

```bash
curl -H "Authorization: Bearer $TOKEN" \
  'https://localhost:8443/admin/logs/view?source=app.log.1&limit=100&offset=0&reverse=true'
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

Common errors for admin log endpoints: `400` (invalid filename or traversal attempt on `source`), `401` (missing/invalid token), `403` (non-admin), `404` (source/file not found or file logging unavailable), `422` (invalid query params on `/admin/logs/view`), `503` (log I/O/permission issues).

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
| POST | `/introspection/reconcile-managed-mounts` | admin,manager | Run a manual live-safe reconciliation pass for managed network and USB mounts |
| GET | `/introspection/jobs/{job_id}/debug` | admin,auditor | Debug info for specific job |

`GET /introspection/drives` includes the port-based `port_system_path` and separate `serial_number` for each registered drive. `GET /introspection/usb/topology` includes a `serial` field when sysfs exposes one.

`POST /introspection/reconcile-managed-mounts` returns a summary payload with `status` (`ok` or `partial`), `scope` (`managed_mounts_only`), `network_mounts_checked`, `network_mounts_corrected`, `usb_mounts_checked`, `usb_mounts_corrected`, and `failure_count`. The endpoint is lock-protected and returns `409 Conflict` (`MANUAL_RECONCILIATION_IN_PROGRESS`) if another manual run is already in progress.

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
