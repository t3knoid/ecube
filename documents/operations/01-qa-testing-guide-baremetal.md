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
8. [Run Database Migrations](#8-run-database-migrations)
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

## 8. Run Database Migrations

```bash
cd /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head
```

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

# Initialize a drive for a project (replace {id})
curl -sk -X POST https://localhost:8443/drives/{id}/initialize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": "PROJ-QA-001"}' | jq

# Prepare drive for safe physical removal
curl -sk -X POST https://localhost:8443/drives/{id}/prepare-eject \
  -H "Authorization: Bearer $TOKEN" | jq
```

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

---

## 12. QA Test Cases

### 12.1 Login Endpoint (`POST /auth/token`)

| # | Test | How | Expected |
|---|------|-----|----------|
| 1 | Valid login | `POST /auth/token` with valid OS username/password | 200, response contains `access_token` and `token_type: "bearer"` |
| 2 | Invalid password | `POST /auth/token` with wrong password | 401, `Invalid credentials` |
| 3 | Unknown user | `POST /auth/token` with non-existent username | 401, `Invalid credentials` |
| 4 | Missing username | `POST /auth/token` with `{"password": "x"}` | 422 |
| 5 | Missing password | `POST /auth/token` with `{"username": "x"}` | 422 |
| 6 | Empty username | `POST /auth/token` with `{"username": "", "password": "x"}` | 422 |
| 7 | Token contains correct roles | Decode JWT from login response | `roles` matches group mapping in `LOCAL_GROUP_ROLE_MAP` |
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
| 6 | Processor reads audit | `GET /audit` with processor token | 403, `FORBIDDEN` |
| 7 | Auditor reads audit | `GET /audit` with auditor token | 200 |
| 8 | Processor creates job | `POST /jobs` with processor token | 200 |
| 9 | All error responses have `trace_id` | Inspect any 4xx/5xx JSON body | `trace_id` field present |

### 12.3 Project Isolation

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an AVAILABLE drive with `PROJ-A` | 200, state → `IN_USE` |
| 2 | Re-initialize same drive with `PROJ-B` | 403, `FORBIDDEN` — isolation violation |
| 3 | Check audit log for `PROJECT_ISOLATION_VIOLATION` | Record present with `requested_project_id: PROJ-B` |

### 12.4 Drive State Machine

| # | Test | Expected |
|---|------|----------|
| 1 | Initialize an `AVAILABLE` drive | 200, state → `IN_USE` |
| 2 | Initialize an `EMPTY` drive | 200, state → `IN_USE` |
| 3 | Prepare-eject an `IN_USE` drive | 200, state → `AVAILABLE` |
| 4 | Prepare-eject an `AVAILABLE` drive | 409, `CONFLICT` |

### 12.5 USB Hardware (Bare-Metal Specific)

These tests exercise real hardware paths and are the primary reason to use bare-metal.

| # | Test | Steps | Expected |
|---|------|-------|----------|
| 1 | Hot-plug detection | Plug in a USB drive, wait 30 seconds | `GET /drives` shows the new drive in `AVAILABLE` state (discovery auto-transitions `EMPTY → AVAILABLE`) |
| 2 | USB topology | `GET /introspection/usb/topology` | Shows real hub serial numbers, port numbers, connected devices |
| 3 | Physical eject | Initialize drive → prepare-eject → physically remove | After the next discovery cycle, `GET /drives` still lists the drive with `current_state=EMPTY`; audit shows `DRIVE_EJECT_PREPARED` |
| 4 | Re-plug same drive | Remove and re-insert the same drive | Drive reappears as `AVAILABLE` with same `device_identifier` (after discovery cycle) |
| 5 | Multiple drives | Plug in 2+ drives simultaneously | All drives appear in `/drives`; each can be initialized to different projects |
| 6 | Sync + unmount | Initialize drive, create/start a job, then prepare-eject | Filesystem flushed and unmounted before eject (verify via `mount` command — no partitions from that drive should be listed) |

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

4. **List drives** — `GET /drives` — and note the drive ID.

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
    `MOUNT_ADDED → DRIVE_INITIALIZED → JOB_CREATED → JOB_STARTED → JOB_COMPLETED → DRIVE_EJECT_PREPARED`

### 12.7 Error Handling

| # | Test | Expected |
|---|------|----------|
| 1 | `GET /jobs/99999` | 404, `NOT_FOUND` |
| 2 | `DELETE /mounts/99999` | 404, `NOT_FOUND` |
| 3 | Start an already-running job | 409, `CONFLICT` |
| 4 | All error responses | JSON body includes `code`, `message`, and `trace_id` |

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
