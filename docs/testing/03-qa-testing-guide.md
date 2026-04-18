# ECUBE — QA Testing Guide

| Field | Value |
|---|---|
| Title | QA Testing Guide |
| Purpose | Guides QA personnel through manual hands-on ECUBE UI and functional testing in a Linux-based test environment. |
| Updated on | 04/17/26 |
| Audience | QA personnel. |

## Table of Contents

1. [Machine Setup](#1-machine-setup)
2. [Install System Packages](#2-install-system-packages)
3. [Install and Configure PostgreSQL](#3-install-and-configure-postgresql)
4. [Install ECUBE](#4-install-ecube)
5. [Create QA Test Users and Groups](#5-create-qa-test-users-and-groups)
6. [Configure the Environment (Optional)](#6-configure-the-environment-optional)
7. [Generate TLS Certificates](#7-generate-tls-certificates)
8. [Initialize the Database](#8-initialize-the-database)
9. [Start the Service](#9-start-the-service)
10. [Authenticate and Obtain Tokens](#10-authenticate-and-obtain-tokens)
11. [API Test Scenarios](#11-api-test-scenarios)
12. [QA Test Cases](#12-qa-test-cases)
13. [Environment Reset Between Test Runs](#13-environment-reset-between-test-runs)
14. [Service Management](#14-service-management)
15. [Troubleshooting](#15-troubleshooting)
16. [Version Compatibility](#16-version-compatibility)

This guide covers manual QA execution driven by UI behavior and functional test cases. Automated test execution is documented separately and is out of scope here.

---

## 1. Machine Setup

### Hardware Requirements

| Component | Minimum |
|-----------|---------|
| OS | Ubuntu 22.04 LTS (or Debian 12) |
| CPU | Quad-core 2.0 GHz x86-64 |
| RAM | 8 GB |
| Disk | 256 GB SSD |
| USB | USB 3.x hub with 4+ ports |
| Network | 1 Gbps Ethernet |

Install a fresh Ubuntu 22.04 LTS on the machine and make sure you have `sudo` access.

---

## 2. Install System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  python3.11 \
  python3.11-venv \
  python3.11-dev \
  python3-pip \
  postgresql \
  postgresql-contrib \
  nfs-common \
  cifs-utils \
  usbutils \
  udev \
  curl \
  jq
```

---

## 3. Install and Configure PostgreSQL

```bash
# Start PostgreSQL
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Create the ecube database and user
sudo -u postgres psql -c "CREATE USER ecube WITH PASSWORD 'ecube123';"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"

# Verify connectivity
psql -U ecube -d ecube -h localhost -c "SELECT 1;"
```

> If the `psql` connection fails with a peer authentication error, edit
> `/etc/postgresql/*/main/pg_hba.conf` and change the `local` line for user
> `ecube` to `md5`, then restart PostgreSQL:
> ```bash
> sudo systemctl restart postgresql
> ```

---

## 4. Install ECUBE

```bash
# Create service account
sudo useradd --system --create-home --shell /bin/bash ecube
sudo mkdir -p /opt/ecube
sudo chown -R ecube:ecube /opt/ecube

# Download the latest release package
cd /tmp
export GITHUB_OWNER="t3knoid"
export GITHUB_REPO="ecube"

LATEST_TAG=$(curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")

echo "Installing ECUBE ${LATEST_TAG}"

curl -fsSL -O \
  "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${LATEST_TAG}/ecube-package-${LATEST_TAG}.tar.gz"

curl -fsSL -O \
  "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${LATEST_TAG}/ecube-package-${LATEST_TAG}.sha256"

# Verify checksum and extract
sha256sum -c "ecube-package-${LATEST_TAG}.sha256"

# Ensure /opt/ecube exists and is owned by the ecube user
sudo mkdir -p /opt/ecube
sudo chown -R ecube:ecube /opt/ecube

# Extract package as ecube user to avoid root-owned files
sudo -u ecube tar -xzf "ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube/

# Set up Python virtual environment and install
sudo -u ecube python3.11 -m venv /opt/ecube/venv
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u ecube /opt/ecube/venv/bin/pip install -e "/opt/ecube/[dev]"
```

---

## 5. Create QA Test Users and Groups

ECUBE authenticates users via PAM on the host OS. Create OS users and groups
that map to ECUBE roles so QA can log in via the `POST /auth/token` endpoint.

```bash
# Create groups that will map to ECUBE roles
sudo groupadd qa-admins
sudo groupadd qa-managers
sudo groupadd qa-processors
sudo groupadd qa-auditors

# Create QA user accounts with passwords
for ROLE in admin manager processor auditor; do
  sudo useradd -m "qa-${ROLE}" -G "qa-${ROLE}s"
  echo "qa-${ROLE}:QaPass-${ROLE}!" | sudo chpasswd
done
```

> **PAM access:** The ECUBE service account must be able to call PAM
> for authentication. On Ubuntu/Debian this typically requires membership
> in the `shadow` group:
> ```bash
> sudo usermod -aG shadow ecube
> ```

Verify the users and groups were created:

```bash
for ROLE in admin manager processor auditor; do
  echo "qa-${ROLE}: $(id qa-${ROLE})"
done
```

---

## 6. Configure the Environment (Optional)

The `.env` file is **optional**. All settings have built-in defaults (see `.env.example` in the
release package for the full list with descriptions). You only need to create a `.env` file if
you want to override one or more defaults.

The most common reason to create one is if your PostgreSQL credentials differ from the defaults
(`ecube:ecube@localhost/ecube`).

```bash
# Copy the example file as a starting point
sudo -u ecube cp /opt/ecube/.env.example /opt/ecube/.env

# Edit only the settings you need to change
sudo -u ecube nano /opt/ecube/.env
```

For example, if your database password is `ecube123` instead of the default `ecube`:

```bash
# Only override what differs from defaults
sudo -u ecube tee /opt/ecube/.env > /dev/null << 'EOF'
DATABASE_URL=postgresql://ecube:ecube123@localhost:5432/ecube

# Map the QA groups created in step 5 to ECUBE roles
LOCAL_GROUP_ROLE_MAP={"qa-admins": ["admin"], "qa-managers": ["manager"], "qa-processors": ["processor"], "qa-auditors": ["auditor"]}

# Token lifetime (default: 60 minutes; increase for long QA sessions)
TOKEN_EXPIRE_MINUTES=480
EOF
```

> **Note:** Inside a heredoc, do not wrap the JSON value in extra quotes.
> The `KEY=value` format passes the raw value directly to the application.

> **Tip:** See `.env.example` for every available setting and its default value.

---

## 7. Generate TLS Certificates

For QA testing, self-signed certificates are fine:

```bash
sudo mkdir -p /opt/ecube/certs
sudo chown -R ecube:ecube /opt/ecube/certs

sudo -u ecube openssl genrsa -out /opt/ecube/certs/key.pem 2048
sudo -u ecube openssl req -new -x509 -key /opt/ecube/certs/key.pem \
  -out /opt/ecube/certs/cert.pem -days 365 \
  -subj "/C=US/ST=QA/L=Lab/O=ECUBE-QA/CN=ecube-qa.local"

sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
```

---

## 8. Initialize the Database

There are two ways to create the application database and run migrations.
Choose **one**:

### Option A — CLI (Alembic directly)

Run migrations from the command line. This requires that the database, user,
and `.env` `DATABASE_URL` have already been configured manually (see step 6).

```bash
cd /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head
```

Proceed to **step 9** to start the service.

### Option B — API-based provisioning

Use the `/setup/database/provision` endpoint to create the database user,
database, and run migrations in one step. This path requires the service to
be running first, so **skip ahead to step 9**, start the service, then return
here.

Once the service is listening, follow the curl examples in
[section 11.10 — Database Provisioning API](#1110-database-provisioning-api)
to test connectivity and provision the database. The endpoint is
unauthenticated during initial setup (before any admin user exists), so no
token is needed for the first provision.

> **Note:** After provisioning writes `DATABASE_URL` to `.env`, it
> reconfigures the running engine in-place — no service restart is required.

---

## 9. Start the Service

### Option A — Run directly (foreground, good for initial testing)

```bash
cd /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile /opt/ecube/certs/key.pem \
  --ssl-certfile /opt/ecube/certs/cert.pem
```

Leave this terminal open. Open a second terminal for testing.

### Option B — Install as systemd service (background, persistent)

```bash
sudo tee /etc/systemd/system/ecube.service > /dev/null << 'EOF'
[Unit]
Description=ECUBE Evidence Export Service
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=ecube
Group=ecube
WorkingDirectory=/opt/ecube
EnvironmentFile=-/opt/ecube/.env

ExecStart=/opt/ecube/venv/bin/uvicorn \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile=/opt/ecube/certs/key.pem \
  --ssl-certfile=/opt/ecube/certs/cert.pem \
  app.main:app

Restart=on-failure
RestartSec=10
PrivateTmp=yes
# Required for setup endpoints that invoke tightly scoped sudoers commands.
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ecube
sudo systemctl start ecube
sudo systemctl status ecube
```

### Verify the service is running

```bash
curl -k https://localhost:8443/health
# Expected: {"status": "ok"}
```

---

## 10. Authenticate and Obtain Tokens

All endpoints except the public routes (`/health`, `/health/live`, `/health/ready`, `/auth/token`, `/setup/status`, `/setup/initialize`, `/introspection/version`, `/setup/database/system-info`) require a JWT bearer token. During initial setup, `/setup/database/test-connection`, `/setup/database/provision`, and `/setup/database/provision-status` are also accessible without a token; after setup, they require an `admin` token.
Log in via `POST /auth/token` using the OS accounts created in step 5.

### Log in as admin

```bash
TOKEN=$(curl -sk -X POST https://localhost:8443/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "qa-admin", "password": "QaPass-admin!"}' \
  | jq -r '.access_token')

echo "Admin token: $TOKEN"
```

### Tokens for other roles

```bash
for ROLE in admin manager processor auditor; do
  TOK=$(curl -sk -X POST https://localhost:8443/auth/token \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"qa-${ROLE}\", \"password\": \"QaPass-${ROLE}!\"}" \
    | jq -r '.access_token')
  echo "${ROLE^^}_TOKEN=${TOK}"
done
```

Save the admin token for the examples below:

```bash
export TOKEN="<paste admin token here>"
```

> **Fallback — manual token generation:** If PAM authentication is not
> available (e.g. running tests on a machine where the QA users haven't
> been created), you can still generate tokens directly with the signing
> key:
>
> ```bash
> TOKEN=$(/opt/ecube/venv/bin/python3 -c "
> import jwt, time
> token = jwt.encode({
>     'sub': 'qa-admin-001',
>     'username': 'qa-admin',
>     'groups': ['qa-admins'],
>     'roles': ['admin'],
>     'exp': int(time.time()) + 86400
> }, 'change-me-in-production-please-rotate-32b', algorithm='HS256')
> print(token)
> ")
> ```

---

## 11. API Test Scenarios

> **Note:** Because the service runs with TLS, all `curl` commands use `-k` (skip certificate verification for self-signed certs) and port `8443`.

Open the interactive **Swagger UI** at: `https://localhost:8443/docs`

### 11.1 Health & Introspection

```bash
# Health (no auth)
curl -sk https://localhost:8443/health | jq

# Liveness (no auth)
curl -sk https://localhost:8443/health/live | jq

# Readiness (no auth)
curl -sk https://localhost:8443/health/ready | jq

# Public version metadata (no auth)
curl -sk https://localhost:8443/introspection/version | jq

# System health (CPU, memory, DB status)
curl -sk https://localhost:8443/introspection/system-health \
  -H "Authorization: Bearer $TOKEN" | jq

# USB topology — should show real hubs/ports on the QA test host
curl -sk https://localhost:8443/introspection/usb/topology \
  -H "Authorization: Bearer $TOKEN" | jq

# Block devices
curl -sk https://localhost:8443/introspection/block-devices \
  -H "Authorization: Bearer $TOKEN" | jq

# Active mounts
curl -sk https://localhost:8443/introspection/mounts \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.2 Mount Management

```bash
# Add an NFS mount
MOUNT_JSON=$(curl -sk -X POST https://localhost:8443/mounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "NFS",
    "remote_path": "10.0.0.5:/evidence"
  }')

# Capture the local mount point returned by ECUBE
MOUNT_POINT=$(echo "$MOUNT_JSON" | jq -r '.local_mount_point')
echo "Mount point: $MOUNT_POINT"
echo "$MOUNT_JSON" | jq

# List all mounts
curl -sk https://localhost:8443/mounts \
  -H "Authorization: Bearer $TOKEN" | jq

# Validate a specific mount (replace {mount_id})
curl -sk -X POST https://localhost:8443/mounts/{mount_id}/validate \
  -H "Authorization: Bearer $TOKEN" | jq

# Validate all mounts
curl -sk -X POST https://localhost:8443/mounts/validate \
  -H "Authorization: Bearer $TOKEN" | jq

# Remove a mount (replace {mount_id})
curl -sk -X DELETE https://localhost:8443/mounts/{mount_id} \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.3 Drive Management

Plug a USB drive into the machine and wait ~30 seconds for automatic discovery.

```bash
# List drives — should include the plugged-in drive
curl -sk https://localhost:8443/drives \
  -H "Authorization: Bearer $TOKEN" | jq

# Check the filesystem_type field — unformatted drives need formatting first
curl -sk https://localhost:8443/drives \
  -H "Authorization: Bearer $TOKEN" | jq '.[].filesystem_type'

# Format a drive (replace {drive_id}) — required before initialization if unformatted
curl -sk -X POST https://localhost:8443/drives/{drive_id}/format \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filesystem_type": "ext4"}' | jq

# Initialize a drive for a project (replace {drive_id})
curl -sk -X POST https://localhost:8443/drives/{drive_id}/initialize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "PROJ-QA-001"}' | jq

# Mount the initialized drive so it can be used as a managed export destination
curl -sk -X POST https://localhost:8443/drives/{drive_id}/mount \
  -H "Authorization: Bearer $TOKEN" | jq

# Prepare drive for safe physical removal
curl -sk -X POST https://localhost:8443/drives/{drive_id}/prepare-eject \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.3a Port Management

USB ports default to disabled. For drives on disabled ports, the backend/API state
remains `DISCONNECTED` until the port is enabled and a discovery refresh runs.

```bash
# List all USB ports with enablement state (admin or manager)
curl -sk https://localhost:8443/admin/ports \
  -H "Authorization: Bearer $TOKEN" | jq

# Enable a port (replace {port_id})
curl -sk -X PATCH https://localhost:8443/admin/ports/{port_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}' | jq

# Disable a port
curl -sk -X PATCH https://localhost:8443/admin/ports/{port_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' | jq

# After enabling, run a discovery refresh so drives become AVAILABLE
curl -sk -X POST https://localhost:8443/drives/refresh \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.3b Hub & Port Identification Enrichment

USB hubs and ports are enriched with hardware metadata (`vendor_id`,
`product_id`, `speed`) during discovery. Admins and managers can also assign
human-readable labels (`location_hint` on hubs, `friendly_label` on ports).

```bash
# List all USB hubs with hardware metadata (admin or manager)
curl -sk https://localhost:8443/admin/hubs \
  -H "Authorization: Bearer $TOKEN" | jq

# Set a location hint on a hub (replace {hub_id})
curl -sk -X PATCH https://localhost:8443/admin/hubs/{hub_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"location_hint": "back-left rack"}' | jq

# Set a friendly label on a port (replace {port_id})
curl -sk -X PATCH https://localhost:8443/admin/ports/{port_id}/label \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"friendly_label": "Bay 3 - Top Left"}' | jq

# Verify enriched fields appear in port listing
curl -sk https://localhost:8443/admin/ports \
  -H "Authorization: Bearer $TOKEN" | jq '.[0] | {vendor_id, product_id, speed, friendly_label}'

# Verify labels survive a discovery refresh
curl -sk -X POST https://localhost:8443/drives/refresh \
  -H "Authorization: Bearer $TOKEN" | jq
curl -sk https://localhost:8443/admin/hubs \
  -H "Authorization: Bearer $TOKEN" | jq '.[0].location_hint'
```

**Key Testing Points:**
- `vendor_id`, `product_id` are populated from sysfs during discovery
- `speed` on ports shows the negotiated link speed in Mbps
- Admin-assigned labels (`location_hint`, `friendly_label`) survive discovery resync
- Processor and auditor roles receive `403` for hub/port management endpoints
- Non-existent hub/port IDs return `404`
- Audit logs record `HUB_LABEL_UPDATED` and `PORT_LABEL_UPDATED` events

### 11.4 Job Management

```bash
# Create a copy job targeting the mounted USB drive (replace {drive_id})
# target_mount_path is optional; when omitted, ECUBE derives it from the drive's managed mount point
# If the assigned drive is not mounted, expect 409 CONFLICT
curl -sk -X POST https://localhost:8443/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "PROJ-QA-001",
    "evidence_number": "EV-001",
    "source_path": "'"$MOUNT_POINT""'/case-001",
    "drive_id": "{drive_id}",
    "thread_count": 4
  }' | jq

# Start the job (replace {job_id})
curl -sk -X POST https://localhost:8443/jobs/{job_id}/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq

# Poll job status
curl -sk https://localhost:8443/jobs/{job_id} \
  -H "Authorization: Bearer $TOKEN" | jq

# List file-level status rows (operator-safe)
curl -sk https://localhost:8443/jobs/{job_id}/files \
  -H "Authorization: Bearer $TOKEN" | jq

# Verify checksums after completion
curl -sk -X POST https://localhost:8443/jobs/{job_id}/verify \
  -H "Authorization: Bearer $TOKEN" | jq

# Generate manifest
curl -sk -X POST https://localhost:8443/jobs/{job_id}/manifest \
  -H "Authorization: Bearer $TOKEN" | jq

# Create a job with an HTTPS callback sink
curl -sk -X POST https://localhost:8443/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "PROJ-QA-CB-001",
    "evidence_number": "EV-CB-001",
    "source_path": "'"$MOUNT_POINT""'/case-001",
    "drive_id": "{drive_id}",
    "thread_count": 4,
    "callback_url": "https://example.com/webhook"
  }' | jq
```

#### 11.4a Jobs Page UI Workflow Checks

For the current Jobs page UI, verify the grouped `Create Job` dialog behaves as follows:

- When the dialog opens, only the `Project` field is active.
- After selecting a project, the `Source` and `Destination` sections unlock and show only mounted project-matching sources and eligible mounted USB drives.
- If no matching project, mount, or drive exists, the dialog shows the corresponding helper message instead of an empty or generic failure state.
- If `Run job immediately` is checked, the created job transitions directly into the start flow after successful creation.
- If the selected drive or mount becomes unavailable, the operator sees a specific conflict or availability message instead of a generic validation error.

### 11.5 Audit Logs

```bash
# View recent audit logs
curl -sk https://localhost:8443/audit \
  -H "Authorization: Bearer $TOKEN" | jq

# Filter by action
curl -sk "https://localhost:8443/audit?action=DRIVE_INITIALIZED" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.6 File Operations

```bash
# Get file hashes (replace {file_id})
curl -sk https://localhost:8443/files/{file_id}/hashes \
  -H "Authorization: Bearer $TOKEN" | jq

# Compare files
curl -sk -X POST https://localhost:8443/files/compare \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_id_a": 1, "file_id_b": 2}' | jq
```

### 11.7 User Role Management (Admin Only)

These endpoints manage DB-backed role assignments. They require the `admin` role.

```bash
# List all users with role assignments
curl -sk https://localhost:8443/users \
  -H "Authorization: Bearer $TOKEN" | jq

# Get roles for a specific user
curl -sk https://localhost:8443/users/qa-processor/roles \
  -H "Authorization: Bearer $TOKEN" | jq

# Assign roles to a user (replaces all existing assignments)
curl -sk -X PUT https://localhost:8443/users/qa-processor/roles \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"roles": ["processor", "auditor"]}' | jq

# Remove all role assignments for a user (reverts to OS group fallback)
curl -sk -X DELETE https://localhost:8443/users/qa-processor/roles \
  -H "Authorization: Bearer $TOKEN" | jq
```

> **Note:** These endpoints manage authorization only — they do not create or
> delete OS user accounts. To manage OS-level accounts through the API, use
> the `/admin/os-users` and `/admin/os-groups` endpoints (requires `admin`
> role). Alternatively, the admin can use OS/LDAP tools directly.

### 11.8 OS User & Group Management (Admin Only, Local Mode)

These endpoints manage OS-level user and group accounts. They require the `admin` role and are only available when `role_resolver = "local"` (returns `404` otherwise). Group names must start with the `ecube-` prefix. Creating a user requires at least one role that maps to an `ecube-*` group, and mutative user operations require the target user to be ECUBE-managed.

```bash
# Create an OS group
curl -sk -X POST https://localhost:8443/admin/os-groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "ecube-testers"}' | jq

# List OS groups (filtered to ecube-* prefix)
curl -sk https://localhost:8443/admin/os-groups \
  -H "Authorization: Bearer $TOKEN" | jq

# Create an OS user with password, groups, and DB roles
curl -sk -X POST https://localhost:8443/admin/os-users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "qa-testuser",
    "password": "TestPass-123!",
    "groups": ["ecube-testers"],
    "roles": ["processor"]
  }' | jq

# Existing-user decision flow (no password): request confirmation
curl -sk -X POST https://localhost:8443/admin/os-users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "qa-existing",
    "roles": ["processor"]
  }' | jq

# Confirm linking an existing OS/directory user into ECUBE roles
curl -sk -X POST https://localhost:8443/admin/os-users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "qa-existing",
    "roles": ["processor"],
    "confirm_existing_os_user": true
  }' | jq

# Cancel the existing-user create request (records cancellation audit event)
curl -sk -X POST https://localhost:8443/admin/os-users \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "qa-existing",
    "roles": ["processor"],
    "confirm_existing_os_user": false
  }' | jq

# List OS users relevant to ECUBE user management
# Includes users in ecube-* groups and users with DB role assignments.
# Reserved accounts are excluded.
curl -sk https://localhost:8443/admin/os-users \
  -H "Authorization: Bearer $TOKEN" | jq

# List OS users with optional username search (case-insensitive substring)
curl -sk 'https://localhost:8443/admin/os-users?search=qa-testuser' \
  -H "Authorization: Bearer $TOKEN" | jq

# Reset a user's password
curl -sk -X PUT https://localhost:8443/admin/os-users/qa-testuser/password \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "NewPass-456!"}' | jq

# Replace a user's group memberships
curl -sk -X PUT https://localhost:8443/admin/os-users/qa-testuser/groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"groups": ["ecube-processors", "ecube-auditors"]}' | jq

# Append groups without removing existing ones
curl -sk -X POST https://localhost:8443/admin/os-users/qa-testuser/groups \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"groups": ["ecube-managers"]}' | jq

# Delete an OS user
curl -sk -X DELETE https://localhost:8443/admin/os-users/qa-testuser \
  -H "Authorization: Bearer $TOKEN" | jq

# Delete an OS group
curl -sk -X DELETE https://localhost:8443/admin/os-groups/ecube-testers \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.9 First-Run Setup

These endpoints are **unauthenticated** and only succeed once (guarded by a cross-process lock).

```bash
# Check initialization status (no auth required)
curl -sk https://localhost:8443/setup/status | jq
# Expected: {"initialized": false} on a fresh database

# Initialize the system — creates ecube-* groups, admin user, seeds DB role
curl -sk -X POST https://localhost:8443/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "AdminPass-789!"}' | jq
# Expected: 200 with message, username, groups_created

# Verify status changed
curl -sk https://localhost:8443/setup/status | jq
# Expected: {"initialized": true}

# Attempt re-initialization
curl -sk -X POST https://localhost:8443/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "another-admin", "password": "Pass-000!"}' | jq
# Expected: 409 Conflict
```

### 11.10 Database Provisioning API

> **Prerequisite:** The service must be running (step 9). If you chose
> step 8 Option B (API-based provisioning), you should already be here.

These endpoints support API-based PostgreSQL database setup.  During initial setup (before any admin exists), `test-connection` and `provision` are unauthenticated.  After setup, they require the `admin` role.

```bash
# Runtime hints for setup wizard (always public)
curl -sk https://localhost:8443/setup/database/system-info | jq
# Expected: 200, {"in_docker": false, "suggested_db_host": "localhost"}

# Check whether database is already provisioned (public before setup, admin-only after)
curl -sk https://localhost:8443/setup/database/provision-status | jq
# Expected during initial setup: 200, {"provisioned": false}

# Test PostgreSQL connectivity (unauthenticated during initial setup)
curl -sk -X POST https://localhost:8443/setup/database/test-connection \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "YourPostgresPass"}' | jq
# Expected: 200, {"status": "ok", "server_version": "16.x"}

# Provision database (creates user, database, runs migrations)
curl -sk -X POST https://localhost:8443/setup/database/provision \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "YourPostgresPass", "app_database": "ecube", "app_username": "ecube", "app_password": "ecube123"}' | jq
# Expected: 200, {"status": "provisioned", "database": "ecube", "user": "ecube", "migrations_applied": 4}

# Re-provision attempt (blocked if already provisioned)
curl -sk -X POST https://localhost:8443/setup/database/provision \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "YourPostgresPass", "app_database": "ecube", "app_username": "ecube", "app_password": "ecube123"}' | jq
# Expected: 409, {"message": "Database is already provisioned. Set 'force' to true to re-provision."}

# Force re-provision (admin only, use with caution)
curl -sk -X POST https://localhost:8443/setup/database/provision \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "YourPostgresPass", "app_database": "ecube", "app_username": "ecube", "app_password": "ecube123", "force": true}' | jq
# Expected: 200, {"status": "provisioned", ...}

# Check database status (requires admin token)
curl -sk https://localhost:8443/setup/database/status \
  -H "Authorization: Bearer $TOKEN" | jq
# Expected: 200, {"connected": true, "database": "ecube", ...}

# Update database settings (requires admin token, partial update)
curl -sk -X PUT https://localhost:8443/setup/database/settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pool_size": 10, "pool_max_overflow": 20}' | jq
# Expected: 200, {"status": "updated", "host": "localhost", ...}

# Test connection after setup — requires admin token
curl -sk -X POST https://localhost:8443/setup/database/test-connection \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "YourPostgresPass"}' | jq
# Expected: 200, {"status": "ok", ...}

# SSRF-safe host validation
curl -sk -X POST https://localhost:8443/setup/database/test-connection \
  -H "Content-Type: application/json" \
  -d '{"host": "http://evil.com", "port": 5432, "admin_username": "postgres", "admin_password": "x"}' | jq
# Expected: 422, host must be a hostname or IP address
```

### 11.11 Runtime Configuration & Service Restart

These endpoints are admin-only and support runtime tuning plus explicit service restart requests.

```bash
# View current runtime configuration
curl -sk https://localhost:8443/admin/configuration \
  -H "Authorization: Bearer $TOKEN" | jq

# Update a runtime-only setting
curl -sk -X PUT https://localhost:8443/admin/configuration \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"log_level": "DEBUG"}' | jq

# Update a setting that requires restart metadata
curl -sk -X PUT https://localhost:8443/admin/configuration \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"db_pool_recycle_seconds": 120}' | jq

# Request a restart with explicit confirmation
curl -sk -X POST https://localhost:8443/admin/configuration/restart \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm": true}' | jq
```

---

## 12. QA Test Cases

> **Tracking spreadsheet:** A trackable version of these test cases with columns for Status, Tester, Date, and Notes is available in [`ecube-qa-test-cases.xlsx`](ecube-qa-test-cases.xlsx) in this directory.

### 12.1 Login Endpoint (`POST /auth/token`)

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Valid login | `POST /auth/token` with valid OS username/password | 200, response contains `access_token` and `token_type: "bearer"` |
| 2 | Invalid password | `POST /auth/token` with wrong password | 401, `Invalid credentials` |
| 3 | Unknown user | `POST /auth/token` with non-existent username | 401, `Invalid credentials` |
| 4 | Missing username | `POST /auth/token` with `{"password": "x"}` | 422 |
| 5 | Missing password | `POST /auth/token` with `{"username": "x"}` | 422 |
| 6 | Empty username | `POST /auth/token` with `{"username": "", "password": "x"}` | 422 |
| 7 | Token contains correct roles | Decode JWT from login response | `roles` matches DB `user_roles` entry if present, otherwise matches group mapping in `LOCAL_GROUP_ROLE_MAP` |
| 8 | Token contains groups | Decode JWT from login response | `groups` lists the user's OS groups |
| 9 | Token is usable | Use returned token to call `GET /drives` | 200 |
| 10 | Login audit log | `GET /audit?action=AUTH_SUCCESS` after successful login | `AUTH_SUCCESS` entry with username |
| 11 | Failed login audit log | `GET /audit?action=AUTH_FAILURE` after failed login | `AUTH_FAILURE` entry with username |
| 12 | No auth required for login | `POST /auth/token` without `Authorization` header | 200 (not 401) |

### 12.2 Authorization

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | No token | `curl -sk https://localhost:8443/drives` | 401, `UNAUTHORIZED` |
| 2 | Garbage token | Add header `Authorization: Bearer not.a.real.token` | 401, `UNAUTHORIZED` |
| 3 | Expired token | Generate token with `'exp': int(time.time()) - 60` | 401, `UNAUTHORIZED` |
| 4 | Processor adds mount | `POST /mounts` with processor token | 403, `FORBIDDEN` |
| 5 | Processor initializes drive | `POST /drives/{drive_id}/initialize` with processor token | 403, `FORBIDDEN` |
| 6 | Processor mounts drive | `POST /drives/{drive_id}/mount` with processor token | 403, `FORBIDDEN` |
| 7 | Auditor mounts drive | `POST /drives/{drive_id}/mount` with auditor token | 403, `FORBIDDEN` |
| 8 | Processor formats drive | `POST /drives/{drive_id}/format` with processor token | 403, `FORBIDDEN` |
| 9 | Processor reads audit | `GET /audit` with processor token | 403, `FORBIDDEN` |
| 10 | Auditor reads audit | `GET /audit` with auditor token | 200 |
| 11 | Processor creates job | `POST /jobs` with processor token | 200 |
| 12 | All four roles read job files | `GET /jobs/{job_id}/files` with admin/manager/processor/auditor tokens | 200 for each role |
| 13 | All error responses have `trace_id` | Inspect any 4xx/5xx JSON body | `trace_id` field present |

### 12.2.1 Session Lifecycle and Token Expiry

Validate authenticated-session behavior from the UI shell and API access patterns.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Authenticated shell shows current identity | Log in through the UI as `qa-admin` or another QA role | Current username, role badge, and remaining session indicator are visible in the shell |
| 2 | Token works until expiry | Log in, then call an authenticated endpoint such as `GET /drives` with the issued token | 200 until token expiry or explicit logout |
| 3 | Expired token is rejected | Generate a deliberately expired token or wait for expiry, then call `GET /drives` | 401, `UNAUTHORIZED`; UI should redirect or prompt for re-authentication |
| 4 | Invalid token does not grant shell access | Replace a valid token with a malformed token in browser/session state or API call | Protected endpoints return 401 and the UI does not continue as authenticated |
| 5 | Logout ends the active session | Use the UI `Log Out` action, then revisit a protected page | User is returned to the login screen and protected pages no longer load without re-authentication |

### 12.3 Project Isolation

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an AVAILABLE drive with request project ` proj-a ` while a mounted share is assigned to `PROJ-A` | 200, state → `IN_USE`, stored `current_project_id` is normalized to `PROJ-A` |
| 2 | Re-initialize same drive with `PROJ-B` (drive still `IN_USE`) | 403, `FORBIDDEN` — isolation violation |
| 3 | Check audit log for row 2 | `PROJECT_ISOLATION_VIOLATION` record present with `requested_project_id: PROJ-B` |
| 4 | Prepare-eject the drive from step 1 (state → `AVAILABLE`), then initialize with `PROJ-B` | 409, `CONFLICT` — drive is bound to `PROJ-A`; format required before reassigning to a different project |
| 5 | Check audit log for row 4 | `INIT_REJECTED_PROJECT_MISMATCH` record present with `requested_project_id: PROJ-B` |
| 6 | Attempt initialize when no `MOUNTED` share is assigned to the requested project | 409, `CONFLICT`; audit includes `INIT_REJECTED_NO_PROJECT_SOURCE` |
| 7 | Retry initialize while the same project's share is being modified concurrently | 409, `CONFLICT`; audit includes `INIT_REJECTED_PROJECT_SOURCE_BUSY` |

### 12.4 Drive State Machine

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an `AVAILABLE` drive with recognized filesystem | 200, state → `IN_USE` |
| 2 | Initialize a drive with `filesystem_type=NULL` | 409, `CONFLICT` — must have recognized filesystem |
| 3 | Initialize a drive with `filesystem_type=unformatted` | 409, `CONFLICT` — must have recognized filesystem |
| 4 | Initialize a drive with `filesystem_type=unknown` | 409, `CONFLICT` — must have recognized filesystem |
| 5 | Initialize a `DISCONNECTED` drive (not present / disabled port) | 409, `CONFLICT`; audit `INIT_REJECTED_NOT_AVAILABLE` recorded; note: `GET /drives` excludes disconnected drives by default — use `include_disconnected=true` to see them |
| 6 | Mount an `AVAILABLE` or `IN_USE` drive with a recognized filesystem | 200, `mount_path` is populated |
| 7 | Mount a drive with `filesystem_type=unknown`, `unformatted`, or `NULL` | 409, `CONFLICT` — must have recognized filesystem |
| 8 | Prepare-eject an `IN_USE` drive | 200, state → `AVAILABLE`, `mount_path` cleared |
| 9 | Prepare-eject an `AVAILABLE` drive | 409, `CONFLICT` |
| 10 | Format-then-initialize-mount workflow: discover unformatted → format ext4 → initialize → mount | Each step succeeds; `mount_path` becomes populated |
| 11 | Attempt to format an `IN_USE` drive | 409, `CONFLICT` — must be `AVAILABLE` |
| 12 | Open the Initialize dialog when no eligible mounted project exists | UI shows a helper message, disables the project selector, and blocks submission |
| 13 | View drive detail after initialization | Sensitive device and path fields are shown as `Protected` instead of raw internal identifiers |
| 14 | View the mounts list and browse controls | Raw remote and local mount paths are redacted in the table; browse remains enabled only for mounted shares |
| 15 | Operate the Initialize and Add Mount dialogs with keyboard only | Focus enters the dialog, Tab stays trapped within it, Escape closes it, and focus returns to the triggering control |

### 12.4.1 Filesystem Detection

| # | Test | Expected |
|---|------|----------|
| 1 | Hot-plug a formatted drive, wait for discovery | `GET /drives` shows drive with `filesystem_type` set (e.g. `ext4`) |
| 2 | Hot-plug an unformatted drive | `GET /drives` shows `filesystem_type: "unformatted"` |
| 3 | Trigger manual refresh | `POST /drives/refresh`, then `GET /drives` — `filesystem_type` updated |
| 4 | Reformat drive externally (`mkfs.exfat /dev/sdX`), then `POST /drives/refresh` | `filesystem_type` updates to `exfat` on next refresh |
| 5 | Drive discovered without block device path (hub-only) | `filesystem_type` is `null` in `GET /drives` |

### 12.4.2 Drive Formatting

| # | Test | Expected |
|---|------|----------|
| 1 | Format `AVAILABLE` drive as `ext4` | 200, `filesystem_type` → `ext4`, `DRIVE_FORMATTED` audit log |
| 2 | Format `AVAILABLE` drive as `exfat` | 200, `filesystem_type` → `exfat` |
| 3 | Format with unsupported type (`ntfs`) | 422, validation error |
| 4 | Format a drive in `IN_USE` state | 409, `CONFLICT` |
| 5 | Format a mounted drive | 409, `CONFLICT` — must unmount first |
| 6 | Processor attempts format | 403, `FORBIDDEN` |
| 7 | Auditor attempts format | 403, `FORBIDDEN` |
| 8 | Admin formats drive | 200, success |
| 9 | Manager formats drive | 200, success |
| 10 | Format drive with no device path (`filesystem_path` is null) | 400, `BAD_REQUEST` — no filesystem_path |
| 11 | Format, then verify via `blkid /dev/sdX` on host | Host `blkid` output matches `filesystem_type` in API response |
| 12 | Re-format: format ext4, then format exfat on same `AVAILABLE` drive | 200 both times; final `filesystem_type` is `exfat` |
| 13 | `DRIVE_FORMAT_FAILED` audit log when hardware error occurs | `GET /audit?action=DRIVE_FORMAT_FAILED` shows entry with `drive_id` and `error` |

### 12.4.3 Port Enablement

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | List ports — admin | `GET /admin/ports` with admin token | 200, array of port objects with `enabled` field |
| 2 | List ports — manager | `GET /admin/ports` with manager token | 200 |
| 3 | List ports — processor denied | `GET /admin/ports` with processor token | 403, `FORBIDDEN` |
| 4 | List ports — unauthenticated | `GET /admin/ports` without token | 401, `UNAUTHORIZED` |
| 5 | Enable a port | `PATCH /admin/ports/{port_id}` with `{"enabled": true}` | 200, port returned with `enabled: true` |
| 6 | Disable a port | `PATCH /admin/ports/{port_id}` with `{"enabled": false}` | 200, port returned with `enabled: false` |
| 7 | Enable port — manager | `PATCH /admin/ports/{port_id}` with manager token | 200 |
| 8 | Enable port — processor denied | `PATCH /admin/ports/{port_id}` with processor token | 403, `FORBIDDEN` |
| 9 | Enable non-existent port | `PATCH /admin/ports/99999` with `{"enabled": true}` | 404, `NOT_FOUND` |
| 10 | Ports default to disabled | Discover a new port, then `GET /admin/ports` | New port has `enabled: false` |
| 11 | Drive on disabled port stays DISCONNECTED | Plug in drive on disabled port, run `POST /drives/refresh` | `GET /drives?include_disconnected=true` shows drive in `DISCONNECTED` state |
| 12 | Drive on enabled port becomes AVAILABLE | Enable port, run `POST /drives/refresh` | `GET /drives` shows drive in `AVAILABLE` state |
| 13 | Disable port — IN_USE drive unaffected | Disable a port with an `IN_USE` drive, run `POST /drives/refresh` | Drive remains `IN_USE` (project isolation priority) |
| 14 | Disable port — AVAILABLE drive demoted | Enable port, confirm drive is `AVAILABLE`, disable port, run `POST /drives/refresh` | Drive transitions to `DISCONNECTED`; `GET /drives` (default) no longer returns it |
| 15 | Orphan drive stays DISCONNECTED | Discover a drive with no matching port (`port_id = NULL`), run `POST /drives/refresh` | Drive remains in `DISCONNECTED` state (unknown port treated as disabled); only visible with `include_disconnected=true` |
| 16 | PORT_ENABLED audit log | `GET /audit?action=PORT_ENABLED` after enabling a port | Audit entry with `port_id`, `system_path`, `hub_id`, `enabled`, `path` |
| 17 | PORT_DISABLED audit log | `GET /audit?action=PORT_DISABLED` after disabling a port | Audit entry with `port_id`, `system_path`, `hub_id`, `enabled`, `path` |
| 18 | Enable Drive hidden for absent disconnected drive | Open the drive detail view for a historical `DISCONNECTED` drive with no detected device path | The operator does not see an actionable Enable Drive control |
| 19 | Enable Drive available for physically detected disconnected drive | Insert a drive on a disabled but known port, refresh, then open drive detail as admin or manager | The Enable Drive action is available; after enable plus refresh the drive becomes `AVAILABLE` or remains `IN_USE` if already mounted |

### 12.4.4 Hub & Port Identification Enrichment

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | List hubs — admin | `GET /admin/hubs` with admin token | 200, array of hub objects with `vendor_id`, `product_id`, `location_hint` |
| 2 | List hubs — manager | `GET /admin/hubs` with manager token | 200 |
| 3 | List hubs — processor denied | `GET /admin/hubs` with processor token | 403, `FORBIDDEN` |
| 4 | List hubs — unauthenticated | `GET /admin/hubs` without token | 401, `UNAUTHORIZED` |
| 5 | Set hub location hint | `PATCH /admin/hubs/{hub_id}` with `{"location_hint": "back-left rack"}` | 200, hub returned with `location_hint: "back-left rack"` |
| 6 | Set hub location hint — manager | `PATCH /admin/hubs/{hub_id}` with manager token | 200 |
| 7 | Set hub location hint — processor denied | `PATCH /admin/hubs/{hub_id}` with processor token | 403, `FORBIDDEN` |
| 8 | Set hub location hint — not found | `PATCH /admin/hubs/99999` | 404, `NOT_FOUND` |
| 9 | HUB_LABEL_UPDATED audit log | `GET /audit?action=HUB_LABEL_UPDATED` after setting a hub label | Audit entry with `hub_id`, `system_identifier`, `field`, `old_value`, `new_value`, `path` |
| 10 | Set port friendly label | `PATCH /admin/ports/{port_id}/label` with `{"friendly_label": "Bay 3"}` | 200, port returned with `friendly_label: "Bay 3"` |
| 11 | Set port friendly label — manager | `PATCH /admin/ports/{port_id}/label` with manager token | 200 |
| 12 | Set port friendly label — processor denied | `PATCH /admin/ports/{port_id}/label` with processor token | 403, `FORBIDDEN` |
| 13 | Set port friendly label — not found | `PATCH /admin/ports/{port_id}/label` for non-existent port | 404, `NOT_FOUND` |
| 14 | PORT_LABEL_UPDATED audit log | `GET /audit?action=PORT_LABEL_UPDATED` after setting a port label | Audit entry with `port_id`, `system_path`, `field`, `old_value`, `new_value`, `path` |
| 15 | Port listing includes enriched fields | `GET /admin/ports` after discovery | Port objects include `vendor_id`, `product_id`, `speed` fields |
| 16 | Labels survive discovery resync | Set hub `location_hint` and port `friendly_label`, then `POST /drives/refresh` | Labels remain unchanged after resync |
| 17 | Discovery populates vendor/product IDs | Run `POST /drives/refresh` with USB hardware connected | Hub and port records show `vendor_id` and `product_id` from sysfs |

### 12.4.5 Mount Validation and Connectivity

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Validate mounted NFS share | Create an NFS mount, then `POST /mounts/{mount_id}/validate` | 200, mount remains `MOUNTED`, `last_checked_at` advances |
| 2 | Validate mounted SMB share | Create an SMB mount, then `POST /mounts/{mount_id}/validate` | 200, mount remains `MOUNTED` |
| 3 | Validate disconnected mount | Break connectivity or unmount externally, then `POST /mounts/{mount_id}/validate` | 200, mount status becomes `UNMOUNTED` or `ERROR` with a descriptive error |
| 4 | Validate all mounts reports mixed states | Register one reachable mount and one broken mount, then `POST /mounts/validate` | 200, response includes updated status for each mount |
| 5 | Validate missing mount | `POST /mounts/9999/validate` | 404, `NOT_FOUND` |
| 6 | Processor cannot validate mounts | `POST /mounts/{mount_id}/validate` with processor token | 403, `FORBIDDEN` |
| 7 | Mount validation audit trail | Validate a mount, then query `GET /audit?action=MOUNT_VALIDATED` | Audit entry records actor, mount id, and resulting status |
| 8 | Reject exact duplicate remote path | Create a mount, then submit the same `remote_path` again for the same project | 409, `CONFLICT`, operator-readable message indicating the source is already configured |
| 9 | Reject nested overlap across projects | Create a parent source for project A, then add a child path for project B | 409, `CONFLICT`, overlap message returned and request is not applied |
| 10 | Allow nested path for same project | Create a parent source for project A, then add a child path for the same project | 200, second mount is accepted |
| 11 | Normalize SMB path variants before duplicate check | Create an SMB mount with slash-separated path, then submit the same source with backslash separators | 409, `CONFLICT`, duplicate source rejected |
| 12 | Reject concurrent duplicate submit | Submit two near-simultaneous add-mount requests for the same remote source from separate sessions | Only one mount is created; the competing request returns a safe conflict instead of producing duplicates |

### 12.5 USB Hardware Validation

These tests exercise real hardware paths that must be validated during manual QA on systems with attached USB hardware.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Hot-plug detection | Plug in a USB drive, wait 30 seconds | `GET /drives` shows the new drive (in `DISCONNECTED` state if port is disabled, or `AVAILABLE` if port is enabled); disconnected drives require `include_disconnected=true` |
| 2 | USB topology | `GET /introspection/usb/topology` | Shows real hub serial numbers, port numbers, connected devices |
| 3 | Physical eject | Initialize drive → prepare-eject → physically remove | After the next discovery cycle, `GET /drives?include_disconnected=true` lists the drive with `current_state=DISCONNECTED`; audit shows `DRIVE_EJECT_PREPARED` |
| 4 | Re-plug same drive | Remove and re-insert the same drive | Drive reappears as `AVAILABLE` with same `device_identifier` (after discovery cycle) |
| 5 | Multiple drives | Plug in 2+ drives simultaneously | All drives appear in `/drives`; each can be initialized to different projects |
| 6 | Sync + unmount | Initialize drive, create/start a job, then prepare-eject | Filesystem flushed and unmounted before eject (verify via `mount` command — no partitions from that drive should be listed) |
| 7 | Disabled port blocks AVAILABLE | Disable a port, plug in a drive to that port, run discovery | Drive appears in `DISCONNECTED` state (visible with `include_disconnected=true`); enable port + refresh → drive transitions to `AVAILABLE` |

### 12.6 End-to-End Copy Workflow

#### 12.6.1 Job Progress and Source Guardrails

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Active job progress stays conservative | Start a multi-file job and observe the Dashboard, Jobs list, and Job Detail view while bytes advance faster than completed file rows | All three views stay below 100% until the finished-file counts indicate completion; no view reports 100% while status remains RUNNING or VERIFYING |
| 2 | Completion summary is visible | Let a job finish and open its detail page | The detail screen shows start time, copy threads, files copied, total copied, elapsed time, and copy rate |
| 3 | Mount-root source selection works | In Create Job, choose a mounted share and enter / as the source path | The job is created successfully and the selected mount root is used as the source |
| 4 | Path traversal outside selected mount is blocked | In Create Job, choose a mounted share and enter a traversal path such as ../../etc | The UI/API rejects the request, no job is created, and the operator sees a validation-style error rather than a host path leak |

Walk through the complete data export lifecycle:

1. **Set up a test file share.** Create a local directory with known sample files and checksums:
   ```bash
   sudo mkdir -p /mnt/test-evidence/case-001

   # Create sample files with known content
   echo "Evidence document alpha" | sudo tee /mnt/test-evidence/case-001/doc-alpha.txt
   echo "Evidence document bravo" | sudo tee /mnt/test-evidence/case-001/doc-bravo.txt
   dd if=/dev/urandom bs=1M count=10 2>/dev/null | sudo tee /mnt/test-evidence/case-001/binary-10mb.bin > /dev/null

   # Record checksums for later verification
   sudo sha256sum /mnt/test-evidence/case-001/* | sudo tee /mnt/test-evidence/case-001.sha256
   ```

   **For NFS testing:** If you have an NFS server, mount it instead:
   ```bash
   sudo mkdir -p /mnt/nfs-evidence
   sudo mount -t nfs 10.0.0.5:/evidence /mnt/nfs-evidence
   # Verify the mount is accessible
   ls -la /mnt/nfs-evidence/
   ```

   **For SMB/CIFS testing:**
   ```bash
   sudo mkdir -p /mnt/smb-evidence
   sudo mount -t cifs //10.0.0.5/evidence /mnt/smb-evidence \
     -o username=evidence_user,password=evidence_pass,vers=3.0
   ls -la /mnt/smb-evidence/
   ```

2. **Add the mount** via `POST /mounts` and record the returned `local_mount_point`.

3. **Plug in a USB drive** and wait for auto-discovery.

3b. **Enable the port** — `GET /admin/ports` to find the port ID, then
    `PATCH /admin/ports/{port_id}` with `{"enabled": true}`.
    Run `POST /drives/refresh` so the drive transitions to `AVAILABLE`.

4. **List drives** — `GET /drives` — and note the drive ID and `filesystem_type`.

4b. **Format the drive (if needed)** — If `filesystem_type` is `unformatted`, `unknown`, or `null`:
  `POST /drives/{drive_id}/format` with `{"filesystem_type": "ext4"}`.
    Confirm `filesystem_type` → `ext4` in the response.

5. **Initialize the drive** — `POST /drives/{drive_id}/initialize` with `project_id: "PROJ-E2E"`.

6. **Create a job** — `POST /jobs` with the selected `mount_id` from step 2 and a `source_path` that stays inside that mounted share. Use `/` to target the share root or a relative subfolder path for a narrower source.

7. **Start the job** — `POST /jobs/{job_id}/start`.

8. **Poll status** — `GET /jobs/{job_id}` — until `status` becomes `COMPLETED`.

9. **Verify checksums** — `POST /jobs/{job_id}/verify` — confirm all files pass.

10. **Generate manifest** — `POST /jobs/{job_id}/manifest`.

11. **Prepare eject** — `POST /drives/{drive_id}/prepare-eject` — drive returns to `AVAILABLE`.

12. **Physically remove the drive** and verify data on another computer.
    Compare file checksums against the values recorded in step 1:
    ```bash
    # On the verification computer
    sha256sum /media/usb/case-001/* | diff - case-001.sha256
    ```

13. **Check audit trail** — `GET /audit` — confirm the complete chain:
    `MOUNT_ADDED → PORT_ENABLED → DRIVE_FORMATTED → DRIVE_INITIALIZED → JOB_CREATED → JOB_STARTED → JOB_COMPLETED → DRIVE_EJECT_PREPARED`

### 12.6.1 Job Callback URL Notifications

Use a controlled HTTPS webhook sink when validating callback behavior.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | HTTPS callback URL accepted on job create | `POST /jobs` with `"callback_url": "https://example.com/webhook"` | 200, job response echoes `callback_url` |
| 2 | HTTP callback URL rejected | `POST /jobs` with `"callback_url": "http://example.com/webhook"` | 422, validation error mentions HTTPS |
| 3 | Callback URL with embedded credentials rejected | `POST /jobs` with `"callback_url": "https://user:pass@example.com/hook"` | 422, validation error rejects URL credentials |
| 4 | Callback URL with no hostname rejected | `POST /jobs` with malformed HTTPS URL such as `"https:///path-only"` | 422 |
| 5 | Terminal-state callback delivered | Create a job with a reachable HTTPS webhook sink, run job to completion, inspect sink | Sink receives terminal-state payload and job completes normally |
| 6 | Callback delivery audit trail | After terminal-state delivery, query `GET /audit?action=CALLBACK_SENT` | Audit entry records delivery result without leaking secret material |

### 12.7 Error Handling

| # | Test | Expected |
|---|------|----------|
| 1 | `GET /jobs/99999` | 404, `NOT_FOUND` |
| 2 | `GET /jobs/99999/files` | 404, `NOT_FOUND` |
| 3 | `DELETE /mounts/99999` | 404, `NOT_FOUND` |
| 4 | Start an already-running job | 409, `CONFLICT` |
| 5 | All error responses | JSON body includes `code`, `message`, and `trace_id` |
| 6 | `POST /drives/999/format` with `{"filesystem_type": "ext4"}` | 404, `NOT_FOUND` |
| 7 | `POST /drives/{drive_id}/format` with `{"filesystem_type": "ntfs"}` | 422, validation error |
| 8 | `POST /drives/{drive_id}/format` with empty body | 422 |

### 12.8 User Role Management

All user role management endpoints require the `admin` role.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | List users (empty) | `GET /users` with admin token (no roles assigned yet) | 200, `{"users": []}` |
| 2 | Assign roles | `PUT /users/qa-processor/roles` with `{"roles": ["processor", "auditor"]}` | 200, returns username and sorted roles |
| 3 | Get roles | `GET /users/qa-processor/roles` after assignment | 200, `{"username": "qa-processor", "roles": ["auditor", "processor"]}` |
| 4 | List users after assignment | `GET /users` after assigning roles | 200, user appears in list with correct roles |
| 5 | Replace roles | `PUT /users/qa-processor/roles` with `{"roles": ["manager"]}` | 200, only `["manager"]` returned; old roles removed |
| 6 | Deduplicate roles | `PUT /users/qa-processor/roles` with `{"roles": ["admin", "admin", "processor"]}` | 200, deduplicated to `["admin", "processor"]` |
| 7 | Invalid role name | `PUT /users/qa-processor/roles` with `{"roles": ["superuser"]}` | 422, error message mentions `superuser` |
| 8 | Empty role list | `PUT /users/qa-processor/roles` with `{"roles": []}` | 422, at least one role required |
| 9 | Remove roles | `DELETE /users/qa-processor/roles` | 200, `{"username": "qa-processor", "roles": []}` |
| 10 | Get roles after removal | `GET /users/qa-processor/roles` after DELETE | 200, `{"roles": []}` |
| 11 | Get roles for unknown user | `GET /users/nonexistent/roles` | 200, `{"username": "nonexistent", "roles": []}` |
| 12 | Processor cannot list users | `GET /users` with processor token | 403, `FORBIDDEN` |
| 13 | Processor cannot set roles | `PUT /users/x/roles` with processor token | 403, `FORBIDDEN` |
| 14 | Processor cannot delete roles | `DELETE /users/x/roles` with processor token | 403, `FORBIDDEN` |
| 15 | Unauthenticated access | `GET /users` without Authorization header | 401, `UNAUTHORIZED` |
| 16 | ROLE_ASSIGNED audit log | `GET /audit?action=ROLE_ASSIGNED` after assigning roles | Audit entry with actor, target user, and roles |
| 17 | ROLE_REMOVED audit log | `GET /audit?action=ROLE_REMOVED` after removing roles | Audit entry with actor and target user |
| 18 | DB roles override groups | Assign `["manager"]` to `qa-processor` via `PUT`, then login as `qa-processor` | JWT `roles` is `["manager"]`, not `["processor"]` from OS groups |
| 19 | Fallback to group roles | `DELETE /users/qa-processor/roles`, then login as `qa-processor` | JWT `roles` falls back to OS group mapping (`["processor"]`) |

### 12.9 OS User & Group Management

All OS user and group management endpoints require the `admin` role and are only available when `role_resolver = "local"`.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Create group | `POST /admin/os-groups` with `{"name": "ecube-testers"}` | 201, returns name, gid, members |
| 2 | Create group without prefix | `POST /admin/os-groups` with `{"name": "testers"}` | 422, group name must start with `ecube-` |
| 3 | List groups | `GET /admin/os-groups` | 200, only `ecube-*` groups listed |
| 4 | Delete group | `DELETE /admin/os-groups/ecube-testers` | 200 |
| 5 | Delete group without prefix | `DELETE /admin/os-groups/somegroup` | 422, group name must start with `ecube-` |
| 6 | Create new user | `POST /admin/os-users` with username, password, roles | 201, returns username, uid, gid, home, shell, groups |
| 7 | Create user — existing ECUBE mapping | `POST /admin/os-users` with username that already has DB roles | 409, Conflict |
| 8 | Create user — existing OS/directory account (step 1) | `POST /admin/os-users` with username+roles and no `confirm_existing_os_user` | 200, `status: "confirmation_required"` |
| 9 | Create user — existing OS/directory account (confirm) | `POST /admin/os-users` with `confirm_existing_os_user: true` | 200, `status: "synced_existing_user"` |
| 10 | Create user — existing OS/directory account (cancel) | `POST /admin/os-users` with `confirm_existing_os_user: false` | 200, `status: "canceled"` |
| 11 | Create user — reserved name | `POST /admin/os-users` with `{"username": "root", ...}` | 422, reserved username |
| 12 | Create user — empty password (new user path) | `POST /admin/os-users` with `{"password": "", ...}` | 422 |
| 13 | Create user — password with newline | `POST /admin/os-users` with password containing `\n` | 422, unsafe characters |
| 14 | Create user — password with colon | `POST /admin/os-users` with password containing `:` | 422, unsafe characters |
| 15 | Create user — invalid group | `POST /admin/os-users` with non-existent group in groups list | 422, group does not exist |
| 16 | Create user — no roles | `POST /admin/os-users` with empty/omitted roles | 422, at least one role required |
| 17 | List users | `GET /admin/os-users` | 200, includes users in `ecube-*` groups and users with DB role assignments |
| 18 | List users — directory-backed role-only account | Assign DB roles for a directory user that is not in OS enumeration, then `GET /admin/os-users` | 200, user appears with placeholder host fields (`uid=-1`, `gid=-1`) |
| 19 | Reset password | `PUT /admin/os-users/{username}/password` with `{"password": "NewPass!"}` | 200 |
| 20 | Reset password — non-ECUBE user | `PUT /admin/os-users/postgres/password` | 422, user is not ECUBE-managed |
| 21 | Replace groups | `PUT /admin/os-users/{username}/groups` with `{"groups": ["ecube-admins"]}` | 200, updated group list; non-`ecube-*` groups preserved |
| 22 | Replace groups — empty list | `PUT /admin/os-users/{username}/groups` with `{"groups": []}` | 422, at least one `ecube-*` group required |
| 23 | Replace groups — non-ecube name | `PUT /admin/os-users/{username}/groups` with `{"groups": ["docker"]}` | 422, group does not start with `ecube-` |
| 24 | Append groups | `POST /admin/os-users/{username}/groups` with `{"groups": ["ecube-managers"]}` | 200, updated group list |
| 25 | Modify groups — non-ECUBE user | `PUT /admin/os-users/www-data/groups` | 422, user is not ECUBE-managed |
| 26 | Delete user | `DELETE /admin/os-users/{username}` | 200, user and DB roles removed |
| 27 | Delete user — non-ECUBE user | `DELETE /admin/os-users/daemon` | 422, user is not ECUBE-managed |
| 28 | Delete user — not found | `DELETE /admin/os-users/nonexistent` | 404 |
| 29 | Processor cannot access OS endpoints | `GET /admin/os-users` with processor token | 403, FORBIDDEN |
| 30 | Non-local mode returns 404 | All `/admin/os-*` endpoints when `role_resolver != "local"` | 404, Not Found |
| 31 | OS_USER_CREATED audit log | `GET /audit?action=OS_USER_CREATED` after creating user | Audit entry with actor and username |
| 32 | OS_USER_CREATE_CONFIRMATION_REQUIRED audit log | `GET /audit?action=OS_USER_CREATE_CONFIRMATION_REQUIRED` after existing-user step 1 | Audit entry with actor and target username |
| 33 | OS_USER_CREATE_CANCELED audit log | `GET /audit?action=OS_USER_CREATE_CANCELED` after cancel path | Audit entry with actor and target username |
| 34 | OS_USER_SYNCED_EXISTING audit log | `GET /audit?action=OS_USER_SYNCED_EXISTING` after confirm path | Audit entry with actor and target username |
| 35 | OS_USER_DELETED audit log | `GET /audit?action=OS_USER_DELETED` after deleting user | Audit entry with actor and username |
| 36 | OS_PASSWORD_RESET audit log | `GET /audit?action=OS_PASSWORD_RESET` after resetting password | Audit entry (no password in details) |
| 37 | OS_GROUP_CREATED audit log | `GET /audit?action=OS_GROUP_CREATED` after creating group | Audit entry with group name |
| 38 | OS_GROUP_DELETED audit log | `GET /audit?action=OS_GROUP_DELETED` after deleting group | Audit entry with group name |

### 12.9.1 UI Validation Checklist — Create User Modal Flow

Use this checklist to validate frontend behavior in the `Users` page for manual QA runs.

| # | UI Check | Steps | Expected |
|---|----------|-------|----------|
| 1 | Existing user shows confirmation prompt | In `Users` -> `Create User`, enter username that exists in OS/directory, select roles, click `Create` | Create dialog closes and existing-user confirmation dialog appears |
| 2 | Existing user confirm path | From confirmation dialog click confirm (`Add to ECUBE`) | Confirmation dialog closes, user is linked to ECUBE roles, no password dialog appears |
| 3 | Existing user cancel path | From confirmation dialog click `Cancel` | Dialog closes, returns to Users page (no create dialog reopened) |
| 4 | New user opens password dialog | In `Create User`, enter brand-new username + roles and click `Create` | Password dialog appears (with password + confirm-password fields) |
| 5 | Password mismatch validation | In password dialog enter different values in password and confirm fields | Inline mismatch message appears and submit remains disabled |
| 6 | Show/hide password toggle | In password dialog click show/hide control | Password field visibility toggles between masked and plain text |
| 7 | New user completion | Enter matching password/confirm values and submit | Dialog closes and newly created user appears in Users list with expected roles |
| 8 | Directory-backed visibility | Link a directory-backed user with DB roles and refresh Users page | User is visible in list even if host-level fields are placeholders |

### 12.10 Admin Log Viewing API

All admin log endpoints require the `admin` role.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | View logs — unauthenticated | `GET /admin/logs/view` without token | 401, `UNAUTHORIZED` |
| 2 | View logs — non-admin denied | `GET /admin/logs/view` with manager/processor/auditor token | 403, `FORBIDDEN`; denied audit event recorded |
| 3 | View logs — unknown source | `GET /admin/logs/view?source=unknown` with admin token | 404, unknown log source |
| 4 | View logs — baseline response shape | `GET /admin/logs/view?source=app&limit=5&offset=0` | 200 with object fields: `source`, `fetched_at`, `file_modified_at`, `offset`, `limit`, `returned`, `has_more`, `lines` |
| 5 | View logs — source path redaction | Inspect `source.path` in successful response | Basename only (for example `app.log`), no absolute filesystem path |
| 6 | View logs — offset pagination | Create known numbered lines, call `GET /admin/logs/view?limit=5&offset=2` | Returns correct window from tail semantics, `returned <= limit` |
| 7 | View logs — reverse ordering | Compare `reverse=false` vs `reverse=true` on same query | Same selected window; line order is inverted when `reverse=true` |
| 8 | View logs — search filtering | `GET /admin/logs/view?search=error` | Only matching lines are returned (case-insensitive contains) |
| 9 | View logs — sensitive value redaction | Include tokens/passwords in source log lines, call view endpoint | Sensitive values replaced with redacted markers in `lines[].content` |
| 10 | View logs — success audit | `GET /audit?action=LOG_LINES_VIEWED` after successful view | Audit entry includes `source`, `limit`, `offset`, `returned`, `has_more`, and basename `log_file` |
| 11 | List logs — unauthenticated | `GET /admin/logs` without token | 401, `UNAUTHORIZED` |
| 12 | List logs — non-admin denied | `GET /admin/logs` with non-admin token | 403, `FORBIDDEN`; denied audit event recorded |
| 13 | List logs — response envelope | `GET /admin/logs` with admin token and file logging configured | 200 object with `log_files` array and `total_size`; no `log_directory` field in response |
| 14 | Download log — non-admin denied | `GET /admin/logs/app.log` with non-admin token | 403, `FORBIDDEN`; denied audit event recorded |
| 15 | Download log — path traversal blocked | `GET /admin/logs/../../../etc/passwd` | Rejected (400/404/422), no file disclosure |
| 16 | Download log — success audit | Download valid file as admin, then query audit | `LOG_FILE_DOWNLOADED` entry includes requested filename |

### 12.10.1 Runtime Configuration

Runtime configuration endpoints are admin-only.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Get configuration — admin | `GET /admin/configuration` with admin token | 200, response includes editable settings such as `log_level` and DB pool fields |
| 2 | Get configuration — non-admin denied | `GET /admin/configuration` with manager/processor/auditor token | 403, `FORBIDDEN` |
| 3 | Update runtime-only setting | `PUT /admin/configuration` with `{"log_level": "DEBUG"}` | 200, `status: "updated"`, `changed_settings` includes `log_level`, `restart_required` is `false` |
| 4 | Update restart-required setting | `PUT /admin/configuration` with `{"db_pool_recycle_seconds": 120}` | 200, `restart_required` is `true` and the response lists the restart-required setting |
| 5 | Reject empty update payload | `PUT /admin/configuration` with `{}` | 422 |
| 6 | Reject unwritable log file path | `PUT /admin/configuration` with `{"log_file": "/var/log/ecube/denied.log"}` when path is not writable | 422, message indicates the log file cannot be written |
| 7 | Configuration update audit trail | Update configuration, then query `GET /audit?action=CONFIGURATION_UPDATED` | Audit entry lists changed settings without leaking sensitive paths or secrets |
| 8 | Restart requires confirmation | `POST /admin/configuration/restart` with `{"confirm": false}` | 400 |
| 9 | Restart request accepted when confirmed | `POST /admin/configuration/restart` with `{"confirm": true}` | 200, `status: "restart_requested"`, `service: "ecube"` |

### 12.10.2 Help System

Run these checks when the tested build includes the in-app Help feature.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Help trigger is visible in authenticated shell | Sign in to the application and inspect the shell/header | A Help trigger is visible without navigating away from the current page |
| 2 | Help opens in-app | Activate the Help trigger from any primary page | Help opens in a modal or equivalent in-app panel |
| 3 | Help does not break current workflow context | Open Help while on Drives, Mounts, Jobs, or Audit, then close it | Closing Help returns to the same page and preserved workflow context |
| 4 | Help content is curated and user-facing | Review Help content in the modal | Content is derived from the user manual and excludes installer-only or operator-only internals |
| 5 | Open full help document works | Use the Help modal action to open the full document if present | Full help content opens successfully and remains consistent with the in-app content |
| 6 | Missing help asset fails gracefully | Test a build with the Help asset intentionally missing or inaccessible | UI shows a non-fatal fallback state with retry or operator guidance instead of breaking the app shell |

### 12.11 First-Run Setup

Setup endpoints are unauthenticated and can only succeed once.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Status — not initialized | `GET /setup/status` on fresh database | 200, `{"initialized": false}` |
| 2 | Initialize | `POST /setup/initialize` with valid username and password | 200, returns message, username, groups_created |
| 3 | Status — initialized | `GET /setup/status` after initialization | 200, `{"initialized": true}` |
| 4 | Re-initialize rejected | `POST /setup/initialize` again | 409, Conflict |
| 5 | Invalid username | `POST /setup/initialize` with uppercase or special chars | 422 |
| 6 | Empty password | `POST /setup/initialize` with `{"password": ""}` | 422 |
| 7 | Unsafe password chars | `POST /setup/initialize` with password containing newline or colon | 422, unsafe characters |
| 8 | Login as initialized admin | `POST /auth/token` with the admin credentials from step 2 | 200, JWT contains `admin` role |
| 9 | SYSTEM_INITIALIZED audit log | `GET /audit?action=SYSTEM_INITIALIZED` | Audit entry with actor |

### 12.12 Chain-of-Custody Handoff

Chain-of-Custody (CoC) handoff ensures legal custody transfer of evidence is properly recorded and drives are archived after transfer to prevent accidental reuse or operational confusion.

#### 12.12.1 CoC Report Retrieval

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Retrieve CoC — by drive_id | `GET /audit/chain-of-custody?drive_id=42` with auditor/manager/admin token | 200, `selector_mode: "DRIVE_ID"`, report contains events for that drive |
| 2 | Retrieve CoC — by drive_sn | `GET /audit/chain-of-custody?drive_sn=ABC123DEF` with manager token | 200, `selector_mode: "DRIVE_SN"`, report contains events for that drive |
| 3 | Retrieve CoC — by project_id | `GET /audit/chain-of-custody?project_id=CASE-2026-007` with auditor token | 200, `selector_mode: "PROJECT"`, reports array contains all non-archived drives for project |
| 4 | CoC — processor denied | `GET /audit/chain-of-custody?drive_id=42` with processor token | 403, `FORBIDDEN` |
| 5 | CoC — unauthenticated denied | `GET /audit/chain-of-custody?drive_id=42` without token | 401, `UNAUTHORIZED` |
| 6 | CoC — no selector | `GET /audit/chain-of-custody` with no query parameters | 422, at least one selector required |
| 7 | CoC — drive_id takes precedence | `GET /audit/chain-of-custody?drive_id=42&drive_sn=ABC&project_id=CASE-X` | 200, `selector_mode: "DRIVE_ID"` (ignores other selectors) |
| 8 | CoC — project_id mismatch | `GET /audit/chain-of-custody?drive_id=42&project_id=WRONG-PROJECT` where drive is bound to different project | 409, `CONFLICT`, mismatch detail |
| 9 | CoC report fields | Inspect any `GET /audit/chain-of-custody` response | `reports[].drive_id`, `reports[].drive_sn`, `reports[].project_id`, `reports[].custody_complete`, `reports[].chain_of_custody_events` present |
| 10 | CoC events include lifecycle | Inspect `chain_of_custody_events` in a report with completed job | Events include `DRIVE_INITIALIZED`, `JOB_CREATED`, `JOB_STARTED`, `JOB_COMPLETED`, `DRIVE_EJECT_PREPARED`, `COC_HANDOFF_CONFIRMED` (if handed off) |
| 11 | CoC manifest summary | Inspect `manifest_summary` in CoC report | Array of objects with `job_id`, `total_files`, `total_bytes`, `manifest_count` |
| 12 | CoC — delivery_time absence (no handoff) | Complete a job and eject without handoff, query `GET /audit/chain-of-custody?drive_id=...` | `chain_of_custody_events` do not contain `COC_HANDOFF_CONFIRMED`; `custody_complete` is `false` |

#### 12.12.2 CoC Handoff Confirmation

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Confirm handoff — valid | `POST /audit/chain-of-custody/handoff` with drive_id, possessor, delivery_time (UTC ISO), received_by, receipt_ref | 200, response includes all submitted fields + server-generated `event_id` |
| 2 | Confirm handoff — possessor required | `POST /audit/chain-of-custody/handoff` with missing `possessor` | 422, validation error |
| 3 | Confirm handoff — delivery_time required | `POST /audit/chain-of-custody/handoff` with missing `delivery_time` | 422, validation error |
| 4 | Confirm handoff — UTC only | `POST /audit/chain-of-custody/handoff` with `delivery_time: "2026-04-12T14:00:00+05:00"` (non-UTC) | 422, must be UTC timezone |
| 5 | Confirm handoff — drive_id required | `POST /audit/chain-of-custody/handoff` with missing `drive_id` | 422, validation error |
| 6 | Confirm handoff — idempotent | Submit same handoff twice with identical (drive_id, possessor, delivery_time, receipt_ref, project_id) | Both return 200 with same `event_id`; only one `COC_HANDOFF_CONFIRMED` audit entry. Idempotency is scoped to the resolved `project_id` — a prior-project handoff on the same drive does not match. |
| 7 | Confirm handoff — project_id mismatch | `POST /audit/chain-of-custody/handoff` with `project_id` that differs from drive binding | 409, `CONFLICT` |
| 8 | Confirm handoff — drive not found | `POST /audit/chain-of-custody/handoff` with non-existent drive_id | 404, `NOT_FOUND` |
| 9 | Confirm handoff — processor denied | `POST /audit/chain-of-custody/handoff` with processor token | 403, `FORBIDDEN` |
| 10 | Confirm handoff — auditor denied | `POST /audit/chain-of-custody/handoff` with auditor token | 403, `FORBIDDEN` |
| 11 | Audit trail — COC_HANDOFF_CONFIRMED | Query `GET /audit?action=COC_HANDOFF_CONFIRMED` after handoff | Entry includes drive_id, project_id, possessor, delivery_time (ISO), received_by, receipt_ref, actor |

#### 12.12.3 Drive Archival After Handoff

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Drive state post-handoff | Initialize drive (state → IN_USE), run prepare-eject (state → AVAILABLE), confirm handoff | Drive transitions to `current_state: ARCHIVED` |
| 2 | Archived drive excluded from CoC by drive_id | Archive a drive, then `GET /audit/chain-of-custody?drive_id=<archived_id>` | 410, `Gone`, message includes "archived" |
| 3 | Archived drive excluded from CoC by project_id | Archive one of two drives in a project, then `GET /audit/chain-of-custody?project_id=PROJ` | 200, report contains only the non-archived drive |
| 4 | Archived drive excluded from CoC by drive_sn | Archive a drive, then `GET /audit/chain-of-custody?drive_sn=<sn>` | 410, `Gone` |
| 5 | Archived drives cannot initialize (prevents reuse) | Archive a drive, attempt `POST /drives/<archived_id>/initialize` | 409, `CONFLICT`, message includes "archived" |
| 6 | Archived drives cannot format | Archive a drive, attempt `POST /drives/<archived_id>/format` | 409, `CONFLICT` |
| 7 | Archived drives cannot prepare-eject | Archive a drive, attempt `POST /drives/<archived_id>/prepare-eject` | 409, `CONFLICT` |
| 8 | Archived audit trail preserved | Review full audit log (without CoC filter) after archival | All audit entries for the archived drive remain visible (CoC filtering is read-side only) |
| 9 | Archive idempotency | Call handoff endpoint twice with same contract (drive_id, possessor, delivery_time, receipt_ref) | Both succeed; drive transitions to ARCHIVED once (no duplicate operations) |

#### 12.12.4 UI: CoC Wizard Workflow

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | CoC page accessible after job completion | Complete a job, prepare-eject drive, navigate to Audit view | CoC tab/section visible and accessible |
| 2 | Drive selector is dropdown | In CoC filter panel, click drive selector | Dropdown shows list of existing (non-archived) drives sorted by ID |
| 3 | Project selector is dropdown | In CoC filter panel, click project selector | Dropdown shows list of unique project IDs from current drive bindings |
| 4 | Load CoC by drive | Select a drive from dropdown and click "Load CoC" | Report displays lifecycle events and manifest summary for that drive |
| 5 | CoC prefill handoff form | Click "Prefill Handoff" on a CoC report | Handoff form populates with drive_id and project_id from the report |
| 6 | Handoff confirmation warning modal appears | After filling handoff form and clicking "Confirm Handoff" | Modal appears with warning text: "This action will permanently archive the drive..." |
| 7 | Handoff warning shows confirmation buttons | Inspect warning modal | Two buttons: "Yes, archive drive" (danger styling) and "Cancel" |
| 8 | Cancel handoff from modal | Click "Cancel" in warning modal | Modal closes, form state preserved, no handoff submitted |
| 9 | Confirm handoff from modal | Click "Yes, archive drive" in warning modal | Modal closes, handoff submitted; upon success, status message "Custody handoff recorded." appears and report reloads |
| 10 | Archived drive removed from report lists | After handoff, reload page or navigate away/back | Archived drive no longer appears in CoC filter dropdowns or project reports |
| 11 | Handoff form validation | Submit handoff form with missing possessor or delivery_time | Inline validation error shown (form not submitted) |
| 12 | Manual archive result | After successful handoff, query drive state via API | Drive state is `ARCHIVED` |

#### 12.12.5 Manual Test Data Setup (SQL)

This section provides SQL scripts to populate the database with realistic chain-of-custody test data, enabling manual QA testing of the CoC workflows without requiring a full copy sequence.

**Prerequisites:**
- Initialized ECUBE system with at least one admin user (`ecube_admin` in examples below)
- PostgreSQL database connection via `psql` or equivalent admin tool
- Audit log entries will be created by the SQL inserts directly (not via API)

**Scenario Summary:**
The following setup creates two projects with three USB drives each:
- Project `CASE-2026-001`: Two completed jobs (one with archived drive, one with active drive)
- Project `CASE-2026-002`: One completed job with a non-archived drive
- All drives in `IN_USE` state (already initialized), with job lifecycle and manifest records
- Full audit trail showing `DRIVE_INITIALIZED`, `JOB_CREATED`, `JOB_STARTED`, `JOB_COMPLETED`, and (for one drive) `COC_HANDOFF_CONFIRMED`

**Setup Script (PostgreSQL):**

```sql
-- ============================================================================
-- ECUBE Chain-of-Custody Test Data Setup
-- ============================================================================
-- This script populates test data for manual CoC testing.
-- Adjust project IDs, drive serial numbers, and timestamps as needed.
-- ============================================================================

BEGIN; -- Start transaction; ROLLBACK if errors encountered

-- ============================================================================
-- 1. Hub and Port Setup
-- ============================================================================

INSERT INTO usb_hubs (name, system_identifier, location_hint, vendor_id, product_id)
VALUES
  ('Test Hub 1', 'test-hub-001', 'Back rack left', '0x1234', '0x5678'),
  ('Test Hub 2', 'test-hub-002', 'Back rack right', '0xabcd', '0xef00')
ON CONFLICT (system_identifier) DO NOTHING;

-- Retrieve hub IDs for port insertion
WITH hub_mapping AS (
  SELECT id, system_identifier FROM usb_hubs WHERE system_identifier IN ('test-hub-001', 'test-hub-002')
)
INSERT INTO usb_ports (hub_id, port_number, system_path, friendly_label, enabled, vendor_id, product_id, speed)
SELECT h.id, port_num, sys_path, label, true, vendor, product, '480'
FROM (VALUES
  ('test-hub-001', 1, '1-1', 'Port 1A', '0xd000', '0x0001'),
  ('test-hub-001', 2, '1-2', 'Port 1B', '0xd000', '0x0002'),
  ('test-hub-001', 3, '1-3', 'Port 1C', '0xd000', '0x0003'),
  ('test-hub-002', 1, '4-1', 'Port 2A', '0xd001', '0x0004'),
  ('test-hub-002', 2, '4-2', 'Port 2B', '0xd001', '0x0005'),
  ('test-hub-002', 3, '4-3', 'Port 2C', '0xd001', '0x0006')
) AS v (hub_sys, port_num, sys_path, label, vendor, product)
JOIN hub_mapping h ON h.system_identifier = v.hub_sys
ON CONFLICT (system_path) DO NOTHING;

-- ============================================================================
-- 2. USB Drives Setup (3 per project, IN_USE state)
-- ============================================================================

WITH port_mapping AS (
  SELECT id, hub_id FROM usb_ports WHERE system_path IN ('1-1', '1-2', '1-3', '4-1', '4-2', '4-3')
)
INSERT INTO usb_drives (port_id, device_identifier, filesystem_path, capacity_bytes, encryption_status, filesystem_type, current_state, current_project_id, last_seen_at)
SELECT 
  (SELECT id FROM usb_ports WHERE system_path = sys_p ORDER BY id LIMIT 1),
  dev_id, fs_path, 16000000000, 'encrypted', 'exfat', 'IN_USE', proj_id, NOW()
FROM (VALUES
  ('1-1', 'coC-test-drive-001', '/dev/sdb', 'CASE-2026-001'),
  ('1-2', 'coC-test-drive-002', '/dev/sdc', 'CASE-2026-001'),
  ('1-3', 'coC-test-drive-003', '/dev/sdd', 'CASE-2026-001'),
  ('4-1', 'coC-test-drive-004', '/dev/sde', 'CASE-2026-002'),
  ('4-2', 'coC-test-drive-005', '/dev/sdf', 'CASE-2026-002'),
  ('4-3', 'coC-test-drive-006', '/dev/sdg', 'CASE-2026-002')
) AS v (sys_p, dev_id, fs_path, proj_id)
ON CONFLICT (device_identifier) DO NOTHING;

-- ============================================================================
-- 3. Network Mount Setup (one test mount per project)
-- ============================================================================

INSERT INTO network_mounts (type, remote_path, local_mount_point, status, last_checked_at)
VALUES
  ('NFS', '192.168.1.10:/evidence/case-001', '/mnt/evidence-001', 'MOUNTED', NOW()),
  ('NFS', '192.168.1.10:/evidence/case-002', '/mnt/evidence-002', 'MOUNTED', NOW())
ON CONFLICT (local_mount_point) DO NOTHING;

-- ============================================================================
-- 4. Export Jobs Setup (2 per project, COMPLETED state)
-- ============================================================================

-- Note: retrieve drive IDs via SELECT * FROM usb_drives WHERE current_project_id = 'CASE-2026-001';
-- Then use those IDs in subsequent inserts.

INSERT INTO export_jobs (
  project_id, evidence_number, source_path, target_mount_path, status,
  total_bytes, copied_bytes, file_count, thread_count, max_file_retries,
  retry_delay_seconds, started_at, completed_at, created_by, started_by, client_ip, created_at
)
VALUES
  ('CASE-2026-001', 'EV-2026-001-A', '/mnt/evidence-001/data-batch-1', '/mnt/external-001/batch-1',
   'COMPLETED', 5000000000, 5000000000, 2500, 4, 3, 1, NOW() - INTERVAL '2 days 5 hours', NOW() - INTERVAL '2 days 3 hours',
   'ecube_admin', 'ecube_admin', '192.168.1.50', NOW() - INTERVAL '2 days 6 hours'),
  
  ('CASE-2026-001', 'EV-2026-001-B', '/mnt/evidence-001/data-batch-2', '/mnt/external-002/batch-2',
   'COMPLETED', 3500000000, 3500000000, 1800, 4, 3, 1, NOW() - INTERVAL '1 day 8 hours', NOW() - INTERVAL '1 day 6 hours',
   'ecube_admin', 'ecube_admin', '192.168.1.50', NOW() - INTERVAL '1 day 9 hours'),
  
  ('CASE-2026-002', 'EV-2026-002-A', '/mnt/evidence-002/data-batch-3', '/mnt/external-003/batch-3',
   'COMPLETED', 4200000000, 4200000000, 2100, 4, 3, 1, NOW() - INTERVAL '12 hours', NOW() - INTERVAL '10 hours',
   'ecube_admin', 'ecube_admin', '192.168.1.50', NOW() - INTERVAL '13 hours')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 5. Export Files Setup (sample files per job)
-- ============================================================================

-- Get job IDs: SELECT id, project_id, evidence_number FROM export_jobs;
-- Then use in the following (example with assumed IDs 1, 2, 3):

INSERT INTO export_files (job_id, relative_path, size_bytes, checksum, status, error_message, retry_attempts)
SELECT j.id, f_path, f_size, f_hash, 'COMPLETED', NULL, 0
FROM export_jobs j
JOIN (VALUES
  (1, 'file-001.pdf', 105000000, 'sha256:aabbccdd11223344556677889900aabbccddee00112233445566778899'),
  (1, 'file-002.xlsx', 52000000, 'sha256:1122334455667788990011223344556677889900aabbccddee00112233'),
  (1, 'file-003.docx', 8500000, 'sha256:99887766554433221100aabbccddee00112233445566778899aabbccdd'),
  (2, 'batch2-file-001.zip', 75000000, 'sha256:11223344556677889900aabbccddee00112233445566778899aabbcc'),
  (2, 'batch2-file-002.jpg', 45000000, 'sha256:aabbccddee00112233445566778899aabbccddee0011223344556677'),
  (3, 'case2-001.tar.gz', 200000000, 'sha256:5566778899aabbccddee00112233445566778899aabbccddee0011'),
  (3, 'case2-002.iso', 150000000, 'sha256:ddee00112233445566778899aabbccddee00112233445566778899')
) AS v (job_id, f_path, f_size, f_hash) ON v.job_id = j.id
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 6. Manifests Setup (one per job)
-- ============================================================================

INSERT INTO manifests (job_id, manifest_path, format, created_at)
SELECT id, CONCAT('/manifests/job-', id, '-manifest.json'), 'JSON', NOW()
FROM export_jobs
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 7. Drive Assignments Setup (link drives to jobs)
-- ============================================================================

-- Assign the first drive from each project to its first job, second drive to second job
INSERT INTO drive_assignments (drive_id, job_id, assigned_at, released_at)
SELECT d.id, j.id, NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days'
FROM export_jobs j
JOIN usb_drives d ON j.project_id = d.current_project_id
WHERE j.project_id = 'CASE-2026-001'
LIMIT 2
ON CONFLICT DO NOTHING;

-- Assign third job's drive
INSERT INTO drive_assignments (drive_id, job_id, assigned_at, released_at)
SELECT d.id, j.id, NOW() - INTERVAL '12 hours', NOW() - INTERVAL '12 hours'
FROM export_jobs j
JOIN usb_drives d ON j.project_id = d.current_project_id
WHERE j.project_id = 'CASE-2026-002'
LIMIT 1
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 8. Audit Logs Setup (lifecycle events for CoC visibility)
-- ============================================================================

-- A single-row CTE resolves all drive/job IDs from their known unique
-- identifiers so that audit_logs.drive_id, audit_logs.job_id, and every
-- occurrence of those IDs inside the details JSONB are always consistent,
-- regardless of what other rows already exist in the database.
WITH ids AS (
  SELECT
    (SELECT id FROM usb_drives  WHERE device_identifier = 'coC-test-drive-001') AS d001,
    (SELECT id FROM usb_drives  WHERE device_identifier = 'coC-test-drive-002') AS d002,
    (SELECT id FROM usb_drives  WHERE device_identifier = 'coC-test-drive-004') AS d004,
    (SELECT id FROM export_jobs WHERE evidence_number   = 'EV-2026-001-A')      AS j001a,
    (SELECT id FROM export_jobs WHERE evidence_number   = 'EV-2026-001-B')      AS j001b,
    (SELECT id FROM export_jobs WHERE evidence_number   = 'EV-2026-002-A')      AS j002a
)
INSERT INTO audit_logs (timestamp, user, action, project_id, drive_id, job_id, details, client_ip)
SELECT evt_ts, 'ecube_admin', evt_action, proj_id, drive_id_col, job_id_col, evt_details, '192.168.1.50'
FROM ids
CROSS JOIN LATERAL (VALUES
  -- CASE-2026-001, Job 1 lifecycle (drive-001 / EV-2026-001-A)
  (NOW() - INTERVAL '2 days 6 hours', 'CASE-2026-001', 'DRIVE_INITIALIZED',
   ids.d001, NULL::INT,
   jsonb_build_object('drive_id', ids.d001, 'project_id', 'CASE-2026-001', 'state_before', 'AVAILABLE', 'state_after', 'IN_USE')),
  (NOW() - INTERVAL '2 days 6 hours', 'CASE-2026-001', 'JOB_CREATED',
   NULL::INT, ids.j001a,
   jsonb_build_object('job_id', ids.j001a, 'evidence_number', 'EV-2026-001-A', 'source_path', '/mnt/evidence-001/data-batch-1')),
  (NOW() - INTERVAL '2 days 5 hours', 'CASE-2026-001', 'JOB_STARTED',
   NULL::INT, ids.j001a,
   jsonb_build_object('job_id', ids.j001a, 'evidence_number', 'EV-2026-001-A', 'thread_count', 4)),
  (NOW() - INTERVAL '2 days 3 hours', 'CASE-2026-001', 'JOB_COMPLETED',
   NULL::INT, ids.j001a,
   jsonb_build_object('job_id', ids.j001a, 'evidence_number', 'EV-2026-001-A', 'total_bytes', 5000000000, 'file_count', 2500, 'duration_seconds', 7200)),

  -- CASE-2026-001, Job 2 lifecycle (drive-002 / EV-2026-001-B)
  (NOW() - INTERVAL '1 day 9 hours', 'CASE-2026-001', 'DRIVE_INITIALIZED',
   ids.d002, NULL::INT,
   jsonb_build_object('drive_id', ids.d002, 'project_id', 'CASE-2026-001', 'state_before', 'AVAILABLE', 'state_after', 'IN_USE')),
  (NOW() - INTERVAL '1 day 9 hours', 'CASE-2026-001', 'JOB_CREATED',
   NULL::INT, ids.j001b,
   jsonb_build_object('job_id', ids.j001b, 'evidence_number', 'EV-2026-001-B', 'source_path', '/mnt/evidence-001/data-batch-2')),
  (NOW() - INTERVAL '1 day 8 hours', 'CASE-2026-001', 'JOB_STARTED',
   NULL::INT, ids.j001b,
   jsonb_build_object('job_id', ids.j001b, 'evidence_number', 'EV-2026-001-B', 'thread_count', 4)),
  (NOW() - INTERVAL '1 day 6 hours', 'CASE-2026-001', 'JOB_COMPLETED',
   NULL::INT, ids.j001b,
   jsonb_build_object('job_id', ids.j001b, 'evidence_number', 'EV-2026-001-B', 'total_bytes', 3500000000, 'file_count', 1800, 'duration_seconds', 7200)),

  -- CASE-2026-001, CoC handoff (drive-001 archived)
  (NOW() - INTERVAL '1 day', 'CASE-2026-001', 'COC_HANDOFF_CONFIRMED',
   ids.d001, NULL::INT,
   jsonb_build_object('drive_id', ids.d001, 'project_id', 'CASE-2026-001', 'possessor', 'Officer Smith',
                      'delivery_time', '2026-04-11T14:30:00Z', 'received_by', 'Evidence Custody', 'receipt_ref', 'RCP-2026-001')),

  -- CASE-2026-002, Job 3 lifecycle (drive-004 / EV-2026-002-A)
  (NOW() - INTERVAL '13 hours', 'CASE-2026-002', 'DRIVE_INITIALIZED',
   ids.d004, NULL::INT,
   jsonb_build_object('drive_id', ids.d004, 'project_id', 'CASE-2026-002', 'state_before', 'AVAILABLE', 'state_after', 'IN_USE')),
  (NOW() - INTERVAL '13 hours', 'CASE-2026-002', 'JOB_CREATED',
   NULL::INT, ids.j002a,
   jsonb_build_object('job_id', ids.j002a, 'evidence_number', 'EV-2026-002-A', 'source_path', '/mnt/evidence-002/data-batch-3')),
  (NOW() - INTERVAL '12 hours', 'CASE-2026-002', 'JOB_STARTED',
   NULL::INT, ids.j002a,
   jsonb_build_object('job_id', ids.j002a, 'evidence_number', 'EV-2026-002-A', 'thread_count', 4)),
  (NOW() - INTERVAL '10 hours', 'CASE-2026-002', 'JOB_COMPLETED',
   NULL::INT, ids.j002a,
   jsonb_build_object('job_id', ids.j002a, 'evidence_number', 'EV-2026-002-A', 'total_bytes', 4200000000, 'file_count', 2100, 'duration_seconds', 7200))
) AS v (evt_ts, proj_id, evt_action, drive_id_col, job_id_col, evt_details)
ON CONFLICT DO NOTHING;

-- ============================================================================
-- 9. Manually Archive Drive 1 (CASE-2026-001) via state transition
-- ============================================================================
-- This simulates the automatic state transition that occurs on CoC handoff.
-- Drive 1 should now be ARCHIVED.

UPDATE usb_drives
SET current_state = 'ARCHIVED'
WHERE device_identifier = 'coC-test-drive-001' AND current_state = 'IN_USE';

-- ============================================================================
-- 10. Verify Setup
-- ============================================================================

SELECT 'Hubs created:' AS check_point;
SELECT COUNT(*) AS hub_count FROM usb_hubs WHERE system_identifier LIKE 'test-hub-%';

SELECT 'Ports created:' AS check_point;
SELECT COUNT(*) AS port_count FROM usb_ports WHERE system_path IN ('1-1', '1-2', '1-3', '4-1', '4-2', '4-3');

SELECT 'Drives (IN_USE and ARCHIVED):' AS check_point;
SELECT current_project_id, current_state, COUNT(*) AS count FROM usb_drives WHERE current_project_id IN ('CASE-2026-001', 'CASE-2026-002') GROUP BY current_project_id, current_state;

SELECT 'Jobs COMPLETED:' AS check_point;
SELECT project_id, COUNT(*) AS job_count FROM export_jobs WHERE status = 'COMPLETED' GROUP BY project_id;

SELECT 'Audit entries by action:' AS check_point;
SELECT action, COUNT(*) AS count FROM audit_logs WHERE project_id IN ('CASE-2026-001', 'CASE-2026-002') GROUP BY action;

COMMIT;
```

**Cleanup Script (PostgreSQL):**

```sql
-- ============================================================================
-- ECUBE Test Data Cleanup
-- ============================================================================
-- Remove all test data in reverse dependency order (respecting FKs).
-- This script is idempotent and safe to run multiple times.
-- ============================================================================

BEGIN; -- Wrap in transaction for safety

-- Delete audit logs first (no dependents, but clears history)
DELETE FROM audit_logs WHERE project_id IN ('CASE-2026-001', 'CASE-2026-002');

-- Delete drive assignments (FK to drives and jobs)
DELETE FROM drive_assignments WHERE job_id IN (
  SELECT id FROM export_jobs WHERE project_id IN ('CASE-2026-001', 'CASE-2026-002')
);

-- Delete manifests (FK to jobs)
DELETE FROM manifests WHERE job_id IN (
  SELECT id FROM export_jobs WHERE project_id IN ('CASE-2026-001', 'CASE-2026-002')
);

-- Delete export files (FK to jobs)
DELETE FROM export_files WHERE job_id IN (
  SELECT id FROM export_jobs WHERE project_id IN ('CASE-2026-001', 'CASE-2026-002')
);

-- Delete export jobs (FK to nothing, but cascades above)
DELETE FROM export_jobs WHERE project_id IN ('CASE-2026-001', 'CASE-2026-002');

-- Delete network mounts
DELETE FROM network_mounts WHERE local_mount_point LIKE '/mnt/evidence-%';

-- Delete USB drives (FK to ports)
DELETE FROM usb_drives WHERE current_project_id IN ('CASE-2026-001', 'CASE-2026-002');

-- Delete USB ports (FK to hubs)
DELETE FROM usb_ports WHERE system_path IN ('1-1', '1-2', '1-3', '4-1', '4-2', '4-3');

-- Delete USB hubs
DELETE FROM usb_hubs WHERE system_identifier LIKE 'test-hub-%';

-- Verify cleanup
SELECT 'Cleanup verification:' AS status;
SELECT 'Remaining CASE-2026 drives:', COUNT(*) FROM usb_drives WHERE current_project_id LIKE 'CASE-2026%';
SELECT 'Remaining test hubs:', COUNT(*) FROM usb_hubs WHERE system_identifier LIKE 'test-hub%';
SELECT 'Remaining test jobs:', COUNT(*) FROM export_jobs WHERE project_id LIKE 'CASE-2026%';

COMMIT;
```

**Manual Testing Workflow:**

1. **Run setup script:**
   ```bash
   psql -h localhost -U ecube_admin -d ecube < setup-coc-testdata.sql
   ```

2. **Verify population via API:**
  - `GET /audit/chain-of-custody?project_id=CASE-2026-001` — should return 200 with only non-archived drives (for this dataset: 1 IN_USE drive)
   - `GET /audit/chain-of-custody?drive_id=<archived_drive_id>` — should return 410 Gone
   - Inspect lifecycle events in the response

3. **Test CoC UI:**
   - Navigate to Audit view
   - Filter by project `CASE-2026-001` — verify archived drive is hidden
   - Filter by project `CASE-2026-002` — verify active drive is shown
   - Attempt handoff on active drive; verify modal appears and archival succeeds

4. **Run cleanup script before next test run:**
   ```bash
   psql -h localhost -U ecube_admin -d ecube < cleanup-coc-testdata.sql
   ```

**Notes:**
- Adjust timestamps (`NOW() - INTERVAL`) to reflect your test timing preferences.
- Replace `192.168.1.50` with your actual QA machine IP if needed.
- The `ON CONFLICT DO NOTHING` clauses make the script idempotent; safe to re-run.
- For SQLite-based test suites, use equivalent SQL syntax or rely on the Python test fixtures in `tests/conftest.py`.



- The target database does not exist yet (PostgreSQL SQLSTATE `3D000`).
- The application role does not exist yet (PostgreSQL SQLSTATE `28000`).
- The database is reachable but the schema has not been migrated (e.g. `user_roles` table missing).

Only a truly unreachable server (connection refused, timeout, network failure) triggers the fail-closed 503.  Transient query errors (e.g. permission denied on the `user_roles` table) on a reachable database also fail closed — they are **not** treated as initial setup.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | System info — Linux host defaults | `GET /setup/database/system-info` before setup | 200, `{"in_docker": false, "suggested_db_host": "localhost"}` |
| 2 | Provision status — pre-init public | `GET /setup/database/provision-status` before any admin exists | 200, `{"provisioned": false}` |
| 3 | Provision status — post-init requires admin | `GET /setup/database/provision-status` without token after setup | 401 |
| 4 | Provision status — state unknown | Stop PostgreSQL, `GET /setup/database/provision-status` during initial setup | 503, cannot determine provisioning state |
| 5 | Test connection — success | `POST /setup/database/test-connection` with valid PostgreSQL credentials | 200, `{"status": "ok", "server_version": "..."}` |
| 6 | Test connection — bad host | `POST /setup/database/test-connection` with unreachable host | 400, connection error |
| 7 | Test connection — SSRF host | `POST /setup/database/test-connection` with `"host": "http://evil.com"` | 422, invalid host |
| 8 | Test connection — port out of range | `POST /setup/database/test-connection` with `"port": 99999` | 422 |
| 9 | Provision — success | `POST /setup/database/provision` with valid credentials | 200, returns database, user, migrations_applied |
| 10 | Provision — bad admin credentials | `POST /setup/database/provision` with wrong admin password | 400, connection error |
| 11 | Provision — invalid database name | `POST /setup/database/provision` with `"app_database": "drop;--"` | 422, invalid identifier |
| 12 | Status — connected | `GET /setup/database/status` with admin token | 200, `connected: true`, migration info |
| 13 | Status — requires auth | `GET /setup/database/status` without token | 401 |
| 14 | Status — requires admin | `GET /setup/database/status` with processor token | 403 |
| 15 | Settings update — success | `PUT /setup/database/settings` with valid partial update | 200, `{"status": "updated", ...}` |
| 16 | Settings update — bad connection | `PUT /setup/database/settings` with unreachable host | 400, connection test failed |
| 17 | Settings update — empty body | `PUT /setup/database/settings` with `{}` | 422, at least one field required |
| 18 | Settings update — requires admin | `PUT /setup/database/settings` with processor token | 403 |
| 19 | Auth after setup — test-connection | `POST /setup/database/test-connection` without token (after admin exists) | 401 |
| 20 | Auth after setup — provision | `POST /setup/database/provision` without token (after admin exists) | 401 |
| 21 | Password redaction | `POST /setup/database/provision` and check response | No password in response body |
| 22 | Re-provision blocked | `POST /setup/database/provision` after successful provisioning (no `force`) | 409, already provisioned |
| 23 | Force re-provision (admin) | `POST /setup/database/provision` with `"force": true` and admin token after successful provisioning | 200, returns database, user, migrations_applied |
| 24 | Force rejected unauthenticated | `POST /setup/database/provision` with `"force": true` during initial setup (no admin exists) | 403, force requires admin |
| 25 | Fail-closed — DB unreachable, no JWT | Stop PostgreSQL, `POST /setup/database/test-connection` without token | 503, database unavailable message |
| 26 | Fail-closed — DB unreachable, admin JWT | Stop PostgreSQL, `POST /setup/database/test-connection` with valid admin token | Request proceeds (not blocked by 503) |
| 27 | Fail-closed — provision state unknown | Stop PostgreSQL, `POST /setup/database/provision` without `"force": true` | 503, cannot determine provisioning state |
| 28 | Force bypasses state check | Stop PostgreSQL, `POST /setup/database/provision` with `"force": true` and admin token | Proceeds to provisioning (no 503 from state check) |
| 29 | Unmigrated DB treated as initial setup | Drop `user_roles` table (or use a fresh empty database), `POST /setup/database/test-connection` without token | 200, request allowed (not 503) |
| 30 | Fresh install — DB/role missing | With PostgreSQL running but the application database or role not yet created, `POST /setup/database/provision` without `force` | 200, provisioning proceeds (not 503) |
| 31 | Fail-closed — OperationalError on reachable DB | Revoke SELECT on `user_roles` (or simulate permission denied), `POST /setup/database/test-connection` without token | 503, does NOT grant unauthenticated access |
| 32 | Fail-closed — unexpected error | Trigger an unexpected exception from admin-check (e.g. coding bug), `POST /setup/database/test-connection` without token | 503, does NOT grant unauthenticated access |
| 33 | Provision — migration failure | `POST /setup/database/provision` with valid credentials but a broken Alembic migration (e.g. conflicting schema) | 500, "migration failed" message; `.env` not updated, engine not swapped |
| 34 | Provision — .env write failure | `POST /setup/database/provision` after making `.env` read-only (or disk full) | 500, "failed to persist" message; engine not swapped |
| 35 | Provision — engine reinit failure | `POST /setup/database/provision` while another reinit is in progress (lock contention) | 500, "engine could not be switched" message; `.env` already written |

### 12.14 Startup State Reconciliation

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Running job failed after restart | Create a job, start it, restart the service while RUNNING | Job status is `FAILED`, `completed_at` is set, audit log contains `JOB_RECONCILED` with `reason: "interrupted by restart"` |
| 2 | Verifying job failed after restart | Start a job, let it reach VERIFYING, restart the service | Job status is `FAILED`, audit log contains `JOB_RECONCILED` with `old_status: "VERIFYING"` |
| 3 | Pending job not affected | Create a job (PENDING), restart the service | Job remains `PENDING`, no `JOB_RECONCILED` audit entry for this job |
| 4 | Completed job not affected | Complete a job, restart the service | Job remains `COMPLETED`, no `JOB_RECONCILED` audit entry |
| 5 | Stale mount corrected | Add and mount a network share, unmount it at OS level (`sudo umount`), restart the service | Mount status is `UNMOUNTED`, audit log contains `MOUNT_RECONCILED` |
| 6 | Active mount preserved | Add and mount a network share (leave it mounted), restart the service | Mount status remains `MOUNTED`, no `MOUNT_RECONCILED` audit entry |
| 7 | USB drives re-discovered | Insert USB drives, restart the service | Drives re-appear with correct state (`AVAILABLE` on enabled ports), `USB_DISCOVERY_SYNC` audit entry present |
| 8 | Idempotency | Restart the service twice without any state changes between restarts | Second restart produces no additional `MOUNT_RECONCILED` or `JOB_RECONCILED` audit entries |
| 9 | Partial failure isolation | Disconnect the NFS server (to cause mount check failure), have a RUNNING job, restart the service | Job is still reconciled to `FAILED` even though mount reconciliation may error; check logs for error message |
| 10 | Cross-process lock — only one worker reconciles | Start Uvicorn with `--workers 4`, have a RUNNING job and a MOUNTED (but stale) mount | Exactly one `JOB_RECONCILED` and one `MOUNT_RECONCILED` audit entry; remaining workers log "skipping reconciliation" at INFO level |
| 11 | Stale lock reclaim | Insert a stale lock row (`locked_at` > 5 minutes ago) via SQL, restart the service | Service reclaims the stale lock, reconciliation runs normally |
| 12 | Lock released after failure | Disconnect NFS, restart the service, reconnect NFS, restart again | Second restart acquires lock and runs reconciliation; lock table is empty after startup completes |

### 12.15 System Health

`GET /introspection/system-health` requires any authenticated role.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Healthy response | `GET /introspection/system-health` with valid token | 200, `status: "ok"`, `database: "connected"` |
| 2 | CPU metric present | Inspect response body | `cpu_percent` is a number between 0 and 100 |
| 3 | Memory metrics present | Inspect response body | `memory_percent` is a number; `memory_used_bytes` and `memory_total_bytes` are positive integers; `memory_used_bytes` ≤ `memory_total_bytes` |
| 4 | Disk I/O metrics present | Inspect response body | `disk_read_bytes` and `disk_write_bytes` are non-negative integers |
| 5 | Active jobs count | Start an export job, call endpoint | `active_jobs` ≥ 1 |
| 6 | Worker queue size | Create a PENDING job (created but not started), call endpoint | `worker_queue_size` ≥ 1 |
| 7 | Worker queue size decrements | Start the pending job, call endpoint again | `worker_queue_size` decreases by 1 (is 0 if no other PENDING jobs exist; job moved to RUNNING) |
| 8 | Degraded when DB down | Stop PostgreSQL, call endpoint with valid token | 200, `status: "degraded"`, `database: "error"`, `database_error` is non-null |
| 9 | Unauthenticated rejected | `GET /introspection/system-health` without token | 401 |
| 10 | Processor role allowed | `GET /introspection/system-health` with processor token | 200 |

### 12.15.1 Liveness, Readiness, and Version

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Liveness endpoint is public | `GET /health/live` without token | 200, service reports live |
| 2 | Readiness endpoint is public | `GET /health/ready` without token on a healthy system | 200, `status: "ready"`, checks show healthy or initialized dependencies |
| 3 | Readiness reports missing database configuration | Clear DB config or test before configuration, then `GET /health/ready` | 503, `status: "not_ready"`, reason indicates database is not configured |
| 4 | Readiness reports mount or provider problems | Break a configured mount or provider, then `GET /health/ready` | 503, response identifies the failing check without using the generic error schema |
| 5 | Version endpoint is public | `GET /introspection/version` without token | 200, returns version/application metadata |
| 6 | Readiness remains separate from authenticated system health | Compare `GET /health/ready` and authenticated `GET /introspection/system-health` | Readiness stays public and fail-fast; system health returns richer operational metrics |

### 12.16 Real-World Copy Performance & Hashing Addendum

This addendum defines a reproducible manual QA scenario that exercises ECUBE copy throughput and hashing with publicly available forensic/eDiscovery-style datasets.

#### Public Dataset Sources

- NIST CFReDS: `https://www.cfreds.nist.gov/` (forensic reference images and challenge datasets).
- Digital Corpora: `https://digitalcorpora.org/` (disk images, file corpora, scenarios; bulk download available via AWS Open Data bucket `s3://digitalcorpora/`).
- EDRM datasets: `https://edrm.net/resources/data-sets/` (EDRM micro/file-format/internationalization datasets).

Use only datasets you are authorized to download and handle in your environment.

#### Test Objective

Validate that ECUBE can copy realistic mixed-file corpora to USB media at stable throughput while preserving hash integrity end-to-end.

#### Recommended Test Matrix

| Profile | Dataset Size | File Mix | USB Targets | Thread Count |
|---|---|---|---|---|
| RW-1 (Baseline) | 10-25 GB | Many small + medium files | 1 drive | 4 |
| RW-2 (Throughput) | 50-100 GB | Large files (100 MB to multi-GB) | 1 drive | 4 and 8 |
| RW-3 (Scale-out) | 25-50 GB per destination | Mixed corpus | 4 drives in parallel | 4 per job |

#### Dataset Preparation (Example)

```bash
# Workspace for source corpora
sudo mkdir -p /mnt/test-evidence/public-corpus
sudo chown -R "$USER":"$USER" /mnt/test-evidence/public-corpus

# Example Digital Corpora pull (choose a specific folder to keep size bounded)
aws s3 cp --recursive s3://digitalcorpora/corpora/files/ \
  /mnt/test-evidence/public-corpus/files/

# Optional: add CFReDS/EDRM downloads into the same corpus root
# (use the provider's documented download links/process)

# Build independent source hash manifest
cd /mnt/test-evidence/public-corpus
find . -type f -print0 | sort -z | xargs -0 sha256sum > source.sha256

# Record source footprint
du -sh .
find . -type f | wc -l
```

#### Execution Procedure

1. Enable target USB ports and confirm drives are `AVAILABLE`.
2. Initialize each target drive to a QA project ID (for example `PROJ-RW-COPY-001`).
3. Create one ECUBE job per target drive using the same `source_path`.
4. Start jobs and poll until terminal status.
5. Run `POST /jobs/{job_id}/verify` for each completed job.
6. Generate manifest for each completed job.
7. Prepare-eject each drive and mount read-only on a verifier host.
8. Recompute destination SHA-256 and compare with `source.sha256`.

#### Throughput Capture Method

Capture per-job metrics from ECUBE job payloads and/or audit timestamps:

- `total_bytes`
- `started_at`
- `completed_at`
- `status`

Compute effective throughput per job:

$$
throughput\_MBps = \frac{total\_bytes}{completed\_at - started\_at} \div 1{,}048{,}576
$$

For parallel runs, also report aggregate throughput:

$$
aggregate\_MBps = \sum_{jobs=1}^{n} throughput\_MBps(job)
$$

#### Hashing and Integrity Validation

- ECUBE verification step must return success for all files (`POST /jobs/{job_id}/verify`).
- Independent verifier check (`sha256sum -c`) on destination copy must report zero mismatches.
- Any mismatch is a test failure and must include attached audit/job/manifest evidence.

#### Pass/Fail Criteria

| Check | Pass Condition |
|---|---|
| Job completion | All benchmark jobs end in `COMPLETED` |
| ECUBE verify | All jobs return successful verification |
| Independent hash check | 0 SHA-256 mismatches against `source.sha256` |
| Stability | No unexpected job retries/failures attributable to ECUBE logic |
| Performance baseline | Throughput variance between repeated RW-1 runs is within +/-15% on same hardware |
| Scale-out behavior | RW-3 aggregate throughput increases versus RW-1 single-drive baseline |

#### Evidence to Attach to QA Report

- Dataset source and exact download scope (paths/filters/date).
- `source.sha256` file and destination hash-check outputs.
- ECUBE job JSON snapshots (`/jobs/{id}`), verify responses, and manifest outputs.
- Audit excerpts for `JOB_CREATED`, `JOB_STARTED`, `JOB_COMPLETED`, verification and manifest events, and `DRIVE_EJECT_PREPARED`.
- Host hardware profile (CPU, RAM, USB controller/hub, drive model).

---

## 13. Environment Reset Between Test Runs

To ensure clean, repeatable results, reset the environment between QA test runs.

### Quick reset (database only)

```bash
# Drop and recreate the database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ecube;"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"

# Re-run migrations
cd /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head
```

### Full reset (database + test data + tokens)

```bash
# 1. Stop the service
sudo systemctl stop ecube

# 2. Drop and recreate the database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ecube;"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"

# 3. Re-run migrations
cd /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head

# 4. (Optional) Re-seed admin role in user_roles table
#    If using DB-managed roles, re-assign after migration:
#    curl -sk -X PUT https://localhost:8443/users/qa-admin/roles \
#      -H "Authorization: Bearer $TOKEN" \
#      -H "Content-Type: application/json" \
#      -d '{"roles": ["admin"]}'

# 4. Clear test evidence data
sudo rm -rf /mnt/test-evidence/case-001

# 5. Physically remove and re-insert any USB drives
#    (this ensures drives start in a clean AVAILABLE state after discovery)

# 6. Start the service
sudo systemctl start ecube

# 7. Re-authenticate (previous tokens are invalid after restart
#    if SECRET_KEY changed, or expired)
TOKEN=$(curl -sk -X POST https://localhost:8443/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username": "qa-admin", "password": "QaPass-admin!"}' \
  | jq -r '.access_token')
```

> **Tip:** USB drives that were in `IN_USE` state will retain that state
> across restarts (project isolation). To fully reset a drive, drop the
> database as shown above, then re-plug the drive.

---

## 14. Service Management

### Systemd Commands

```bash
# Start / stop / restart
sudo systemctl start ecube
sudo systemctl stop ecube
sudo systemctl restart ecube

# Status
sudo systemctl status ecube

# Stream logs
sudo journalctl -u ecube -f

# View last 100 log lines
sudo journalctl -u ecube -n 100

# Filter errors only
sudo journalctl -u ecube -p err
```

### Useful System Commands

```bash
# List USB devices
lsusb

# Detailed USB info
lsusb -v

# Check block devices
lsblk

# View active mounts
mount | grep /dev/sd

# Check which ports the service is listening on
sudo ss -tlnp | grep 8443
```

---

## 15. Troubleshooting

| Symptom | Possible Cause | Resolution |
|---------|---------------|------------|
| Service won't start | Missing `.env` or bad `DATABASE_URL` | Check `sudo journalctl -u ecube -n 50`; verify `/opt/ecube/.env`; test DB with `psql -U ecube -d ecube -h localhost -c "SELECT 1"` |
| Migration fails | Wrong DB credentials or DB doesn't exist | Re-run `CREATE DATABASE` and `CREATE USER` commands from step 3 |
| 401 on all requests | Token expired or wrong `SECRET_KEY` | Re-authenticate via `POST /auth/token`; ensure `.env SECRET_KEY` has not changed since the token was issued |
| 401 on login (`POST /auth/token`) | PAM authentication failed | Verify user exists (`id qa-admin`); verify password (`su - qa-admin`); ensure `ecube` user is in the `shadow` group |
| 403 on all requests | Groups not mapped to roles | Check `LOCAL_GROUP_ROLE_MAP` in `.env`; ensure the OS user belongs to a mapped group (`id qa-admin`) |
| No USB drives detected | `ecube` user lacks permission | Add user to `disk` and `plugdev` groups: `sudo usermod -aG disk,plugdev ecube` then restart |
| `lsusb` shows device but ECUBE doesn't | sysfs path may differ | Check `USB_DISCOVERY_INTERVAL` > 0; check `/sys/bus/usb/devices` is readable by `ecube` user |
| TLS certificate errors in curl | Self-signed cert | Always use `curl -k` for self-signed certs |
| Port 8443 in use | Another process bound | `sudo ss -tlnp \| grep 8443` to find it; change port in systemd unit if needed |
| Copy job hangs at IN_PROGRESS | Source path unreachable | Verify mount is active: `mount \| grep /mnt/evidence`; check NFS server connectivity |
| Database connection pool exhausted | Too many concurrent requests | Increase `DB_POOL_SIZE` and `DB_POOL_MAX_OVERFLOW` in `.env` |

---

## 16. Version Compatibility

| Component | Tested Version | Notes |
|-----------|---------------|-------|
| Ubuntu | 22.04 LTS | Primary target; Debian 12 also supported |
| Python | 3.11+ | Required; 3.12 also works |
| PostgreSQL | 14+ | Ubuntu 22.04 ships with 14; versions 15 and 16 also work |
| Node.js | Not required | Backend is Python only |
| OpenSSL | 3.0+ | Required for TLS certificate generation |
| USB subsystem | Linux kernel 5.15+ | Required for sysfs-based USB discovery |

Always test against the ECUBE release tag matching your deployment. Check the release notes
for any version-specific migration steps or breaking changes:
`https://github.com/t3knoid/ecube/releases`

## References

- [docs/testing/04-ui-use-cases.md](04-ui-use-cases.md)
- [docs/requirements/04-functional-requirements.md](../requirements/04-functional-requirements.md)
