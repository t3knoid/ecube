# ECUBE Docker Deployment

| Field | Value |
|---|---|
| Title | ECUBE Docker Deployment |
| Purpose | Describes how to deploy ECUBE with Docker Compose, including container configuration and environment variable setup. |
| Updated on | 04/08/26 |
| Audience | Systems administrators, IT staff. |

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Quick Start](#quick-start)
4. [Using Pre-built Release Images](#using-pre-built-release-images)
5. [Configuration](#configuration)
6. [Setup Wizard Auto-Detection](#setup-wizard-auto-detection)
7. [Starting and Stopping](#starting-and-stopping)
8. [Logs](#logs)
9. [Common Docker Commands](#common-docker-commands)
10. [Reference](#reference)

---

## Overview

Docker Compose is the recommended method for quick testing and evaluation.
For production native deployments, see [02-manual-installation.md](02-manual-installation.md).

In the Compose deployment, only the HTTPS port is published to the host by default. The `ecube-app` container serves both the API and the Vue SPA with built-in TLS:

- Web UI: `https://localhost:${UI_PORT:-8443}/`
- Setup wizard: `https://localhost:${UI_PORT:-8443}/setup`
- API endpoints: `https://localhost:${UI_PORT:-8443}/api/...`
- Swagger UI: `https://localhost:${UI_PORT:-8443}/docs`
- OpenAPI schema: `https://localhost:${UI_PORT:-8443}/openapi.json`

For Docker-specific USB passthrough setup and detailed architecture, see
[12-runtime-environment-and-usb-visibility.md](../design/12-runtime-environment-and-usb-visibility.md).

---

## Prerequisites

### Installing Docker Engine from the Official Repository

Ubuntu's default `docker.io` package may be outdated. For the latest Docker Engine with Compose plugin support, install from Docker's official APT repository:

```bash
# Remove older distro-packaged Docker (if present)
sudo apt remove docker.io docker-compose

# Install prerequisites
sudo apt update
sudo apt install ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Add the Docker APT repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine, CLI, and Compose plugin
sudo apt update
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Verify the installation:

```bash
docker --version
docker compose version
```

> **Note:** The official Docker packages provide `docker compose` (Compose v2 plugin) rather than the standalone `docker-compose` binary. All commands in this guide use the `docker compose` form.

### Running Docker Without `sudo`

To run Docker commands without `sudo`, add your user to the `docker` group:

```bash
# Create the group (usually already created during install)
sudo groupadd docker

# Add your user
sudo usermod -aG docker $USER
```

Apply the change by logging out and back in, or run `newgrp docker` in your current shell.

---

## Quick Start

```bash
git clone https://github.com/t3knoid/ecube.git
cd ecube

# Create .env file (see Configuration section)
cp .env.example .env
nano .env          # set POSTGRES_PASSWORD at minimum

# Start services
docker compose -f docker-compose.ecube.yml up -d --build

# Open the setup wizard (default UI port: 8443)
# https://localhost:8443/setup
#
# The container starts with an empty DATABASE_URL and enters setup wizard
# mode.  The wizard provisions the database using the PG_SUPERUSER_*
# credentials from .env, runs migrations, and writes DATABASE_URL back
# to the mounted .env file so subsequent restarts skip the wizard.

# View logs
docker compose -f docker-compose.ecube.yml logs -f ecube-app
```

---

## Using Pre-built Release Images

If you do not want to build from source, use the release compose artifact and published GHCR images.

Image repositories:

- `ghcr.io/t3knoid/ecube-app`

For each published release, images are pushed with:

- Version tag: `vX.Y.Z` (example: `v0.2.0`)
- Floating tag: `latest`

Recommended workflow:

1. Download the `docker-compose.yml` asset from [GitHub Releases](https://github.com/t3knoid/ecube/releases/latest).
2. Place it in your deployment directory.
3. Create/edit your `.env` file (see [04-configuration-reference.md](04-configuration-reference.md)).
4. Pull and start:

```bash
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
```

Optional manual image pull:

```bash
docker pull ghcr.io/t3knoid/ecube-app:v0.2.0
```

The release `docker-compose.yml` references pre-built images directly and is intended for environments where source checkout and local image build are not required.

---

## Configuration

ECUBE reads configuration from environment variables or a `.env` file. For the
complete list of environment variables, defaults, and descriptions, see:

> **[04-configuration-reference.md](04-configuration-reference.md)**

Copy the example file and edit as needed:

```bash
cp .env.example .env
nano .env
```

`cp .env.example .env` produces a working local/test configuration, including a default `POSTGRES_PASSWORD`. The `.env` file is bind-mounted into the container so the setup wizard can persist `DATABASE_URL` after provisioning. Adjust secrets and ports before using this in any non-lab environment.

### Running Without TLS

By default, the `ecube-app` container starts with TLS enabled (HTTPS on port 8443). To disable TLS and run plain HTTP, add the following to your `.env` file:

```dotenv
ECUBE_NO_TLS=true
ECUBE_PORT=8000
UI_PORT=8000
```

This starts uvicorn without `--ssl-keyfile` / `--ssl-certfile` on port 8000. No TLS certificates are required.

> **Warning:** Only disable TLS in trusted lab or development environments. Production deployments must use TLS.

## Setup Wizard Auto-Detection

When the container starts with an empty `DATABASE_URL` it enters **setup wizard mode** — the same flow used by the native installer. Open `https://localhost:8443/setup` to complete database provisioning and admin user creation.

Both native and Docker deployments use the same credential defaulting cascade:

- `PG_SUPERUSER_NAME` → `POSTGRES_USER` → `ecube`
- `PG_SUPERUSER_PASS` → `POSTGRES_PASSWORD` → `ecube`

The wizard auto-fills superuser credentials from these defaults. With the default `.env.example` values, the wizard connects using `ecube`/`ecube` — the same account the `postgres:16` container creates on first start. No manual password entry is required.

The wizard also detects that it is running inside a container and pre-fills the **Database Host** field with the PostgreSQL service name (default: `postgres`).

After successful provisioning:
- `DATABASE_URL` is written to the mounted `.env` file.
- `PG_SUPERUSER_NAME` and `PG_SUPERUSER_PASS` are cleared from `.env` for security.
- On subsequent container restarts the entrypoint reads `DATABASE_URL` from `.env`, waits for the database, and runs any pending migrations automatically.

**Customising the suggested host:** If your PostgreSQL service is named something other than `postgres`, set the `SETUP_DOCKER_DB_HOST` environment variable in your `.env` file before starting the stack:

```env
SETUP_DOCKER_DB_HOST=my-postgres-service
```

See [04-configuration-reference.md](04-configuration-reference.md) for the full list of environment variables.

---

## Starting and Stopping

### Start Services

```bash
docker compose -f docker-compose.ecube.yml up -d --build
```

### Check Status

```bash
docker compose -f docker-compose.ecube.yml ps
docker compose -f docker-compose.ecube.yml logs -f ecube-app
```

### Stop Services

```bash
docker compose -f docker-compose.ecube.yml down
```

### Restart Application

```bash
docker compose -f docker-compose.ecube.yml restart ecube-app
```

### Verify API Endpoint

```bash
curl -k https://localhost:8443/api/introspection/version

# Returns version metadata as JSON.
```

> **Note:** In this Compose deployment, ECUBE serves both the API and the UI from the `ecube-app` container on HTTPS port `8443` (or `UI_PORT` if overridden).

---

## Logs

```bash
# View logs
docker compose -f docker-compose.ecube.yml logs ecube-app

# Follow logs in real-time
docker compose -f docker-compose.ecube.yml logs -f ecube-app

# View specific number of lines
docker compose -f docker-compose.ecube.yml logs -n 100 ecube-app
```

---

## Common Docker Commands

### Restart the ECUBE Container

```bash
docker compose -f docker-compose.ecube.yml restart ecube-app
```

### Tail Logs

```bash
docker compose -f docker-compose.ecube.yml logs -f --tail 200 ecube-app
```

### Open a Shell Inside the Container

```bash
docker compose -f docker-compose.ecube.yml exec ecube-app /bin/bash
```

### Stop and Remove Containers

```bash
docker compose -f docker-compose.ecube.yml down
```

### Remove Containers and Locally Built Images

Useful for troubleshooting build issues — forces a full rebuild on the next `up --build`:

```bash
docker compose -f docker-compose.ecube.yml down --rmi local
```

### Remove Containers, Images, and Volumes (Full Reset)

> **Warning:** This destroys the PostgreSQL data volume. Back up your database first.

```bash
docker compose -f docker-compose.ecube.yml down --rmi local --volumes
```

---

## Reference

- **Design document:** [12-runtime-environment-and-usb-visibility.md](../design/12-runtime-environment-and-usb-visibility.md)
- **Configuration reference:** [04-configuration-reference.md](04-configuration-reference.md)
- **Administration automation guide:** [07-administration-automation-guide.md](07-administration-automation-guide.md)

## References

- [docs/operations/01-installation.md](01-installation.md)
- [docs/operations/04-configuration-reference.md](04-configuration-reference.md)
