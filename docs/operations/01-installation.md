# ECUBE Installation Guide

| Field | Value |
|---|---|
| Title | ECUBE Installation Guide |
| Purpose | Guides administrators through deploying ECUBE using the automated installer or Docker, including prerequisites and environment validation. |
| Updated on | 04/16/26 |
| Audience | Systems administrators, IT staff. |

## Table of Contents

1. [Deployment Options](#deployment-options)
2. [Deployment Topologies](#deployment-topologies)
3. [Prerequisites](#prerequisites)
4. [Quick Start (native)](#quick-start-native)
5. [CLI Flags Reference](#cli-flags-reference)
6. [Install Modes](#install-modes)
7. [Prepare PostgreSQL](#prepare-postgresql)
8. [Database Configuration](#database-configuration)
9. [TLS Certificates](#tls-certificates)
10. [Post-Install: Setup Wizard](#post-install-setup-wizard)
11. [Upgrade Procedure](#upgrade-procedure)
12. [Uninstall Procedure](#uninstall-procedure)

---

## Deployment Options

| Method | When to use |
|--------|-------------|
| **Automated Installer (`install.sh`)** | Recommended for most deployments on a dedicated Linux host or VM. |
| **Manual installation** | Advanced administrators who want full control of the installation and host provisioning steps instead of using the automated installer. See [02-manual-installation.md](02-manual-installation.md). |
| **Docker Compose** | Dev/lab environments or container-native ops. See [03-docker-deployment.md](03-docker-deployment.md). |

---

## Deployment Topologies

### Topology A: Single Host (recommended for small/medium installs)

One host runs:

- PostgreSQL
- ECUBE backend + frontend (`ecube.service`)

Behavior:

- Uvicorn terminates TLS and serves both the API and the SPA frontend
- Single process, single port (default `8443`)
- Frontend sends API calls to `/api/...`; the application middleware strips the prefix before routing

### Topology B: Enterprise Split Host

Two dedicated hosts:

- DB host: PostgreSQL only
- Backend host: ECUBE backend + frontend (`ecube.service`)

Behavior:

- Backend host serves frontend and API on a single port
- DB host is isolated from client networks

For detailed manual deployment steps for each topology, see [02-manual-installation.md](02-manual-installation.md).

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

**ECUBE runtime packages for native/manual hosts:**

The ECUBE service depends on several non-standard OS packages for USB formatting, USB discovery, and NFS/SMB evidence mounts. These packages are provisioned by the Ansible deployment path and mirrored by the container image runtime dependencies, but operators preparing a bare-metal or minimal VM host should ensure they are installed before running the native installer or starting the service manually.

| Package | Purpose |
|---|---|
| `exfatprogs` | Provides `mkfs.exfat` for formatting evidence drives as exFAT. |
| `nfs-common` | NFS client utilities for mounting evidence shares. |
| `cifs-utils` | SMB/CIFS client utilities for mounting evidence shares. |
| `usbutils` | Provides `lsusb` and USB enumeration support. |
| `util-linux` | Provides core block and session utilities such as `lsblk`, `blkid`, and `runuser`. |

On minimal Ubuntu installs, also install `linux-modules-extra-$(uname -r)` so the native exFAT kernel module is available at runtime. On Ubuntu 20.04 hosts using the 5.4 kernel series, install `exfat-fuse` instead of the native module package.

**Required commands (must be present before running `install.sh`):**

- `curl`
- `openssl`
- `systemctl`

---

## Quick Start (native)

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
3. Install `/etc/sudoers.d/ecube-user-mgmt` with narrowly scoped `NOPASSWD` rules for setup OS user/group management, mount/unmount operations, and selected drive filesystem commands.
4. Install `/etc/pam.d/ecube` PAM configuration for local and domain user authentication (detects SSSD at install time and installs an SSSD-enabled or local-only variant accordingly).
5. Set up a Python virtual environment in `<install-dir>/venv`.
6. Generate a self-signed TLS certificate (skipped with `--no-tls`).
7. Write `<install-dir>/.env` with a random `SECRET_KEY`, empty `SETUP_DEFAULT_ADMIN_USERNAME` (populated later by the superuser creation step), and runtime defaults. `DATABASE_URL` is left empty and configured later via the setup wizard.
8. Write and start the `ecube.service` systemd unit.
9. Deploy the pre-built frontend to `<install-dir>/www` so FastAPI serves the SPA directly (no separate web server required).
10. Optionally configure `ufw` firewall rules.

At the end it prints a summary with the UI URL, API URL, and service management commands.

ECUBE supports domain-backed user login through the host PAM stack when SSSD is installed and configured on the host. In that case, the installer writes an SSSD-enabled PAM configuration so both local accounts and domain accounts can authenticate to ECUBE.

When PostgreSQL is available locally, the installer also creates (or updates) a PostgreSQL superuser for setup-wizard database provisioning. By default it uses the same credentials as Docker Compose (`POSTGRES_USER`/`POSTGRES_PASSWORD`, falling back to `ecube`/`ecube`). Override with `--pg-superuser-name` and `--pg-superuser-pass`.

**Immediate next step:** open the ECUBE web UI and complete setup:

- HTTPS (default): `https://<hostname>:<api-port>/setup`
- HTTP (`--no-tls`): `http://<hostname>:<api-port>/setup`

---

## CLI Flags Reference

| Flag | Default | Description |
| ------ | --------- | ------------- |
| `--install-dir DIR` | `/opt/ecube` | Root installation directory |
| `--api-port PORT` | `8443` | Port for the service (default: `8443`, or `80` with `--no-tls`) |
| `--no-tls` | — | Disable TLS entirely (plain HTTP, default port 80). Suitable for lab/testing only. |
| `--pg-superuser-name NAME` | `POSTGRES_USER` or `ecube` | Name for the PostgreSQL superuser created during installation. |
| `--pg-superuser-pass PASS` | `POSTGRES_PASSWORD` or `ecube` | Password for the PostgreSQL superuser. |
| `--hostname HOST` | `$(hostname -f)` | Hostname/IP for TLS cert CN |
| `--cert-validity DAYS` | `730` | Self-signed cert validity |
| `--yes`, `-y` | off | Non-interactive / unattended mode. Firewall rules are skipped unless `--firewall-cidr` is provided. |
| `--firewall-cidr CIDR` | *(skip)* | Source CIDR to allow through ufw for the API port (e.g. `192.168.1.0/24`). In `--yes` mode, if omitted the firewall rule is **skipped** (safe default). Use `any` to explicitly open to all sources. |
| `--version TAG` | *(current package)* | Download and install a specific GitHub release tag. Must be exact format: v<major>.<minor>.<patch> (e.g. v0.2.0). Pre-releases, build metadata, and tags without a leading v are not supported. |
| `--uninstall` | — | Remove ECUBE from this host |
| `--drop-database` | — | With --uninstall, also drop the configured application database (best-effort; requires sufficient DB privileges) |
| `--dry-run` | — | Print all actions without executing them |
| `-h`, `--help` | — | Show this help message |

---

## Install Modes

### Default Install (HTTPS)

```bash
sudo ./install.sh
```

Installs the backend service, deploys the pre-built frontend, and starts `ecube.service`. Uvicorn terminates TLS itself and binds to `0.0.0.0` on port `8443` (configurable with `--api-port`). FastAPI serves both the API and the SPA frontend from a single process — no separate web server is required.

### Plain HTTP Install (`--no-tls`)

```bash
sudo ./install.sh --no-tls
```

Same as the default install but skips TLS certificate generation. Uvicorn listens on port `80` (configurable with `--api-port`). When the service port is below 1024, the systemd unit is configured with `AmbientCapabilities=CAP_NET_BIND_SERVICE` so the unprivileged `ecube` user can bind to it.

Use `--no-tls` only for lab/testing or when TLS termination is handled by an external load balancer.

---

## Prepare PostgreSQL

Before running the setup wizard, ensure PostgreSQL is installed, running, and
reachable from the ECUBE host.

In current installer flow, `install.sh` creates (or updates) a PostgreSQL
superuser for setup-wizard provisioning. By default this uses `POSTGRES_USER`/`POSTGRES_PASSWORD` (falling back to `ecube`/`ecube`) — the same defaulting cascade as Docker Compose. The credentials are written to `.env` so the setup wizard can auto-fill them. The setup wizard then uses those admin credentials to:

1. Create/update the ECUBE application role.
2. Create the ECUBE application database.
3. Run Alembic migrations.

You can override the defaults with CLI flags:

```bash
sudo ./install.sh \
  --pg-superuser-name myadmin \
  --pg-superuser-pass '<strong-password>' \
  --firewall-cidr 192.168.1.0/24
```

For fully unattended installs, add `--yes`.  Without `--firewall-cidr`, the firewall step is safely skipped in `--yes` mode:

```bash
sudo ./install.sh --yes \
  --firewall-cidr 10.0.0.0/8
```

If local PostgreSQL access via `sudo -u postgres psql` is not available,
create a PostgreSQL superuser (or a role with `CREATEDB` privilege) manually
and enter those credentials in the setup wizard's database provisioning screen.

---

## Database Configuration

Database configuration is performed in the web setup wizard, not by `install.sh`.

During installation:

1. `.env` is created (or preserved) with `DATABASE_URL` left untouched by the installer.
2. `ecube.service` starts without installer-managed database credential prompts.
3. The setup wizard (`/setup`) is the required next step to configure database
  connection/provisioning and apply schema migrations.

Notes:

1. On first install, open `https://<hostname>:<api-port>/setup` (or `http://` for `--no-tls`) and complete the database provisioning/configuration step.
2. On upgrades/re-runs, the installer preserves existing `.env`; it does not
  rotate or overwrite `DATABASE_URL`.
3. During normal install flow, only `--pg-superuser-name` and `--pg-superuser-pass` configure
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

**Bring your own certificate:** Place your `cert.pem` and `key.pem` in `<install-dir>/certs/` before running the installer. The installer skips certificate generation if those files already exist. Certificate files are owned by `ecube:ecube` (`600` for key, `644` for cert) since uvicorn terminates TLS directly.

When certificate generation is attempted, OpenSSL stderr is appended to the installer log (`/var/log/ecube-install.log`, or the configured fallback), so generation failures are diagnosable.

---

## Post-Install: Setup Wizard

After installation, open the setup wizard in a browser (this is the required next step before normal use):

```text
https://<hostname>:<api-port>/setup
```

For `--no-tls` installs, use `http://` instead.

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

   The installer automatically stops `ecube.service` before running pre-flight checks, so re-running on an active host does not produce a "port already in use" error. The service is restarted at the end of the run.

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

Note: when `--drop-database` targets a remote PostgreSQL instance, superuser-role cleanup may require credentials for `SETUP_DEFAULT_ADMIN_USERNAME` via `.pgpass` or `PGPASSWORD`.

If ECUBE was installed with a custom `--install-dir`, run the installer from that location instead (for example, `sudo /srv/ecube/install.sh --uninstall`).

> **Warning:** Database drop is destructive and irreversible.
> Before using `--drop-database`, create and verify a backup (for example,
> a `pg_dump` backup that has been tested with a restore run).

This will:

1. Stop and disable `ecube*.service` units discovered on the host.
2. Remove `<install-dir>` and `/var/lib/ecube`.
3. Remove the `ecube` system user/group (and the legacy `ecube-www` group if present).
4. Remove `/etc/sudoers.d/ecube-user-mgmt`.
5. Remove `/etc/pam.d/ecube` PAM configuration.
6. Remove ECUBE-related ufw rules and installer log (if present).
7. Remove the deadsnakes PPA entry if detected.
8. Remove any legacy nginx ecube site configuration (if present from a previous version).
9. When `--drop-database` is provided, attempt to terminate active sessions and drop the configured application database (best-effort).

Use `--yes` to auto-accept the initial uninstall confirmation prompt.

## References

- [docs/operations/02-manual-installation.md](02-manual-installation.md)
- [docs/operations/03-docker-deployment.md](03-docker-deployment.md)
- [docs/operations/04-configuration-reference.md](04-configuration-reference.md)
