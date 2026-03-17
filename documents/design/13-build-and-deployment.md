# 13. Build and Deployment

This document is the canonical reference for ECUBE build and deployment workflows.

It covers:

- CI packaging to GitHub Releases (`.tar.gz` + checksum).
- Package deployment on Linux hosts (no Docker runtime).
- Docker image build details.
- Docker Compose deployment for Linux host + PostgreSQL.

## Deployment Paths

ECUBE supports two runtime deployment paths. Choose exactly one for a target environment.

- **Path A — Package deployment:** use the release `.tar.gz` artifact and run ECUBE as a system service on Linux.
- **Path B — Docker deployment:** run ECUBE in containers using Docker image + Docker Compose.

These paths are alternatives, not sequential steps.

Use this quick rule:

- If your environment standard is host-level services (`systemd`, local Python runtime), use **Path A**.
- If your environment standard is container orchestration/Compose, use **Path B**.

## 13.1 Build Outputs

ECUBE supports two primary deployment outputs:

1. **Release package artifact** (recommended for package deployments without Docker runtime)
   - `ecube-package-<release-tag>.tar.gz`
   - `ecube-package-<release-tag>.sha256`
2. **Docker runtime image** for containerized deployment.

## 13.2 Dependencies

### Python Packages

ECUBE now requires `PyJWT[crypto]` for OIDC support (RSA/EC signature verification for OIDC tokens).

This is automatically installed via:

```bash
pip install -e ".[dev]"
```

If deploying from a pre-built package or in an environment without `pyproject.toml`, ensure cryptographic support is installed:

```bash
pip install "PyJWT[crypto]>=2.7.0"
```

## 13.3 CI Release Packaging (GitHub Releases)

Workflow: `.github/workflows/release-artifact.yml`

Trigger:

- `release.published`

Behavior:

- Packages `app/`, `alembic/`, `pyproject.toml`, `alembic.ini`, `README.md`, `LICENSE`.
- Creates release assets:
  - `ecube-package-<release-tag>.tar.gz`
  - `ecube-package-<release-tag>.sha256`

## 13.3 Package Deployment

### Prerequisites

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip postgresql postgresql-contrib nfs-common cifs-utils usbutils udev
```

### Provision service account and target directory

```bash
sudo useradd --system --create-home --shell /bin/bash ecube
sudo mkdir -p /opt/ecube
sudo chown -R ecube:ecube /opt/ecube
```

### Download latest public release package (curl)

```bash
export GITHUB_OWNER="t3knoid"
export GITHUB_REPO="ecube"
mkdir -p /tmp/ecube-release

LATEST_TAG=$(curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/latest" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['tag_name'])")

