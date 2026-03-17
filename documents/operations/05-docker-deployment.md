# ECUBE Docker Deployment

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Systems Administrators, IT Staff  
**Document Type:** Deployment Procedures

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Configuration](#configuration)
4. [Starting and Stopping](#starting-and-stopping)
5. [Logs](#logs)
6. [Reference](#reference)

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
docker compose up -d

# Initialize database
docker compose exec app alembic upgrade head

# Run first-run setup (creates admin user, seeds DB role)
# Option A: API-based (after service starts)
curl -k -X POST https://localhost:8443/setup/initialize \
  -H "Content-Type: application/json" \
  -d '{"username": "ecube-admin", "password": "s3cret"}'
# Option B: CLI
docker compose exec app ecube-setup

# View logs
docker compose logs -f app
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
docker compose up -d
```

### Check Status

```bash
docker compose ps
docker compose logs -f app
```

### Stop Services

```bash
docker compose down
```

### Restart Application

```bash
docker compose restart app
```

### Verify API Endpoint

```bash
curl -k https://localhost:8443/introspection/version

# Expected response (JSON):
# {"version": "0.1.0", "api_version": "1.0.0"}
```

---

## Logs

```bash
# View logs
docker compose logs app

# Follow logs in real-time
docker compose logs -f app

# View specific number of lines
docker compose logs -n 100 app
```

---

## Reference

- **Design document:** [12-linux-host-deployment-and-usb-passthrough.md](../design/12-linux-host-deployment-and-usb-passthrough.md)
- **Configuration reference:** [02-configuration-reference.md](02-configuration-reference.md)
- **User manual:** [06-user-manual.md](06-user-manual.md)
