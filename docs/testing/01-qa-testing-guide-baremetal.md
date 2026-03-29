# ECUBE — QA Testing Guide (Bare-Metal Linux)

**Audience:** QA Personnel  
**Deployment:** Native Linux installation (no Docker/containers)

---

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
14. [Running the Automated Integration Tests](#14-running-the-automated-integration-tests)
15. [Service Management](#15-service-management)
16. [Troubleshooting](#16-troubleshooting)
17. [Version Compatibility](#17-version-compatibility)

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
NoNewPrivileges=true

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

All endpoints except `/health` and `/auth/token` require a JWT bearer token.
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

# System health (CPU, memory, DB status)
curl -sk https://localhost:8443/introspection/system-health \
  -H "Authorization: Bearer $TOKEN" | jq

# USB topology — should show real hubs/ports on bare metal
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
curl -sk -X POST https://localhost:8443/mounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "NFS",
    "remote_path": "10.0.0.5:/evidence",
    "local_mount_point": "/mnt/evidence"
  }' | jq

# List all mounts
curl -sk https://localhost:8443/mounts \
  -H "Authorization: Bearer $TOKEN" | jq

# Remove a mount (replace {id})
curl -sk -X DELETE https://localhost:8443/mounts/{id} \
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

# Format a drive (replace {id}) — required before initialization if unformatted
curl -sk -X POST https://localhost:8443/drives/{id}/format \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"filesystem_type": "ext4"}' | jq

# Initialize a drive for a project (replace {id})
curl -sk -X POST https://localhost:8443/drives/{id}/initialize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "PROJ-QA-001"}' | jq

# Prepare drive for safe physical removal
curl -sk -X POST https://localhost:8443/drives/{id}/prepare-eject \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 11.3a Port Management

USB ports default to disabled. Drives on disabled ports stay in `EMPTY` state
until the port is enabled and a discovery refresh runs.

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
# Create a copy job targeting the initialized USB drive (replace {drive_id})
curl -sk -X POST https://localhost:8443/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "PROJ-QA-001",
    "evidence_number": "EV-001",
    "source_path": "/mnt/evidence/case-001",
    "drive_id": "{drive_id}",
    "target_mount_path": "/mnt/usb/{drive_id}",
    "thread_count": 4
  }' | jq

# Start the job (replace {id})
curl -sk -X POST https://localhost:8443/jobs/{id}/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq

# Poll job status
curl -sk https://localhost:8443/jobs/{id} \
  -H "Authorization: Bearer $TOKEN" | jq

# Verify checksums after completion
curl -sk -X POST https://localhost:8443/jobs/{id}/verify \
  -H "Authorization: Bearer $TOKEN" | jq

# Generate manifest
curl -sk -X POST https://localhost:8443/jobs/{id}/manifest \
  -H "Authorization: Bearer $TOKEN" | jq
```

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

These endpoints manage OS-level user and group accounts. They require the `admin` role and are only available when `role_resolver = "local"` (returns `404` otherwise). Group names must start with the `ecube-` prefix. Creating a user requires at least one `ecube-*` group, and all other mutative user operations require the target user to be a member of at least one `ecube-*` group.

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

# List OS users (filtered to ecube-* group members)
curl -sk https://localhost:8443/admin/os-users \
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
| 5 | Processor initializes drive | `POST /drives/{id}/initialize` with processor token | 403, `FORBIDDEN` |
| 6 | Processor formats drive | `POST /drives/{id}/format` with processor token | 403, `FORBIDDEN` |
| 7 | Processor reads audit | `GET /audit` with processor token | 403, `FORBIDDEN` |
| 8 | Auditor reads audit | `GET /audit` with auditor token | 200 |
| 9 | Processor creates job | `POST /jobs` with processor token | 200 |
| 10 | All error responses have `trace_id` | Inspect any 4xx/5xx JSON body | `trace_id` field present |

### 12.3 Project Isolation

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an AVAILABLE drive with `PROJ-A` | 200, state → `IN_USE` |
| 2 | Re-initialize same drive with `PROJ-B` | 403, `FORBIDDEN` — isolation violation |
| 3 | Check audit log for `PROJECT_ISOLATION_VIOLATION` | Record present with `requested_project_id: PROJ-B` |

### 12.4 Drive State Machine

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an `AVAILABLE` drive with recognized filesystem | 200, state → `IN_USE` |
| 2 | Initialize a drive with `filesystem_type=NULL` | 409, `CONFLICT` — must have recognized filesystem |
| 3 | Initialize a drive with `filesystem_type=unformatted` | 409, `CONFLICT` — must have recognized filesystem |
| 4 | Initialize a drive with `filesystem_type=unknown` | 409, `CONFLICT` — must have recognized filesystem |
| 5 | Prepare-eject an `IN_USE` drive | 200, state → `AVAILABLE` |
| 6 | Prepare-eject an `AVAILABLE` drive | 409, `CONFLICT` |
| 7 | Format-then-initialize workflow: discover unformatted → format ext4 → initialize | Each step succeeds; final state `IN_USE` |
| 8 | Attempt to format an `IN_USE` drive | 409, `CONFLICT` — must be `AVAILABLE` |

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
| 5 | Enable a port | `PATCH /admin/ports/{id}` with `{"enabled": true}` | 200, port returned with `enabled: true` |
| 6 | Disable a port | `PATCH /admin/ports/{id}` with `{"enabled": false}` | 200, port returned with `enabled: false` |
| 7 | Enable port — manager | `PATCH /admin/ports/{id}` with manager token | 200 |
| 8 | Enable port — processor denied | `PATCH /admin/ports/{id}` with processor token | 403, `FORBIDDEN` |
| 9 | Enable non-existent port | `PATCH /admin/ports/99999` with `{"enabled": true}` | 404, `NOT_FOUND` |
| 10 | Ports default to disabled | Discover a new port, then `GET /admin/ports` | New port has `enabled: false` |
| 11 | Drive on disabled port stays EMPTY | Plug in drive on disabled port, run `POST /drives/refresh` | `GET /drives` shows drive in `EMPTY` state |
| 12 | Drive on enabled port becomes AVAILABLE | Enable port, run `POST /drives/refresh` | `GET /drives` shows drive in `AVAILABLE` state |
| 13 | Disable port — IN_USE drive unaffected | Disable a port with an `IN_USE` drive, run `POST /drives/refresh` | Drive remains `IN_USE` (project isolation priority) |
| 14 | Disable port — AVAILABLE drive demoted | Enable port, confirm drive is `AVAILABLE`, disable port, run `POST /drives/refresh` | Drive transitions to `EMPTY` |
| 15 | Orphan drive stays EMPTY | Discover a drive with no matching port (`port_id = NULL`), run `POST /drives/refresh` | Drive remains in `EMPTY` state (unknown port treated as disabled) |
| 16 | PORT_ENABLED audit log | `GET /audit?action=PORT_ENABLED` after enabling a port | Audit entry with `port_id`, `system_path`, `hub_id`, `enabled`, `path` |
| 17 | PORT_DISABLED audit log | `GET /audit?action=PORT_DISABLED` after disabling a port | Audit entry with `port_id`, `system_path`, `hub_id`, `enabled`, `path` |

### 12.4.4 Hub & Port Identification Enrichment

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | List hubs — admin | `GET /admin/hubs` with admin token | 200, array of hub objects with `vendor_id`, `product_id`, `location_hint` |
| 2 | List hubs — manager | `GET /admin/hubs` with manager token | 200 |
| 3 | List hubs — processor denied | `GET /admin/hubs` with processor token | 403, `FORBIDDEN` |
| 4 | List hubs — unauthenticated | `GET /admin/hubs` without token | 401, `UNAUTHORIZED` |
| 5 | Set hub location hint | `PATCH /admin/hubs/{id}` with `{"location_hint": "back-left rack"}` | 200, hub returned with `location_hint: "back-left rack"` |
| 6 | Set hub location hint — manager | `PATCH /admin/hubs/{id}` with manager token | 200 |
| 7 | Set hub location hint — processor denied | `PATCH /admin/hubs/{id}` with processor token | 403, `FORBIDDEN` |
| 8 | Set hub location hint — not found | `PATCH /admin/hubs/99999` | 404, `NOT_FOUND` |
| 9 | HUB_LABEL_UPDATED audit log | `GET /audit?action=HUB_LABEL_UPDATED` after setting a hub label | Audit entry with `hub_id`, `system_identifier`, `field`, `old_value`, `new_value`, `path` |
| 10 | Set port friendly label | `PATCH /admin/ports/{id}/label` with `{"friendly_label": "Bay 3"}` | 200, port returned with `friendly_label: "Bay 3"` |
| 11 | Set port friendly label — manager | `PATCH /admin/ports/{id}/label` with manager token | 200 |
| 12 | Set port friendly label — processor denied | `PATCH /admin/ports/{id}/label` with processor token | 403, `FORBIDDEN` |
| 13 | Set port friendly label — not found | `PATCH /admin/ports/{id}/label` for non-existent port | 404, `NOT_FOUND` |
| 14 | PORT_LABEL_UPDATED audit log | `GET /audit?action=PORT_LABEL_UPDATED` after setting a port label | Audit entry with `port_id`, `system_path`, `field`, `old_value`, `new_value`, `path` |
| 15 | Port listing includes enriched fields | `GET /admin/ports` after discovery | Port objects include `vendor_id`, `product_id`, `speed` fields |
| 16 | Labels survive discovery resync | Set hub `location_hint` and port `friendly_label`, then `POST /drives/refresh` | Labels remain unchanged after resync |
| 17 | Discovery populates vendor/product IDs | Run `POST /drives/refresh` with USB hardware connected | Hub and port records show `vendor_id` and `product_id` from sysfs |

### 12.5 USB Hardware (Bare-Metal Specific)

These tests exercise real hardware paths and are the primary reason to use bare-metal.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Hot-plug detection | Plug in a USB drive, wait 30 seconds | `GET /drives` shows the new drive (in `EMPTY` state if port is disabled, or `AVAILABLE` if port is enabled) |
| 2 | USB topology | `GET /introspection/usb/topology` | Shows real hub serial numbers, port numbers, connected devices |
| 3 | Physical eject | Initialize drive → prepare-eject → physically remove | After the next discovery cycle, `GET /drives` still lists the drive with `current_state=EMPTY`; audit shows `DRIVE_EJECT_PREPARED` |
| 4 | Re-plug same drive | Remove and re-insert the same drive | Drive reappears as `AVAILABLE` with same `device_identifier` (after discovery cycle) |
| 5 | Multiple drives | Plug in 2+ drives simultaneously | All drives appear in `/drives`; each can be initialized to different projects |
| 6 | Sync + unmount | Initialize drive, create/start a job, then prepare-eject | Filesystem flushed and unmounted before eject (verify via `mount` command — no partitions from that drive should be listed) |
| 7 | Disabled port blocks AVAILABLE | Disable a port, plug in a drive to that port, run discovery | Drive appears in `EMPTY` state; enable port + refresh → drive transitions to `AVAILABLE` |

### 12.6 End-to-End Copy Workflow

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

2. **Add the mount** via `POST /mounts`.

3. **Plug in a USB drive** and wait for auto-discovery.

3b. **Enable the port** — `GET /admin/ports` to find the port ID, then
    `PATCH /admin/ports/{port_id}` with `{"enabled": true}`.
    Run `POST /drives/refresh` so the drive transitions to `AVAILABLE`.

4. **List drives** — `GET /drives` — and note the drive ID and `filesystem_type`.

4b. **Format the drive (if needed)** — If `filesystem_type` is `unformatted`, `unknown`, or `null`:
    `POST /drives/{id}/format` with `{"filesystem_type": "ext4"}`.
    Confirm `filesystem_type` → `ext4` in the response.

5. **Initialize the drive** — `POST /drives/{id}/initialize` with `project_id: "PROJ-E2E"`.

6. **Create a job** — `POST /jobs` with `source_path` pointing to the test files.

7. **Start the job** — `POST /jobs/{id}/start`.

8. **Poll status** — `GET /jobs/{id}` — until `status` becomes `COMPLETED`.

9. **Verify checksums** — `POST /jobs/{id}/verify` — confirm all files pass.

10. **Generate manifest** — `POST /jobs/{id}/manifest`.

11. **Prepare eject** — `POST /drives/{id}/prepare-eject` — drive returns to `AVAILABLE`.

12. **Physically remove the drive** and verify data on another computer.
    Compare file checksums against the values recorded in step 1:
    ```bash
    # On the verification computer
    sha256sum /media/usb/case-001/* | diff - case-001.sha256
    ```

13. **Check audit trail** — `GET /audit` — confirm the complete chain:
    `MOUNT_ADDED → PORT_ENABLED → DRIVE_FORMATTED → DRIVE_INITIALIZED → JOB_CREATED → JOB_STARTED → JOB_COMPLETED → DRIVE_EJECT_PREPARED`

### 12.7 Error Handling

| # | Test | Expected |
|---|------|----------|
| 1 | `GET /jobs/99999` | 404, `NOT_FOUND` |
| 2 | `DELETE /mounts/99999` | 404, `NOT_FOUND` |
| 3 | Start an already-running job | 409, `CONFLICT` |
| 4 | All error responses | JSON body includes `code`, `message`, and `trace_id` |
| 5 | `POST /drives/999/format` with `{"filesystem_type": "ext4"}` | 404, `NOT_FOUND` |
| 6 | `POST /drives/{id}/format` with `{"filesystem_type": "ntfs"}` | 422, validation error |
| 7 | `POST /drives/{id}/format` with empty body | 422 |

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
| 6 | Create user | `POST /admin/os-users` with username, password, roles | 201, returns username, uid, gid, home, shell, groups |
| 7 | Create user — duplicate | `POST /admin/os-users` with existing username | 409, Conflict |
| 8 | Create user — reserved name | `POST /admin/os-users` with `{"username": "root", ...}` | 422, reserved username |
| 9 | Create user — empty password | `POST /admin/os-users` with `{"password": "", ...}` | 422 |
| 10 | Create user — password with newline | `POST /admin/os-users` with password containing `\n` | 422, unsafe characters |
| 11 | Create user — password with colon | `POST /admin/os-users` with password containing `:` | 422, unsafe characters |
| 12 | Create user — invalid group | `POST /admin/os-users` with non-existent group in groups list | 422, group does not exist |
| 13 | Create user — no roles | `POST /admin/os-users` with empty/omitted roles | 422, at least one role required |
| 14 | List users | `GET /admin/os-users` | 200, only users in `ecube-*` groups listed |
| 15 | Reset password | `PUT /admin/os-users/{username}/password` with `{"password": "NewPass!"}` | 200 |
| 16 | Reset password — non-ECUBE user | `PUT /admin/os-users/postgres/password` | 422, user is not ECUBE-managed |
| 17 | Replace groups | `PUT /admin/os-users/{username}/groups` with `{"groups": ["ecube-admins"]}` | 200, updated group list; non-`ecube-*` groups preserved |
| 18 | Replace groups — empty list | `PUT /admin/os-users/{username}/groups` with `{"groups": []}` | 422, at least one `ecube-*` group required |
| 19 | Replace groups — non-ecube name | `PUT /admin/os-users/{username}/groups` with `{"groups": ["docker"]}` | 422, group does not start with `ecube-` |
| 20 | Append groups | `POST /admin/os-users/{username}/groups` with `{"groups": ["ecube-managers"]}` | 200, updated group list |
| 21 | Modify groups — non-ECUBE user | `PUT /admin/os-users/www-data/groups` | 422, user is not ECUBE-managed |
| 22 | Delete user | `DELETE /admin/os-users/{username}` | 200, user and DB roles removed |
| 23 | Delete user — non-ECUBE user | `DELETE /admin/os-users/daemon` | 422, user is not ECUBE-managed |
| 24 | Delete user — not found | `DELETE /admin/os-users/nonexistent` | 404 |
| 25 | Processor cannot access OS endpoints | `GET /admin/os-users` with processor token | 403, FORBIDDEN |
| 26 | Non-local mode returns 404 | All `/admin/os-*` endpoints when `role_resolver != "local"` | 404, Not Found |
| 27 | OS_USER_CREATED audit log | `GET /audit?action=OS_USER_CREATED` after creating user | Audit entry with actor and username |
| 28 | OS_USER_DELETED audit log | `GET /audit?action=OS_USER_DELETED` after deleting user | Audit entry with actor and username |
| 29 | OS_PASSWORD_RESET audit log | `GET /audit?action=OS_PASSWORD_RESET` after resetting password | Audit entry (no password in details) |
| 30 | OS_GROUP_CREATED audit log | `GET /audit?action=OS_GROUP_CREATED` after creating group | Audit entry with group name |
| 31 | OS_GROUP_DELETED audit log | `GET /audit?action=OS_GROUP_DELETED` after deleting group | Audit entry with group name |

### 12.10 First-Run Setup

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

### 12.11 Database Provisioning API

Database provisioning endpoints use a dual-auth model with fail-closed semantics: unauthenticated during initial setup, admin-only after, and 503 when the database server is unreachable without a valid admin JWT.  The following conditions are treated as "not provisioned" (allowing initial provisioning to proceed without `force`):

- The target database does not exist yet (PostgreSQL SQLSTATE `3D000`).
- The application role does not exist yet (PostgreSQL SQLSTATE `28000`).
- The database is reachable but the schema has not been migrated (e.g. `user_roles` table missing).

Only a truly unreachable server (connection refused, timeout, network failure) triggers the fail-closed 503.  Transient query errors (e.g. permission denied on the `user_roles` table) on a reachable database also fail closed — they are **not** treated as initial setup.

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Test connection — success | `POST /setup/database/test-connection` with valid PostgreSQL credentials | 200, `{"status": "ok", "server_version": "..."}` |
| 2 | Test connection — bad host | `POST /setup/database/test-connection` with unreachable host | 400, connection error |
| 3 | Test connection — SSRF host | `POST /setup/database/test-connection` with `"host": "http://evil.com"` | 422, invalid host |
| 4 | Test connection — port out of range | `POST /setup/database/test-connection` with `"port": 99999` | 422 |
| 5 | Provision — success | `POST /setup/database/provision` with valid credentials | 200, returns database, user, migrations_applied |
| 6 | Provision — bad admin credentials | `POST /setup/database/provision` with wrong admin password | 400, connection error |
| 7 | Provision — invalid database name | `POST /setup/database/provision` with `"app_database": "drop;--"` | 422, invalid identifier |
| 8 | Status — connected | `GET /setup/database/status` with admin token | 200, `connected: true`, migration info |
| 9 | Status — requires auth | `GET /setup/database/status` without token | 401 |
| 10 | Status — requires admin | `GET /setup/database/status` with processor token | 403 |
| 11 | Settings update — success | `PUT /setup/database/settings` with valid partial update | 200, `{"status": "updated", ...}` |
| 12 | Settings update — bad connection | `PUT /setup/database/settings` with unreachable host | 400, connection test failed |
| 13 | Settings update — empty body | `PUT /setup/database/settings` with `{}` | 422, at least one field required |
| 14 | Settings update — requires admin | `PUT /setup/database/settings` with processor token | 403 |
| 15 | Auth after setup — test-connection | `POST /setup/database/test-connection` without token (after admin exists) | 401 |
| 16 | Auth after setup — provision | `POST /setup/database/provision` without token (after admin exists) | 401 |
| 17 | Password redaction | `POST /setup/database/provision` and check response | No password in response body |
| 18 | Re-provision blocked | `POST /setup/database/provision` after successful provisioning (no `force`) | 409, already provisioned |
| 19 | Force re-provision (admin) | `POST /setup/database/provision` with `"force": true` and admin token after successful provisioning | 200, returns database, user, migrations_applied |
| 20 | Force rejected unauthenticated | `POST /setup/database/provision` with `"force": true` during initial setup (no admin exists) | 403, force requires admin |
| 21 | Fail-closed — DB unreachable, no JWT | Stop PostgreSQL, `POST /setup/database/test-connection` without token | 503, database unavailable message |
| 22 | Fail-closed — DB unreachable, admin JWT | Stop PostgreSQL, `POST /setup/database/test-connection` with valid admin token | Request proceeds (not blocked by 503) |
| 23 | Fail-closed — provision state unknown | Stop PostgreSQL, `POST /setup/database/provision` without `"force": true` | 503, cannot determine provisioning state |
| 24 | Force bypasses state check | Stop PostgreSQL, `POST /setup/database/provision` with `"force": true` and admin token | Proceeds to provisioning (no 503 from state check) |
| 25 | Unmigrated DB treated as initial setup | Drop `user_roles` table (or use a fresh empty database), `POST /setup/database/test-connection` without token | 200, request allowed (not 503) |
| 26 | Fresh install — DB/role missing | With PostgreSQL running but the application database or role not yet created, `POST /setup/database/provision` without `force` | 200, provisioning proceeds (not 503) |
| 27 | Fail-closed — OperationalError on reachable DB | Revoke SELECT on `user_roles` (or simulate permission denied), `POST /setup/database/test-connection` without token | 503, does NOT grant unauthenticated access |
| 28 | Fail-closed — unexpected error | Trigger an unexpected exception from admin-check (e.g. coding bug), `POST /setup/database/test-connection` without token | 503, does NOT grant unauthenticated access |
| 29 | Provision — migration failure | `POST /setup/database/provision` with valid credentials but a broken Alembic migration (e.g. conflicting schema) | 500, "migration failed" message; `.env` not updated, engine not swapped |
| 30 | Provision — .env write failure | `POST /setup/database/provision` after making `.env` read-only (or disk full) | 500, "failed to persist" message; engine not swapped |
| 31 | Provision — engine reinit failure | `POST /setup/database/provision` while another reinit is in progress (lock contention) | 500, "engine could not be switched" message; `.env` already written |

### 12.11 Startup State Reconciliation

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

## 14. Running the Automated Integration Tests

The project includes an automated integration test suite that runs against a real PostgreSQL database.

### Set up a test database

```bash
# Create a separate database for integration tests
sudo -u postgres psql -c "CREATE USER ecube_test WITH PASSWORD 'ecube_test';"
sudo -u postgres psql -c "CREATE DATABASE ecube_integration OWNER ecube_test;"
```

### Run the tests

```bash
cd /opt/ecube

export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5432/ecube_integration"

/opt/ecube/venv/bin/python -m pytest tests/integration/ -v --run-integration
```

### Run unit tests (in-memory SQLite; no external DB server)

Unit tests use a pytest fixture–managed in-memory SQLite database (no PostgreSQL instance needed), so DB-related failures can still occur.

```bash
cd /opt/ecube
/opt/ecube/venv/bin/python -m pytest tests/ \
  --ignore=tests/integration \
  --ignore=tests/hardware \
  -v
```

---

## 15. Service Management

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

## 16. Troubleshooting

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

## 17. Version Compatibility

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
