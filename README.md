# ecube

Evidence Copying &amp; USB Based Export

ECUBE is a secure evidence export platform designed to copy eDiscovery data onto encrypted USB drives from a Linux-based copy machine, with strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Application Stack

- **System Layer API:** Python 3.11+, FastAPI
- **Data Layer:** PostgreSQL 14+ with SQLAlchemy + Alembic
- **Background Processing:** Celery or RQ workers for copy, verification, and manifest tasks
- **UI Layer:** React, Vue, or server-rendered templates (HTTPS-only)
- **Runtime Platform:** Linux-based copy machine with USB hub integration and NFS/SMB mount support
- **Planned/Optional Security:** LDAP identity provider mode and token-based API authentication (JWT or signed session token)

## PostgreSQL and Alembic Setup

ECUBE uses PostgreSQL (14+) as the system-of-record database and Alembic for database schema versioning.

### PostgreSQL (Data Layer)

#### What PostgreSQL is used for in ECUBE

PostgreSQL stores all persistent operational data for the system layer, including:

- USB hardware state (hubs, ports, drives)
- Mount records
- Export jobs and file-level copy metadata
- Audit logs

It is the authoritative source for security and lifecycle state across drive, mount, and job workflows.

#### Install PostgreSQL

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

#### Create ECUBE database and user

After PostgreSQL is installed, create an application user and database:

```sql
CREATE USER ecube WITH PASSWORD 'ecube';
CREATE DATABASE ecube OWNER ecube;
GRANT ALL PRIVILEGES ON DATABASE ecube TO ecube;
```

#### Configure ECUBE connection

Set the database URL in environment (or `.env`) to match your local setup:

```env
DATABASE_URL=postgresql://ecube:ecube@localhost/ecube
```

---

### Alembic (Schema Migration Layer)

#### What Alembic is used for in ECUBE

Alembic manages database schema changes over time. In ECUBE it is used to:

- Create and evolve tables and constraints
- Keep schema aligned between local/dev/test/prod environments
- Apply versioned, auditable migration history

#### Install Alembic

Alembic is installed automatically with project dependencies:

```bash
pip install -e ".[dev]"
```

If needed, install directly:

```bash
pip install alembic
```

#### Initialize and run migrations

This repository already includes Alembic configuration (`alembic.ini` and `alembic/`).

Apply all pending migrations:

```bash
alembic upgrade head
```

Check current migration version:

```bash
alembic current
```

Create a new migration revision (when schema changes are added):

```bash
alembic revision -m "describe change"
```

#### Typical startup sequence

1. Start PostgreSQL and ensure `DATABASE_URL` is correct.
2. Run `alembic upgrade head` (or use the API-based provisioning wizard at `/setup/database/provision` after starting the server — see the Operational Guide for details).
3. Start the API server (`uvicorn app.main:app --reload`).

## API Documentation

ECUBE provides interactive API documentation via OpenAPI (Swagger UI) and ReDoc. Once the API server is running, access the documentation at:

- **Swagger UI (Interactive):** `http://localhost:8000/docs`
- **ReDoc (Alternative UI):** `http://localhost:8000/redoc`
- **OpenAPI Schema (JSON):** `http://localhost:8000/openapi.json`

The Swagger UI allows you to:

- View all available endpoints with descriptions
- Understand request/response schemas
- Test API endpoints directly from the browser
- Explore authentication and role requirements

All application/API endpoints (except `/health` and documentation endpoints such as `/docs`, `/redoc`, and `/openapi.json`) require authentication via JWT bearer tokens. Full API specification and security role details are documented in:

- `documents/design/06-rest-api-specification.md`
- `documents/design/10-security-and-access-control.md`

---

## Identity Provider Configuration

ECUBE supports three pluggable role resolver modes, selected by the `role_resolver` environment variable.

### Local mode (default)

Uses a static group-to-role mapping defined in configuration.

```bash
role_resolver=local
local_group_role_map='{"evidence-admins": ["admin"], "evidence-team": ["processor", "auditor"]}'
```

### LDAP mode

