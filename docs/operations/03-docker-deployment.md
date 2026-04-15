# ECUBE Docker Deployment

| Field | Value |
|---|---|
| Title | ECUBE Docker Deployment |
| Purpose | Describes how to deploy ECUBE with Docker Compose, including container configuration and environment variable setup. |
| Updated on | 04/08/26 |
| Audience | Systems administrators, IT staff. |

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Using Pre-built Release Images](#using-pre-built-release-images)
4. [Configuration](#configuration)
5. [Setup Wizard Auto-Detection](#setup-wizard-auto-detection)
6. [Starting and Stopping](#starting-and-stopping)
7. [Logs](#logs)
8. [Reference](#reference)

---

## Overview

Docker Compose is the recommended method for quick testing and evaluation.
For production native deployments, see [02-manual-installation.md](02-manual-installation.md).

In the Compose deployment, only the HTTPS frontend port is published to the host by default. The FastAPI backend listens on port `8000` inside the `ecube-app` container and is reached externally through the `ecube-ui` nginx reverse proxy:

- Web UI: `https://localhost:${UI_PORT:-8443}/`
- Setup wizard: `https://localhost:${UI_PORT:-8443}/setup`
- API endpoints: `https://localhost:${UI_PORT:-8443}/api/...`
- Swagger UI: `https://localhost:${UI_PORT:-8443}/docs`
- OpenAPI schema: `https://localhost:${UI_PORT:-8443}/openapi.json`

For Docker-specific USB passthrough setup and detailed architecture, see
[12-runtime-environment-and-usb-visibility.md](../design/12-runtime-environment-and-usb-visibility.md).

---

## Quick Start

```bash
git clone https://github.com/t3knoid/ecube.git
cd ecube

# Create .env file (see Configuration section)
cp .env.example .env
nano .env

# Start services
docker compose -f docker-compose.ecube.yml up -d --build

# Open the UI / setup wizard (default UI port: 8443)
# https://localhost:8443/setup

# Database migrations run automatically on startup via the ecube-app entrypoint.
# If you need to run them manually:
docker compose -f docker-compose.ecube.yml exec ecube-app alembic upgrade head

# Run first-run setup (creates admin user, seeds DB role)
# Option A: API-based through the published HTTPS frontend
curl -k -X POST https://localhost:8443/api/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
# Option B: Web UI
# Open https://localhost:8443/setup and complete the setup wizard

# View logs
docker compose -f docker-compose.ecube.yml logs -f ecube-app
```

---

## Using Pre-built Release Images

If you do not want to build from source, use the release compose artifact and published GHCR images.

Image repositories:

- `ghcr.io/t3knoid/ecube-app`
- `ghcr.io/t3knoid/ecube-ui`

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
docker pull ghcr.io/t3knoid/ecube-ui:v0.2.0
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

`cp .env.example .env` produces a working local/test configuration, including a default `POSTGRES_PASSWORD`. Adjust secrets and ports before using this in any non-lab environment.

## Setup Wizard Auto-Detection

When you open the ECUBE web UI for the first time inside a Docker Compose environment, the setup wizard automatically detects that it is running inside a container and pre-fills the **Database Host** field with the PostgreSQL service name (default: `postgres`).

A contextual hint is displayed below the host field confirming that the Docker Compose service name is being used.  You do not need to enter the host manually for standard Docker Compose deployments.

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

> **Note:** In this Compose deployment, the host-facing entry point is `ecube-ui` on HTTPS port `8443` (or `UI_PORT` if overridden). The backend's port `8000` is intentionally not published to the host. For container-local debugging, run commands inside `ecube-app`, for example `docker compose -f docker-compose.ecube.yml exec ecube-app curl http://localhost:8000/health`.

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

## Reference

- **Design document:** [12-runtime-environment-and-usb-visibility.md](../design/12-runtime-environment-and-usb-visibility.md)
- **Configuration reference:** [04-configuration-reference.md](04-configuration-reference.md)
- **Administration automation guide:** [07-administration-automation-guide.md](07-administration-automation-guide.md)

## References

- [docs/operations/01-installation.md](01-installation.md)
- [docs/operations/04-configuration-reference.md](04-configuration-reference.md)