ASSET_JSON=$(curl -fsSL \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/releases/tags/${LATEST_TAG}")

PACKAGE_URL=$(printf "%s" "$ASSET_JSON" | python3 -c "import sys,json; a=json.load(sys.stdin)['assets']; print(next(x['browser_download_url'] for x in a if x['name'].endswith('.tar.gz')))" )
CHECKSUM_URL=$(printf "%s" "$ASSET_JSON" | python3 -c "import sys,json; a=json.load(sys.stdin)['assets']; print(next(x['browser_download_url'] for x in a if x['name'].endswith('.sha256')))" )

curl -fL "${PACKAGE_URL}" -o /tmp/ecube-release/ecube-package.tar.gz
curl -fL "${CHECKSUM_URL}" -o /tmp/ecube-release/ecube-package.sha256
cd /tmp/ecube-release
sha256sum -c ecube-package.sha256
```

### Extract and install Python dependencies

```bash
sudo -u ecube tar -xzf /tmp/ecube-release/ecube-package.tar.gz -C /opt/ecube
cd /opt/ecube
sudo -u ecube python3.11 -m venv .venv
sudo -u ecube ./.venv/bin/pip install --upgrade pip setuptools wheel
sudo -u ecube ./.venv/bin/pip install -e ".[dev]"
```

### Configure PostgreSQL and app environment

```sql
CREATE USER ecube WITH PASSWORD 'ecube';
CREATE DATABASE ecube OWNER ecube;
GRANT ALL PRIVILEGES ON DATABASE ecube TO ecube;
```

Create `/opt/ecube/.env`:

```env
DATABASE_URL=postgresql://ecube:ecube@localhost/ecube
SECRET_KEY=change-me-in-production
ALGORITHM=HS256
```

### Apply schema migrations

```bash
cd /opt/ecube
sudo -u ecube ./.venv/bin/alembic upgrade head
```

### Create and start systemd service

`/etc/systemd/system/ecube.service`:

```ini
[Unit]
Description=ECUBE API Service
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=ecube
Group=ecube
WorkingDirectory=/opt/ecube
EnvironmentFile=/opt/ecube/.env
ExecStart=/opt/ecube/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ecube
sudo systemctl start ecube
sudo systemctl status ecube
curl http://localhost:8000/health
```

### Package deployment update process

```bash
sudo -u ecube tar -xzf /tmp/ecube-release/ecube-package.tar.gz -C /opt/ecube
cd /opt/ecube
sudo -u ecube ./.venv/bin/pip install -e ".[dev]"
sudo -u ecube ./.venv/bin/alembic upgrade head
sudo systemctl restart ecube
```

## 13.4 Docker Image Build

Container runtime Dockerfile: `deploy/ecube-host/Dockerfile`

### Build behavior

1. Uses a pinned Python base image.
2. Installs required Linux tooling (mount/NFS/SMB/USB/udev).
3. Copies ECUBE source and migration files into image.
4. Installs app and dependencies using `pip install -e ".[dev]"`.
5. Runs `uvicorn app.main:app` on container start.

### Build locally

```bash
docker build -f deploy/ecube-host/Dockerfile -t ecube-host:local .
```

### Rebuild with refreshed upstream layers

```bash
docker build --pull --no-cache -f deploy/ecube-host/Dockerfile -t ecube-host:local .
```

## 13.5 Docker Compose Deployment (Linux Host)

Compose file: `docker-compose.ecube-host.yml`

### Services

- `ecube-host`
- `postgres`

### Start

```bash
docker compose -f docker-compose.ecube-host.yml up -d --build
```

Migrations are applied automatically when `ecube-host` starts (entrypoint waits for DB then runs `alembic upgrade head`).

Optional manual migration command (only if `ECUBE_RUN_MIGRATIONS_ON_START=false`):

```bash
docker compose -f docker-compose.ecube-host.yml exec ecube-host alembic upgrade head
```

### Validate

```bash
docker compose -f docker-compose.ecube-host.yml ps
curl http://localhost:8000/health
```

### Stop

```bash
docker compose -f docker-compose.ecube-host.yml down
```

## 13.6 USB Passthrough in VM-Based Deployments

For USB hub/device passthrough guidance (physical host → VM → container), see:

- `documents/design/12-linux-host-deployment-and-usb-passthrough.md`

## 13.7 Session and Cookie Configuration

ECUBE supports configurable session management with two storage backends.

### Backend selection

| Value | Description |
|-------|-------------|
| `cookie` (default) | Signed browser cookies via Starlette `SessionMiddleware`. No external dependencies. |
| `redis` | Session data stored server-side in Redis; only a session-id cookie is sent to the browser. Requires the `redis` Python package. |

Set `SESSION_BACKEND` in your `.env` or environment to choose a backend.

### Cookie settings

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `SESSION_COOKIE_NAME` | `ecube_session` | Name of the session cookie. |
| `SESSION_COOKIE_EXPIRATION_SECONDS` | `3600` | Cookie lifetime in seconds. Use `86400` for 24 hours. |
| `SESSION_COOKIE_DOMAIN` | *(unset)* | Domain scope. Leave empty for the browser's default rules. |
| `SESSION_COOKIE_SECURE` | `true` | Send cookie only over HTTPS. Set `false` for local dev. **Must be `true` when `SESSION_COOKIE_SAMESITE=none`.** |
| `SESSION_COOKIE_SAMESITE` | `lax` | Values: `strict`, `lax`, `none`. |

> **Note:** The `HttpOnly` flag is always enabled on session cookies and cannot be disabled.

### Redis configuration (optional)

Required only when `SESSION_BACKEND=redis`:

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `REDIS_URL` | *(unset)* | Redis connection URL, e.g. `redis://localhost:6379/0`. |
| `REDIS_CONNECTION_TIMEOUT` | `5` | Timeout in seconds for establishing a connection. |
| `REDIS_SOCKET_KEEPALIVE` | `true` | TCP keepalive on the Redis socket. |

### Graceful fallback

If `SESSION_BACKEND=redis` but Redis is unreachable (or the `redis` package is not installed), ECUBE logs a warning and automatically falls back to cookie-based sessions. The application continues to function normally.

### Example `.env` — cookie backend (default)

```env
SESSION_BACKEND=cookie
SESSION_COOKIE_NAME=ecube_session
SESSION_COOKIE_EXPIRATION_SECONDS=3600
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
```

### Example `.env` — Redis backend

```env
SESSION_BACKEND=redis
REDIS_URL=redis://localhost:6379/0
REDIS_CONNECTION_TIMEOUT=5
REDIS_SOCKET_KEEPALIVE=true
SESSION_COOKIE_NAME=ecube_session
SESSION_COOKIE_EXPIRATION_SECONDS=86400
SESSION_COOKIE_SECURE=true
```

### Redis deployment

**Docker Compose** — add a `redis` service alongside `ecube-host` and `postgres`:

```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
volumes:
  redis_data:
```

**Systemd (package deployment)** — install Redis from your distribution package manager:

```bash
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

Then set `REDIS_URL=redis://localhost:6379/0` in `/opt/ecube/.env`.
