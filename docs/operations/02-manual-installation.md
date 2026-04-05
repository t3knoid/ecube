# ECUBE Manual Installation

**Version:** 3.0  
**Last Updated:** April 2026  
**Audience:** Systems Administrators, Platform Engineers  
**Document Type:** Manual Deployment Procedures

> This guide is the manual equivalent of what `install.sh` automates in [01-installation.md](01-installation.md).  
> Use it when you must deploy without the installer, need custom host layout, or need stricter enterprise controls.
>
> **Important:** In installer-driven deployments, `install.sh` now creates/updates a PostgreSQL superuser for setup and database provisioning is performed in the web setup wizard (`/setup`).
> This manual guide also documents an explicit operator-managed alternative where `DATABASE_URL` is written directly in `.env`.

---

## Table of Contents

- [Table of Contents](#table-of-contents)
- [1. Scope and Source of Truth](#1-scope-and-source-of-truth)
- [2. Requirements](#2-requirements)
- [3. Deployment Topologies](#3-deployment-topologies)
- [4. Package Contents and Verification](#4-package-contents-and-verification)
- [5. Single-Host Manual Deployment (DB + Backend + Frontend)](#5-single-host-manual-deployment-db--backend--frontend)
- [6. Enterprise Split-Host Deployment (DB, Backend, Frontend on Separate Hosts)](#6-enterprise-split-host-deployment-db-backend-frontend-on-separate-hosts)
- [7. Host Firewall Hardening](#7-host-firewall-hardening)
- [8. Operations and Upgrades](#8-operations-and-upgrades)
- [9. Advanced: Hosting UI with Another Web Frontend](#9-advanced-hosting-ui-with-another-web-frontend)

---

## 1. Scope and Source of Truth

This document describes manual installation for:

- Bare-metal / VM Linux hosts (no Docker runtime required)
- systemd-managed ECUBE backend service
- frontend static bundle hosting and API reverse proxying

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

- `nginx` (if hosting frontend/UI on same or dedicated frontend host)
- `ufw` (host firewall hardening)
- `psql` (DB credential verification and troubleshooting)

Quick install (Debian/Ubuntu) for web and database components:

```bash
sudo apt-get update
sudo apt-get install -y nginx postgresql postgresql-contrib
```

Enable and start both services:

```bash
sudo systemctl enable --now postgresql nginx
```

Repository source note:

- The commands above install `nginx` and `postgresql` from the host's configured Ubuntu/Debian APT repositories.
- For enterprise production environments, prefer the official vendor distribution channels and lifecycle guidance for tighter control of patch cadence, compatibility testing, and upgrade windows:
  - nginx: official nginx packages/repository guidance
  - PostgreSQL: official PostgreSQL (PGDG) packages/repository guidance

### 2.4 Service Account Requirement (Backend)

The backend must run as a dedicated non-login service account (`ecube`) with ownership of install/runtime paths.

---

## 3. Deployment Topologies

### Topology A: Single Host (recommended for small/medium installs)

One host runs:

- PostgreSQL
- ECUBE backend (`ecube.service`)
- Web frontend + reverse proxy (nginx)

Behavior target (same as installer full mode):

- nginx terminates external TLS
- backend serves HTTP on `127.0.0.1:<api-port>`
- nginx proxies `/api/` to backend

### Topology B: Enterprise Split Host

Three dedicated hosts:

- DB host: PostgreSQL only
- Backend host: ECUBE backend only
- Frontend host: static UI + reverse proxy to backend

Behavior target (same as installer frontend-only + remote backend mode):

- frontend proxies `/api/` to backend over HTTPS
- backend `.env` explicitly sets:
  - `TRUST_PROXY_HEADERS=true`
  - `API_ROOT_PATH=/api`

---

## 4. Package Contents and Verification

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

## 5. Single-Host Manual Deployment (DB + Backend + Frontend)

### 5.1 Install OS packages

```bash
sudo apt-get update
sudo apt-get install -y \
  python3.11 python3.11-venv \
  postgresql postgresql-contrib \
  nginx curl openssl
```

### 5.2 Create backend service account and directories

```bash
sudo useradd --system --create-home --home-dir /opt/ecube --shell /usr/sbin/nologin ecube
sudo mkdir -p /opt/ecube /var/lib/ecube
sudo chown -R ecube:ecube /opt/ecube /var/lib/ecube
sudo chmod 750 /opt/ecube
sudo chmod 700 /var/lib/ecube

# Optional hardware groups when present on the host
getent group plugdev >/dev/null && sudo usermod -aG plugdev ecube
getent group dialout >/dev/null && sudo usermod -aG dialout ecube

# Required on some hardened hosts for reliable local PAM password checks
getent group shadow >/dev/null && sudo usermod -aG shadow ecube
```

The `shadow` group membership allows the non-root `ecube` service process to
perform local PAM (`pam_unix`) authentication consistently on hosts where
helper privilege transitions are restricted by host security policy.

Install the sudoers policy required for setup-time OS user/group management:

```bash
sudo install -d -m 0755 /etc/sudoers.d
sudo tee /etc/sudoers.d/ecube-user-mgmt > /dev/null <<'EOF_SUDOERS'
# /etc/sudoers.d/ecube-user-mgmt
# Narrowly scoped privilege escalation for the ECUBE service account.
ecube ALL=(root) NOPASSWD: /usr/sbin/useradd, /usr/sbin/usermod, /usr/sbin/userdel, /usr/sbin/groupadd, /usr/sbin/groupdel, /usr/sbin/chpasswd
EOF_SUDOERS
sudo chmod 0440 /etc/sudoers.d/ecube-user-mgmt
sudo visudo -cf /etc/sudoers.d/ecube-user-mgmt
```

Install the PAM configuration for local and domain user authentication:

```bash
sudo install -d -m 0755 /etc/pam.d

# If SSSD is present on the host, install the full config with domain support
if command -v sssd &>/dev/null || [[ -f /lib/security/pam_sss.so || -f /lib/x86_64-linux-gnu/security/pam_sss.so ]]; then
  sudo tee /etc/pam.d/ecube > /dev/null <<'EOF_PAM'
# /etc/pam.d/ecube
# PAM configuration for the ECUBE service (local and domain user authentication).
#
# Tries local users first (pam_unix, sufficient = stop on success), then
# domain users via SSSD (pam_sss, only attempted if SSSD is installed).
# Falls back to an unconditional deny so a missing module does not open a hole.

auth    sufficient  pam_unix.so nullok
auth    [success=done ignore=ignore default=die] pam_sss.so use_first_pass
auth    required    pam_deny.so
account sufficient  pam_unix.so
account [success=done ignore=ignore default=die] pam_sss.so
account required    pam_deny.so
EOF_PAM
  echo "PAM config installed with SSSD support: /etc/pam.d/ecube"
else
  # SSSD not present — install a local-only variant
  sudo tee /etc/pam.d/ecube > /dev/null <<'EOF_PAM'
# /etc/pam.d/ecube
# Local-only PAM configuration (SSSD not detected at install time).
# Re-run setup steps after installing SSSD to enable domain user authentication.

auth    sufficient  pam_unix.so nullok
auth    required    pam_deny.so
account sufficient  pam_unix.so
account required    pam_deny.so
EOF_PAM
  echo "PAM config installed (local users only): /etc/pam.d/ecube"
fi

sudo chmod 0644 /etc/pam.d/ecube
```

### 5.3 Extract package

```bash
sudo mkdir -p /opt/ecube
sudo tar -xzf "/tmp/ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube --strip-components=1
sudo chown -R ecube:ecube /opt/ecube
```

### 5.4 Prepare PostgreSQL (Installer-equivalent wizard flow)

To mirror current `install.sh` behavior, create a PostgreSQL superuser for the
setup wizard and let the wizard create the ECUBE app role/database.

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE ecubeadmin WITH SUPERUSER LOGIN PASSWORD 'change-me-strong';
SQL
```

If the role already exists:

```bash
sudo -u postgres psql -c "ALTER ROLE ecubeadmin WITH SUPERUSER LOGIN PASSWORD 'change-me-strong';"
```

### 5.5 Build backend runtime

```bash
sudo -u ecube python3.11 -m venv /opt/ecube/venv
sudo -u ecube /opt/ecube/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u ecube /opt/ecube/venv/bin/pip install -e /opt/ecube
```

### 5.6 Write backend `.env`

Installer-equivalent path (wizard-managed DB provisioning):

```bash
sudo tee /opt/ecube/.env > /dev/null <<'EOF_ENV'
SECRET_KEY=replace-with-random-hex
DATABASE_URL=
SETUP_DEFAULT_ADMIN_USERNAME=ecubeadmin
TRUST_PROXY_HEADERS=true
API_ROOT_PATH=/api
EOF_ENV

sudo chown ecube:ecube /opt/ecube/.env
sudo chmod 600 /opt/ecube/.env
```

Alternative manual path (operator-managed DB connection):

```bash
sudo tee /opt/ecube/.env > /dev/null <<'EOF_ENV'
SECRET_KEY=replace-with-random-hex
DATABASE_URL=postgresql://ecube:change-me-strong@localhost:5432/ecube
SETUP_DEFAULT_ADMIN_USERNAME=ecubeadmin
TRUST_PROXY_HEADERS=true
API_ROOT_PATH=/api
EOF_ENV

sudo chown ecube:ecube /opt/ecube/.env
sudo chmod 600 /opt/ecube/.env
```

After service start, open `/setup` and enter the PostgreSQL superuser
credentials (for example, `ecubeadmin`) in the database provisioning step.

### 5.7 Generate certificates (nginx TLS terminator)

The command below creates a **self-signed** certificate with `CN=$(hostname -f)`.
This means clients should access ECUBE using that hostname (for example,
`https://ecube.example.com`), not an IP address, or TLS name validation will
not match. Browsers and API clients will still show trust warnings because the
certificate is self-signed.

Use this only for lab/testing or temporary bring-up. For production, use a
public/enterprise CA-signed certificate (recommended), such as Let's Encrypt.

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

sudo chown root:root /opt/ecube/certs/key.pem
sudo chmod 600 /opt/ecube/certs/key.pem
sudo chown ecube:ecube /opt/ecube/certs/cert.pem
sudo chmod 644 /opt/ecube/certs/cert.pem
```

Notes:

- This mirrors installer defaults (`--cert-validity 730`).
- If you use an IP literal for host identity (especially IPv6), use IP SAN entries instead of `DNS:` SAN entries.

### 5.8 Create backend systemd unit (HTTP loopback behind nginx)

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
  --host 127.0.0.1 \
  --port 8443 \
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

### 5.9 Configure frontend and reverse proxy (same host)

```bash
sudo mkdir -p /opt/ecube/www
sudo rm -rf /opt/ecube/www/*
sudo cp -r /opt/ecube/frontend/dist/. /opt/ecube/www/
sudo chown -R root:root /opt/ecube/www
sudo find /opt/ecube/www -type d -exec chmod 755 {} +
sudo find /opt/ecube/www -type f -exec chmod 644 {} +

# Match installer behavior: let nginx traverse /opt/ecube without granting
# world execute on the whole install tree.
sudo groupadd --system ecube-www 2>/dev/null || true
sudo usermod -aG ecube-www www-data
sudo chown ecube:ecube-www /opt/ecube
sudo chmod 710 /opt/ecube
```

```bash
sudo tee /etc/nginx/sites-available/ecube > /dev/null <<'EOF_NGINX'
server {
    listen 443 ssl;
    listen [::]:443 ssl;

    server_name _;

    ssl_certificate     /opt/ecube/certs/cert.pem;
    ssl_certificate_key /opt/ecube/certs/key.pem;

    root /opt/ecube/www;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location = /api {
        return 301 /api/;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8443/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF_NGINX

sudo ln -sf /etc/nginx/sites-available/ecube /etc/nginx/sites-enabled/ecube
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

### 5.10 Production certificate replacement (recommended)

Replace self-signed certificates with CA-signed certificates before production cutover.

For full procedures (Let's Encrypt/certbot, renewal, firewall prerequisites,
split-host notes, and permissions), see:

- [05-tls-certificates-and-letsencrypt.md](05-tls-certificates-and-letsencrypt.md)

### 5.11 Validate

```bash
curl -fsk https://localhost/api/health
```

### 5.12 Continue in web UI (required)

After the service and nginx validate successfully, open the web UI and complete initial configuration:

```text
https://<frontend-hostname>/setup
```

Operator troubleshooting note (admin step skipped): if setup flashes past admin creation, check whether an admin DB role exists without a matching OS user:

```bash
getent passwd <admin-username> || echo "OS user missing"
sudo -u postgres psql -d postgres -c "SELECT username, role FROM user_roles WHERE role='admin';"
sudo -u postgres psql -d postgres -c "SELECT * FROM system_initialization;"
```

Current ECUBE builds recover this automatically: when DB admin rows exist but the OS admin account is missing, setup stays available and recreates the OS user on the next `/setup/initialize` run.

If this host is backend-only and does not serve the UI, complete setup from a frontend-enabled ECUBE deployment URL.

---

## 6. Enterprise Split-Host Deployment (DB, Backend, Frontend on Separate Hosts)

### 6.1 DB host

- Install and harden PostgreSQL.
- Create DB/user for ECUBE backend.
- Allow inbound PostgreSQL only from backend host(s).

Example DB grants:

```sql
CREATE ROLE ecube LOGIN PASSWORD 'change-me-strong';
CREATE DATABASE ecube OWNER ecube;
```

### 6.2 Backend host (no nginx/UI)

Follow sections 5.1 to 5.6 with these differences:

- For manual DB configuration: set `DATABASE_URL` to the DB host.
- For wizard-managed DB configuration: leave `DATABASE_URL=` blank and configure it in `/setup` from a frontend-enabled host.
- backend serves HTTPS directly (no local nginx).
- backend `.env` includes:
  - `TRUST_PROXY_HEADERS=true`
  - `API_ROOT_PATH=/api`

Use TLS in systemd unit:

```ini
ExecStart=/opt/ecube/venv/bin/uvicorn \
  --host 0.0.0.0 \
  --port 8443 \
  --ssl-keyfile=/opt/ecube/certs/key.pem \
  --ssl-certfile=/opt/ecube/certs/cert.pem \
  app.main:app
```

Set certificate ownership for backend TLS termination:

- `/opt/ecube/certs/key.pem` -> `ecube:ecube`, mode `600`
- `/opt/ecube/certs/cert.pem` -> `ecube:ecube`, mode `644`

### 6.3 Frontend host (no backend service)

- Deploy `frontend/dist` to web root.
- Configure reverse proxy from `/api/` to `https://<backend-host>:8443/`.
- Prefer verified TLS (`proxy_ssl_verify on`) with either:
  - system CA trust, or
  - explicit `proxy_ssl_trusted_certificate`.

Nginx essentials for remote backend:

```nginx
location /api/ {
    proxy_pass https://backend.example.com:8443/;
    proxy_ssl_verify on;
    proxy_ssl_server_name on;
    proxy_ssl_name backend.example.com;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### 6.4 Continue in web UI (required)

After frontend and backend connectivity is validated, open the frontend host URL and complete setup:

```text
https://<frontend-hostname>/setup
```

---

## 7. Host Firewall Hardening

Use local firewall policy on each host. Example with `ufw`:

### 7.1 Single-host mode

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 443/tcp
sudo ufw deny 8443/tcp
sudo ufw allow from <admin-cidr> to any port 22 proto tcp
sudo ufw enable
```

### 7.2 Split-host mode

DB host:

```bash
sudo ufw allow from <backend-host-ip-or-cidr> to any port 5432 proto tcp
sudo ufw deny 5432/tcp
```

Backend host:

```bash
sudo ufw allow from <frontend-host-ip-or-cidr> to any port 8443 proto tcp
sudo ufw deny 8443/tcp
```

Frontend host:

```bash
sudo ufw allow 443/tcp
sudo ufw deny 8443/tcp
```

General rule:

- allow only required source CIDRs
- deny direct API exposure except from trusted frontend hosts
- keep SSH restricted to admin networks

---

## 8. Operations and Upgrades

### 8.1 Service operations

```bash
sudo systemctl status ecube
sudo systemctl restart ecube
sudo journalctl -u ecube -n 200 -f
```

### 8.2 Manual package upgrade

```bash
sudo tar -xzf "/tmp/ecube-package-${LATEST_TAG}.tar.gz" -C /opt/ecube --strip-components=1
sudo chown -R ecube:ecube /opt/ecube
sudo -u ecube /opt/ecube/venv/bin/pip install -e /opt/ecube
sudo systemctl restart ecube
```

Then complete setup so migrations are applied:

- UI-based flow: open `https://<frontend-hostname>/setup`

### 8.3 Uninstall / cleanup

If the host was installed using the ECUBE installer package, you can run:

```bash
sudo ./install.sh --uninstall
```

Optional database cleanup (installer-managed path):

```bash
sudo ./install.sh --uninstall --drop-database
```

> **Warning:** `--drop-database` is destructive and irreversible.
> Before dropping the database, perform and verify a backup (for example, a
> `pg_dump` backup restored successfully in a test environment).

For strictly manual teardown, remove:

- `ecube.service` systemd unit and reload systemd
- `/etc/sudoers.d/ecube-user-mgmt` sudoers policy (if installed)
- `/etc/pam.d/ecube` PAM configuration (if installed)
- `/opt/ecube` application files
- `/var/lib/ecube` runtime directory
- nginx ECUBE site config/symlinks (if present)
- ECUBE service user/group and firewall rules (if created for this deployment)
- PostgreSQL role/database only after verified backup

---

## 9. Advanced: Hosting UI with Another Web Frontend

You can host `frontend/dist` with another web server/CDN/load balancer instead of nginx.

Requirements for alternative frontend hosting:

1. Serve SPA static files with fallback to `index.html` for client routes.
2. Expose UI over HTTPS.
3. Reverse proxy `/api/` to ECUBE backend and strip `/api` prefix before forwarding.
4. Forward `Host`, `X-Forwarded-For`, and `X-Forwarded-Proto` headers.
5. For split-host backend over HTTPS, enable upstream certificate verification.

Backend requirements remain the same:

- `TRUST_PROXY_HEADERS=true`
- `API_ROOT_PATH=/api`

Validation checklist:

- UI loads at `https://<ui-host>/`
- OpenAPI works at `https://<ui-host>/api/docs`
- API schema loads from `https://<ui-host>/api/openapi.json`
- "Try it out" in Swagger uses `/api/...` URLs (not backend-internal paths)
