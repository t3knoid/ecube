# ECUBE Installation Guide

**Version:** 1.0  
**Last Updated:** April 2026  
**Audience:** Systems Administrators, IT Staff

---

## Table of Contents

1. [Deployment Options](#deployment-options)
2. [Prerequisites](#prerequisites)
3. [Quick Start (bare-metal)](#quick-start-bare-metal)
4. [CLI Flags Reference](#cli-flags-reference)
5. [Install Modes](#install-modes)
6. [Prepare PostgreSQL](#prepare-postgresql)
7. [Database Configuration](#database-configuration)
8. [TLS Certificates](#tls-certificates)
9. [Post-Install: Setup Wizard](#post-install-setup-wizard)
10. [Upgrade Procedure](#upgrade-procedure)
11. [Uninstall Procedure](#uninstall-procedure)

---
- [Docker Compose Deployment](#docker-compose-deployment)

---

## Deployment Options

| Method | When to use |
|--------|-------------|
| **Bare-metal (`install.sh`)** | Dedicated Linux host or VM; no Docker required. |
| **Docker Compose** | Dev/lab environments or container-native ops. See [03-docker-deployment.md](03-docker-deployment.md). |

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

For how CI generates release packages and the installer artifact contract (required package names and contents), see [CI Build and Installer Artifact Contract](../development/03-ci-build-and-installer-artifacts.md).

```bash
tar -xzf ecube-package-<version>.tar.gz
cd ecube-package-<version>
sudo ./install.sh
```

The installer will:

1. Run pre-flight checks (OS, disk space, ports, Python 3.11).
2. Create the `ecube` system user and add it to required host groups (`plugdev`, `dialout`, and `shadow` when present).
3. Install `/etc/sudoers.d/ecube-user-mgmt` with narrowly scoped `NOPASSWD` rules so setup endpoints can create required OS groups/users without interactive sudo prompts.
4. Install `/etc/pam.d/ecube` PAM configuration for local and domain user authentication (detects SSSD at install time and creates appropriate config variant).
5. Set up a Python virtual environment in `<install-dir>/venv`.
6. Generate a self-signed TLS certificate.
7. Write `<install-dir>/.env` with a random `SECRET_KEY`, `SETUP_DEFAULT_ADMIN_USERNAME=ecubeadmin`, and runtime defaults. `DATABASE_URL` is left empty and configured later via the setup wizard.
8. Write and start the `ecube.service` systemd unit.
9. (Full install) Configure nginx to serve the frontend and proxy `/api/` to the backend.
10. Optionally configure `ufw` firewall rules.

At the end it prints a summary with the UI URL, API URL, and service management commands.
When PostgreSQL is available locally, the installer also creates (or updates)
a PostgreSQL superuser for setup-wizard database provisioning and prints those
credentials in the summary.

**Immediate next step:** open the ECUBE web UI and complete setup:

- Full install / frontend available: `https://<hostname>:<ui-port>/setup`
- Backend-only install (no UI on this host): complete setup from a frontend-enabled ECUBE deployment URL (see the Operations guides for split-host deployment)

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
| `--pg-superuser-name NAME` | `ecubeadmin` | PostgreSQL superuser name to create/update during install for use in setup wizard provisioning. Skips prompt when supplied. |
| `--pg-superuser-pass PASS` | — | PostgreSQL superuser password to set during install. Skips prompt when supplied. Must be non-empty and contain no whitespace. |
| `--hostname HOST` | `$(hostname -f)` | Hostname/IP used as TLS certificate CN and in summary URLs |
| `--cert-validity DAYS` | `730` | Self-signed certificate validity in days |
| `--yes` / `-y` | off | Non-interactive / unattended mode |
| `--version TAG` | *(current package)* | Download and install a specific release tag from GitHub. Must match `v<major>.<minor>.<patch>` exactly (e.g. `v0.2.0`). Pre-release suffixes, build metadata, and tags without a leading `v` are not accepted. |
| `--uninstall` | — | Remove all installed ECUBE components |
| `--drop-database` | — | With `--uninstall`, also attempt to drop the configured application database resolved from `DATABASE_URL` in `<install-dir>/.env`. Requires sufficient PostgreSQL privileges. |
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

Installs the backend service only. uvicorn terminates TLS itself and binds to `0.0.0.0` so the API is directly reachable from the network. No nginx configuration is created. If you later run `--frontend-only` on the same host, the installer will automatically switch uvicorn to plain HTTP on `127.0.0.1` (nginx takes over TLS termination), patch `.env`, and preserve the existing backend API port unless `--api-port` is passed explicitly.

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

If `--frontend-only` is used with the default `--backend-host 127.0.0.1`, but no local backend service exists/listens on `--api-port`, the installer fails fast with guidance to either install the backend first or pass `--backend-host <remote-host>`.

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
> `API_ROOT_PATH=/api` tells FastAPI that the application is mounted behind nginx at `/api`, so Swagger UI (`/api/docs`), the OpenAPI schema (`/api/openapi.json`), and all "Try it out" request URLs are generated with the correct prefix. `TRUST_PROXY_HEADERS=true` controls whether the backend trusts proxy headers (such as `X-Forwarded-For`) from nginx when determining the client IP address, which affects audit logging and any IP-aware features. After editing `.env`, restart the backend service:
>
> ```bash
> sudo systemctl restart ecube.service
> ```

---

## Prepare PostgreSQL

Before running the setup wizard, ensure PostgreSQL is installed, running, and
reachable from the ECUBE host.

In current installer flow, `install.sh` creates (or updates) a PostgreSQL
superuser for setup-wizard provisioning and prints its credentials in the
install summary. The setup wizard then uses those admin credentials to:

1. Create/update the ECUBE application role.
2. Create the ECUBE application database.
3. Run Alembic migrations.

You can pre-seed the installer and avoid interactive prompts:

```bash
sudo ./install.sh \
  --pg-superuser-name ecubeadmin \
  --pg-superuser-pass '<strong-password>'
```

If local PostgreSQL access via `sudo -u postgres psql` is not available,
create a PostgreSQL superuser manually and enter those credentials in the
setup wizard's database provisioning screen.

---

## Database Configuration

Database configuration is performed in the web setup wizard, not by `install.sh`.

During installation:

1. `.env` is created (or preserved) with `DATABASE_URL` left untouched by the installer.
2. `ecube.service` starts without installer-managed database credential prompts.
3. The setup wizard (`/setup`) is the required next step to configure database
  connection/provisioning and apply schema migrations.

Notes:

1. On first install, open `https://<hostname>:<ui-port>/setup` and complete the
  database provisioning/configuration step.
2. On upgrades/re-runs, the installer preserves existing `.env`; it does not
  rotate or overwrite `DATABASE_URL`.
3. Only `--pg-superuser-name` and `--pg-superuser-pass` configure
  database-related installer behavior.

---

## TLS Certificates

The installer generates a self-signed RSA-2048 certificate if `<install-dir>/certs/cert.pem` does not already exist:

```bash
openssl req -x509 -nodes -days <cert-validity> -newkey rsa:2048 \
  -keyout <install-dir>/certs/key.pem \
  -out   <install-dir>/certs/cert.pem \
  -subj  "/CN=<hostname-or-ip>" \
  -addext "subjectAltName=<computed-san-list>"
```

`<computed-san-list>` is built conditionally by the installer:

- If `--hostname` (or detected host) is a **DNS name**: `DNS:<hostname>,IP:<host-ip>`
- If `--hostname` is an **IP literal** (IPv4 or IPv6): `IP:<hostname-ip>`
- If `--hostname` is an IP literal and differs from detected `<host-ip>`: `IP:<hostname-ip>,IP:<host-ip>`

Notes:

- IPv6 passed in bracketed form (for example `[2001:db8::10]`) is normalized to the bare address (`2001:db8::10`) for CN/SAN generation.
- The installer does not emit `DNS:` SAN entries for IP literals (especially important for IPv6), because values containing `:` are not valid DNS SAN names.

**Bring your own certificate:** Place your `cert.pem` and `key.pem` in `<install-dir>/certs/` before running the installer. The installer skips certificate generation if those files already exist, but it still reconciles file mode/ownership for the selected topology:

- nginx topology (full install / `--frontend-only`): `key.pem` remains `root:root` with mode `600`; `cert.pem` is `ecube:ecube` with mode `644`
- backend-only topology: `key.pem` and `cert.pem` are `ecube:ecube` (`600` for key, `644` for cert)

When certificate generation is attempted, OpenSSL stderr is appended to the installer log (`/var/log/ecube-install.log`, or the configured fallback), so generation failures are diagnosable.

---

## Post-Install: Setup Wizard

After installation, open the setup wizard in a browser (this is the required next step before normal use):

```text
https://<hostname>:<ui-port>/setup
```

The wizard will:

1. Connect to PostgreSQL with admin credentials.
2. Provision the ECUBE role/database and run migrations.
3. Create the initial admin user.

> **Troubleshooting (admin step skipped):** If setup appears to skip admin creation or briefly flashes an error, verify OS account state and setup state:
>
> ```bash
> getent passwd <admin-username> || echo "OS user missing"
> sudo -u postgres psql -d postgres -c "SELECT username, role FROM user_roles WHERE role='admin';"
> sudo -u postgres psql -d postgres -c "SELECT * FROM system_initialization;"
> ```
>
> Current ECUBE builds auto-recover this mismatch: if an admin role exists in the DB but the OS account is missing, setup remains available and recreates the OS admin account on the next `/setup/initialize` run.

> **Note:** `DATABASE_URL` in `<install-dir>/.env` is configured by the setup wizard (not by `install.sh`). If you need to point the service at a different database later, use setup/admin workflows or edit `.env` and restart `ecube.service`.

---

## Upgrade Procedure

1. Download the new release package.
2. Extract it and run the installer:

   ```bash
   tar -xzf ecube-package-<new-version>.tar.gz
   cd ecube-package-<new-version>
   sudo ./install.sh
   ```

   The installer automatically stops `ecube.service` (and `nginx` for full installs) before running pre-flight checks, so re-running on an active host does not produce a "port already in use" error. Services are restarted at the end of the run.

3. Application files (`app/`, `alembic/`, etc.) are **overwritten where present** — the installer copies a fixed list of items from the new release onto the existing installation. Files or directories that existed in the previous release but are no longer shipped are **not removed**; stale content may remain under `INSTALL_DIR` until manually cleaned up or a full uninstall/reinstall is performed. `.env` is **never overwritten** — existing operator secrets are preserved.
4. The service is always restarted after an upgrade.
5. Complete setup after upgrade using the setup wizard (`/setup`) so migrations are applied.

---

## Uninstall Procedure

```bash
sudo /opt/ecube/install.sh --uninstall
```

Optional database cleanup during uninstall:

```bash
sudo /opt/ecube/install.sh --uninstall --drop-database
```

If ECUBE was installed with a custom `--install-dir`, run the installer from that location instead (for example, `sudo /srv/ecube/install.sh --uninstall`).

> **Warning:** Database drop is destructive and irreversible.
> Before using `--drop-database`, create and verify a backup (for example,
> a `pg_dump` backup that has been tested with a restore run).

This will:

1. Stop and disable `ecube*.service` units discovered on the host.
2. Remove the nginx ecube site and reload nginx.
3. Remove `<install-dir>` and `/var/lib/ecube`.
4. Remove the `ecube` system user/group and the `ecube-www` bridge group (if present).
5. Remove `/etc/sudoers.d/ecube-user-mgmt`.
6. Remove `/etc/pam.d/ecube` PAM configuration.
7. Remove ECUBE-related ufw rules and installer log (if present).
8. Remove the deadsnakes PPA entry if detected.
9. When `--drop-database` is provided, attempt to terminate active sessions
  and drop the configured application database (best-effort).

Use `--yes` to auto-accept the initial uninstall confirmation prompt.
