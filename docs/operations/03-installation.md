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
- [Database Configuration](#database-configuration)
  - [Interactive mode (default)](#interactive-mode-default)
  - [Unattended mode (`--yes`)](#unattended-mode---yes)
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
3. Set up a Python virtual environment in `<install-dir>/venv`.
4. Generate a self-signed TLS certificate.
5. Prompt for PostgreSQL connection details (host, port, database name, username, password) and verify TCP reachability. If `psql` is present it also tests the credentials against the database; if `psql` is absent this step is skipped and no error is raised. The installer never creates the PostgreSQL database or role — these must exist before running the installer for the service to function correctly.
6. Write `<install-dir>/.env` with a random `SECRET_KEY` and the assembled `DATABASE_URL`.
7. Write and start the `ecube.service` systemd unit.
8. (Full install) Configure nginx to serve the frontend and proxy `/api/` to the backend.
9. Optionally configure `ufw` firewall rules.

At the end it prints a summary with the UI URL, API URL, and service management commands.

---

## CLI Flags Reference

| Flag | Default | Description |
| ------ | --------- | ------------- |
| *(none)* | — | Install both backend and frontend |
| `--backend-only` | — | Install the backend service and systemd unit only |
| `--frontend-only` | — | Install nginx and the pre-built frontend only |
| `--install-dir DIR` | `/opt/ecube` | Root installation directory |
| `--api-port PORT` | `8443` | Port the backend (uvicorn) binds to (HTTP when behind nginx, HTTPS in backend-only mode) |
| `--ui-port PORT` | `443` | HTTPS port nginx listens on |
| `--backend-host HOST` | `127.0.0.1` | Hostname/IP of the backend. The default (`127.0.0.1`) assumes the backend runs on the same host and is only valid for same-host deployments. **Must be specified when using `--frontend-only` with a backend on a separate host.** |
| `--allow-insecure-backend` | *(default)* | Explicitly select TLS verification disabled (`proxy_ssl_verify off`) when proxying to a remote backend. This is already the default behaviour; the flag is provided for clarity in scripts that also set `--secure-backend` in some code paths. A warning is always printed when verification is off. |
| `--secure-backend` | — | Enable TLS certificate verification against the OS trust store (`proxy_ssl_verify on`). Use when the remote backend has a CA-signed cert already trusted by the system and no custom CA file is needed. Mutually exclusive with `--allow-insecure-backend`. |
| `--backend-ca-file FILE` | — | Path to a PEM CA certificate used to verify the remote backend's TLS certificate (`proxy_ssl_trusted_certificate`). Use when the backend has a private CA-signed cert that is not in the system trust store. Implies `proxy_ssl_verify on`. |
| `--db-host HOST` | *(prompted)* | **Backend installs only.** PostgreSQL server hostname or IP address. Must be non-empty and contain only DNS/IP-safe characters. Required in `--yes` mode. Ignored for `--frontend-only`. |
| `--db-port PORT` | `5432` | **Backend installs only.** PostgreSQL server port. Must be a valid integer between 1 and 65535. Ignored for `--frontend-only`. |
| `--db-name NAME` | `ecube` | **Backend installs only.** Name of the PostgreSQL database. Must contain only alphanumerics and underscores. Ignored for `--frontend-only`. |
| `--db-user USER` | *(prompted)* | **Backend installs only.** PostgreSQL username. Must be non-empty and must contain only alphanumerics and underscores. Required in `--yes` mode. Ignored for `--frontend-only`. |
| `--db-password PASS` | *(prompted)* | **Backend installs only.** PostgreSQL password. Must be non-empty and must not contain whitespace. Required in `--yes` mode. All characters outside the RFC 3986 unreserved set are percent-encoded automatically when building `DATABASE_URL`. Ignored for `--frontend-only`. |
| `--hostname HOST` | `$(hostname -f)` | Hostname/IP used as TLS certificate CN and in summary URLs |
| `--cert-validity DAYS` | `730` | Self-signed certificate validity in days |
| `--yes` / `-y` | off | Non-interactive / unattended mode |
| `--version TAG` | *(current package)* | Download and install a specific release tag from GitHub. Must match `v<major>.<minor>.<patch>` exactly (e.g. `v0.2.0`). Pre-release suffixes, build metadata, and tags without a leading `v` are not accepted. |
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

# Backend on a separate host (--backend-host is required):
sudo ./install.sh --frontend-only --backend-host <backend-ip-or-hostname>
```

Installs nginx and deploys the pre-built frontend bundle only.

> **`--backend-host` requirement:** The default value (`127.0.0.1`) is only valid when the backend is running on the same host. When the backend is on a separate machine, `--backend-host` **must** be specified — omitting it will cause nginx to proxy to `127.0.0.1`, which will not reach the remote backend.

**Same-host backend (default — `--backend-host 127.0.0.1`):** When `ecube.service` is already present on this host the installer automatically:

- Patches `.env` to set `TRUST_PROXY_HEADERS=true` and `API_ROOT_PATH=/api` so FastAPI renders Swagger UI and OpenAPI schema URLs correctly behind nginx.
- Rewrites the systemd unit so uvicorn serves plain HTTP on `127.0.0.1` instead of HTTPS on `0.0.0.0`; nginx becomes the sole TLS termination point.
- Restarts `ecube.service` to apply the changes.

Two successive invocations (`--backend-only` then `--frontend-only`) on the same host are therefore fully supported without any manual reconfiguration.

**Remote backend (`--backend-host HOST`):** nginx proxies `/api/` to `https://<HOST>:<api-port>/`, stripping the `/api` prefix before requests reach FastAPI. TLS verification is **disabled by default** (`proxy_ssl_verify off`) for quick bring-up — the installer prints a warning when this is in effect. Three modes are supported:

| Scenario | Command |
|----------|---------|
| Quick start / self-signed cert (default, warning shown) | `sudo ./install.sh --frontend-only --backend-host <host>` |
| Backend has a private/internal CA cert | `sudo ./install.sh --frontend-only --backend-host <host> --backend-ca-file /path/to/ca.pem` |
| Backend has a CA-signed cert trusted by the OS | `sudo ./install.sh --frontend-only --backend-host <host> --secure-backend` |

Only leave TLS verification disabled (the default) on trusted networks (VPN, private subnet, etc.). Pass `--secure-backend` or `--backend-ca-file` to enable certificate verification in any other environment.

> **Remote backend: required `.env` settings on the backend host.**  
> Unlike a same-host install (where the installer patches `.env` automatically), when the backend runs on a separate machine you must manually set the following in the backend's `.env` before or after running `--backend-only`:
>
> ```env
> TRUST_PROXY_HEADERS=true
> API_ROOT_PATH=/api
> ```
>
> Without these settings FastAPI does not know it is mounted at `/api`, so Swagger UI (`/api/docs`), the OpenAPI schema (`/api/openapi.json`), and all "Try it out" request URLs will be incorrect. `TRUST_PROXY_HEADERS=true` is needed so FastAPI reconstructs the correct `https://` scheme and host from the `X-Forwarded-*` headers that nginx injects. After editing `.env`, restart the backend service:
>
> ```bash
> sudo systemctl restart ecube.service
> ```

---

## Database Configuration

> **Applies to:** full install (default) and `--backend-only`. The PostgreSQL prompts, TCP reachability check, and `DATABASE_URL` assembly are **skipped entirely** when running `--frontend-only` — the frontend installer never touches database credentials or `DATABASE_URL`.
>
> **Note on `.env` patching with `--frontend-only`:** When adding a frontend to an existing same-host backend-only install, the installer *does* patch `.env` — but only to set `TRUST_PROXY_HEADERS=true` and `API_ROOT_PATH=/api` so FastAPI serves correct URLs behind nginx. No database settings are changed. See [Frontend Only](#frontend-only) for details.

The installer prompts for the PostgreSQL connection details required to assemble `DATABASE_URL`. You can supply any or all values via CLI flags to reduce or eliminate prompting.

**Re-runs and upgrades:** If `<install-dir>/.env` already exists and **no** `--db-*` flag is supplied, the installer skips database credential collection entirely and preserves the existing `DATABASE_URL` unchanged. This makes idempotent re-runs and `--yes` upgrades safe — `--db-host`, `--db-user`, and `--db-password` are only required on first install or when explicitly rotating credentials.

To update the database connection on an existing install, supply the new values via `--db-*` flags. The installer will collect and validate the credentials then patch only the `DATABASE_URL` line in `.env`, leaving `SECRET_KEY` and all other settings untouched.

### Interactive mode (default)

When `--db-host`, `--db-user`, or `--db-password` are omitted the installer prompts for them:

```
── PostgreSQL database configuration ──────────────────────────
PostgreSQL host (hostname or IP): db.example.com
PostgreSQL port [5432]:
PostgreSQL database name [ecube]:
PostgreSQL username: ecube_app
PostgreSQL password: ****
```

Each value is validated as it is entered. The installer then:

1. **TCP reachability check** — uses `nc -z` (or `/dev/tcp` as a fallback) to confirm the port is reachable. The install aborts if the check fails.
2. **Credential verification** — if `psql` is found on `PATH`, it runs `SELECT 1` against the database to verify the username and password. The install aborts if authentication fails.
3. Percent-encodes all characters outside the RFC 3986 unreserved set (`A–Z a–z 0–9 - _ . ~`) in the password before embedding it in the connection string. This ensures any valid PostgreSQL password produces a valid connection URL regardless of which reserved characters it contains.
4. Writes `DATABASE_URL=postgresql://<user>:<encoded-pass>@<host>:<port>/<dbname>` into `.env`.

### Unattended mode (`--yes`)

On a **first install**, three flags without defaults become **required** when `--yes` is passed: `--db-host`, `--db-user`, and `--db-password`. `--db-port` and `--db-name` are optional — their defaults (`5432` and `ecube`) are used if omitted:

```bash
sudo ./install.sh --yes \
  --db-host db.example.com \
  --db-port 5432 \
  --db-name ecube \
  --db-user ecube_app \
  --db-password 'S3cret!'
```

On a **re-run or upgrade** where `<install-dir>/.env` already exists, `--db-host`, `--db-user`, and `--db-password` are **not** required — the existing `DATABASE_URL` is preserved automatically. Supply them only if you want to rotate the database credentials:

```bash
# Upgrade (no DB flags needed — existing credentials are kept):
sudo ./install.sh --yes

# Upgrade and rotate DB credentials:
sudo ./install.sh --yes \
  --db-host new-db.example.com \
  --db-user new_user \
  --db-password 'NewP@ss!'
```

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

1. Run Alembic migrations.
2. Create the initial admin user.

> **Note:** `DATABASE_URL` in `<install-dir>/.env` is written with the credentials you supplied during installation. If you need to point the service at a different database later, edit `.env` and restart `ecube.service`.

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

3. Application files (`app/`, `alembic/`, etc.) are **overwritten where present** — the installer copies a fixed list of items from the new release onto the existing installation. Files or directories that existed in the previous release but are no longer shipped are **not removed**; stale content may remain under `INSTALL_DIR` until manually cleaned up or a full uninstall/reinstall is performed. `.env` is **never overwritten** — existing operator secrets are preserved.
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
