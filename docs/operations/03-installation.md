# ECUBE Installation Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, IT Staff  
**Document Type:** Installation Procedures

---

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Deployment Options](#deployment-options)
- [Prerequisites](#prerequisites)
  - [Hardware Requirements](#hardware-requirements)
  - [Software Requirements](#software-requirements)
- [Quick Start (bare-metal)](#quick-start-bare-metal)
- [CLI Flags Reference](#cli-flags-reference)
- [Install Modes](#install-modes)
  - [Full Install (default)](#full-install-default)
  - [Backend Only](#backend-only)
  - [Frontend Only](#frontend-only)
- [TLS Certificates](#tls-certificates)
- [Post-Install: Setup Wizard](#post-install-setup-wizard)
- [Upgrade Procedure](#upgrade-procedure)
- [Uninstall Procedure](#uninstall-procedure)
- [Docker Compose Deployment](#docker-compose-deployment)

---

## Deployment Options

| Method | When to use |
|--------|-------------|
| **Bare-metal (`install.sh`)** | Dedicated Linux host or VM; no Docker required. |
| **Docker Compose** | Dev/lab environments or container-native ops. See [05-docker-deployment.md](05-docker-deployment.md). |

---

## Prerequisites

### Hardware Requirements

**Recommended Minimum:**

- CPU: Quad-core 2.0 GHz x86-64
- RAM: 8 GB
- Storage: 256 GB SSD (for system, database, logs) — installer requires ≥ 2 GiB free
- USB: USB 3.1 hub with ≥4 ports
- Network: 1Gbps Ethernet

**Connectivity:**

- HTTPS network access to identity provider (LDAP, OIDC provider, or local authentication)
- NFS/SMB mount access to evidence source shares
- PostgreSQL 14+ database over network or localhost (the installer does **not** install PostgreSQL)

### Software Requirements

**Operating System:** Ubuntu 20.04 LTS, 22.04 LTS, or later. Debian 11 (Bullseye) and 12 (Bookworm) are also supported. On Debian, the installer sources Python 3.11 entirely from official Debian repositories: Debian 12 ships it in `main`; on Debian 11 the installer enables `bullseye-backports` (the official Debian backports mirror) and installs from there. No third-party script is downloaded or executed.

The installer will:

- Verify Debian/Ubuntu and bail out on unsupported OS.
- Offer to install `python3.11` if it is absent:
  - **Ubuntu:** adds the `deadsnakes/ppa` Ubuntu PPA (`ppa:deadsnakes/ppa`) via `add-apt-repository`.
  - **Debian 12:** installs `python3.11` directly from `main` (no extra source needed).
  - **Debian 11:** adds `bullseye-backports` (official Debian mirror, already trusted by `debian-archive-keyring`) and installs from there.
- Install `nginx` via `apt` if `--frontend-only` or full install is selected and nginx is absent.

**Required commands (must be present before running `install.sh`):**

- `curl`
- `openssl`
- `systemctl`

---

## Quick Start (bare-metal)

Download a release package from [GitHub Releases](https://github.com/t3knoid/ecube/releases), extract it, and run the installer as root:

```bash
tar -xzf ecube-package-<version>.tar.gz
cd ecube-package-<version>
sudo ./install.sh
```

The installer will:

1. Run pre-flight checks (OS, disk space, ports, Python 3.11).
2. Create the `ecube` system user.
3. Set up a Python virtual environment in `/opt/ecube/venv`.
4. Generate a self-signed TLS certificate.
5. Write `/opt/ecube/.env` with a random `SECRET_KEY` and a `DATABASE_URL` placeholder.
6. Write and start the `ecube.service` systemd unit.
7. (Full install) Configure nginx to serve the frontend and proxy `/api/` to the backend.
8. Optionally configure `ufw` firewall rules.

At the end it prints a summary with the UI URL, API URL, and service management commands.

---

## CLI Flags Reference

| Flag | Default | Description |
| ------ |--------- | ------------- |
| *(none)* | — | Install both backend and frontend |
| `--backend-only` | — | Install the backend service and systemd unit only |
| `--frontend-only` | — | Install nginx and the pre-built frontend only |
| `--install-dir DIR` | `/opt/ecube` | Root installation directory |
| `--api-port PORT` | `8443` | Port the backend (uvicorn) binds to (HTTP when behind nginx, HTTPS in backend-only mode) |
| `--ui-port PORT` | `443` | HTTPS port nginx listens on |
| `--backend-host HOST` | `127.0.0.1` | Hostname/IP of the backend; set when the backend is on a separate host |
| `--hostname HOST` | `$(hostname -f)` | Hostname/IP used as TLS certificate CN and in summary URLs |
| `--cert-validity DAYS` | `3650` | Self-signed certificate validity in days |
| `--yes` / `-y` | off | Non-interactive / unattended mode |
| `--version TAG` | *(current package)* | Download and install a specific release tag from GitHub |
| `--uninstall` | — | Remove all installed ECUBE components |
| `--dry-run` | — | Print all planned actions without executing them |

---

## Install Modes

### Full Install (default)

```bash
sudo ./install.sh
```

Installs the backend **and** the nginx-fronted frontend on the same host. nginx terminates TLS externally on port `443`; uvicorn serves plain HTTP on `127.0.0.1` (loopback only) so there is no TLS hop between nginx and uvicorn.

### Backend Only

```bash
sudo ./install.sh --backend-only
```

Installs the backend service only. uvicorn terminates TLS itself and binds to `0.0.0.0` so the API is directly reachable from the network. No nginx configuration is created. If you later run `--frontend-only` on the same host, the installer will automatically switch uvicorn to plain HTTP on `127.0.0.1` (nginx takes over TLS termination) and update `.env`.

### Frontend Only

```bash
# Backend on the same host (default):
sudo ./install.sh --frontend-only

# Backend on a separate host:
sudo ./install.sh --frontend-only --backend-host <backend-ip-or-hostname>
```

Installs nginx and deploys the pre-built frontend bundle only.

**Same-host backend (default — `--backend-host 127.0.0.1`):** When `ecube.service` is already present on this host the installer automatically:

- Patches `.env` to set `TRUST_PROXY_HEADERS=true` and `API_ROOT_PATH=/api` so FastAPI renders Swagger UI and OpenAPI schema URLs correctly behind nginx.
- Rewrites the systemd unit so uvicorn serves plain HTTP on `127.0.0.1` instead of HTTPS on `0.0.0.0`; nginx becomes the sole TLS termination point.
- Restarts `ecube.service` to apply the changes.

Two successive invocations (`--backend-only` then `--frontend-only`) on the same host are therefore fully supported without any manual reconfiguration.

**Remote backend (`--backend-host HOST`):** nginx proxies `/api/` to `https://<HOST>:<api-port>/` with `proxy_ssl_verify off`, because the remote backend may use a self-signed certificate. Only use `--backend-host` on trusted networks (VPN, private subnet, etc.). To enable certificate verification, place the backend's CA certificate at `<install-dir>/certs/backend-ca.pem` and manually update the nginx site config with `proxy_ssl_verify on; proxy_ssl_trusted_certificate <path>;` after installation.

---

## TLS Certificates

The installer generates a self-signed RSA-2048 certificate if `<install-dir>/certs/cert.pem` does not already exist:

```bash
openssl req -x509 -nodes -days <cert-validity> -newkey rsa:2048 \
  -keyout <install-dir>/certs/key.pem \
  -out   <install-dir>/certs/cert.pem \
  -subj  "/CN=<hostname>" \
  -addext "subjectAltName=IP:<ip>,DNS:<hostname>"
```

**Bring your own certificate:** Place your `cert.pem` and `key.pem` in `<install-dir>/certs/` before running the installer. The installer skips generation if those files already exist.

---

## Post-Install: Setup Wizard

After installation, open the setup wizard in a browser:

```text
https://<hostname>:<ui-port>/setup
```

The wizard will:

1. Test and provision the PostgreSQL database connection.
2. Run Alembic migrations.
3. Create the initial admin user.

> **Note:** `<install-dir>/.env` contains `DATABASE_URL=postgresql://ecube:CHANGE_ME@localhost/ecube` as a placeholder. Update it with your real PostgreSQL credentials **before** completing the setup wizard, or use the wizard's database provisioning form which overwrites it automatically.

The `ecube-setup` CLI (`/opt/ecube/venv/bin/ecube-setup`) is an advanced alternative for headless environments. The setup wizard is the recommended path.

---

## Upgrade Procedure

1. Download the new release package.
2. Extract it and run the installer:

   ```bash
   tar -xzf ecube-package-<new-version>.tar.gz
   cd ecube-package-<new-version>
   sudo ./install.sh
   ```

3. Application files (`app/`, `alembic/`, etc.) are overwritten unconditionally. `.env` is **never overwritten** — existing operator secrets are preserved.
4. The service is always restarted after an upgrade.
5. **Run database migrations** after the service restarts — open the setup wizard in a browser, or run `alembic upgrade head` directly:

   ```bash
   sudo -u ecube /opt/ecube/venv/bin/alembic --config /opt/ecube/alembic.ini upgrade head
   ```

---

## Uninstall Procedure

```bash
sudo ./install.sh --uninstall
```

This will:

1. Stop and disable `ecube.service`.
2. Remove the nginx ecube site and reload nginx.
3. Prompt to remove `<install-dir>` and `/var/lib/ecube`.
4. Prompt to remove the `ecube` system user and group.
5. Optionally remove the deadsnakes PPA entry (Ubuntu only) if it was added by the installer.

Use `--yes` to skip all confirmation prompts.

---

## Docker Compose Deployment

See [05-docker-deployment.md](05-docker-deployment.md) for Docker-based setup.
