# ECUBE API Quick Reference

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Developers, Operators, IT Staff  
**Document Type:** API Reference

---

## Table of Contents

1. [Interactive API Documentation](#interactive-api-documentation)
2. [Authentication](#authentication)
3. [Drives](#drives-drives)
4. [Mounts](#mounts-mounts)
5. [Jobs](#jobs-jobs)
6. [Audit](#audit-audit)
7. [Introspection](#introspection-introspection)
8. [Support and Resources](#support-and-resources)

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
- `GET /introspection/version`
- `POST /auth/token` (login / token issuance)
- API documentation: `GET /docs`, `GET /redoc`, `GET /openapi.json`

All other API endpoints require a bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer $JWT_TOKEN" https://localhost:8443/endpoint
```

---

## Drives (`/drives`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/drives` | admin/manager/processor/auditor | List all drives and state (includes `filesystem_type`). Optional `?project_id=` filter |
| POST | `/drives/refresh` | admin/manager | Force rescan of attached drives |
| POST | `/drives/{drive_id}/initialize` | admin/manager | Initialize drive for project (rejects unformatted/unknown drives) |
| POST | `/drives/{drive_id}/format` | admin/manager | Format drive with `ext4` or `exfat`; drive must be AVAILABLE and unmounted |
| POST | `/drives/{drive_id}/prepare-eject` | admin/manager | Flush filesystem + unmount all partitions; transitions drive to AVAILABLE on success, stays IN_USE on failure |

---

## Mounts (`/mounts`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/mounts` | manager+ | List network mounts |
| POST | `/mounts` | manager | Add new mount |
| POST | `/mounts/{mount_id}/validate` | admin/manager | Validate mount connectivity |
| POST | `/mounts/validate` | admin/manager | Validate all mounts |
| DELETE | `/mounts/{mount_id}` | admin/manager | Remove mount |

---

## Jobs (`/jobs`)

| Method | Endpoint | Role | Description |
| ------ | -------- | -------- | ----------- |
| POST | `/jobs` | processor+ | Create new export job (omit `drive_id` for auto-assignment) |
| GET | `/jobs/{job_id}` | processor+ | Get job detail (status, progress) |
| POST | `/jobs/{job_id}/start` | processor | Start copy operation |
| POST | `/jobs/{job_id}/verify` | processor+ | Verify data integrity |
| POST | `/jobs/{job_id}/manifest` | processor+ | Generate manifest document |

**Automatic Drive Assignment:** When `drive_id` is omitted from `POST /jobs`, the system auto-selects a drive: picks the single project-bound `AVAILABLE` drive, or falls back to an unbound drive. Returns **409** if the drive is temporarily unavailable (retry), if multiple project-bound drives exist (caller must specify `drive_id`), or if no usable drive can be acquired for the requested project. In both auto-assign and explicit `drive_id` paths, unbound drives are automatically bound to the requested project.

**Webhook Callbacks:** Include `callback_url` (HTTPS only) when creating a job to receive a POST notification when the job reaches `COMPLETED` or `FAILED`. Makes up to 4 attempts on server errors with exponential backoff. Private/reserved IPs are blocked by default (SSRF protection). See the [Third-Party Integration Guide](10-third-party-integration.md) for payload details.

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

## Support and Resources

### Documentation

- **Design Docs:** `docs/design/` — Technical design and architecture
- **API Spec:** `docs/design/06-rest-api-specification.md` — Detailed API endpoints
- **Security:** `docs/design/10-security-and-access-control.md` — Authentication, RBAC
- **Configuration:** [02-configuration-reference.md](02-configuration-reference.md) — All environment variables

### Logging and Debugging

- **Service Logs:** `journalctl -u ecube -f`
- **Database Logs:** PostgreSQL log file (check postgresql.conf)
- **API Errors:** Check response JSON for `code`, `message`, and `trace_id` fields

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
