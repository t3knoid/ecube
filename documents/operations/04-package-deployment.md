# ECUBE Package Deployment

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, IT Staff  
**Document Type:** Deployment Procedures

---

## Table of Contents

1. [Create Service Account](#create-service-account)
2. [Download and Extract Release Package](#download-and-extract-release-package)
3. [Set Up Python Virtual Environment](#set-up-python-virtual-environment)
4. [Create Systemd Service File](#create-systemd-service-file)
5. [Initialize Database](#initialize-database)
6. [Run First-Run Setup](#run-first-run-setup)
7. [Enable and Start Service](#enable-and-start-service)
8. [Configuration](#configuration)
9. [User Management](#user-management)
10. [Starting and Stopping the Service](#starting-and-stopping-the-service)

---

## Create Service Account

```bash
sudo useradd --system --create-home --shell /bin/bash ecube
sudo mkdir -p /opt/ecube
sudo chown -R ecube:ecube /opt/ecube
```

## Download and Extract Release Package

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

# Extract and fix ownership so the ecube user can access all files
tar -xzf "ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube/
chown -R ecube:ecube /opt/ecube
```

## Set Up Python Virtual Environment

```bash
sudo -u ecube python3.11 -m venv /opt/ecube/venv
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade pip setuptools wheel

# Install ECUBE and dependencies
sudo -u ecube /opt/ecube/venv/bin/pip install -e /opt/ecube/
```

## Create Systemd Service File

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

# Environment configuration (dash prefix: service starts even if file is absent)
EnvironmentFile=-/opt/ecube/.env

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

## Initialize Database

Database setup can be done manually or via the API-based provisioning endpoint.
Choose **one** option:

### Option A: API-Based Database Provisioning (Recommended)

This path requires the service to be running. Skip ahead to
[Enable and Start Service](#enable-and-start-service) to start the service,
then return here.

Once the service is listening, use the provisioning endpoints (unauthenticated
during initial setup — no token needed):

```bash
# Test PostgreSQL connectivity
curl -k -X POST https://localhost:8443/setup/database/test-connection \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "secret"}'

# Provision the application database, user, and run migrations
curl -k -X POST https://localhost:8443/setup/database/provision \
  -H "Content-Type: application/json" \
  -d '{"host": "localhost", "port": 5432, "admin_username": "postgres", "admin_password": "secret", "app_database": "ecube", "app_username": "ecube", "app_password": "ecube123"}'
```

The provision endpoint creates the PostgreSQL user and database, runs Alembic
migrations, and writes `DATABASE_URL` to `.env`. The running service
reconfigures its connection pool in-place — no restart is required.

### Option B: Manual Setup (CLI)

Configure the database, user, and `DATABASE_URL` in `.env` manually (see the
[Configuration](#configuration) section), then run migrations from the
command line:

```bash
sudo -u ecube /opt/ecube/venv/bin/alembic upgrade head
```

## Run First-Run Setup

The setup creates OS groups, an initial admin user, and seeds the database
with the admin role. This step requires a provisioned database.

### Option A: API-based

Requires the service to be running. If you haven't started it yet, complete
[Enable and Start Service](#enable-and-start-service) first, then return here:

```bash
# Check if initialization is needed
curl -k https://localhost:8443/setup/status
# {"initialized": false}

# Initialize (creates OS groups, admin user, seeds DB)
curl -k -X POST https://localhost:8443/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
```

The API endpoint is **unauthenticated** but can only succeed once. A
`system_initialization` single-row table provides a cross-process guard,
ensuring only one worker can complete initialization even in multi-worker
deployments. Subsequent calls return `409 Conflict`.

### Option B: CLI Setup Script

Alternatively, run the setup script as root:

```bash
sudo /opt/ecube/venv/bin/ecube-setup
```

### What setup creates

1. **OS groups:** `ecube-admins`, `ecube-managers`, `ecube-processors`, `ecube-auditors`
2. **Admin OS user:** Created with the specified username, added to `ecube-admins`
3. **DB admin role seed:** Inserts the admin user into the `user_roles` table with the `admin` role
4. **Initialization marker:** A row in `system_initialization` recording who initialized the system and when (API-based setup only)

**Prerequisites:**

- Database migrations must be applied first: `alembic upgrade head`
- Refuses to re-seed if an admin role already exists in the database

### Example session

```text
============================================================
ECUBE First-Run Setup
============================================================

Step 1: Creating ECUBE groups...
  Created group 'ecube-admins'
  Created group 'ecube-managers'
  Created group 'ecube-processors'
  Created group 'ecube-auditors'

Step 2: Creating admin user...
Enter admin username [ecube-admin]:
Enter admin password:
Confirm admin password:
  Created OS user 'ecube-admin'
  Added 'ecube-admin' to group 'ecube-admins'

Step 3: Generating configuration...
  Generated /opt/ecube/.env with random SECRET_KEY

Step 4: Seeding database...
  Seeded database: 'ecube-admin' → admin

============================================================
Setup complete!

Next steps:
  1. Review configuration: /opt/ecube/.env
  2. Start the service:    systemctl start ecube
============================================================
```

> **Important:** Setup must run **after** database initialization
> because it writes to the `user_roles` and `system_initialization` tables.

## Enable and Start Service

```bash
sudo systemctl enable ecube
sudo systemctl start ecube
sudo systemctl status ecube
```

---

## Configuration

For the complete list of environment variables, defaults, and descriptions, see:

> **[02-configuration-reference.md](02-configuration-reference.md)**

### Quick Start

ECUBE reads configuration from environment variables or a `.env` file. All settings have built-in defaults — the `.env` file is **optional**. Create one only to override defaults:

```bash
# Copy the example file as a starting point
sudo -u ecube cp /opt/ecube/.env.example /opt/ecube/.env

# Edit only the settings you need to change
sudo -u ecube nano /opt/ecube/.env
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

## User Management

### Adding Users After Initial Setup

```bash
# Option A: Via admin API (recommended)
curl -k -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "frank", "password": "s3cret", "groups": ["ecube-processors"]}' \
  https://localhost:8443/admin/os-users

# Option B: Manual OS commands
sudo useradd -m frank
sudo passwd frank
sudo usermod -aG ecube-processors frank

# Assign roles directly via the admin API (preferred over group fallback)
curl -k -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"roles": ["processor"]}' \
  https://localhost:8443/users/frank/roles
```

### OS Group-to-Role Mapping

Configure in `.env`:

```bash
LOCAL_GROUP_ROLE_MAP='{"ecube-admins": ["admin"], "ecube-managers": ["manager"], "ecube-processors": ["processor"], "ecube-auditors": ["auditor"]}'
```

### Token Configuration

```bash
# Token lifetime in minutes (default: 60)
TOKEN_EXPIRE_MINUTES=60
```

For full user management details, see [06-administration-guide.md](06-administration-guide.md#user-management).

---

## Starting and Stopping the Service

### Start Service

```bash
sudo systemctl start ecube
```

### Check Service Status

```bash
sudo systemctl status ecube
sudo journalctl -u ecube -n 50 -f  # Stream logs
```

### Stop Service

```bash
sudo systemctl stop ecube
```

### Restart Service

```bash
sudo systemctl restart ecube
```

### Verify API Endpoint

```bash
# Check HTTPS endpoint (self-signed cert will fail verification; use -k to skip)
curl -k https://localhost:8443/introspection/version

# Expected response (JSON):
# {"version": "0.1.0", "api_version": "1.0.0"}
```