Uses LDAP group distinguished names mapped to ECUBE roles.

```bash
role_resolver=ldap
ldap_group_role_map='{"CN=EvidenceAdmins,DC=corp,DC=example,DC=com": ["admin"]}'
```

### OIDC mode

Validates OIDC ID tokens (from Auth0, Okta, Azure AD, Google Cloud Identity, etc.) against the
provider's public keys and maps the group claim to ECUBE roles.

```bash
role_resolver=oidc
oidc_discovery_url=<provider-discovery-url>
oidc_client_id=<your-client-id>
oidc_client_secret=<your-client-secret>  # kept secret; not used for token validation
oidc_audience=<your-client-id>           # optional; enables audience validation
oidc_group_claim_name=groups             # claim that carries group memberships
oidc_group_role_map='{"evidence-admins": ["admin"], "evidence-team": ["processor"]}'
```

OIDC tokens are validated using the provider's JWKS endpoint (fetched via the discovery URL).
The JWKS is cached for the process lifetime for performance.

#### Provider examples

**Auth0**

```bash
role_resolver=oidc
oidc_discovery_url=https://<YOUR_AUTH0_DOMAIN>/.well-known/openid-configuration
oidc_client_id=<YOUR_CLIENT_ID>
oidc_client_secret=<YOUR_CLIENT_SECRET>
oidc_group_claim_name=org_groups
oidc_group_role_map='{"evidence-admins": ["admin"], "evidence-team": ["processor", "auditor"]}'
```

**Okta**

```bash
role_resolver=oidc
oidc_discovery_url=https://<YOUR_OKTA_DOMAIN>/oauth2/default/.well-known/openid-configuration
oidc_client_id=<YOUR_CLIENT_ID>
oidc_client_secret=<YOUR_CLIENT_SECRET>
oidc_group_claim_name=groups
oidc_group_role_map='{"EvidenceAdmins": ["admin"], "EvidenceTeam": ["processor"]}'
```

**Azure AD (OIDC mode)**

```bash
role_resolver=oidc
oidc_discovery_url=https://login.microsoftonline.com/<TENANT_ID>/v2.0/.well-known/openid-configuration
oidc_client_id=<YOUR_CLIENT_ID>
oidc_client_secret=<YOUR_CLIENT_SECRET>
oidc_audience=<YOUR_CLIENT_ID>
oidc_group_claim_name=groups
oidc_group_role_map='{"<ObjectId_of_AdminGroup>": ["admin"]}'
```

**Google Cloud Identity**

```bash
role_resolver=oidc
oidc_discovery_url=https://accounts.google.com/.well-known/openid-configuration
oidc_client_id=<YOUR_CLIENT_ID>
oidc_client_secret=<YOUR_CLIENT_SECRET>
oidc_audience=<YOUR_CLIENT_ID>
oidc_group_claim_name=groups
oidc_group_role_map='{"evidence-admins@example.com": ["admin"]}'
```

#### How `oidc_group_role_map` works

Each key is the exact string value that appears in the group claim of the OIDC token.
Each value is a list of ECUBE roles to grant.  Unmapped groups are silently ignored
(**deny-by-default**).  Roles from multiple groups are merged and deduplicated.

Example token claim:

```json
{ "groups": ["evidence-admins", "evidence-team"] }
```

With the map `{"evidence-admins": ["admin"], "evidence-team": ["processor"]}`, the resolved
roles are `["admin", "processor"]`.

#### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 OIDC is enabled but 'oidc_discovery_url' is not configured` | Missing env var | Set `oidc_discovery_url` |
| `401 OIDC token has expired` | Token past `exp` | Ensure the client refreshes tokens before expiry |
| `401 OIDC token audience mismatch` | `aud` claim does not match `oidc_audience` | Verify `oidc_audience` matches the client ID registered with your provider |
| `403` on all requests | Groups present but none mapped | Add the group to `oidc_group_role_map` |
| `401 Failed to obtain signing key` | JWKS URI unreachable | Check network access from ECUBE host to the provider's JWKS endpoint |

---

## Build and Deployment

