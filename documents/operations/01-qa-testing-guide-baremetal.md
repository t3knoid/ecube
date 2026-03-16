# ECUBE — QA Testing Guide (Bare-Metal Linux)

**Audience:** QA Personnel  
**Deployment:** Native Linux installation (no Docker/containers)

---

## Table of Contents

1. [Machine Setup](#1-machine-setup)
2. [Install System Packages](#2-install-system-packages)
3. [Install and Configure PostgreSQL](#3-install-and-configure-postgresql)
4. [Install ECUBE](#4-install-ecube)
5. [Create the Environment File](#5-create-the-environment-file)
6. [Generate TLS Certificates](#6-generate-tls-certificates)
7. [Run Database Migrations](#7-run-database-migrations)
8. [Start the Service](#8-start-the-service)
9. [Generate Test Tokens](#9-generate-test-tokens)
10. [API Test Scenarios](#10-api-test-scenarios)
11. [QA Test Cases](#11-qa-test-cases)
12. [Running the Automated Integration Tests](#12-running-the-automated-integration-tests)
13. [Service Management](#13-service-management)
14. [Troubleshooting](#14-troubleshooting)

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
tar -xzf "ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube/

# Set up Python virtual environment and install
sudo -u ecube python3.11 -m venv /opt/ecube/venv
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u ecube /opt/ecube/venv/bin/pip install -e /opt/ecube/
```

---

## 5. Configure the Environment (Optional)

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
EOF
```

> **Tip:** See `.env.example` for every available setting and its default value.

---

## 6. Generate TLS Certificates

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

## 7. Run Database Migrations

```bash
cd /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head
```

---

## 8. Start the Service

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
EnvironmentFile=/opt/ecube/.env

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

## 9. Generate Test Tokens

All endpoints except `/health` require a JWT bearer token. Generate tokens for each role you need to test.

### Admin Token

```bash
TOKEN=$(/opt/ecube/venv/bin/python3 -c "
import jwt, time
token = jwt.encode({
    'sub': 'qa-admin-001',
    'username': 'qa-admin',
    'groups': ['qa-admins'],
    'roles': ['admin'],
    'exp': int(time.time()) + 86400
}, 'change-me-in-production-please-rotate-32b', algorithm='HS256')
print(token)
")
echo "Admin token: $TOKEN"
```

### Tokens for Other Roles

Generate tokens by changing the `roles` value:

| Role | `roles` value | Create command |
|------|---------------|----------------|
| Manager | `["manager"]` | Same as above, replace `'roles': ['manager']` |
| Processor | `["processor"]` | Same as above, replace `'roles': ['processor']` |
| Auditor | `["auditor"]` | Same as above, replace `'roles': ['auditor']` |

**Convenience — generate all four tokens at once:**

```bash
for ROLE in admin manager processor auditor; do
  TOK=$(/opt/ecube/venv/bin/python3 -c "
import jwt, time
t = jwt.encode({
    'sub': 'qa-${ROLE}-001',
    'username': 'qa-${ROLE}',
    'groups': ['qa-${ROLE}s'],
    'roles': ['${ROLE}'],
    'exp': int(time.time()) + 86400
}, 'change-me-in-production-please-rotate-32b', algorithm='HS256')
print(t)
")
  echo "${ROLE^^}_TOKEN=${TOK}"
done
```

Save the admin token for the examples below:

```bash
export TOKEN="<paste admin token here>"
```

---

## 10. API Test Scenarios

> **Note:** Because the service runs with TLS, all `curl` commands use `-k` (skip certificate verification for self-signed certs) and port `8443`.

Open the interactive **Swagger UI** at: `https://localhost:8443/docs`

### 10.1 Health & Introspection

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

### 10.2 Mount Management

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

### 10.3 Drive Management

Plug a USB drive into the machine and wait ~30 seconds for automatic discovery.

```bash
# List drives — should include the plugged-in drive
curl -sk https://localhost:8443/drives \
  -H "Authorization: Bearer $TOKEN" | jq

# Initialize a drive for a project (replace {id})
curl -sk -X POST https://localhost:8443/drives/{id}/initialize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "PROJ-QA-001"}' | jq

# Prepare drive for safe physical removal
curl -sk -X POST https://localhost:8443/drives/{id}/prepare-eject \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 10.4 Job Management

```bash
# Create a copy job
curl -sk -X POST https://localhost:8443/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "PROJ-QA-001",
    "evidence_number": "EV-001",
    "source_path": "/mnt/evidence/case-001",
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

### 10.5 Audit Logs

```bash
# View recent audit logs
curl -sk https://localhost:8443/audit \
  -H "Authorization: Bearer $TOKEN" | jq

# Filter by action
curl -sk "https://localhost:8443/audit?action=DRIVE_INITIALIZED" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### 10.6 File Operations

```bash
# Get file hashes (replace {file_id})
curl -sk https://localhost:8443/files/{file_id}/hashes \
  -H "Authorization: Bearer $TOKEN" | jq

# Compare files
curl -sk -X POST https://localhost:8443/files/compare \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"file_ids": [1, 2]}' | jq
```

---

## 11. QA Test Cases

### 11.1 Authentication & Authorization

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | No token | `curl -sk https://localhost:8443/drives` | 401, `UNAUTHORIZED` |
| 2 | Garbage token | Add header `Authorization: Bearer not.a.real.token` | 401, `UNAUTHORIZED` |
| 3 | Expired token | Generate token with `'exp': int(time.time()) - 60` | 401, `UNAUTHORIZED` |
| 4 | Processor adds mount | `POST /mounts` with processor token | 403, `FORBIDDEN` |
| 5 | Processor initializes drive | `POST /drives/{id}/initialize` with processor token | 403, `FORBIDDEN` |
| 6 | Processor reads audit | `GET /audit` with processor token | 403, `FORBIDDEN` |
| 7 | Auditor reads audit | `GET /audit` with auditor token | 200 |
| 8 | Processor creates job | `POST /jobs` with processor token | 200 |
| 9 | All error responses have `trace_id` | Inspect any 4xx/5xx JSON body | `trace_id` field present |

### 11.2 Project Isolation

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an AVAILABLE drive with `PROJ-A` | 200, state → `IN_USE` |
| 2 | Re-initialize same drive with `PROJ-B` | 403, `FORBIDDEN` — isolation violation |
| 3 | Check audit log for `PROJECT_ISOLATION_VIOLATION` | Record present with `requested_project_id: PROJ-B` |

### 11.3 Drive State Machine

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an `AVAILABLE` drive | 200, state → `IN_USE` |
| 2 | Initialize an `EMPTY` drive | 409, `CONFLICT` |
| 3 | Prepare-eject an `IN_USE` drive | 200, state → `AVAILABLE` |
| 4 | Prepare-eject an `AVAILABLE` drive | 409, `CONFLICT` |

### 11.4 USB Hardware (Bare-Metal Specific)

These tests exercise real hardware paths and are the primary reason to use bare-metal.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Hot-plug detection | Plug in a USB drive, wait 30 seconds | `GET /drives` shows the new drive in `EMPTY` state |
| 2 | USB topology | `GET /introspection/usb/topology` | Shows real hub serial numbers, port numbers, connected devices |
| 3 | Physical eject | Initialize drive → prepare-eject → physically remove | Drive disappears from `/drives` list; audit shows `DRIVE_EJECT_PREPARED` |
| 4 | Re-plug same drive | Remove and re-insert the same drive | Drive reappears as `EMPTY` with same `device_identifier` |
| 5 | Multiple drives | Plug in 2+ drives simultaneously | All drives appear in `/drives`; each can be initialized to different projects |
| 6 | Sync + unmount | Initialize drive, create/start a job, then prepare-eject | Filesystem flushed and unmounted before eject (verify via `mount` command — no partitions from that drive should be listed) |

### 11.5 End-to-End Copy Workflow

Walk through the complete data export lifecycle:

1. **Set up a test file share.** Create a directory on the local machine or mount an NFS share with sample files:
   ```bash
   sudo mkdir -p /mnt/test-evidence
   # Copy some sample files
   sudo cp -r /usr/share/doc/bash /mnt/test-evidence/case-001
   ```

2. **Add the mount** via `POST /mounts`.

3. **Plug in a USB drive** and wait for auto-discovery.

4. **List drives** — `GET /drives` — and note the drive ID.

5. **Initialize the drive** — `POST /drives/{id}/initialize` with `project_id: "PROJ-E2E"`.

6. **Create a job** — `POST /jobs` with `source_path` pointing to the test files.

7. **Start the job** — `POST /jobs/{id}/start`.

8. **Poll status** — `GET /jobs/{id}` — until `status` becomes `COMPLETED`.

9. **Verify checksums** — `POST /jobs/{id}/verify` — confirm all files pass.

10. **Generate manifest** — `POST /jobs/{id}/manifest`.

11. **Prepare eject** — `POST /drives/{id}/prepare-eject` — drive returns to `AVAILABLE`.

12. **Physically remove the drive** and verify data on another computer.

13. **Check audit trail** — `GET /audit` — confirm the complete chain:
    `MOUNT_ADDED → DRIVE_INITIALIZED → JOB_CREATED → JOB_STARTED → JOB_COMPLETED → DRIVE_EJECT_PREPARED`

### 11.6 Error Handling

| # | Test | Expected |
|---|------|----------|
| 1 | `GET /jobs/99999` | 404, `NOT_FOUND` |
| 2 | `DELETE /mounts/99999` | 404, `NOT_FOUND` |
| 3 | Start an already-running job | 409, `CONFLICT` |
| 4 | All error responses | JSON body includes `code`, `message`, and `trace_id` |

---

## 12. Running the Automated Integration Tests

The project includes an automated integration test suite that runs against a real PostgreSQL database.

### Set up a test database

```bash
# Create a separate database for integration tests
sudo -u postgres psql -c "CREATE USER ecube_test WITH PASSWORD 'ecube_test';"
sudo -u postgres psql -c "CREATE DATABASE ecube_integration OWNER ecube_test;"
```

### Run the tests

```bash
cd /opt/ecube/src

export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5432/ecube_integration"

/opt/ecube/venv/bin/python -m pytest tests/integration/ -v --run-integration
```

### Run unit tests (no database required)

```bash
cd /opt/ecube/src
/opt/ecube/venv/bin/python -m pytest tests/ \
  --ignore=tests/integration \
  --ignore=tests/hardware \
  -v
```

---

## 13. Service Management

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

## 14. Troubleshooting

| Symptom | Possible Cause | Resolution |
|---------|---------------|------------|
| Service won't start | Missing `.env` or bad `DATABASE_URL` | Check `sudo journalctl -u ecube -n 50`; verify `/opt/ecube/.env`; test DB with `psql -U ecube -d ecube -h localhost -c "SELECT 1"` |
| Migration fails | Wrong DB credentials or DB doesn't exist | Re-run `CREATE DATABASE` and `CREATE USER` commands from step 3 |
| 401 on all requests | Token expired or wrong `SECRET_KEY` | Regenerate token; ensure `.env SECRET_KEY` matches the key used to sign the token |
| 403 on all requests | Groups not mapped to roles | Check `LOCAL_GROUP_ROLE_MAP` in `.env`; ensure token `groups` claim has a mapped group |
| No USB drives detected | `ecube` user lacks permission | Add user to `disk` and `plugdev` groups: `sudo usermod -aG disk,plugdev ecube` then restart |
| `lsusb` shows device but ECUBE doesn't | sysfs path may differ | Check `USB_DISCOVERY_INTERVAL` > 0; check `/sys/bus/usb/devices` is readable by `ecube` user |
| TLS certificate errors in curl | Self-signed cert | Always use `curl -k` for self-signed certs |
| Port 8443 in use | Another process bound | `sudo ss -tlnp \| grep 8443` to find it; change port in systemd unit if needed |
| Copy job hangs at IN_PROGRESS | Source path unreachable | Verify mount is active: `mount \| grep /mnt/evidence`; check NFS server connectivity |
| Database connection pool exhausted | Too many concurrent requests | Increase `DB_POOL_SIZE` and `DB_POOL_MAX_OVERFLOW` in `.env` |
