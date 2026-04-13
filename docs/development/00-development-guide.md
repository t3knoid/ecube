# ECUBE Development Guide

| Field | Value |
|---|---|
| Title | ECUBE Development Guide |
| Purpose | Provides an overview and index for developer setup, debugging, CI workflows, and contribution procedures. |
| Updated on | 04/08/26 |
| Audience | Developers, contributors. |

## Table of Contents

1. [Introduction](#introduction)
2. [Quick Start](#quick-start)
3. [Development Environment Setup](#development-environment-setup)
4. [Repository Layout](#repository-layout)
5. [Running the Application](#running-the-application)
6. [Database and Migrations](#database-and-migrations)
7. [Testing](#testing)
8. [Architecture Overview](#architecture-overview)
9. [Coding Conventions](#coding-conventions)
10. [Related Documentation](#related-documentation)

---

## Introduction

This guide is the entry point for developers working on the ECUBE codebase on macOS and Linux. It covers local setup, project structure, testing practices, and key architectural patterns. For Windows development (Docker Desktop + WSL2, including usbipd-win), use the dedicated **[Windows Development Guide](02-windows-development-guide.md)**. For production deployment, see the [Operational Guide](../operations/00-operational-guide.md).

---

## Quick Start

Use this section for a concise startup path; subsequent sections provide more comprehensive instructions, alternatives, and troubleshooting details.

Assumes Python 3.11+, Node.js 20 LTS+, npm 10+, and PostgreSQL 14+ are already installed.

1. Clone the source code

```bash
git clone https://github.com/t3knoid/ecube.git && cd ecube
```

2. Configure the Python environment

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

3. Configure the environment file

Set DATABASE_URL in .env (e.g. DATABASE_URL=postgresql://ecube:ecube@localhost/ecube).

```bash
cp .env.example .env
```

4. Create a PostgreSQL admin login for the setup wizard (first time only)

```bash
sudo -u postgres psql -c "CREATE ROLE ecubeadmin WITH LOGIN CREATEDB CREATEROLE PASSWORD 'ecubeadmin';"
```

5. Install PAM service config (first time only, Linux)

```bash
sudo cp deploy/ecube-pam /etc/pam.d/ecube
```

6. Start backend (must run as root for PAM authentication)

```bash
sudo .venv/bin/uvicorn app.main:app --reload
```

7. In a second terminal, install dependencies and run the development frontend

```bash
cd frontend && npm ci && npm run dev
```

8. Compile the frontend code (production build)

```bash
cd frontend && npm run build
```


Then open the setup wizard at `http://localhost:5173` to test the database connection using `ecube_admin`, provision the application database/user, run migrations, and create the first ECUBE admin user.

| URL | Purpose |
|-----|---------|
| `http://localhost:5173` | Frontend UI |
| `http://localhost:8000` | Backend API |
| `http://localhost:8000/docs` | Interactive API docs |

---

## Development Environment Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (for local development; tests use SQLite in-memory)
- Node.js 20 LTS+
- npm 10+
- Git

Quick check:

```bash
python3.11 --version
node --version
npm --version
git --version
```

### Install Tooling (If Missing)

If one of the commands above is missing, install the required tools first.

Linux (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y curl git python3.11 python3.11-venv postgresql postgresql-contrib

# Install Node.js 20 LTS (includes npm)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

macOS (Homebrew):

```bash
brew install python@3.11 git node@20
```

After installation, verify versions again:

```bash
python3.11 --version
node --version
npm --version
git --version
psql --version
```

If you plan to run PostgreSQL via Docker Compose instead of a system service,
install Docker Engine and Docker Compose plugin, then verify:

```bash
docker --version
docker compose version
```

### Development Tooling Reference

The table below summarizes the core tools used during ECUBE development and what each is used for.

| Tool | Required | Installed Via | Used For |
|------|----------|---------------|----------|
| Python 3.11+ | Yes | OS package manager (for example, apt or Homebrew) | Running the FastAPI backend, services, scripts, and tests. |
| pip (via Python) | Yes | Bundled with Python (`ensurepip`) or OS Python packages | Installing backend dependencies and developer packages (`pip install -e ".[dev]"`). |
| PostgreSQL 14+ | Yes | OS package manager (for example, apt/Homebrew) or Docker image | Local development database for API runtime and integration testing. |
| Alembic | Yes | Python package installation via `pip install -e ".[dev]"` | Applying and generating database schema migrations. |
| Git | Yes | OS package manager (for example, apt/Homebrew) | Source control, branch workflow, and contribution flow. |
| Node.js 20 LTS+ | Yes (frontend work) | NodeSource/OS package manager or Homebrew | JavaScript runtime for frontend build/test toolchain (Vite, Vitest, Playwright). |
| npm 10+ | Yes (frontend work) | Bundled with Node.js installation | Installing frontend dependencies and running frontend scripts (`npm ci`, `npm run dev`, `npm run build`). |
| Docker + Docker Compose | Optional (recommended) | Docker Engine packages + Compose plugin | Running PostgreSQL locally with project compose files instead of system-installed Postgres. |
| pytest | Yes | Python package installation via `pip install -e ".[dev]"` | Running backend unit and integration test suites. |
| Uvicorn | Yes | Python package installation via `pip install -e ".[dev]"` | Running the backend API locally in development (`uvicorn app.main:app --reload`). |

Build-focused minimums:

- To build backend source: Python 3.11+, pip, Git
- To build frontend source (`npm run build`): Node.js 20 LTS+, npm 10+
- To run full-stack locally with database: PostgreSQL 14+ (or Docker + Compose)

### Install Dependencies

```bash
# Clone the repository
git clone https://github.com/t3knoid/ecube.git
cd ecube

# Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install the project with dev dependencies
pip install -e ".[dev]"
```

What `pip install -e ".[dev]"` installs:

- Python packages from this project and its Python dependency graph (for example: FastAPI stack, SQLAlchemy, Alembic, pytest, Uvicorn).
- Developer/test Python packages declared in `pyproject.toml` under the `dev` extra.

What it does **not** install:

- System tooling: PostgreSQL server/client, Git, Docker, Node.js, npm.
- OS packages required by external binaries and services.

### Environment Configuration

ECUBE reads settings from environment variables or a `.env` file in the project root.

```bash
# Create a .env file (required for docker compose workflows)
cp .env.example .env
```

For local development, use the platform compose file to run **PostgreSQL only** and run the ECUBE app/UI natively on the host:

- Linux/macOS: `docker-compose.ecube.yml`
- Windows: `docker-compose.ecube-win.yml`

Set at least:

```env
POSTGRES_PASSWORD=ecube
```

Linux/macOS quick setup:

```bash
sed -i.bak 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=ecube/' .env
```

Windows (pwsh) quick setup:

```powershell
Copy-Item .env .env.bak
(Get-Content .env) -replace '^POSTGRES_PASSWORD=.*', 'POSTGRES_PASSWORD=ecube' | Set-Content .env
```

Key settings for development:

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql://ecube:ecube@localhost/ecube` | Matches postgres-only run from `docker-compose.ecube.yml` / `docker-compose.ecube-win.yml` |
| `SECRET_KEY` | (built-in dev default) | JWT signing key; change in production |
| `POSTGRES_PASSWORD` | (none) | Required by compose postgres service |
| `ROLE_RESOLVER` | `local` | Uses OS group → role mapping |

See [02 — Configuration Reference](../operations/04-configuration-reference.md) for the full list.

### Pre-Commit Hook (Optional)

A pre-commit hook ensures the QA test-case spreadsheet stays in sync with the markdown guide:

```bash
git config core.hooksPath .githooks
```

---

## Repository Layout

```text
docker-compose.ecube.yml      # Linux/macOS compose file (use `up -d postgres` for local dev DB)
docker-compose.ecube-win.yml  # Windows compose file (use `up -d postgres` for local dev DB)
app/
  main.py              # FastAPI application entry point and lifespan
  config.py            # Pydantic Settings class (all env vars)
  database.py          # SQLAlchemy engine, SessionLocal, Base
  auth.py              # JWT validation and get_current_user dependency
  auth_providers.py    # Role resolver implementations (Local, LDAP, OIDC)
  dependencies.py      # Shared FastAPI dependencies
  exceptions.py        # Custom exception classes
  session.py           # Session backend (cookie/Redis)
  setup.py             # First-run setup CLI entry point
  infrastructure/      # Platform abstraction (OS-specific operations)
    __init__.py        # Factory functions (get_filesystem_detector, get_drive_formatter)
    drive_eject.py     # Drive unmount/eject
    drive_format.py    # DriveFormatter Protocol + Linux implementation
    filesystem_detection.py  # FilesystemDetector Protocol + Linux implementation
    usb_discovery.py   # USB device enumeration
  models/              # SQLAlchemy ORM models
    hardware.py        # usb_hubs, usb_ports, usb_drives
    jobs.py            # export_jobs, export_files, manifests, drive_assignments
    network.py         # network_mounts
    audit.py           # audit_logs (append-only)
    users.py           # user_roles
    system.py          # system_initialization
  repositories/        # Data access layer (query encapsulation)
  routers/             # FastAPI routers (one per domain)
  schemas/             # Pydantic request/response schemas
  services/            # Business logic and state machines
alembic/
  env.py               # Alembic environment configuration
  versions/            # Migration scripts (0001–0004+)
tests/
  conftest.py          # Shared fixtures (SQLite StaticPool, role-specific clients)
  test_*.py            # Unit and integration tests
  integration/         # Integration test suite (requires --run-integration)
  hardware/            # Hardware-in-the-loop tests (requires --run-hardware)
scripts/
  run_schemathesis.sh    # One-command Schemathesis API fuzz testing
  sync_qa_test_cases.py  # QA spreadsheet ↔ markdown sync tool
docs/
  design/              # Architecture and design specifications
  development/         # This folder — developer documentation
  operations/          # Production deployment and operations guides
  requirements/        # Requirements documents
  testing/             # QA testing guides and test-case tracking
```

---

## Running the Application

The ECUBE backend and frontend run natively on the host in development. Choose one PostgreSQL option, then run backend and frontend in separate terminals.

### PostgreSQL Options

#### Option A: Dockerized PostgreSQL (Recommended)

```bash
# Ensure local environment file exists and required postgres password is set
cp .env.example .env
sed -i.bak 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=ecube/' .env

# Linux/macOS: start PostgreSQL only
docker compose -f docker-compose.ecube.yml up -d postgres
```

Windows equivalent:

```bash
docker compose -f docker-compose.ecube-win.yml up -d postgres
```

#### Option B: System-Installed PostgreSQL

Linux example:

```bash
sudo systemctl start postgresql

# First-time setup only
sudo -u postgres psql -c "CREATE USER ecube WITH PASSWORD 'ecube';"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"
```

For macOS, use your PostgreSQL service manager (for example, Homebrew services) and run the same two commands before migrations.

### PAM Service Config

The `POST /auth/token` login endpoint authenticates OS credentials via Linux PAM. Two one-time setup steps are required.

**1. Install the PAM service config:**

```bash
sudo cp deploy/ecube-pam /etc/pam.d/ecube
```

**2. Run the backend as root.**

Linux's `unix_chkpwd` helper (used by `pam_unix` for non-root processes) only allows a process to verify its *own* password. The ECUBE service must run as root to authenticate arbitrary OS users:

```bash
sudo .venv/bin/uvicorn app.main:app --reload
```

Without root, all login attempts return `401 Unauthorized` regardless of credentials. In production, the service runs as root via systemd — the same restriction applies.

### Backend Execution

Run from the repository root (with your virtual environment activated):

```bash
alembic upgrade head
sudo .venv/bin/uvicorn app.main:app --reload
```

### Frontend Execution

Run in a separate terminal:

```bash
cd frontend
npm ci
npm run dev
```

To access the frontend from another machine, browse to `http://<host-ip>:5173`.

### Access URLs

The backend API is available at `http://localhost:8000`, the frontend at `http://localhost:5173` (or `http://<host-ip>:5173` from another machine), and interactive backend docs at `http://localhost:8000/docs`.

---

## Database and Migrations

### ORM Models

All models inherit from `app.database.Base` and live in `app/models/`. Key conventions:

- **Enum columns:** Always use `native_enum=False` for SQLite test compatibility.
- **JSON columns:** Use SQLAlchemy's portable `JSON` type in models (not `JSONB`). Alembic migrations use `JSONB` for PostgreSQL production.
- **Timestamps:** Use `server_default=func.now()` for creation timestamps.

### Creating Migrations

```bash
# Auto-generate from model changes
alembic revision --autogenerate -m "describe change"

# Or create an empty migration for manual SQL
alembic revision -m "describe change"

# Apply
alembic upgrade head

# Check current version
alembic current

# Rollback one step
alembic downgrade -1
```

### Reset PostgreSQL Database (Start Fresh)

For local PostgreSQL installs, run a single command block:

```bash
sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'ecube' AND pid <> pg_backend_pid();"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ecube;"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"
```

After recreating the database, apply migrations again:

```bash
alembic upgrade head
```

### Migration Naming

Migrations are numbered sequentially: `0001_initial.py`, `0002_retry_resume.py`, etc.

---

## Testing

### Running Tests

```bash
# Run all unit tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_drives.py -v

# Run integration tests (see Integration Testing below)
python -m pytest tests/ -v --run-integration

# Run hardware-in-the-loop tests (requires physical USB hardware)
python -m pytest tests/ -v --run-hardware
```

### Test Architecture

- **Database:** Tests use an **SQLite in-memory database** with `StaticPool` — never PostgreSQL. The `conftest.py` overrides `SessionLocal` before importing `app.main`.
- **Client fixtures:** `conftest.py` provides role-specific TestClient fixtures:
  - `client` — authenticated as `processor`
  - `admin_client` — authenticated as `admin`
  - `manager_client` — authenticated as `manager`
  - `auditor_client` — authenticated as `auditor`
  - `unauthenticated_client` — no auth headers
- **Database fixture:** The `db` fixture creates all tables before each test and drops them after, ensuring full isolation.
- **Dependency overrides:** Each client fixture overrides `get_db` to inject the test session and clears overrides on teardown.

### Writing Tests

```python
def test_list_drives(client):
    """client fixture is pre-authenticated as processor."""
    response = client.get("/drives")
    assert response.status_code == 200

def test_admin_only_endpoint(admin_client):
    """admin_client fixture is pre-authenticated as admin."""
    response = admin_client.get("/admin/os-users")
    assert response.status_code == 200

def test_unauthenticated_returns_401(unauthenticated_client):
    response = unauthenticated_client.get("/drives")
    assert response.status_code == 401
```

### Integration Testing

Integration tests run against a real PostgreSQL database. Use the platform compose file and start only the postgres service:

```bash
# Start the integration test database (Linux/macOS)
docker compose -f docker-compose.ecube.yml up -d postgres

# Run integration tests
INTEGRATION_DATABASE_URL=postgresql://ecube:ecube@localhost:5432/ecube \
  python -m pytest tests/integration/ -v --run-integration

# Stop the database when done
docker compose -f docker-compose.ecube.yml down -v
```

Windows command for integration DB startup:

```bash
docker compose -f docker-compose.ecube-win.yml up -d postgres
```

The integration database container can be left running across test runs. Use `down -v` when you want a completely fresh database.

### Frontend Development and Tests

The frontend is a separate Node-based workspace under `frontend/`.

```bash
cd frontend
npm ci

# Local UI dev server
npm run dev

# Unit tests (Vitest)
npm run test:unit

# E2E tests (Playwright)
npm run build
npm run test:e2e
```

For first-time Playwright setup, install browser dependencies:

```bash
cd frontend
npx playwright install --with-deps chromium webkit
```

### API Fuzz Testing (Schemathesis)

Schemathesis reads the OpenAPI schema and auto-generates randomised requests to find schema violations, server errors, and undocumented status codes. A one-command script runs the full scan in Docker containers:

```bash
./scripts/run_schemathesis.sh
```

Results are saved to `schemathesis-output.txt` in the project root. See the [Schemathesis Local Guide](../testing/06-schemathesis-local.md) for manual steps, environment variables, and troubleshooting.

### API Smoke Testing (Newman)

For a lightweight API smoke check based on the synced Postman collection:

```bash
./scripts/run_newman_smoke.sh
```

The script starts/stops the ECUBE Docker stack, waits for health, generates a token, and runs a curated smoke subset. See the [Newman Local Guide](../testing/07-newman-local.md) for options and troubleshooting.

### QA Test-Case Sync

The QA test-case spreadsheet in `docs/testing/` is generated from the markdown guide. After editing test cases:

```bash
python scripts/sync_qa_test_cases.py --sync
```

See the [QA Testing Guide](../testing/03-qa-testing-guide.md) for manual test procedures.

---

## Architecture Overview

### Trust Boundary

- **System Layer (trusted):** The FastAPI service is the only component that touches the database and hardware. It enforces policy, executes operations, and writes audit logs.
- **UI Layer (untrusted):** Consumes the HTTPS API only.
- **Database:** Reachable only from the system-layer network segment.

### Platform Abstraction

OS-specific operations (drive discovery, formatting, mount/unmount, eject, user management) are defined as `Protocol` or `ABC` interfaces in `app/infrastructure/`. Concrete implementations target Linux. Services depend on the interface, not the implementation. Tests inject fakes/mocks via `dependency_overrides`.

When adding new OS-level functionality:
1. Define the interface in `app/infrastructure/`
2. Implement the Linux concrete class
3. Wire via dependency injection in the relevant router/service

### Key Patterns

- **Repositories** (`app/repositories/`): Encapsulate all database queries. Services call repositories, not raw SQLAlchemy.
- **Services** (`app/services/`): Business logic and state machines. Each domain has a dedicated service module.
- **Routers** (`app/routers/`): One router per domain. Thin layer that validates input, calls services, and returns responses.
- **Schemas** (`app/schemas/`): Pydantic models for request/response validation. Separate from ORM models.

---

## Coding Conventions

- **Audit logging:** Every security-relevant event must emit a structured JSON record to `audit_logs`.
- **Role gating:** Use the `require_roles(*roles)` dependency on every endpoint.
- **Enum columns:** Always `native_enum=False`.
- **Introspection endpoints:** Read-only; redact sensitive fields.
- **HTTP status codes:** `401` for missing/invalid/expired tokens; `403` for role or project isolation violations.
- **Error responses:** All error responses use the `ErrorResponse` schema (`app/schemas/errors.py`) with `code`, `message`, and `trace_id` fields. Declare error responses on every route decorator using the reusable dicts (`R_400`, `R_401`, `R_403`, `R_404`, `R_409`, `R_422`, `R_500`, `R_503`, `R_504`) from `app/schemas/errors.py`. Combine them via `responses={**R_401, **R_403}`.
- **Input sanitization:** Path-like fields (e.g. `remote_path`, `source_path`) use `StrictSafeStr` which rejects malformed Unicode with `422`; non-path string fields use `SafeStr` which silently strips null bytes and surrogates. Both are defined in `app/utils/sanitize.py`.

---

## Related Documentation

| Folder | Description |
|--------|-------------|
| [Windows Development Guide](02-windows-development-guide.md) | Windows-specific setup, Docker, USB passthrough |
| [Debugging Guide](01-debugging-guide.md) | Command-line and VS Code debugging reference |
| [CI Build and Installer Artifact Contract](03-ci-build-and-installer-artifacts.md) | GitHub Actions package build flow and installer-required artifact contract |
| [operations/](../operations/00-operational-guide.md) | Production deployment, configuration, user manual, security hardening |
| [testing/](../testing/03-qa-testing-guide.md) | QA testing guide and test-case spreadsheet |
| [design/](../design/00-overview.md) | Architecture, data model, API specification, security design |
| [requirements/](../requirements/00-overview.md) | Requirements documents |

---

**End of Development Guide**

## References

- [docs/development/01-debugging-guide.md](01-debugging-guide.md)
- [docs/development/02-windows-development-guide.md](02-windows-development-guide.md)
- [docs/development/03-ci-build-and-installer-artifacts.md](03-ci-build-and-installer-artifacts.md)
