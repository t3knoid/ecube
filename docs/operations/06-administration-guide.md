# ECUBE Administration Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, Operators, IT Staff  
**Document Type:** Operational Procedures

---

## Table of Contents

1. [System Overview](#system-overview)
2. [First-Time Setup](#first-time-setup)
3. [User Management](#user-management)
4. [Drive Management](#drive-management)
5. [Job Management](#job-management)
6. [Mount Management](#mount-management)
7. [Auditing](#auditing)
8. [Monitoring and Logs](#monitoring-and-logs)
9. [Troubleshooting](#troubleshooting)
10. [Backup and Recovery](#backup-and-recovery)
11. [Maintenance](#maintenance)

---

## System Overview

### Architecture

ECUBE consists of three components:

```text
┌─────────────────────────────────────────────────────────────┐
│ UI Layer (Web Browser)                                      │
│ - Displays job status, drive inventory, audit logs          │
│ - Makes authenticated API calls via HTTPS                   │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTPS (REST API)
┌────────────────────▼────────────────────────────────────────┐
│ System Layer (FastAPI Service)                              │
│ - Validates tokens and authorizations                       │
│ - Manages mounts, drives, copy jobs                         │
│ - Writes audit logs to database                             │
│ - Executes copy operations                                  │
└────────────────────┬────────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────────┐
│ Data & Hardware                                             │
│ - PostgreSQL database (job state, audit logs, drive state)  │
│ - USB drives, NFS/SMB mounts, Linux /dev interfaces         │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. Operator logs in via UI with username/password or SSO token
2. UI authenticates against ECUBE API (`POST /auth/token` → JWT bearer token)
3. API validates credentials via PAM (or OIDC/LDAP)
4. Roles resolved using a **DB-first hybrid model**:
   - Check `user_roles` table for explicit role assignments → use if found
   - Fall back to OS group memberships + `LOCAL_GROUP_ROLE_MAP` → use if found
   - No roles from either source → 403 Forbidden
5. JWT issued with resolved roles
6. Each subsequent API call validates roles from JWT claims
7. Role checked against operation (e.g., "processor" can start jobs, "auditor" can only read)
8. Operation executed (e.g., mount network share, initialize drive, start copy)
9. All actions logged to audit table with timestamp, user, action, result

### Key Characteristics

- Secure, single-purpose evidence export appliance
- Centralized audit logging of all operations
- Hardware-aware USB drive and mount management
- Role-based access control (admin, manager, processor, auditor)
- REST API for integration with external systems

---

## First-Time Setup

Before ECUBE can be used, the system must be initialized. This is a one-time
process that creates the required OS groups, the initial admin user (as a
real Linux account on the host or container), and seeds the database with the
admin role assignment.

### Prerequisites

- The ECUBE service must be running and the database must be provisioned with
  migrations applied. See [04-package-deployment.md](04-package-deployment.md)or [05-docker-deployment.md](05-docker-deployment.md) for deployment steps.

### Database Provisioning

Before the system can be initialized, the PostgreSQL database must be
reachable and properly provisioned. ECUBE provides API endpoints for testing
connectivity, provisioning the database, and checking migration status.

#### Test Database Connection

```bash
# Unauthenticated (before first admin exists) or requires admin role
curl -k -X POST https://localhost:8443/setup/database/test-connection
```

Returns connection status. Use this to verify PostgreSQL is reachable before
provisioning.

#### Provision Database

Creates the application user, database, and runs Alembic migrations:

```bash
# Unauthenticated (before first admin exists) or requires admin role
curl -k -X POST https://localhost:8443/setup/database/provision
```

> **Note:** This is safe to re-run — Alembic migrations are idempotent.
> After initial setup, this endpoint requires admin authentication.
>
> **Migration 0008 — Unique port system_path:** This migration adds a unique
> constraint to `usb_ports.system_path`. Before applying the constraint it
> automatically de-duplicates any existing rows: the lowest-id row for each
> `system_path` is kept, non-null attribute values (`friendly_label`,
> `enabled`, `vendor_id`, `product_id`, `speed`) are coalesced from
> duplicates into the survivor, drives are re-pointed, and duplicate rows
> are deleted. No manual intervention is required.

#### Check Database Status

```bash
# Requires admin role
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/setup/database/status
```

Returns database connection health and current migration revision.

#### Update Database Settings

```bash
# Requires admin role
curl -k -X PUT https://localhost:8443/setup/database/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"database_url": "postgresql://ecube:newpass@db-host:5432/ecube"}'
```

Updates the database connection string and reinitializes the connection pool.

### Check Initialization Status

```bash
# Bare-metal (HTTPS on port 8443)
curl -k https://localhost:8443/setup/status

# Docker (HTTP on port 8000)
curl http://localhost:8000/setup/status
```

Response when not yet initialized:

```json
{"initialized": false}
```

### Initialize the System

#### Option A: API-based (recommended)

The `username` and `password` you provide will be used to create a **real Linux operating system account** on the host machine (or inside the Docker container). The username must follow Linux naming rules (lowercase
alphanumeric, hyphens, underscores — no spaces or uppercase). The password becomes the OS account password and is also used to authenticate via `POST /auth/token` after setup.

```bash
# Bare-metal
curl -k -X POST https://localhost:8443/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
```

```bash
# Docker
curl -X POST http://localhost:8000/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
```

```powershell
# Powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/setup/initialize \
  -ContentType "application/json" \
  -Body '{"username": "ecube-admin", "password": "s3cret"}'
```

#### Option B: CLI setup script

```bash
# Bare-metal
sudo /opt/ecube/venv/bin/ecube-setup

# Docker
docker exec -it <container-name> ecube-setup
```

### What Initialization Does

The initialization endpoint performs the following steps in order:

1. **Acquires a lock** — inserts a row into the `system_initialization` table
   to prevent concurrent initialization attempts.
2. **Creates OS groups** — `ecube-admins`, `ecube-managers`,
   `ecube-processors`, `ecube-auditors`.
3. **Creates the admin OS user** — the username you provide becomes an actual
   Linux user account (via `useradd`) on the host system or inside the
   container. The user is added to the `ecube-admins` group with the
   specified password.
4. **Seeds the database** — inserts a `user_roles` record assigning the
   `admin` role to the new user.
5. **Records an audit event** — logs `SYSTEM_INITIALIZED` with a timestamp
   and the admin username.

> **Important:** The username must be a valid Linux username (lowercase
> alphanumeric, hyphens, underscores). It does not need to be a
> pre-existing account — the endpoint creates it. If a user with that name
> already exists, the endpoint adds it to `ecube-admins` and resets its
> password to the value provided.

### Security Notes

- The endpoint is **unauthenticated** (no token needed) but **can only
  succeed once**. Subsequent calls return `409 Conflict`.
- Choose a strong password — this account has unrestricted admin access.
- After initialization, authenticate with the new admin account to obtain
  a JWT token, then use it to create additional users and assign roles.

### After Initialization

```bash
# 1. Log in with the admin account
curl -k -X POST https://localhost:8443/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'

# 2. Use the returned token for all subsequent operations
export TOKEN="<access_token from response>"

# 3. Verify access
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/version
```

From here, proceed to [User Management](#user-management) to create additional users, or [Common Operational Tasks](#common-operational-tasks) to begin using ECUBE.

---

## User Management

### Authentication Methods

#### Local Identity (Default — PAM Authentication)

ECUBE authenticates users via PAM on the host OS. Users log in by calling `POST /auth/token` with their OS username and password. The system validates credentials through PAM, then resolves roles using a **DB-first hybrid model**:
explicit role assignments in the `user_roles` table take priority, with OS group memberships serving as a fallback. A signed JWT is returned containing the resolved roles. See [Assigning Roles](#assigning-roles) for the full resolution
flow.

**Login example:**

```bash
# Authenticate and receive a token
curl -k -X POST https://localhost:8443/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "frank", "password": "mypassword"}'

# Response:
# {"access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer"}

# Use the token for subsequent API calls
export TOKEN="eyJhbGciOiJIUzI1NiIs..."
curl -k -H "Authorization: Bearer $TOKEN" https://localhost:8443/drives
```

**Requirements:**

- The ECUBE service account must have PAM access (typically membership in
  the `shadow` group or equivalent).
- No external user database is required — PAM delegates credential validation
  to whatever backend the host is configured for (`/etc/shadow`, SSSD,
  Kerberos, etc.). Role assignments are stored in the ECUBE database
  (`user_roles` table), with OS group memberships as a fallback.
- Passwords are never logged or stored by ECUBE.

#### LDAP Integration

Configure LDAP server and group-to-role mapping:

```bash
ROLE_RESOLVER=ldap
LDAP_SERVER=ldap://ad.example.com
LDAP_BIND_DN=cn=svc-account,cn=Users,dc=example,dc=com
LDAP_BIND_PASSWORD=secret
LDAP_BASE_DN=dc=example,dc=com
LDAP_GROUP_ROLE_MAP='{"CN=EvidenceAdmins,OU=Groups,DC=example,DC=com": ["admin"]}'
```

#### OIDC Integration

For cloud identity providers (Okta, Auth0, Azure AD, Google Cloud Identity, etc.):

```bash
ROLE_RESOLVER=oidc
OIDC_DISCOVERY_URL=https://auth.example.com/.well-known/openid-configuration
OIDC_CLIENT_ID=your-client-id
OIDC_CLIENT_SECRET=your-client-secret  # Not used for token validation; for provider integration only
OIDC_AUDIENCE=your-client-id            # Optional; validates 'aud' claim in token
OIDC_GROUP_CLAIM_NAME=groups            # Which JWT claim contains group memberships
OIDC_GROUP_ROLE_MAP='{"admin-group": ["admin"], "ops-group": ["processor"]}'
```

**Network Requirements:**

- HTTPS outbound access to OIDC provider's discovery URL
- HTTPS outbound access to provider's JWKS endpoint (cached for process lifetime)
- Recommend 10-second timeout for initial discovery URL fetch

##### OIDC Provider Examples

**Okta**

```bash
ROLE_RESOLVER=oidc
OIDC_DISCOVERY_URL=https://<YOUR_OKTA_DOMAIN>/oauth2/default/.well-known/openid-configuration
OIDC_CLIENT_ID=<YOUR_CLIENT_ID>
OIDC_CLIENT_SECRET=<YOUR_CLIENT_SECRET>
OIDC_GROUP_CLAIM_NAME=groups
OIDC_GROUP_ROLE_MAP='{"EvidenceAdmins": ["admin"], "EvidenceTeam": ["processor"]}'
```

**Auth0**

```bash
ROLE_RESOLVER=oidc
OIDC_DISCOVERY_URL=https://<YOUR_AUTH0_DOMAIN>/.well-known/openid-configuration
OIDC_CLIENT_ID=<YOUR_CLIENT_ID>
OIDC_CLIENT_SECRET=<YOUR_CLIENT_SECRET>
OIDC_GROUP_CLAIM_NAME=org_groups
OIDC_GROUP_ROLE_MAP='{"evidence-admins": ["admin"], "evidence-team": ["processor", "auditor"]}'
```

**Azure AD (OIDC mode)**

```bash
ROLE_RESOLVER=oidc
OIDC_DISCOVERY_URL=https://login.microsoftonline.com/<TENANT_ID>/v2.0/.well-known/openid-configuration
OIDC_CLIENT_ID=<YOUR_CLIENT_ID>
OIDC_CLIENT_SECRET=<YOUR_CLIENT_SECRET>
OIDC_AUDIENCE=<YOUR_CLIENT_ID>
OIDC_GROUP_CLAIM_NAME=groups
OIDC_GROUP_ROLE_MAP='{"<ObjectId_of_AdminGroup>": ["admin"]}'
```

**Google Cloud Identity**

```bash
ROLE_RESOLVER=oidc
OIDC_DISCOVERY_URL=https://accounts.google.com/.well-known/openid-configuration
OIDC_CLIENT_ID=<YOUR_CLIENT_ID>
OIDC_CLIENT_SECRET=<YOUR_CLIENT_SECRET>
OIDC_AUDIENCE=<YOUR_CLIENT_ID>
OIDC_GROUP_CLAIM_NAME=groups
OIDC_GROUP_ROLE_MAP='{"evidence-admins@example.com": ["admin"]}'
```

##### Troubleshooting OIDC

| Issue | Cause | Resolution |
| ------- | ------- | ----------- |
| `401 OIDC is enabled but 'oidc_discovery_url' is not configured` | Missing env var | Set `OIDC_DISCOVERY_URL` |
| `401 OIDC token has expired` | Token past expiration time | Ensure client refreshes tokens before expiry |
| `401 OIDC token audience mismatch` | `aud` claim doesn't match `OIDC_AUDIENCE` | Verify `OIDC_AUDIENCE` matches your provider's client ID |
| `403` on all requests | Groups present but none mapped | Add user's groups to `OIDC_GROUP_ROLE_MAP` |
| `401 Failed to obtain signing key` | JWKS endpoint unreachable | Check network access from ECUBE host to provider's JWKS endpoint |
| Tokens always rejected even when valid | Discovery document fetch timeout | Increase network timeout; check OIDC_DISCOVERY_URL is correct |

### ECUBE Roles

| Role | Permissions |
| ------ | ------------- |
| **admin** | Unrestricted access to all operations |
| **manager** | Drive lifecycle, mount management, job oversight |
| **processor** | Create and start jobs, view status |
| **auditor** | Read-only access to audit logs, file metadata |

### Assigning Roles

ECUBE uses a **DB-first hybrid model** to resolve roles at login time:

1. User calls `POST /auth/token` with username and password
2. PAM validates credentials against the host OS (or LDAP/Kerberos via PAM)
3. Check the `user_roles` database table for explicit role assignments → use if found
4. Fall back to OS group memberships + `LOCAL_GROUP_ROLE_MAP` (or `LDAP_GROUP_ROLE_MAP`) → use if found
5. No roles from either source → 403 Forbidden
6. A signed JWT is issued containing the resolved roles
7. Each subsequent API call validates roles from the JWT claims

**Example Flow:**

```text
User "alice" calls POST /auth/token
    → PAM validates password
    → DB lookup: user_roles("alice") → ["admin"]    # found → use these
    → JWT issued with roles=["admin"]
    → All endpoints accessible until token expires

User "bob" calls POST /auth/token
    → PAM validates password
    → DB lookup: user_roles("bob") → []              # empty → fall back
    → OS groups: ["ecube-processors", "users"]
    → LOCAL_GROUP_ROLE_MAP: "ecube-processors" → ["processor"]
    → JWT issued with roles=["processor"]
```

#### Two Operational Modes

| Stage | Role Source | Managed By |
|---|---|---|
| Initial setup / fallback | OS groups + `LOCAL_GROUP_ROLE_MAP` | Setup script / `.env` |
| Day-to-day operations | `user_roles` table (DB) | Admin via API |

The OS group fallback ensures that a freshly deployed system works immediately
after first-run setup — the admin user is a member of `ecube-admins`
**and** has an explicit DB role. As the deployment matures, admins can manage
all role assignments through the API and the DB takes precedence.

**Note:** If a user's role assignments or group memberships change, they must
re-authenticate (obtain a new token) for the updated roles to take effect.
The old token retains the previous roles until it expires.

### Admin Role Management API

Administrators can manage user role assignments through the following
endpoints. All require the `admin` role.

#### List all users with roles

```bash
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/users
```

Response:

```json
{
  "users": [
    {"username": "alice", "roles": ["admin"]},
    {"username": "bob", "roles": ["processor"]}
  ]
}
```

#### Get roles for a specific user

```bash
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/users/alice/roles
```

Response:

```json
{"username": "alice", "roles": ["admin"]}
```

#### Set roles for a user (replaces all existing assignments)

```bash
curl -k -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"roles": ["manager", "processor"]}' \
  https://localhost:8443/users/bob/roles
```

Response:

```json
{"username": "bob", "roles": ["manager", "processor"]}
```

#### Remove all roles for a user

```bash
curl -k -X DELETE -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/users/bob/roles
```

Response:

```json
{"username": "bob", "roles": []}
```

> **Note:** Removing all DB roles does not lock out a user if they still
> have OS group memberships that map to ECUBE roles — the fallback will
> apply on their next login.

### OS User & Group Management API

Administrators can create and manage OS-level user accounts and groups
directly through the API. All endpoints require the `admin` role.

#### List OS users

```bash
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/admin/os-users
```

#### Create an OS user

```bash
curl -k -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "frank", "password": "s3cret", "groups": ["ecube-processors"]}' \
  https://localhost:8443/admin/os-users
```

#### Reset a user's password

```bash
curl -k -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "newpassword"}' \
  https://localhost:8443/admin/os-users/frank/password
```

#### Delete an OS user

```bash
curl -k -X DELETE -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/admin/os-users/frank
```

#### Set a user's group memberships (replaces all ECUBE groups)

```bash
curl -k -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"groups": ["ecube-processors", "ecube-auditors"]}' \
  https://localhost:8443/admin/os-users/frank/groups
```

#### Add a user to additional groups

```bash
curl -k -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"groups": ["ecube-managers"]}' \
  https://localhost:8443/admin/os-users/frank/groups
```

#### List OS groups / Create / Delete a group

```bash
# List
curl -k -H "Authorization: Bearer $TOKEN" https://localhost:8443/admin/os-groups

# Create
curl -k -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "ecube-reviewers"}' \
  https://localhost:8443/admin/os-groups

# Delete
curl -k -X DELETE -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/admin/os-groups/ecube-reviewers
```

> **Security:** Reserved system usernames (root, daemon, bin, etc.) are
> rejected by all mutation endpoints. All operations are recorded in
> `audit_logs`.

---

## Drive Management

USB drives follow a strict lifecycle managed through the API. This section
covers every drive operation from discovery through ejection.

### Drive Lifecycle

Every USB drive passes through three states:

```text
  ┌───────────┐    discovery    ┌──────────────┐   initialize   ┌──────────┐
  │   EMPTY   │ ──────────────► │  AVAILABLE   │ ─────────────► │  IN_USE  │
  └───────────┘                 └──────────────┘                └──────────┘
        ▲                           ╭─╮ ▲                            │
        │        drive removed      │ │ │       prepare-eject        │
        └───────────────────────────┘ │ └◄───────────────────────────┘
                               format ╯
```

| State | Meaning |
|-------|----------|
| `EMPTY` | Drive known to the database but not physically present |
| `AVAILABLE` | Drive is present and ready to be formatted (if needed) and assigned to a project |
| `IN_USE` | Drive is bound to a project and actively receiving evidence |

Key behaviors:

- **Discovery sync** detects newly inserted drives and transitions `EMPTY → AVAILABLE` — but only if the drive's USB port is **enabled**. Drives on disabled ports remain in `EMPTY` state until the port is enabled and a subsequent discovery sync runs. If a port is disabled while a drive is already `AVAILABLE`, the next sync demotes the drive to `EMPTY`. Drives with no associated port (`port_id = NULL`) are treated as disabled and remain `EMPTY`. Drives in `IN_USE` state are never affected by port enablement — project isolation takes priority.
- **Format** writes a filesystem to the drive (stays `AVAILABLE`). Required before initialize — a drive with no recognized filesystem cannot be initialized.
- **Initialize** binds a drive to a project (`AVAILABLE → IN_USE`).
- **Eject** flushes writes, unmounts, and returns the drive to `AVAILABLE` (`IN_USE → AVAILABLE`). The project binding is preserved.
- **Physical removal** of an `AVAILABLE` drive transitions it back to `EMPTY`. An `IN_USE` drive retains its state and project binding across removal and reinsertion.

### List Drives

Returns all known USB drives with their current state, device path, serial
number, and project assignment.

```bash
# Requires any authenticated role
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/drives
```

Example response:

```json
[
  {
    "id": 1,
    "port_id": 3,
    "device_identifier": "4C530000220226223012",
    "filesystem_path": "/dev/sdg",
    "capacity_bytes": 15376000000,
    "filesystem_type": "ext4",
    "current_state": "IN_USE",
    "current_project_id": "PROJECT-42"
  },
  {
    "id": 2,
    "port_id": 4,
    "device_identifier": "A1B2C3D4E5F60001",
    "filesystem_path": "/dev/sdh",
    "capacity_bytes": 64023257088,
    "filesystem_type": "exfat",
    "current_state": "AVAILABLE",
    "current_project_id": null
  }
]
```

To filter by state, use `jq` client-side:

```bash
# List only drives that are IN_USE
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/drives | jq '[.[] | select(.current_state == "IN_USE")]'

# List only AVAILABLE drives
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/drives | jq '[.[] | select(.current_state == "AVAILABLE")]'
```

```powershell
# PowerShell: list only IN_USE drives
(Invoke-RestMethod -Uri http://localhost:8000/drives `
  -Headers @{ Authorization = "Bearer $TOKEN" }) |
  Where-Object { $_.current_state -eq "IN_USE" }
```

### Refresh / Discovery Sync

Triggers a manual scan of USB hubs, ports, and drives from system sources
(`/sys/bus/usb/devices`). Upserts the hardware topology into the database
and recomputes drive states according to the finite-state machine rules.
The operation is idempotent. Each port is uniquely identified by its
`system_path`; concurrent discovery requests are safe — duplicate inserts
are caught and retried as updates.

```bash
# Requires admin or manager role
curl -k -X POST https://localhost:8443/drives/refresh \
  -H "Authorization: Bearer $JWT_TOKEN"
```

> **Note:** Discovery also runs automatically when the service starts.
> Use this endpoint to pick up drives that were inserted after startup
> without restarting the service.

### Port Management

USB ports default to **disabled** when first discovered. Drives on disabled
ports remain in `EMPTY` state and cannot transition to `AVAILABLE` until the
port is explicitly enabled by an admin or manager. This allows operators to
control which physical ports are active for evidence export.

#### List Ports

Returns all known USB ports with their current enablement state.

```bash
# Requires admin or manager role
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/admin/ports
```

Example response:

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
  },
  {
    "id": 2,
    "hub_id": 1,
    "port_number": 2,
    "system_path": "1-2",
    "friendly_label": null,
    "enabled": true,
    "vendor_id": null,
    "product_id": null,
    "speed": null
  }
]
```

#### Enable or Disable a Port

Toggles the enablement state of a USB port. The change takes effect on the
next discovery sync.

```bash
# Requires admin or manager role

# Enable a port
curl -k -X PATCH https://localhost:8443/admin/ports/1 \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'

# Disable a port
curl -k -X PATCH https://localhost:8443/admin/ports/1 \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

Response: returns the updated port object.

> **Note:** Disabling a port does **not** affect drives already in `IN_USE`
> state — project isolation takes priority. To make drives on a newly
> enabled port available, run a discovery refresh (`POST /drives/refresh`)
> after enabling the port.

### Hub Management

USB hubs are automatically discovered during the discovery sync.  Each hub
record includes hardware metadata (`vendor_id`, `product_id`) read from
sysfs, and an optional admin-assigned `location_hint` label for physical
identification.

#### List Hubs

Returns all known USB hubs with their hardware metadata and labels.

```bash
# Requires admin or manager role
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/admin/hubs
```

Example response:

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

#### Set Hub Location Hint

Assigns or updates the `location_hint` label on a hub. This label is
preserved across discovery resync cycles.

```bash
# Requires admin or manager role
curl -k -X PATCH https://localhost:8443/admin/hubs/1 \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"location_hint": "back-left rack"}'
```

Response: returns the updated hub object.

### Port Labeling

Each port can be given a human-readable `friendly_label` for easier physical
identification. Labels are preserved across discovery resync cycles.

#### Set Port Label

```bash
# Requires admin or manager role
curl -k -X PATCH https://localhost:8443/admin/ports/1/label \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"friendly_label": "Bay 3 - Top Left"}'
```

Response: returns the updated port object including `vendor_id`, `product_id`,
and `speed` fields populated during discovery.

> **Note:** The `vendor_id`, `product_id`, and `speed` fields on ports are
> automatically populated from sysfs during USB discovery. They are visible in
> port listing responses (`GET /admin/ports`) and cannot be set through the API.

### Format Drive

Formats a drive with the specified filesystem. Supported types: `ext4`
(Linux-native, recommended for large evidence sets) and `exfat`
(cross-platform, readable on Windows/macOS).

```bash
# Requires admin or manager role
# Format with ext4
curl -k -X POST https://localhost:8443/drives/1/format \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filesystem_type": "ext4"}'

# Format with exFAT
curl -k -X POST https://localhost:8443/drives/1/format \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filesystem_type": "exfat"}'
```

Response: returns the updated drive object with `filesystem_type` set to the
new value and `current_state` unchanged (`AVAILABLE`).

> **Note:** The drive must be in `AVAILABLE` state and not currently mounted.
> Formatting erases all data on the drive. Replace `1` with the actual drive
> ID from `GET /drives`.

### Initialize Drive

Binds a drive to a project for isolation enforcement. This transitions the
drive from `AVAILABLE` to `IN_USE` and sets `current_project_id`. Once
bound, the drive will only accept copy jobs for its designated project.

```bash
# Requires admin or manager role
curl -k -X POST https://localhost:8443/drives/1/initialize \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "PROJECT-42"}'
```

Response: returns the updated drive object with `current_state: "IN_USE"`
and `current_project_id` set to the provided project ID.

> **Note:** The drive must be in `AVAILABLE` state and have a recognized
> filesystem. The project binding is enforced at copy time — any attempt
> to write data from a different project will be rejected and audited.

### Eject Drive

Prepares a drive for safe physical removal. This flushes pending writes
to disk, unmounts the device, and transitions the drive back to `AVAILABLE`.

```bash
# Requires admin or manager role
curl -k -X POST https://localhost:8443/drives/1/prepare-eject \
  -H "Authorization: Bearer $JWT_TOKEN"
```

Response: returns the updated drive object with `current_state: "AVAILABLE"`.
The `current_project_id` field remains set.

> **Note:** The drive must be in `IN_USE` state. After a successful response
> the drive can be safely physically removed. The project binding
> (`current_project_id`) is preserved — reinserting the same drive will
> restore it as `IN_USE` for the same project on the next discovery sync.

---

## Job Management

Export jobs copy evidence data from a network mount (or local path) to an
assigned USB drive. This section covers the full job lifecycle from creation
through verification and manifest generation.

### Job Lifecycle

Every export job passes through a defined set of states:

```text
  ┌──────────┐    start     ┌──────────┐                ┌─────────────┐
  │ PENDING  │ ────────────►│ RUNNING  │──────────────► │  COMPLETED  │
  └──────────┘              └──────────┘   success      └─────────────┘
       │                         │                             ▲
       │                         │ failure    ┌──────────┐     │ pass
       │                         └──────────► │  FAILED  │     │
       │                                      └──────────┘     │
       │                                                       │
       │                    ┌────────────┐    verify           │
       │                    │ VERIFYING  │────────────────────►│
       │                    └────────────┘         ▲           │
       │                                           │           │
       └───────────────────────────────────────────┘           │
                         (after RUNNING completes)     fail ──►│
                                                        FAILED
```

| State | Meaning |
|-------|----------|
| `PENDING` | Job created but not yet started |
| `RUNNING` | Copy is actively in progress (background task) |
| `VERIFYING` | Hash verification of copied files in progress |
| `COMPLETED` | All files copied and (optionally) verified successfully |
| `FAILED` | Copy or verification encountered an unrecoverable error |

Key behaviors:

- **Create** registers the job with source path, project ID, and evidence number. The job starts in `PENDING`.
- **Start** launches the background copy process (`PENDING → RUNNING`). Progress is tracked via `copied_bytes` and per-file status.
- **Verify** (optional) compares checksums of copied files against source (`RUNNING/completed → VERIFYING → COMPLETED` or `FAILED`).
- **Manifest** generates a JSON document on the USB drive listing all copied files with their checksums, sizes, and metadata.
- Failed files are automatically retried up to `max_file_retries` times with a configurable delay.

### Create Export Job

Registers a new export job. The job's `project_id` must match the target
drive's `current_project_id` — project isolation is enforced at copy time.

```bash
# Requires admin, manager, or processor role
curl -k -X POST https://localhost:8443/jobs \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "PROJECT-42",
    "evidence_number": "EV-2026-001",
    "source_path": "/mnt/evidence/case-001",
    "drive_id": 1,
    "thread_count": 4
  }'
```

Optional parameters:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `drive_id` | `null` | Pre-assign a specific USB drive (omit for auto-assignment) |
| `thread_count` | `4` | Parallel copy threads (1–8) |
| `max_file_retries` | `3` | Maximum retry attempts per failed file |
| `retry_delay_seconds` | `1` | Delay between retries in seconds |

#### Automatic Drive Assignment

When `drive_id` is omitted from the request, ECUBE automatically selects a
drive using strict disambiguation rules:

1. **Single project-bound drive** — If exactly one `AVAILABLE` drive is already
   bound to the job's `project_id`, it is selected automatically. If the drive
   is temporarily unavailable (e.g. locked by a concurrent operation or its
   state changed), the request fails with HTTP 409 — the caller should retry
   after a short delay.
2. **Unbound fallback** — If no project-bound drives are available, the system
   picks the first `AVAILABLE` drive with no project binding and assigns the
   project to it.
3. **Multiple project-bound drives (409)** — If more than one `AVAILABLE` drive
   is bound to the project, the request fails with HTTP 409. The caller must
   specify `drive_id` to disambiguate.
4. **No usable drive (409)** — If no `AVAILABLE` drive is bound to the project
   and no unbound `AVAILABLE` drive can be acquired, the request fails with
   HTTP 409. The caller should retry, as drives may be temporarily held by
   concurrent operations.

When `drive_id` is provided explicitly, the system validates project isolation
and requires the drive to be in `AVAILABLE` state (drives in `EMPTY`, `IN_USE`,
or any other state are rejected with HTTP 409). If the drive is currently
unbound (`current_project_id` is null), the system binds it to the requested
project before committing, consistent with auto-assignment behaviour.

> **Drive Capacity Warning**
>
> ECUBE does **not** validate free space on the target drive before or during
> copy operations. The system tracks `capacity_bytes` (total drive size from
> sysfs) but does not compare source data size against available drive space.
> If the drive fills up during a copy, individual files will fail with write
> errors.
>
> It is the **caller's responsibility** to ensure the target drive has
> sufficient space for the data being copied. This is especially critical for
> automated or third-party integrations where the operator may not be
> monitoring drive usage in real time.
>
> When a project has multiple drives, choosing the correct drive (by specifying
> `drive_id`) also serves as an implicit capacity decision — the caller selects
> the drive they know has room.

Response:

```json
{
  "id": 1,
  "project_id": "PROJECT-42",
  "evidence_number": "EV-2026-001",
  "source_path": "/mnt/evidence/case-001",
  "target_mount_path": null,
  "status": "PENDING",
  "total_bytes": 0,
  "copied_bytes": 0,
  "file_count": 0,
  "thread_count": 4,
  "max_file_retries": 3,
  "retry_delay_seconds": 1,
  "created_by": "ecube-admin"
}
```

> **Note:** The `source_path` must be accessible from the ECUBE service
> (e.g., a mounted NFS/SMB share). Use the [Add Network Mount](#task-1-add-network-mount)
> task to configure mounts before creating jobs.

### View Job Status

Returns the current state, progress counters, and metadata for an export job.

```bash
# Requires any authenticated role
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/jobs/1
```

Key fields in the response:

| Field | Description |
|-------|-------------|
| `status` | Current job state (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `VERIFYING`) |
| `total_bytes` | Total bytes to copy |
| `copied_bytes` | Bytes copied so far (use for progress calculation) |
| `file_count` | Total number of files in the job |

Example response (job in progress):

```json
{
  "id": 1,
  "project_id": "PROJECT-42",
  "evidence_number": "EV-2026-001",
  "source_path": "/mnt/evidence/case-001",
  "status": "RUNNING",
  "total_bytes": 5368709120,
  "copied_bytes": 2147483648,
  "file_count": 342,
  "thread_count": 4
}
```

### Start Copy Job

Launches the background copy process. The job transitions from `PENDING` to
`RUNNING` and files begin copying using the configured thread count.

```bash
# Requires admin, manager, or processor role
curl -k -X POST https://localhost:8443/jobs/1/start \
  -H "Authorization: Bearer $JWT_TOKEN"
```

To override the thread count at start time:

```bash
curl -k -X POST https://localhost:8443/jobs/1/start \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"thread_count": 2}'
```

Response: returns the job object with `status: "RUNNING"`.

> **Note:** The copy runs as a background task. Poll `GET /jobs/{id}` to
> monitor progress. Per-file status (`PENDING`, `COPYING`, `DONE`, `ERROR`,
> `RETRYING`) is tracked in the `export_files` table.

### Verify Copied Data

After the copy completes, verify file integrity by comparing checksums
between source and destination.

```bash
# Requires admin, manager, or processor role
curl -k -X POST https://localhost:8443/jobs/1/verify \
  -H "Authorization: Bearer $JWT_TOKEN"
```

> **Note:** Verification runs as a background task (`VERIFYING` state).
> On success the job transitions to `COMPLETED`; on failure it transitions
> to `FAILED`. Poll `GET /jobs/{id}` for the final result.

### Generate Manifest

Creates a JSON manifest file on the USB drive listing all copied files with
their checksums, sizes, and job metadata. Used for chain-of-custody
documentation and compliance audits.

```bash
# Requires admin, manager, or processor role
curl -k -X POST https://localhost:8443/jobs/1/manifest \
  -H "Authorization: Bearer $JWT_TOKEN"
```

> **Note:** The manifest is written to the target USB drive as a plain JSON
> file. It can be generated at any point after the job has started.

### Get File Hashes

Retrieve the MD5 and SHA-256 hashes for a single export file. Useful for
individual file auditing.

```bash
# Requires admin or auditor role
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/files/42/hashes
```

Example response:

```json
{
  "file_id": 42,
  "relative_path": "docs/report.pdf",
  "md5": "d41d8cd98f00b204e9800998ecf8427e",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb924...f0",
  "size_bytes": 1048576
}
```

### Compare File Hashes

Compare the hashes of two individual files to verify they are identical.
Useful for spot-checking specific files across source and destination.

```bash
# Requires any authenticated role
curl -k -X POST https://localhost:8443/files/compare \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_id_a": 42, "file_id_b": 108}'
```

Example response:

```json
{
  "match": true,
  "hash_match": true,
  "size_match": true,
  "path_match": true,
  "file_a": {
    "file_id": 42,
    "relative_path": "docs/report.pdf",
    "sha256": "a1b2c3...f0",
    "size_bytes": 1048576
  },
  "file_b": {
    "file_id": 108,
    "relative_path": "docs/report.pdf",
    "sha256": "a1b2c3...f0",
    "size_bytes": 1048576
  }
}
```

### Typical Job Workflow

A complete evidence export follows this sequence:

1. **Mount source** — add a network mount pointing to the evidence share
2. **Enable ports** — enable the USB ports you want to use (`PATCH /admin/ports/{id}`)
3. **Prepare drive** — discover, format, and initialize a USB drive for the project
3. **Create job** — `POST /jobs` with project ID, evidence number, source path, and drive ID
4. **Start copy** — `POST /jobs/{id}/start`
5. **Monitor progress** — poll `GET /jobs/{id}` until `status` is `COMPLETED` or `FAILED`
6. **Verify** — `POST /jobs/{id}/verify` to confirm data integrity
7. **Generate manifest** — `POST /jobs/{id}/manifest` for chain-of-custody records
8. **Eject drive** — `POST /drives/{id}/prepare-eject` for safe removal

---

## Mount Management

Network mounts provide access to evidence data stored on NFS or SMB shares.
Mounts must be registered before they can be used as source paths in export
jobs.

### Mount States

| State | Meaning |
|-------|----------|
| `MOUNTED` | Mount is active and accessible |
| `UNMOUNTED` | Mount is registered but not currently active |
| `ERROR` | Mount failed to connect — check credentials or network |

### List Mounts

Returns all registered network mounts and their current connectivity status.
Credentials are not included in the response.

```bash
# Requires any authenticated role
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/mounts
```

Example response:

```json
[
  {
    "id": 1,
    "type": "NFS",
    "remote_path": "nfs.example.com:/evidence",
    "local_mount_point": "/mnt/evidence",
    "status": "MOUNTED",
    "last_checked_at": "2026-03-18T14:30:00Z"
  },
  {
    "id": 2,
    "type": "SMB",
    "remote_path": "//fileserver/cases",
    "local_mount_point": "/mnt/cases",
    "status": "ERROR",
    "last_checked_at": "2026-03-18T14:30:00Z"
  }
]
```

### Add Mount

Registers a new network mount and attempts to connect immediately. The
resulting status reflects whether the mount succeeded.

```bash
# Requires admin or manager role
# NFS mount (no credentials needed)
curl -k -X POST https://localhost:8443/mounts \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "NFS",
    "remote_path": "nfs.example.com:/evidence",
    "local_mount_point": "/mnt/evidence"
  }'

# SMB mount with credentials
curl -k -X POST https://localhost:8443/mounts \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "SMB",
    "remote_path": "//fileserver/cases",
    "local_mount_point": "/mnt/cases",
    "username": "svc-ecube",
    "password": "s3cret"
  }'
```

Response: returns the mount object with `status` reflecting the connection
result (`MOUNTED` or `ERROR`).

> **Note:** As an alternative to inline credentials, use `credentials_file`
> to reference a file on the host containing credentials.

### Remove Mount

Deletes a mount configuration. Any in-progress jobs using this mount as a
source path may fail.

```bash
# Requires admin or manager role
curl -k -X DELETE https://localhost:8443/mounts/1 \
  -H "Authorization: Bearer $JWT_TOKEN"
```

Returns `204 No Content` on success.

### Validate Mount

Tests connectivity for a specific mount by attempting to reconnect with
stored credentials. Updates the mount's `status` and `last_checked_at`.

```bash
# Requires admin or manager role
curl -k -X POST https://localhost:8443/mounts/1/validate \
  -H "Authorization: Bearer $JWT_TOKEN"
```

Response: returns the updated mount object.

### Validate All Mounts

Tests connectivity for every registered mount in one call. Useful as a
pre-flight check before starting a batch of export jobs.

```bash
# Requires admin or manager role
curl -k -X POST https://localhost:8443/mounts/validate \
  -H "Authorization: Bearer $JWT_TOKEN"
```

Response: returns an array of all mount objects with updated statuses.

---

## Auditing

ECUBE maintains an append-only audit log that records every security-relevant
event in the system. Audit entries are structured JSON records stored in the
`audit_logs` database table. They cannot be modified or deleted through the
API — only queried and (optionally) purged by retention policy.

### What Gets Audited

Every audit entry contains:

| Field | Description |
|-------|-------------|
| `id` | Unique entry ID |
| `timestamp` | ISO 8601 timestamp (server time, UTC) |
| `user` | Username of the actor (null for system events) |
| `action` | Machine-readable action code |
| `job_id` | Related export job ID (if applicable) |
| `details` | Structured JSON metadata specific to the action |
| `client_ip` | Client IP address of the request originator (null for background/system events) |

### Audit Actions Reference

#### Authentication & Authorization

| Action | Trigger |
|--------|---------|
| `AUTH_FAILURE` | Failed login attempt |
| `AUTHORIZATION_DENIED` | User lacks required role for endpoint |

#### System Setup

| Action | Trigger |
|--------|---------|
| `SYSTEM_INITIALIZED` | First-time system initialization completed |
| `DATABASE_CONNECTION_TEST` | Database connectivity test executed |
| `DATABASE_PROVISIONED` | Database schema provisioned |
| `DATABASE_SETTINGS_UPDATED` | Application settings changed via API |

#### Drive Management

| Action | Trigger |
|--------|---------|
| `DRIVE_INITIALIZED` | Drive bound to a project |
| `DRIVE_FORMATTED` | Drive filesystem formatted |
| `DRIVE_FORMAT_FAILED` | Drive format operation failed |
| `DRIVE_FORMAT_DB_UPDATE_FAILED` | Format succeeded but DB update failed |
| `DRIVE_EJECT_PREPARED` | Drive flushed and unmounted for removal |
| `DRIVE_EJECT_FAILED` | Eject operation failed |
| `DRIVE_REMOVED` | Drive no longer detected during discovery sync |
| `INIT_REJECTED_FILESYSTEM` | Drive init rejected due to unsupported filesystem |
| `PROJECT_ISOLATION_VIOLATION` | Attempt to use drive bound to a different project |
| `USB_DISCOVERY_SYNC` | USB discovery scan completed |
| `PORT_ENABLED` | USB port enabled for ECUBE use |
| `PORT_DISABLED` | USB port disabled |

#### Job Lifecycle

| Action | Trigger |
|--------|---------|
| `JOB_CREATED` | New export job registered |
| `JOB_STARTED` | Copy process launched |
| `JOB_VERIFY_STARTED` | Hash verification started |
| `JOB_TIMEOUT` | Copy job exceeded time limit |
| `JOB_STATUS_PERSIST_FAILED` | Failed to save job status to database |
| `JOB_RECONCILED` | In-progress job (RUNNING/VERIFYING) failed during startup reconciliation |
| `MANIFEST_CREATED` | Manifest file generated on drive |

#### File Operations

| Action | Trigger |
|--------|---------|
| `FILE_COPY_START` | Individual file copy began |
| `FILE_COPY_SUCCESS` | File copied and checksummed successfully |
| `FILE_COPY_FAILURE` | File copy failed after all retries |
| `FILE_COPY_RETRY` | File copy retried after transient failure |
| `FILE_HASHES_RETRIEVED` | File hash lookup performed |
| `FILE_COMPARE` | Two files compared by hash |

#### Mount Management

| Action | Trigger |
|--------|---------|
| `MOUNT_ADDED` | Network mount registered and attempted |
| `MOUNT_REMOVED` | Network mount deleted |
| `MOUNT_VALIDATED` | Mount connectivity re-tested |
| `MOUNT_RECONCILED` | Mount state corrected during startup reconciliation (MOUNTED → UNMOUNTED/ERROR) |

#### Webhook Callbacks

| Action | Trigger |
|--------|---------|
| `CALLBACK_SENT` | Callback delivered successfully (HTTP 2xx) |
| `CALLBACK_DELIVERY_FAILED` | All retries exhausted, SSRF blocked, redirect received, or permanent failure |
| `CALLBACK_DELIVERY_DROPPED` | Delivery dropped due to backpressure (queue full) |

#### Administrative

| Action | Trigger |
|--------|---------|
| `LOG_FILES_LISTED` | Log file listing accessed |
| `LOG_FILE_DOWNLOADED` | Log file downloaded |

### Querying Audit Logs

The audit API supports filtering by user, action, job, time range, and
pagination.

```bash
# Requires admin, manager, or auditor role

# All recent entries (default limit: 100)
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/audit

# Filter by user and action
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?user=alice&action=JOB_STARTED&limit=50"

# Filter by job ID
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?job_id=42"

# Filter by time range (ISO 8601)
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?since=2026-03-01T00:00:00Z&until=2026-03-18T23:59:59Z"

# Pagination
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?limit=50&offset=100"
```

Supported query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `user` | string | — | Filter by username |
| `action` | string | — | Filter by action code |
| `job_id` | int | — | Filter by related job ID |
| `since` | datetime | — | Entries at or after this timestamp |
| `until` | datetime | — | Entries at or before this timestamp |
| `limit` | int | 100 | Maximum results (1–1000) |
| `offset` | int | 0 | Number of results to skip |

Example response:

```json
[
  {
    "id": 847,
    "timestamp": "2026-03-18T14:30:00Z",
    "user": "alice",
    "action": "JOB_STARTED",
    "job_id": 42,
    "details": {
      "thread_count": 4
    }
  },
  {
    "id": 846,
    "timestamp": "2026-03-18T14:29:55Z",
    "user": "alice",
    "action": "JOB_CREATED",
    "job_id": 42,
    "details": {
      "project_id": "PROJ-001",
      "evidence_number": "EV-2026-0042",
      "source_path": "/mnt/evidence/case42",
      "drive_id": 3
    }
  }
]
```

### Common Audit Queries

```bash
# Failed login attempts
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?action=AUTH_FAILURE&limit=100"

# All project isolation violations
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?action=PROJECT_ISOLATION_VIOLATION"

# Activity for a specific user
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?user=bob"

# Full timeline for a specific job
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?job_id=42"

# All drive events in a date range
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?action=DRIVE_INITIALIZED&since=2026-03-01T00:00:00Z"
```

### Retention and Cleanup

Audit logs are retained for a configurable period (default: **365 days**).
Expired logs are automatically purged at application startup.

After audit cleanup, **startup state reconciliation** runs automatically to
correct any stale state left by an unclean shutdown or reboot:

1. **Mount reconciliation** — verifies all `MOUNTED` mounts against the OS
   and transitions stale entries to `UNMOUNTED` (or `ERROR` if the OS check
   fails). Emits `MOUNT_RECONCILED` audit events.
2. **Job reconciliation** — marks any `RUNNING` or `VERIFYING` jobs as
   `FAILED` (no worker process survives a restart). Emits `JOB_RECONCILED`
   audit events.
3. **Drive reconciliation** — re-runs USB discovery to sync physical device
   presence with the database (same as a periodic discovery cycle).

Reconciliation is fully idempotent and each pass is error-isolated — a
failure in one pass does not block the others. No manual recovery steps are
required after a service restart.

| Setting | Default | Description |
|---------|---------|-------------|
| `AUDIT_LOG_RETENTION_DAYS` | `365` | Days to retain audit entries (0 = no auto-purge) |
| `AUDIT_LOG_DEFAULT_LIMIT` | `100` | Default page size for queries |
| `AUDIT_LOG_MAX_LIMIT` | `1000` | Maximum allowed page size |

To manually purge old entries via PostgreSQL:

```bash
psql -U ecube -d ecube << 'EOF'
DELETE FROM audit_logs
WHERE timestamp < NOW() - INTERVAL '1 year';
VACUUM ANALYZE audit_logs;
EOF
```

> **Note:** The audit log is append-only by design. There is no API endpoint
> to delete or modify audit entries. Manual purge should only be performed
> by a database administrator in accordance with your retention policy.

---

## Monitoring and Logs

### Service Logs

#### Systemd

```bash
# View recent logs
sudo journalctl -u ecube -n 100

# Follow logs in real-time
sudo journalctl -u ecube -f

# Filter by log level
sudo journalctl -u ecube -p err

# View logs for last 24 hours
sudo journalctl -u ecube --since "24 hours ago"
```

#### Docker Compose

```bash
# View logs
docker compose -f docker-compose.ecube.yml logs ecube-host

# Follow logs
docker compose -f docker-compose.ecube.yml logs -f ecube-host

# View specific number of lines
docker compose -f docker-compose.ecube.yml logs -n 100 ecube-host
```

### Database Logs

Monitor database performance and slow queries:

```bash
# Connect to PostgreSQL
psql -U ecube -d ecube -h localhost

# View recent activity
SELECT * FROM pg_stat_statements ORDER BY total_time DESC LIMIT 10;

# View audit logs
SELECT timestamp, user, action, job_id FROM audit_logs ORDER BY timestamp DESC LIMIT 50;
```

### System Metrics

Monitor CPU, memory, disk, and network:

```bash
# Overall system stats
top

# Disk usage
df -h /opt/ecube

# Network connections (port 8443)
sudo netstat -tlnp | grep 8443

# USB device enumeration
lsusb -v

# Process resource usage
ps aux | grep uvicorn
```

### Health Checks

```bash
# Basic health check (no auth required)
curl -k https://localhost:8443/health
# Response: {"status": "ok"}

# API version endpoint (no auth required)
curl -k https://localhost:8443/introspection/version

# System health — DB connectivity and active job count (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/system-health

# Drive inventory (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/drives

# Mount status (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/mounts

# USB topology — raw hub/port/device tree from sysfs (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/usb/topology

# Block devices — all devices detected by the kernel (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/block-devices

# Job debug info — detailed paths and file statuses (admin or auditor)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/jobs/1/debug
```

### Application Logs API

ECUBE exposes log files through the API for remote access without SSH.

```bash
# List available log files with size and timestamps (any authenticated user)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/admin/logs

# Download a specific log file (any authenticated user)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/admin/logs/ecube.log -o ecube.log
```

> **Note:** Path traversal is blocked server-side — only files within the
> configured log directory can be accessed.

---

## Troubleshooting

### Jobs Marked FAILED After Restart

**Symptom:** Jobs that were `RUNNING` or `VERIFYING` now show `FAILED` after
a service restart.

**Explanation:** This is expected behavior. Startup reconciliation
automatically fails any in-progress jobs because worker processes do not
survive a restart. Check the audit log for `JOB_RECONCILED` entries to
confirm:

```bash
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?action=JOB_RECONCILED"
```

Each entry includes the `old_status` and `reason: "interrupted by restart"`.
These jobs can be re-created and re-started normally.

### Mounts Showing UNMOUNTED or ERROR After Restart

**Symptom:** Network mounts that were `MOUNTED` now show `UNMOUNTED` or
`ERROR` after a restart.

**Explanation:** Startup reconciliation verifies each `MOUNTED` mount against
the OS. Mounts that are no longer active (e.g. the NFS/SMB server was
unreachable during shutdown) are corrected. Check audit log for
`MOUNT_RECONCILED` entries:

```bash
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  "https://localhost:8443/audit?action=MOUNT_RECONCILED"
```

Re-mount via `POST /mounts/{id}/validate` or re-add the mount as needed.

### Service Won't Start

**Symptom:** `systemctl start ecube` fails or service immediately stops.

**Debugging:**

```bash
# Check logs
sudo journalctl -u ecube -n 50

# Verify configuration file
cat /opt/ecube/.env

# Test Python import
sudo -u ecube /opt/ecube/venv/bin/python3 -c "import app.main" 2>&1

# Test database connection
sudo -u ecube /opt/ecube/venv/bin/python3 -c "import os; from sqlalchemy import create_engine, text; engine = create_engine(os.getenv('DATABASE_URL')); conn = engine.connect(); print(conn.execute(text('SELECT 1')).scalar()); conn.close()"
```

**Solutions:**

- Verify `.env` file exists and is readable: `sudo -u ecube cat /opt/ecube/.env`
- Check database connectivity: `psql -U ecube -d ecube -h localhost -c "SELECT 1"`
- Verify TLS certificate files exist: `ls -la /opt/ecube/certs/`
- Check disk space: `df -h /opt/ecube`

### High Memory Usage

**Symptom:** ECUBE process consuming >4GB RAM.

**Debugging:**

```bash
# Check process memory
ps aux | grep uvicorn
top -p $(pgrep -f uvicorn)

# Database connection pool status
psql -U ecube -d ecube -c "SELECT count(*) FROM pg_stat_activity WHERE datname='ecube';"
```

**Solutions:**

- Reduce uvicorn worker count in systemd service
- Add limit to `.env`: `MAX_POOL_SIZE=10`
- Check for long-running copy jobs: `curl -H "Authorization: Bearer $TOKEN" https://localhost:8443/jobs?status=running`

### API Returns 401 (Unauthorized)

**Symptom:** All API calls return `{"detail": "Missing authentication token"}`

**Debugging:**

```bash
# Check token format
echo $JWT_TOKEN | base64 -d | head -c 200

# Verify secret key matches
echo $SECRET_KEY
```

**Solutions:**

- Ensure `SECRET_KEY` environment variable matches token issuer
- Verify token is not expired: `python3 -c "import jwt; print(jwt.decode('$JWT_TOKEN', options={'verify_signature': False}))"`
- Check Authorization header format: `Authorization: Bearer <token>`

### API Returns 403 (Forbidden)

**Symptom:** Token valid but returns `{"detail": "Insufficient role"}`

**Debugging:**

```bash
# Decode token to see roles
python3 << 'EOF'
import jwt
token = "$JWT_TOKEN"
print(jwt.decode(token, options={"verify_signature": False}))
EOF

# Check group-to-role mapping
cat /opt/ecube/.env | grep ROLE_MAP
```

**Solutions:**

- Verify user's group is in `LOCAL_GROUP_ROLE_MAP` or LDAP mapping
- Check that mapped role is correct for requested action
- Verify `ROLE_RESOLVER` setting matches identity provider

### Copy Job Hangs or Times Out

**Symptom:** Job stuck in `RUNNING` state for hours.

**Debugging:**

```bash
# View job details
curl -H "Authorization: Bearer $TOKEN" \
  "https://localhost:8443/jobs/$JOB_ID"

# Check system resource usage
top
df -h

# Verify network mount is still responsive
df /mnt/evidence
ls /mnt/evidence/case-001
```

**Solutions:**

- Check network connectivity to source/destination
- Verify mount point is still accessible: `mount | grep evidence`
- Check available disk space: `df -h /dev/sdX` (target USB)
- Increase timeout in `.env`: `COPY_JOB_TIMEOUT=7200`
- Kill stuck job (if safe): Cancel via API, restart drive

### USB Drive Not Detected

**Symptom:** Drive not appearing in `GET /drives` API response.

**Debugging:**

```bash
# List USB devices
lsusb -v

# Check sysfs
ls -la /sys/bus/usb/devices/

# Verify udev rules
cat /etc/udev/rules.d/99-ecube-usb.rules

# Manual udev trigger
sudo udevadm trigger
```

**Solutions:**

- Check USB cable connection
- Try different USB port
- Verify USB hub power supply
- Reload udev rules: `sudo udevadm control --reload && sudo udevadm trigger`
- Check for kernel device errors: `dmesg | tail -20`

### Setup Initialization Fails or Gets Stuck

The `POST /setup/initialize` endpoint performs a multi-step process:

1. Inserts a lock row into `system_initialization` (cross-process guard)
2. Creates OS groups (`ecube-admins`, `ecube-auditors`, `ecube-managers`, `ecube-processors`)
3. Creates the admin OS user and sets the password
4. Seeds the admin role in the `user_roles` database table
5. Writes an audit log entry

If any step after the lock row insertion fails, the endpoint attempts to
delete the lock row so that setup can be retried. However, if the lock
row cannot be deleted (e.g., database connectivity lost), subsequent calls
will return `409 Conflict` indefinitely.

#### Symptom: `409 Conflict` but system is not initialized

**Cause:** A previous initialization attempt failed partway through and the
lock row in `system_initialization` was not cleaned up.

**Diagnosis:**

```bash
# Check if the lock row exists
psql -U ecube -d ecube -c "SELECT * FROM system_initialization;"

# Check if the admin role was actually seeded
psql -U ecube -d ecube -c "SELECT * FROM user_roles WHERE role = 'admin';"

# Check ECUBE service logs for CRITICAL-level messages about the lock
sudo journalctl -u ecube --priority=crit --since="1 hour ago"
```

**Resolution:**

```bash
# Remove the stuck lock row
psql -U ecube -d ecube -c "DELETE FROM system_initialization WHERE id = 1;"

# If partial OS state exists, clean it up:
# Check if groups were created
getent group ecube-admins ecube-auditors ecube-managers ecube-processors

# Check if the admin user was created
id <admin-username>

# Retry initialization
curl -k -X POST https://localhost:8443/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
```

> **Note:** Retrying `POST /setup/initialize` is safe even if the OS user
> already exists from a prior partial attempt. The endpoint detects the
> existing user, adds it to the `ecube-admins` group, and resets its
> password to the value provided in the request.

#### Symptom: `500 Internal Server Error` during initialization

**Possible causes and states:**

| Error message | What succeeded | What failed | Partial state |
|---|---|---|---|
| "Failed to create OS groups: ..." | Lock acquired | Group creation | Lock released; no OS changes |
| "Failed to create admin user: ..." | Lock acquired, groups exist | User creation | Lock released; groups exist (harmless) |
| "An unexpected error occurred..." | Lock acquired, possibly groups/user | Unknown step | Lock released if possible; check OS state |
| "OS setup completed successfully... but writing the admin role..." | Lock acquired, groups, user | DB role seeding | Lock released; OS user exists without DB role |
| Any message ending with "...the initialization lock could not be released..." | Varies | Lock cleanup also failed | Lock row is stuck; manual `DELETE` required |

**Resolution for each case:**

1. **Lock released:** Simply retry `POST /setup/initialize`. The endpoint
   handles pre-existing OS groups and users gracefully.

2. **Lock stuck (message mentions manual intervention):**
   ```bash
   psql -U ecube -d ecube -c "DELETE FROM system_initialization WHERE id = 1;"
   ```
   Then retry `POST /setup/initialize`.

3. **OS user exists without DB role (after "OS setup completed" error):**
   The retry will detect the existing user, add it to `ecube-admins`, reset
   its password, and re-attempt the DB role seeding.

---

## Backup and Recovery

### Database Backup

#### Automated Daily Backup (Systemd Timer)

```bash
# Create backup script
sudo tee /usr/local/bin/ecube-backup.sh > /dev/null << 'EOF'
#!/bin/bash
set -e

BACKUP_DIR="/mnt/backup/ecube"
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="ecube"
DB_USER="ecube"

mkdir -p "$BACKUP_DIR"

# Dump database
pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$BACKUP_DIR/ecube_${BACKUP_DATE}.sql.gz"

# Keep only last 30 days
find "$BACKUP_DIR" -name "ecube_*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_DIR/ecube_${BACKUP_DATE}.sql.gz"
EOF

sudo chmod +x /usr/local/bin/ecube-backup.sh
```

Create systemd service and timer:

```bash
# Backup service
sudo tee /etc/systemd/system/ecube-backup.service > /dev/null << 'EOF'
[Unit]
Description=ECUBE Database Backup
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/ecube-backup.sh
User=postgres
EOF

# Daily timer (2 AM)
sudo tee /etc/systemd/system/ecube-backup.timer > /dev/null << 'EOF'
[Unit]
Description=Daily ECUBE Backup
Requires=ecube-backup.service

[Timer]
OnCalendar=daily
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ecube-backup.timer
sudo systemctl start ecube-backup.timer
```

#### Manual Database Backup

```bash
# Full database dump
pg_dump -U ecube -d ecube > ecube_backup_$(date +%Y%m%d).sql

# Compressed dump
pg_dump -U ecube -d ecube | gzip > ecube_backup_$(date +%Y%m%d).sql.gz

# Specific table (audit logs)
pg_dump -U ecube -d ecube -t audit_logs > audit_logs_backup.sql
```

### Database Recovery

```bash
# Stop ECUBE service
sudo systemctl stop ecube

# Restore from backup
dropdb -U ecube ecube
createdb -U ecube ecube
psql -U ecube -d ecube < ecube_backup_20260306.sql

# Or from compressed backup
zcat ecube_backup_20260306.sql.gz | psql -U ecube -d ecube

# Restart service
sudo systemctl start ecube
```

### Configuration and Secrets Backup

```bash
# Backup .env file (CAREFUL: contains secrets)
sudo cp /opt/ecube/.env /mnt/backup/ecube/.env.backup
sudo chmod 600 /mnt/backup/ecube/.env.backup

# Backup TLS certificates
sudo cp -r /opt/ecube/certs /mnt/backup/ecube/certs.backup

# Backup application code (optional)
sudo cp -r /opt/ecube /mnt/backup/ecube/app.backup_$(date +%Y%m%d)
```

### OS Users and Groups Backup

ECUBE manages OS-level users and groups for authentication. These should be
backed up alongside the database and configuration.

#### Via the API (ECUBE-Managed Only)

Export the ECUBE-managed users and their group memberships as JSON. This is
sufficient to recreate them through the API on a fresh system.

```bash
# Back up ECUBE OS users
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/admin/os-users > ecube_os_users.json

# Back up ECUBE OS groups
curl -k -H "Authorization: Bearer $JWT_TOKEN" \
  https://localhost:8443/admin/os-groups > ecube_os_groups.json
```

#### Via OS-Level Files (All System Users)

Back up the underlying system files directly. This captures all OS users
(not just ECUBE-managed ones) and preserves password hashes.

```bash
sudo cp /etc/passwd /mnt/backup/ecube/passwd.backup
sudo cp /etc/group  /mnt/backup/ecube/group.backup
sudo cp /etc/shadow /mnt/backup/ecube/shadow.backup
sudo chmod 600 /mnt/backup/ecube/shadow.backup
```

> **Tip:** Include OS user/group backup in the automated daily backup script
> to ensure user accounts are recoverable alongside the database.

---

## Maintenance

### Log Rotation

Set up logrotate to prevent log files from consuming disk space:

```bash
sudo tee /etc/logrotate.d/ecube > /dev/null << 'EOF'
/var/log/ecube*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 ecube ecube
    sharedscripts
    postrotate
        systemctl reload ecube > /dev/null 2>&1 || true
    endscript
}
EOF
```

### Certificate Renewal

For Let's Encrypt certificates, set up auto-renewal:

```bash
# If using Certbot
sudo certbot renew --quiet

# For self-signed certificates (before expiration)
sudo -u ecube openssl req -new -x509 -key /opt/ecube/certs/key.pem \
  -out /opt/ecube/certs/cert.pem -days 365 \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=ecube.example.com"

# Restart service to load new certificate
sudo systemctl restart ecube
```

### Database Maintenance

```bash
# Update PostgreSQL statistics
psql -U ecube -d ecube -c "ANALYZE;"

# Reindex tables (if needed for performance)
psql -U ecube -d ecube -c "REINDEX DATABASE ecube;"

# Check table sizes
psql -U ecube -d ecube << 'EOF'
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) 
FROM pg_tables 
WHERE schemaname !~ '^pg_' 
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
EOF
```

### Software Updates

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Update Python dependencies (in ECUBE venv)
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade -e /opt/ecube/

# Apply any new database migrations
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head

# Restart service
sudo systemctl restart ecube
```
