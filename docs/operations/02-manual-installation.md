# ECUBE Manual Installation

| Field | Value |
|---|---|
| Title | ECUBE Manual Installation |
| Purpose | Documents the manual deployment steps for ECUBE on a Linux host without using the automated installer. |
| Updated on | 04/10/26 |
| Audience | Systems administrators, platform engineers. |

## Table of Contents

1. [Scope and Source of Truth](#1-scope-and-source-of-truth)
2. [Requirements](#2-requirements)
   - [2.1 OS Requirements](#21-os-requirements)
   - [2.2 External Services](#22-external-services)
   - [2.3 Required Tools](#23-required-tools)
   - [2.4 Service Account Requirement (Backend)](#24-service-account-requirement-backend)
3. [Package Contents and Verification](#3-package-contents-and-verification)
4. [Single-Host Manual Deployment (DB + Backend + Frontend)](#4-single-host-manual-deployment-db--backend--frontend)
   - [4.1 Install OS packages](#41-install-os-packages)
   - [4.2 Create backend service account and directories](#42-create-backend-service-account-and-directories)
   - [4.3 Install sudoers Policy](#43-install-sudoers-policy)
   - [4.4 Install PAM Configuration](#44-install-pam-configuration)
   - [4.5 Extract package](#45-extract-package)
   - [4.6 Prepare PostgreSQL](#46-prepare-postgresql)
   - [4.7 Build backend runtime](#47-build-backend-runtime)
   - [4.8 Write backend `.env`](#48-write-backend-env)
   - [4.9 Generate TLS certificates](#49-generate-tls-certificates)
   - [4.10 Deploy frontend](#410-deploy-frontend)
   - [4.11 Create systemd unit](#411-create-systemd-unit)
   - [4.12 Production certificate replacement (recommended)](#412-production-certificate-replacement-recommended)
   - [4.13 Validate](#413-validate)
   - [4.14 Continue in web UI (required)](#414-continue-in-web-ui-required)
5. [Enterprise Split-Host Deployment (DB + Backend on Separate Hosts)](#5-enterprise-split-host-deployment-db--backend-on-separate-hosts)
   - [5.1 DB host](#51-db-host)
   - [5.2 Backend host](#52-backend-host)
   - [5.3 Continue in web UI (required)](#53-continue-in-web-ui-required)
6. [Host Firewall Hardening](#6-host-firewall-hardening)
   - [6.1 Single-host mode](#61-single-host-mode)
   - [6.2 Split-host mode](#62-split-host-mode)
7. [Operations and Upgrades](#7-operations-and-upgrades)
   - [7.1 Service operations](#71-service-operations)
   - [7.2 Manual package upgrade](#72-manual-package-upgrade)
   - [7.3 Uninstall / cleanup](#73-uninstall--cleanup)
  - [7.3.1 Manual Teardown (Step-by-Step)](#731-manual-teardown-step-by-step)
8. [Advanced: Hosting UI with Another Web Frontend](#8-advanced-hosting-ui-with-another-web-frontend)

---

## 1. Scope and Source of Truth

This document describes manual installation for:

- Native / VM Linux hosts
- systemd-managed ECUBE backend service with integrated frontend serving

---

## 2. Requirements

### 2.1 OS Requirements

- Ubuntu 20.04+ or Debian 11/12
- systemd-based host
- Root/sudo administrative access

### 2.2 External Services

- PostgreSQL 14+ (local or remote)
- DNS/network routing between frontend and backend hosts (split-host mode)

### 2.3 Required Tools

Minimum required on backend host:

- `curl`
- `openssl`
- `systemctl`
- `python3.11`
- `python3.11-venv`

Recommended:

- `ufw` (host firewall hardening)
- `psql` (DB credential verification and troubleshooting)

Quick install (Debian/Ubuntu) for database components:

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib
```

Enable and start PostgreSQL:

```bash
sudo systemctl enable --now postgresql
```

Repository source note:

- The commands above install `postgresql` from the host's configured Ubuntu/Debian APT repositories.
- For enterprise production environments, prefer the official vendor distribution channels and lifecycle guidance for tighter control of patch cadence, compatibility testing, and upgrade windows:
  - PostgreSQL: official PostgreSQL (PGDG) packages/repository guidance

### 2.4 Service Account Requirement (Backend)

The backend must run as a dedicated non-login service account (`ecube`) with ownership of install/runtime paths.

---

For supported deployment topologies (single-host and enterprise split-host), see [01-installation.md § Deployment Topologies](01-installation.md#deployment-topologies).

---

## 3. Package Contents and Verification

Release package assets:

- `ecube-package-<tag>.tar.gz`
- `ecube-package-<tag>.sha256`

Download and verify:

```bash
cd /tmp
export GITHUB_OWNER="t3knoid"
export GITHUB_REPO="ecube"

LATEST_TAG=$(curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")

curl -fsSL -O \
  "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${LATEST_TAG}/ecube-package-${LATEST_TAG}.tar.gz"

curl -fsSL -O \
  "https://github.com/${GITHUB_OWNER}/${GITHUB_REPO}/releases/download/${LATEST_TAG}/ecube-package-${LATEST_TAG}.sha256"

sha256sum -c "ecube-package-${LATEST_TAG}.sha256"
```

---

## 4. Single-Host Manual Deployment (DB + Backend + Frontend)

### 4.1 Install OS packages

```bash
sudo apt-get update
sudo apt-get install -y \
  python3.11 python3.11-venv \
  postgresql postgresql-contrib \
  curl openssl
```

### 4.2 Create backend service account and directories

```bash
sudo useradd --system --create-home --home-dir /opt/ecube --shell /usr/sbin/nologin ecube
sudo mkdir -p /opt/ecube /var/lib/ecube /var/log/ecube /nfs /smb
sudo chown -R ecube:ecube /opt/ecube /var/lib/ecube /var/log/ecube
sudo chown ecube:ecube /nfs /smb
sudo chmod 750 /opt/ecube
sudo chmod 700 /var/lib/ecube
sudo chmod 750 /var/log/ecube
sudo chmod 755 /nfs /smb

# Optional hardware groups when present on the host
getent group plugdev >/dev/null && sudo usermod -aG plugdev ecube
getent group dialout >/dev/null && sudo usermod -aG dialout ecube

# Required on some hardened hosts for reliable local PAM password checks
getent group shadow >/dev/null && sudo usermod -aG shadow ecube
```

The managed mount roots (`/nfs` and `/smb`) must be owned by the `ecube` service account. Runtime mount requests can use narrowly scoped sudo to create missing leaf folders and repair ownership under these roots.

The `shadow` group membership allows the non-root `ecube` service process to
perform local PAM (`pam_unix`) authentication consistently on hosts where
helper privilege transitions are restricted by host security policy.

### 4.3 Install sudoers Policy
Install the sudoers policy required for setup-time OS user/group management, mount operations, and managed mount-root bootstrap/ownership:

```bash
sudo install -d -m 0755 /etc/sudoers.d
sudo tee /etc/sudoers.d/ecube-user-mgmt > /dev/null <<'EOF_SUDOERS'
# /etc/sudoers.d/ecube-user-mgmt
# Narrowly scoped privilege escalation for the ECUBE service account.
ecube ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/sbin/usermod, /usr/sbin/userdel, /usr/sbin/groupadd, /usr/sbin/groupdel, /usr/sbin/chpasswd, /bin/mount, /bin/umount, /sbin/mount.nfs, /usr/sbin/mount.nfs, /bin/sync, /sbin/mkfs.ext4, /sbin/mkfs.exfat, /bin/mkdir, /bin/chown, /usr/bin/chown
EOF_SUDOERS
sudo chmod 0440 /etc/sudoers.d/ecube-user-mgmt
sudo visudo -cf /etc/sudoers.d/ecube-user-mgmt
```

### 4.4 Install PAM Configuration

Install PAM configuration by selecting one of the two options below.

To detect whether SSSD support is installed on the host:

```bash
if command -v sssd >/dev/null 2>&1 || \
   [[ -f /lib/security/pam_sss.so || -f /lib/x86_64-linux-gnu/security/pam_sss.so ]]; then
  echo "SSSD support detected: use 4.4.1"
else
  echo "SSSD support not detected: use 4.4.2"
fi
```

#### 4.4.1 Install PAM with SSSD support (local + domain users)

Use this option only when SSSD and `pam_sss.so` are installed and operational on the host.

```bash
sudo install -d -m 0755 /etc/pam.d
sudo tee /etc/pam.d/ecube > /dev/null <<'EOF_PAM'
# /etc/pam.d/ecube
# PAM configuration for the ECUBE service (local and domain user authentication).
# Tries local users first (pam_unix, sufficient = stop on success), then domain users via SSSD.
# Falls back to an unconditional deny so missing modules or backend failures do not open a hole.

auth    sufficient  pam_unix.so nullok
auth    [success=done ignore=ignore default=die] pam_sss.so use_first_pass
auth    required    pam_deny.so
account sufficient  pam_unix.so
account [success=done ignore=ignore default=die] pam_sss.so
account required    pam_deny.so
EOF_PAM
sudo chmod 0644 /etc/pam.d/ecube
```

#### 4.4.2 Install PAM without SSSD support (local users only)

Use this option when the host does not use SSSD for directory authentication.

```bash
sudo install -d -m 0755 /etc/pam.d
sudo tee /etc/pam.d/ecube > /dev/null <<'EOF_PAM'
# /etc/pam.d/ecube
# Local-only PAM configuration.
# Use this when SSSD is not installed on the host.

auth    sufficient  pam_unix.so nullok
auth    required    pam_deny.so
account sufficient  pam_unix.so
account required    pam_deny.so
EOF_PAM
sudo chmod 0644 /etc/pam.d/ecube
```

### 4.5 Extract package

```bash
sudo tar -xzf "/tmp/ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube --strip-components=1
sudo chown -R ecube:ecube /opt/ecube
```

### 4.6 Prepare PostgreSQL

Ensure PostgreSQL is installed and running. No manual superuser creation is required — the automated installer creates a PostgreSQL superuser automatically using the same default credentials as Docker Compose (`POSTGRES_USER`/`POSTGRES_PASSWORD`, falling back to `ecube`/`ecube`). The credentials are written to `.env` so the setup wizard can auto-fill them.

If you are performing a fully manual installation (without `install.sh`), create a superuser for the setup wizard:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE ecube WITH SUPERUSER LOGIN PASSWORD 'ecube';
SQL
```

Then set `PG_SUPERUSER_NAME` and `PG_SUPERUSER_PASS` in `.env` to match.

#### Create the ECUBE application role and database

It is recommended to use the setup wizard shown the first time the ECUBE web frontend is visited. The setup wizard will use the superuser credentials entered at `/setup` to create the `ecube` role and `ecube` database automatically.

Optionally, create the application role and database yourself before starting the service, then set `DATABASE_URL` directly in `.env`:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE ecube WITH LOGIN PASSWORD 'change-me-strong';
CREATE DATABASE ecube OWNER ecube;
SQL
```

### 4.7 Build backend runtime

```bash
sudo -u ecube python3.11 -m venv /opt/ecube/venv
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u ecube /opt/ecube/venv/bin/pip install /opt/ecube
```

### 4.8 Write backend `.env`

Installer-equivalent path (wizard-managed DB provisioning):

```bash
sudo tee /opt/ecube/.env > /dev/null <<'EOF_ENV'
SECRET_KEY=replace-with-random-hex
DATABASE_URL=
PG_SUPERUSER_NAME=ecube
PG_SUPERUSER_PASS=ecube
TRUST_PROXY_HEADERS=false
SERVE_FRONTEND_PATH=/opt/ecube/www
EOF_ENV

sudo chown ecube:ecube /opt/ecube/.env
sudo chmod 600 /opt/ecube/.env
```

Alternative manual path (operator-managed DB connection):

```bash
sudo tee /opt/ecube/.env > /dev/null <<'EOF_ENV'
SECRET_KEY=replace-with-random-hex
DATABASE_URL=postgresql://ecube:change-me-strong@localhost:5432/ecube
TRUST_PROXY_HEADERS=false
SERVE_FRONTEND_PATH=/opt/ecube/www
EOF_ENV

sudo chown ecube:ecube /opt/ecube/.env
sudo chmod 600 /opt/ecube/.env
```

After service start, open `/setup` to complete database provisioning. The
wizard auto-fills superuser credentials from `PG_SUPERUSER_NAME`/`PG_SUPERUSER_PASS`
in `.env` and clears them after successful provisioning.

> **Note:** `SERVE_FRONTEND_PATH` tells FastAPI to serve the SPA directly and enables the `/api` prefix-stripping middleware so the frontend's `/api/...` requests reach the correct routes. Set `TRUST_PROXY_HEADERS=true` only when an external reverse proxy (load balancer, CDN) sits in front of ECUBE.

### 4.9 Generate TLS certificates

The command below creates a **self-signed** certificate with `CN=$(hostname -f)`.
This means clients should access ECUBE using that hostname (for example,
`https://ecube.example.com`), not an IP address, or TLS name validation will
not match. Browsers and API clients will still show trust warnings because the
certificate is self-signed.

Use this only for lab/testing or temporary bring-up. For production, use a
public/enterprise CA-signed certificate (recommended), such as Let's Encrypt.

Skip this step if you plan to use `--no-tls` (plain HTTP).

```bash
HOST_NAME="$(hostname -f)"
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -z "$HOST_IP" ]]; then HOST_IP="127.0.0.1"; fi

sudo mkdir -p /opt/ecube/certs
sudo openssl req -x509 -nodes -days 730 -newkey rsa:2048 \
  -keyout /opt/ecube/certs/key.pem \
  -out /opt/ecube/certs/cert.pem \
  -subj "/CN=${HOST_NAME}" \
  -addext "subjectAltName=DNS:${HOST_NAME},IP:${HOST_IP}"

sudo chown ecube:ecube /opt/ecube/certs/key.pem /opt/ecube/certs/cert.pem
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
```

Notes:

- This mirrors installer defaults (`--cert-validity 730`).
- If you use an IP literal for host identity (especially IPv6), use IP SAN entries instead of `DNS:` SAN entries.

### 4.10 Deploy frontend

Copy the pre-built SPA assets to the directory referenced by `SERVE_FRONTEND_PATH`:

```bash
sudo mkdir -p /opt/ecube/www
sudo rm -rf /opt/ecube/www/*
sudo cp -r /opt/ecube/frontend/dist/. /opt/ecube/www/
sudo chown -R ecube:ecube /opt/ecube/www
```

### 4.11 Create systemd unit

#### HTTPS (default)

```bash
sudo tee /etc/systemd/system/ecube.service > /dev/null <<'EOF_UNIT'
[Unit]
Description=ECUBE Evidence Export Service
After=network-online.target
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
EOF_UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now ecube.service
```

#### Plain HTTP (lab/testing)

For plain HTTP on port 80, omit the TLS flags and add `AmbientCapabilities` for the privileged port:

```bash
sudo tee /etc/systemd/system/ecube.service > /dev/null <<'EOF_UNIT'
[Unit]
Description=ECUBE Evidence Export Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ecube
Group=ecube
WorkingDirectory=/opt/ecube
EnvironmentFile=-/opt/ecube/.env
ExecStart=/opt/ecube/venv/bin/uvicorn \
  --host 0.0.0.0 \
  --port 80 \
  app.main:app
Restart=on-failure
RestartSec=10
PrivateTmp=yes
AmbientCapabilities=CAP_NET_BIND_SERVICE
# Required for setup endpoints that invoke tightly scoped sudoers commands.
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
EOF_UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now ecube.service
```

> **Note:** `AmbientCapabilities=CAP_NET_BIND_SERVICE` is required only for ports below 1024. For ports ≥ 1024, omit this line.

### 4.12 Production certificate replacement (recommended)

Replace self-signed certificates with CA-signed certificates before production cutover.

For full procedures (Let's Encrypt/certbot, renewal, firewall prerequisites,
split-host notes, and permissions), see:

- [05-tls-certificates-and-letsencrypt.md](05-tls-certificates-and-letsencrypt.md)

### 4.13 Validate

```bash
curl -fsk https://localhost:8443/health
```

This should return the following if everything has been configured.

```json
{"status":"ok"}
```

For plain HTTP installs, use:

```bash
curl -fs http://localhost:80/health
```

### 4.14 Continue in web UI (required)

After the service validates successfully, open the web UI and complete initial configuration:

```text
https://<hostname>:8443/setup
```

Operator troubleshooting note (admin step skipped): if setup flashes past admin creation, check whether an admin DB role exists without a matching OS user:

```bash
getent passwd <admin-username> || echo "OS user missing"
sudo -u postgres psql -d postgres -c "SELECT username, role FROM user_roles WHERE role='admin';"
sudo -u postgres psql -d postgres -c "SELECT * FROM system_initialization;"
```

Current ECUBE builds recover this automatically: when DB admin rows exist but the OS admin account is missing, setup stays available and recreates the OS user on the next `/setup/initialize` run.

---

## 5. Enterprise Split-Host Deployment (DB + Backend on Separate Hosts)

### 5.1 DB host

- Install and harden PostgreSQL.
- Create DB/user for ECUBE backend.
- Allow inbound PostgreSQL only from backend host(s).

Example DB grants:

```sql
CREATE ROLE ecube LOGIN PASSWORD 'change-me-strong';
CREATE DATABASE ecube OWNER ecube;
```

### 5.2 Backend host

Follow sections 4.1 to 4.7 (skipping 4.6 PostgreSQL setup) with these differences:

- Skip local PostgreSQL installation; point `DATABASE_URL` in `.env` to the remote DB host.
- For wizard-managed DB configuration: leave `DATABASE_URL=` blank and configure it in `/setup` after starting the service.

The backend serves both the API and the frontend on a single port, same as a single-host install. TLS is terminated by uvicorn directly.

### 5.3 Continue in web UI (required)

After backend connectivity to the remote DB is validated, open the web UI and complete setup:

```text
https://<backend-hostname>:8443/setup
```

---

## 6. Host Firewall Hardening

Use local firewall policy on each host. Example with `ufw`:

### 6.1 Single-host mode

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 8443/tcp
sudo ufw allow from <admin-cidr> to any port 22 proto tcp
sudo ufw enable
```

### 6.2 Split-host mode

DB host:

```bash
sudo ufw allow from <backend-host-ip-or-cidr> to any port 5432 proto tcp
sudo ufw deny 5432/tcp
```

Backend host:

```bash
sudo ufw allow 8443/tcp
```

General rule:

- allow only required source CIDRs
- deny direct API exposure except from trusted frontend hosts
- keep SSH restricted to admin networks

---

## 7. Operations and Upgrades

### 7.1 Service operations

```bash
sudo systemctl status ecube
sudo systemctl restart ecube
sudo journalctl -u ecube -n 200 -f
```

### 7.2 Manual package upgrade

```bash
sudo tar -xzf "/tmp/ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube --strip-components=1
sudo chown -R ecube:ecube /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/pip install /opt/ecube
sudo systemctl restart ecube
```

Then complete setup so migrations are applied:

- UI-based flow: open `https://<frontend-hostname>/setup`

### 7.3 Uninstall / cleanup

If the host was installed using the ECUBE installer package, you can run:

```bash
sudo /opt/ecube/install.sh --uninstall
```

Optional database cleanup (installer-managed path):

```bash
sudo /opt/ecube/install.sh --uninstall --drop-database
```

If the original install used a custom `--install-dir`, run the script from that directory (for example, `sudo /srv/ecube/install.sh --uninstall`).

> **Warning:** `--drop-database` is destructive and irreversible.
> Before dropping the database, perform and verify a backup (for example, a
> `pg_dump` backup restored successfully in a test environment).
>
> **Remote Database Note:** When `--drop-database` targets a remote PostgreSQL instance, superuser-role cleanup may require credentials for `SETUP_DEFAULT_ADMIN_USERNAME` (from `.env`) via `.pgpass` or `PGPASSWORD`. Ensure these credentials are available on the host where `install.sh --uninstall` is run.
### 7.3.1 Manual Teardown (Step-by-Step)

If for any reason the installer script is not available or you prefer manual removal, follow these steps:

#### 1. Stop and disable the ECUBE service

```bash
sudo systemctl stop ecube.service
sudo systemctl disable ecube.service
sudo rm /etc/systemd/system/ecube.service
sudo systemctl daemon-reload
```

#### 2. Remove sudoers policy

```bash
sudo rm -f /etc/sudoers.d/ecube-user-mgmt
sudo visudo -cf /etc/sudoers.d  # optional validation
```

#### 3. Remove PAM configuration

```bash
sudo rm -f /etc/pam.d/ecube
```

#### 4. Remove application installation directory

```bash
sudo rm -rf /opt/ecube
```

#### 5. Remove runtime and log directories

```bash
sudo rm -rf /var/lib/ecube
sudo rm -rf /var/log/ecube
```

#### 6. Remove managed mount roots (optional)

Only remove if these directories were created solely for ECUBE and are no longer needed:

```bash
sudo rm -rf /nfs /smb
```

#### 7. Remove service account and group

```bash
sudo userdel -r ecube  # -r removes home directory
```

#### 8. Clean up firewall rules (if using `ufw`)

```bash
sudo ufw delete allow 8443/tcp  # if configured
sudo ufw delete allow from <admin-cidr> to any port 22 proto tcp  # if configured
```

#### 9. PostgreSQL cleanup (optional, after verified backup)

```bash
# Back up the database first
sudo -u postgres pg_dump ecube > /tmp/ecube-backup.sql

# Drop the database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ecube;"

# Drop the application role
sudo -u postgres psql -c "DROP ROLE IF EXISTS ecube;"

# Drop the setup superuser role (if applicable)
sudo -u postgres psql -c "DROP ROLE IF EXISTS ecubeadmin;"
```

For remote PostgreSQL instances, use `psql` with connection parameters or `.pgpass` credentials:

```bash
# Example with explicit host
psql -h db.example.com -U ecubeadmin -d postgres \
  -c "DROP DATABASE IF EXISTS ecube; DROP ROLE IF EXISTS ecube; DROP ROLE IF EXISTS ecubeadmin;"
```

> **Warning:** Database removal is irreversible. Always test your backup restoration before removing the live database.

---

## 8. Advanced: Hosting UI with Another Web Frontend

You can host `frontend/dist` with another web server/CDN/load balancer instead of letting FastAPI serve the frontend directly.

Requirements for alternative frontend hosting:

1. Serve SPA static files with fallback to `index.html` for client routes.
2. Expose UI over HTTPS.
3. Reverse proxy `/api/` to the ECUBE backend and strip the `/api` prefix before forwarding.
4. Forward `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers.
5. For split-host backend over HTTPS, enable upstream certificate verification.

Backend `.env` requirements when behind an external reverse proxy:

- `TRUST_PROXY_HEADERS=true`
- `API_ROOT_PATH=/api`
- `SERVE_FRONTEND_PATH=` (leave empty — the external server handles frontend serving)

Validation checklist:

- UI loads at `https://<ui-host>/`
- API health check works at `https://<ui-host>/api/health`
- OpenAPI docs work at `https://<ui-host>/api/docs`

## References

- [docs/operations/01-installation.md](01-installation.md)
- [docs/operations/04-configuration-reference.md](04-configuration-reference.md)