ECUBE build and deployment guidance (release artifacts, package deployment without Docker runtime, Docker image builds, and compose deployment) is documented in:

- `documents/design/13-build-and-deployment.md`

Choose one runtime path per environment: package deployment **or** Docker deployment.

## Logging

ECUBE includes a structured logging facility that supports human-readable (text) and machine-readable (JSON) output formats.  Configuration is driven by environment variables (or a `.env` file).

### Configuration

| Variable                | Default   | Description                                          |
|-------------------------|-----------|------------------------------------------------------|
| `LOG_LEVEL`             | `INFO`    | Root log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `LOG_FORMAT`            | `text`    | Output format (`text` or `json`)                     |
| `LOG_FILE`              | *(none)*  | Path to a log file; enables rotating file handler    |
| `LOG_FILE_MAX_BYTES`    | `10485760`| Max size per log file before rotation (default 10 MB)|
| `LOG_FILE_BACKUP_COUNT` | `5`       | Number of rotated backup files to keep               |

Example `.env` configuration:

```env
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_FILE=/var/log/ecube/app.log
LOG_FILE_MAX_BYTES=10485760
LOG_FILE_BACKUP_COUNT=5
```

### Log Formats

**Text format** (default):

```
2026-03-07T12:00:00+0000 [INFO] app.services.drive_service: drive_state_transition
```

**JSON format** (`LOG_FORMAT=json`):

```json
{
  "timestamp": "2026-03-07T12:00:00+00:00",
  "level": "INFO",
  "module": "app.services.drive_service",
  "message": "drive_state_transition",
  "extra": {"drive_id": 1, "old_state": "AVAILABLE", "new_state": "IN_USE"}
}
```

### Where Logs Are Written

- **Console (stdout):** Always enabled.
- **File:** Only when `LOG_FILE` is set.  Files are rotated automatically when they reach `LOG_FILE_MAX_BYTES`.

### Log File Access via API

When file-based logging is enabled, log files can be listed and downloaded via the `/admin/logs` endpoints.  All access requires authentication (JWT bearer token).

- `GET /admin/logs` — list available log files with size and timestamp metadata
- `GET /admin/logs/{filename}` — download a specific log file

Path traversal protection is enforced: filenames containing `..` or `/` are rejected.  All log file access is recorded in the audit trail.

## QA Test-Case Sync

The QA test-case spreadsheet (`documents/operations/ecube-qa-test-cases.xlsx`) is generated from the markdown guide (`documents/operations/01-qa-testing-guide-baremetal.md`).  A sync script keeps them aligned:

```bash
# Check for drift (exits non-zero if out of sync)
python scripts/sync_qa_test_cases.py --check

# Regenerate the Excel from the markdown (preserves Status/Tester/Date/Notes)
python scripts/sync_qa_test_cases.py --sync
```

After editing test cases in the markdown guide, run `--sync` and commit both files together.

**Automated enforcement:**

- **Pre-commit hook** — `.githooks/pre-commit` runs `--check` when either file is staged.  Enable with `git config core.hooksPath .githooks`.
- **CI workflow** — `.github/workflows/qa-sync-check.yml` runs `--check` on every PR that touches the QA guide, spreadsheet, or sync script.

## Documentation

- [Requirements Documents](documents/requirements)
- [ECUBE Requirements Overview](documents/requirements/00-overview.md)
- [Security & Access Control (Requirements)](documents/requirements/10-security-and-access-control.md)
- [Design Documents](documents/design)
- [ECUBE Design Overview](documents/design/00-overview.md)
- [Security & Access Control (Design)](documents/design/10-security-and-access-control.md)
- [Testing & Validation (Design)](documents/design/11-testing-and-validation.md)
- [Hardware HIL Testing (USB Hub/Devices)](documents/design/11-testing-and-validation.md#1110-hardware-hil-testing-usb-hub-and-devices)
- [Linux Host Deployment & USB Passthrough](documents/design/12-linux-host-deployment-and-usb-passthrough.md)
- [Build & Deployment (Design)](documents/design/13-build-and-deployment.md)
