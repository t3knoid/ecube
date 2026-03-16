# ECUBE Operational Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, Operators, IT Staff  
**Document Type:** Operational Procedures

---

## Table of Contents

1. [Introduction](#introduction)
2. [System Overview](#system-overview)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Starting and Stopping the Service](#starting-and-stopping-the-service)
7. [User Management](#user-management)
8. [Common Operational Tasks](#common-operational-tasks)
9. [Monitoring and Logs](#monitoring-and-logs)
10. [Troubleshooting](#troubleshooting)
11. [Backup and Recovery](#backup-and-recovery)
12. [Maintenance](#maintenance)
13. [Security Best Practices](#security-best-practices)
14. [API Quick Reference](#api-quick-reference)
15. [Support and Resources](#support-and-resources)

---

## Introduction

ECUBE (Evidence Copying & USB Based Export) is a secure, audited platform for exporting eDiscovery data to encrypted USB drives. This operational guide provides step-by-step instructions for deploying, configuring, operating, and maintaining ECUBE in a production environment.

**Key Characteristics:**

- Secure, single-purpose evidence export appliance
- Centralized audit logging of all operations
- Hardware-aware USB drive and mount management
- Role-based access control (admin, manager, processor, auditor)
- REST API for integration with external systems

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
2. UI authenticates against ECUBE API (JWT bearer token)
3. API validates token and extracts user groups
4. Groups mapped to ECUBE roles (admin, manager, processor, auditor)
5. Role checked against operation (e.g., "processor" can start jobs, "auditor" can only read)
6. Operation executed (e.g., mount network share, initialize drive, start copy)
7. All actions logged to audit table with timestamp, user, action, result

---

## Prerequisites

### Hardware Requirements

**Recommended Minimum:**

- CPU: Quad-core 2.0 GHz x86-64
- RAM: 8 GB
- Storage: 256 GB SSD (for system, database, logs)
- USB: USB 3.1 hub with ≥4 ports
- Network: 1Gbps Ethernet

**Connectivity:**

- HTTPS network access to identity provider (LDAP, OIDC provider, or local authentication)
- NFS/SMB mount access to evidence source shares
- PostgreSQL database over network or localhost

### Software Requirements

**Operating System:**

- Ubuntu 20.04 LTS, 22.04 LTS, or later (recommended)
- CentOS/RHEL 8+ (supported, similar steps)
- Linux kernel 5.10+ (for USB device handling)

**System Packages:**

```bash
sudo apt update
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
  git
```

**Deployment Options:**

- **Option A:** Package deployment (systemd service)
- **Option B:** Docker Compose (recommended for quick testing)

---

## Installation

### Option A: Package Deployment (Systemd Service)

#### 1. Create Service Account

```bash
sudo useradd --system --create-home --shell /bin/bash ecube
sudo mkdir -p /opt/ecube
sudo chown -R ecube:ecube /opt/ecube
```

#### 2. Download and Extract Release Package

```bash
cd /tmp
export GITHUB_OWNER="t3knoid"
export GITHUB_REPO="ecube"

# Fetch latest release tag
LATEST_TAG=$(curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")

echo "Installing ECUBE ${LATEST_TAG}"

# Download package and checksum
curl -fsSL -O \
  "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${LATEST_TAG}/ecube-package-${LATEST_TAG}.tar.gz"

curl -fsSL -O \
  "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${LATEST_TAG}/ecube-package-${LATEST_TAG}.sha256"

# Verify checksum
sha256sum -c "ecube-package-${LATEST_TAG}.sha256"

# Extract
tar -xzf "ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube/
```

#### 3. Set Up Python Virtual Environment

```bash
sudo -u ecube python3.11 -m venv /opt/ecube/venv
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade pip setuptools wheel

# Install ECUBE and dependencies
sudo -u ecube /opt/ecube/venv/bin/pip install -e /opt/ecube/
```

#### 4. Create Systemd Service File

```bash
sudo tee /etc/systemd/system/ecube.service > /dev/null << 'EOF'
[Unit]
Description=ECUBE Evidence Export Service
Documentation=https://github.com/t3knoid/ecube
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=ecube
Group=ecube
WorkingDirectory=/opt/ecube

# Environment configuration
EnvironmentFile=/opt/ecube/.env

# Start command
ExecStart=/opt/ecube/venv/bin/uvicorn \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile=/opt/ecube/certs/key.pem \
  --ssl-certfile=/opt/ecube/certs/cert.pem \
  app.main:app

# Restart policy
Restart=on-failure
RestartSec=10

# Process isolation
PrivateTmp=yes
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
```

#### 5. Initialize Database

```bash
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head
```

#### 6. Enable and Start Service

```bash
sudo systemctl enable ecube
sudo systemctl start ecube
sudo systemctl status ecube
```

### Option B: Docker Compose Deployment

See [12-linux-host-deployment-and-usb-passthrough.md](../design/12-linux-host-deployment-and-usb-passthrough.md) for Docker-specific setup.

**Quick Start:**

```bash
git clone https://github.com/t3knoid/ecube.git
cd ecube

# Create .env file (see Configuration section)
cp .env.example .env
nano .env

# Start services
docker compose up -d

# Initialize database
docker compose exec app alembic upgrade head

# View logs
docker compose logs -f app
```

---

## Configuration

### Environment Variables

ECUBE reads configuration from environment variables or a `.env` file. Key variables:

#### Database

```bash
# PostgreSQL connection
DATABASE_URL=postgresql://ecube:PASSWORD@localhost:5432/ecube
```

#### Security & Authentication

```bash
# JWT signing key (generate: `openssl rand -hex 32`)
SECRET_KEY=your-32-byte-hex-string-here

# Signing algorithm
ALGORITHM=HS256

# Token lifetime in minutes (default: 60)
TOKEN_EXPIRE_MINUTES=60

# Role resolver provider: "local" (default), "ldap", or "oidc"
ROLE_RESOLVER=local

# Local group-to-role mapping (JSON)
LOCAL_GROUP_ROLE_MAP='{"evidence-admins": ["admin"], "evidence-team": ["processor", "auditor"]}'

# LDAP provider (if ROLE_RESOLVER=ldap)
LDAP_SERVER=ldap://example.com
LDAP_BIND_DN=cn=admin,dc=example,dc=com
LDAP_BIND_PASSWORD=password
LDAP_BASE_DN=dc=example,dc=com
LDAP_GROUP_ROLE_MAP='{"CN=EvidenceAdmins,OU=Groups,DC=example,DC=com": ["admin"]}'

# OIDC provider (if ROLE_RESOLVER=oidc)
OIDC_DISCOVERY_URL=https://auth.example.com/.well-known/openid-configuration
OIDC_CLIENT_ID=your-client-id
OIDC_CLIENT_SECRET=your-client-secret
OIDC_GROUP_CLAIM_NAME=groups
OIDC_GROUP_ROLE_MAP='{"admin-group": ["admin"]}'
```

#### HTTPS/TLS

```bash
# Certificate and key files (required for HTTPS)
TLS_CERTFILE=/opt/ecube/certs/cert.pem
TLS_KEYFILE=/opt/ecube/certs/key.pem
```

#### Optional Features

```bash
# Audit log retention (days; 0 = keep all)
AUDIT_LOG_RETENTION_DAYS=365

# Job timeout (seconds)
COPY_JOB_TIMEOUT=3600

# USB device auto-discovery interval (seconds)
USB_DISCOVERY_INTERVAL=30
```

#### Copy Engine Tuning

```bash
# Chunk size in bytes for file copy and checksum computation (default: 1 MB)
COPY_CHUNK_SIZE_BYTES=1048576

# Default thread pool size when job thread_count is not set
COPY_DEFAULT_THREAD_COUNT=4

# Default max retries per file when job max_file_retries is not set
COPY_DEFAULT_MAX_RETRIES=3

# Default retry delay in seconds when job retry_delay_seconds is not set
COPY_DEFAULT_RETRY_DELAY_SECONDS=1.0
```

#### Subprocess & System Paths

```bash
# Timeout in seconds for subprocess calls (mount, umount, sync)
SUBPROCESS_TIMEOUT_SECONDS=30

# Paths to system binaries (Linux defaults; override for non-standard installs)
SYNC_BINARY_PATH=/bin/sync
UMOUNT_BINARY_PATH=/bin/umount

# Filesystem paths (Linux defaults; override for portability/testing)
PROCFS_MOUNTS_PATH=/proc/mounts
SYSFS_USB_DEVICES_PATH=/sys/bus/usb/devices
SYSFS_BLOCK_PATH=/sys/block
```

#### Audit Log Pagination

```bash
# Default page size for audit log queries
AUDIT_LOG_DEFAULT_LIMIT=100

# Maximum allowed page size for audit log queries
AUDIT_LOG_MAX_LIMIT=1000
```

#### Database Connection Pool

```bash
# Number of persistent connections in the connection pool
DB_POOL_SIZE=5

# Maximum overflow connections above pool_size
DB_POOL_MAX_OVERFLOW=10

# Seconds after which a connection is recycled (-1 disables)
DB_POOL_RECYCLE_SECONDS=-1
```

#### OIDC Advanced

```bash
# Timeout in seconds for OIDC discovery document fetch
OIDC_DISCOVERY_TIMEOUT_SECONDS=10

# Allowed JWT signing algorithms (JSON list)
OIDC_ALLOWED_ALGORITHMS='["RS256","RS384","RS512","ES256","ES384","ES512"]'
```

#### OpenAPI Metadata

```bash
# Contact information shown in the OpenAPI spec
API_CONTACT_NAME="ECUBE Support"
API_CONTACT_EMAIL="support@ecube.local"
```

### Example `.env` File

```bash
# Database
DATABASE_URL=postgresql://ecube:ecube123@localhost:5432/ecube

# Security (generate with: openssl rand -hex 32)
SECRET_KEY=abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789
ALGORITHM=HS256
TOKEN_EXPIRE_MINUTES=60

# Local identity (default: no setup needed)
ROLE_RESOLVER=local
LOCAL_GROUP_ROLE_MAP='{"local-admins": ["admin"], "local-operators": ["processor"]}'

# TLS certificates
TLS_CERTFILE=/opt/ecube/certs/cert.pem
TLS_KEYFILE=/opt/ecube/certs/key.pem

# Logging
LOG_LEVEL=INFO
```

### Generating HTTPS Certificates

For development/testing, generate self-signed certificates:

```bash
sudo mkdir -p /opt/ecube/certs
sudo chown -R ecube:ecube /opt/ecube/certs

# Generate private key (2048-bit RSA)
sudo -u ecube openssl genrsa -out /opt/ecube/certs/key.pem 2048

# Generate self-signed certificate (valid 365 days)
sudo -u ecube openssl req -new -x509 -key /opt/ecube/certs/key.pem \
  -out /opt/ecube/certs/cert.pem -days 365 \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=ecube.example.com"

# Fix permissions
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
```

**Production:** Use certificates from your organization's CA or Let's Encrypt.

---

## Starting and Stopping the Service

### Start Service

```bash
# Option A: Systemd (if deployed as service)
sudo systemctl start ecube

# Option B: Docker Compose
docker compose up -d
```

### Check Service Status

```bash
# Option A: Systemd
sudo systemctl status ecube
sudo journalctl -u ecube -n 50 -f  # Stream logs

# Option B: Docker Compose
docker compose ps
docker compose logs -f app
```

### Stop Service

```bash
# Option A: Systemd
sudo systemctl stop ecube

# Option B: Docker Compose
docker compose down
```

### Restart Service

```bash
# Option A: Systemd
sudo systemctl restart ecube

# Option B: Docker Compose
docker compose restart app
```

### Verify API Endpoint

```bash
# Check HTTPS endpoint (self-signed cert will fail verification; use -k to skip)
curl -k https://localhost:8443/introspection/version

# Expected response (JSON):
# {"version": "0.1.0", "api_version": "1.0.0"}
```

---

## User Management

### Authentication Methods

#### Local Identity (Default — PAM Authentication)

ECUBE authenticates users via PAM on the host OS. Users log in by calling
`POST /auth/token` with their OS username and password. The system validates
credentials through PAM, reads the user's OS group memberships, maps groups to
ECUBE roles, and returns a signed JWT.

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

**Setup:**

1. Create OS users and groups on the ECUBE host:

```bash
# Create ECUBE role groups
sudo groupadd evidence-admins
sudo groupadd evidence-ops

# Create a user and assign to groups
sudo useradd -m frank
sudo passwd frank
sudo usermod -aG evidence-admins frank
```

2. Map OS groups to ECUBE roles in `.env`:

```bash
LOCAL_GROUP_ROLE_MAP='{"evidence-admins": ["admin"], "evidence-ops": ["manager", "processor"]}'
```

3. Configure token expiration (optional):

```bash
# Token lifetime in minutes (default: 60)
TOKEN_EXPIRE_MINUTES=60
```

**Requirements:**

- The ECUBE service account must have PAM access (typically membership in
  the `shadow` group or equivalent).
- No user database is required — PAM delegates to whatever backend the
  host is configured for (`/etc/shadow`, SSSD, Kerberos, etc.).
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

Roles are derived from OS group memberships at login time:

1. User calls `POST /auth/token` with username and password
2. PAM validates credentials against the host OS (or LDAP/Kerberos via PAM)
3. ECUBE collects the user's group IDs via `os.getgrouplist()` and resolves them to group names with `grp.getgrgid()`
4. Groups are mapped to ECUBE roles using `LOCAL_GROUP_ROLE_MAP` (or `LDAP_GROUP_ROLE_MAP`)
5. A signed JWT is issued containing the resolved roles
6. Each subsequent API call validates roles from the JWT claims

**Example Flow:**

```text
User "alice" calls POST /auth/token
    → PAM validates password
    → OS groups: ["evidence-admins", "users"]
    → LOCAL_GROUP_ROLE_MAP: "evidence-admins" → ["admin"]
    → JWT issued with roles=["admin"]
    → All endpoints accessible until token expires
```

**Note:** If a user's group memberships change, they must re-authenticate
(obtain a new token) for the updated roles to take effect. The old token
retains the previous roles until it expires.

---

## Common Operational Tasks

### Task 1: Add Network Mount

```bash
# Via API (requires manager role)
curl -X POST https://localhost:8443/mounts \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "evidence-share",
    "mount_type": "nfs",
    "server": "nfs.example.com",
    "export_path": "/evidence",
    "local_mount_point": "/mnt/evidence",
    "username": "optional-if-auth-required",
    "password": "optional-if-auth-required"
  }'
```

### Task 2: Initialize USB Drive

```bash
# Via API (requires manager role)
curl -X POST https://localhost:8443/drives/initialize \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "drive_id": 1,
    "project_id": 42,
    "encryption_key": "16-character-key"
  }'
```

### Task 3: Create Export Job

```bash
# Via API (requires processor role)
curl -X POST https://localhost:8443/jobs \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 42,
    "source_path": "/mnt/evidence/case-001",
    "drive_id": 1,
    "file_filter": "*.txt,*.pdf"
  }'
```

### Task 4: Start Copy Job

```bash
# Via API (requires processor role)
curl -X POST https://localhost:8443/jobs/1/start \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Task 5: View Job Status

```bash
# Via API (all authenticated roles)
curl -X GET https://localhost:8443/jobs/1 \
  -H "Authorization: Bearer $JWT_TOKEN"
```

### Task 6: Query Audit Logs

```bash
# Via API (requires admin, manager, or auditor role)
curl -X GET "https://localhost:8443/audit?user=alice&action=JOB_STARTED&limit=50" \
  -H "Authorization: Bearer $JWT_TOKEN"
```

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
docker compose logs app

# Follow logs
docker compose logs -f app

# View specific number of lines
docker compose logs -n 100 app
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
# API version endpoint (no auth required)
curl -k https://localhost:8443/introspection/version

# Drive inventory (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/drives

# Mount status (requires auth)
curl -k -H "Authorization: Bearer $TOKEN" \
  https://localhost:8443/introspection/mounts
```

---

## Troubleshooting

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
sudo -u ecube /opt/ecube/venv/bin/python3 -c "from sqlalchemy import create_engine; engine = create_engine(os.getenv('DATABASE_URL')); print(engine.execute('SELECT 1'))"
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

### Audit Log Cleanup

Remove old audit logs to prevent database bloat:

```bash
# Via PostgreSQL (example: delete logs older than 1 year)
psql -U ecube -d ecube << 'EOF'
DELETE FROM audit_logs 
WHERE timestamp < NOW() - INTERVAL '1 year';
EOF

# Vacuum database to reclaim space
psql -U ecube -d ecube -c "VACUUM ANALYZE;"
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

---

## Security Best Practices

### 1. Network Isolation

- **Database:** Accessible only from ECUBE system layer (no external PostgreSQL access)
- **API:** HTTPS only (port 8443), no HTTP fallback
- **Mounts:** NFS/SMB shares on isolated VLAN if possible
- **USB:** Local USB hub, not exposed over network

### 2. Certificate Management

```bash
# Use strong certificates (not self-signed in production)
# Let's Encrypt free certificates recommended
sudo certbot certonly --standalone -d ecube.example.com

# Ensure TLS 1.2+ only
# (Configure in reverse proxy or ECUBE settings)
```

### 3. Credential Management

```bash
# Never commit .env to version control
echo "/opt/ecube/.env" >> .gitignore

# Rotate SECRET_KEY annually
# Generate new key: openssl rand -hex 32
# Update .env and restart service

# Use strong LDAP/OIDC credentials
# Rotate LDAP bind password periodically
# Store in secrets manager (HashiCorp Vault, etc.) if available
```

### 4. Access Control

- Restrict API access to trusted networks (firewall rules)
- Use VPN or SSH tunnel for remote access
- Enable audit logging for all operations (enabled by default)
- Review audit logs weekly: `curl https://localhost:8443/audit?limit=1000`

### 5. File Permissions

```bash
# Restrict .env file to ecube user only
sudo chmod 600 /opt/ecube/.env
sudo chown ecube:ecube /opt/ecube/.env

# Restrict certificate files
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem

# Restrict venv
sudo chmod 750 /opt/ecube/venv
sudo chown -R ecube:ecube /opt/ecube
```

### 6. Audit Log Monitoring

```bash
# Export audit logs daily for compliance
psql -U ecube -d ecube -c "
SELECT * FROM audit_logs 
WHERE timestamp >= NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC
" | tee /mnt/audit-export/audit_$(date +%Y%m%d).csv

# Alert on suspicious activity (example: multiple failed logins)
psql -U ecube -d ecube << 'EOF'
SELECT user, COUNT(*) as failures 
FROM audit_logs 
WHERE action = 'AUTH_FAILURE' 
  AND timestamp >= NOW() - INTERVAL '1 hour'
GROUP BY user 
HAVING COUNT(*) > 5;
EOF
```

### 7. Firewall Configuration

```bash
# Allow HTTPS inbound (port 8443)
sudo ufw allow 8443/tcp

# Allow PostgreSQL only from localhost
sudo ufw allow from 127.0.0.1 to any port 5432

# Deny all other inbound
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw enable
```

---

## API Quick Reference

### Interactive API Documentation

ECUBE provides **interactive API documentation** via OpenAPI/Swagger that allows you to explore and test all endpoints directly from your browser. In **local development**, when the API server is running on port `8000`, access:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc (Alternative):** `http://localhost:8000/redoc`
- **OpenAPI JSON Schema:** `http://localhost:8000/openapi.json`

In **production**, use the same paths on your deployed HTTPS endpoint (for example, `https://localhost:8443/docs` or `https://ecube-api.example.com/docs`), replacing `localhost:8000` with the actual host and port configured for the ECUBE API.
Use the Swagger UI to:

- View all available endpoints with detailed descriptions
- Understand request/response schemas for each endpoint
- See required authentication and role requirements
- Test endpoints interactively with test data
- Copy curl commands
- View HTTP request/response examples

### Authentication

The following endpoints are publicly accessible and do **not** require authentication:

- `GET /health`
- API documentation: `GET /docs`, `GET /redoc`, `GET /openapi.json`

All other API endpoints require a bearer token in the `Authorization` header. For example:

```bash
curl -H "Authorization: Bearer $JWT_TOKEN" https://localhost:8443/endpoint
```

### Drives (`/drives`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/drives` | admin/manager/processor/auditor | List all drives and state |
| POST | `/drives/refresh` | admin/manager | Force rescan of attached drives |
| POST | `/drives/{drive_id}/initialize` | admin/manager | Initialize drive for project |
| POST | `/drives/{drive_id}/prepare-eject` | admin/manager | Flush filesystem + unmount all partitions; transitions drive to AVAILABLE on success, stays IN_USE on failure |

### Mounts (`/mounts`)

| Method | Endpoint | Role | Description |
| ------ | -------- | ---- | ----------- |
| GET | `/mounts` | manager+ | List network mounts |
| POST | `/mounts` | manager | Add new mount |
| POST | `/mounts/{mount_id}/validate` | admin/manager | Validate mount connectivity |
| POST | `/mounts/validate` | admin/manager | Validate all mounts |
| DELETE | `/mounts/{mount_id}` | admin/manager | Remove mount |

### Jobs (`/jobs`)

| Method | Endpoint | Role | Description |
| ------ | -------- | -------- | ----------- |
| POST | `/jobs` | processor+ | Create new export job |
| GET | `/jobs/{job_id}` | processor+ | Get job detail (status, progress) |
| POST | `/jobs/{job_id}/start` | processor | Start copy operation |
| POST | `/jobs/{job_id}/verify` | processor+ | Verify data integrity |
| POST | `/jobs/{job_id}/manifest` | processor+ | Generate manifest document |

### Audit (`/audit`)

| Method | Endpoint | Role | Description |
| ------ | -------- | -------- | ----------------------- |
| GET | `/audit` | auditor+ | Query audit logs with filters |

**Filters:**

- `user=alice` — Filter by user
- `action=JOB_CREATED` — Filter by action
- `job_id=5` — Filter by job
- `since=2026-03-01T00:00:00Z` — Start timestamp (ISO 8601)
- `until=2026-03-06T23:59:59Z` — End timestamp (ISO 8601)
- `limit=100` — Max results (default 100, max 1000)
- `offset=0` — Skip N results

**Example:**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  'https://localhost:8443/audit?action=JOB_STARTED&user=alice&limit=50&offset=0'
```

### Introspection (`/introspection`)

| Method | Endpoint | Role | Description |
| ------ | ----------------------- | ------ | ----------------------- |
| GET | `/introspection/usb/topology` | all | USB hub and device topology |
| GET | `/introspection/block-devices` | all | Kernel block device inventory |
| GET | `/introspection/mounts` | all | Mount inventory and status |
| GET | `/introspection/system-health` | all | Database and job engine health |
| GET | `/introspection/jobs/{job_id}/debug` | admin,auditor | Debug info for specific job |

---

## Support and Resources

### Documentation

- **Design Docs:** `documents/design/` — Technical design and architecture
- **API Spec:** `documents/design/06-rest-api-specification.md` — Detailed API endpoints
- **Security:** `documents/design/10-security-and-access-control.md` — Authentication, RBAC

### Logging and Debugging

- **Service Logs:** `journalctl -u ecube -f`
- **Database Logs:** PostgreSQL log file (check postgresql.conf)
- **API Errors:** Check response JSON for `detail` field

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

---

**End of Operational Guide**

For additional information, refer to design documents in `documents/design/` or GitHub repository wiki.
