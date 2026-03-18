# ECUBE Docker Deployment

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, IT Staff  
**Document Type:** Deployment Procedures

---

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Overview](#overview)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Starting and Stopping](#starting-and-stopping)
  - [Start Services](#start-services)
  - [Check Status](#check-status)
  - [Stop Services](#stop-services)
  - [Restart Application](#restart-application)
  - [Verify API Endpoint](#verify-api-endpoint)
- [Logs](#logs)
- [Reference](#reference)

---

## Overview

Docker Compose is the recommended method for quick testing and evaluation.
For production bare-metal deployments, see [04-package-deployment.md](04-package-deployment.md).

For Docker-specific USB passthrough setup and detailed architecture, see
[12-linux-host-deployment-and-usb-passthrough.md](../design/12-linux-host-deployment-and-usb-passthrough.md).

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

# Database migrations run automatically on startup via entrypoint.
# If you need to run them manually:
docker compose -f docker-compose.ecube.yml exec ecube-host alembic upgrade head

# Run first-run setup (creates admin user, seeds DB role)
# Option A: API-based (after service starts)
curl -X POST http://localhost:8000/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
# Option B: CLI
docker compose -f docker-compose.ecube.yml exec ecube-host ecube-setup

# View logs
docker compose -f docker-compose.ecube.yml logs -f ecube-host
```

---

## Configuration

ECUBE reads configuration from environment variables or a `.env` file. For the
complete list of environment variables, defaults, and descriptions, see:

> **[02-configuration-reference.md](02-configuration-reference.md)**

Copy the example file and edit as needed:

```bash
cp .env.example .env
nano .env
```

---

## Starting and Stopping

### Start Services

```bash
docker compose -f docker-compose.ecube.yml up -d --build
```

### Check Status

```bash
docker compose -f docker-compose.ecube.yml ps
docker compose -f docker-compose.ecube.yml logs -f ecube-host
```

### Stop Services

```bash
docker compose -f docker-compose.ecube.yml down
```

### Restart Application

```bash
docker compose -f docker-compose.ecube.yml restart ecube-host
```

### Verify API Endpoint

```bash
curl http://localhost:8000/introspection/version

# Expected response (JSON):
# {"version": "0.1.0", "api_version": "1.0.0"}
```

> **Note:** The Docker deployment exposes HTTP on port 8000 without TLS.
> For production, place a reverse proxy (e.g., Nginx, Caddy) in front to
> terminate TLS on port 8443. See [04-package-deployment.md](04-package-deployment.md)
> for the bare-metal deployment with built-in TLS.

---

## Logs

```bash
# View logs
docker compose -f docker-compose.ecube.yml logs ecube-host

# Follow logs in real-time
docker compose -f docker-compose.ecube.yml logs -f ecube-host

# View specific number of lines
docker compose -f docker-compose.ecube.yml logs -n 100 ecube-host
```

---

## Reference

- **Design document:** [12-linux-host-deployment-and-usb-passthrough.md](../design/12-linux-host-deployment-and-usb-passthrough.md)
- **Configuration reference:** [02-configuration-reference.md](02-configuration-reference.md)
- **Administration guide:** [06-administration-guide.md](06-administration-guide.md)
