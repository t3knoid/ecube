# ECUBE Development Guide

**Version:** 1.2  
**Last Updated:** April 2026  
**Audience:** Developers, Contributors  
**Document Type:** Index / Overview

---

## Table of Contents

1. [Introduction](#introduction)
2. [Development Environment Setup](#development-environment-setup)
3. [Repository Layout](#repository-layout)
4. [Running the Application](#running-the-application)
5. [Database and Migrations](#database-and-migrations)
6. [Testing](#testing)
7. [Architecture Overview](#architecture-overview)
8. [Coding Conventions](#coding-conventions)
9. [Related Documentation](#related-documentation)

---

## Introduction

This guide is the entry point for developers working on the ECUBE codebase on macOS and Linux. It covers local setup, project structure, testing practices, and key architectural patterns. For Windows development (Docker Desktop + WSL2, including usbipd-win), use the dedicated **[Windows Development Guide](02-windows-development-guide.md)**. For production deployment, see the [Operational Guide](../operations/00-operational-guide.md).

---

## Development Environment Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ (for local development; tests use SQLite in-memory)
- Git

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

The ECUBE app and UI always run natively on the host. Docker is used only to provide PostgreSQL by starting the `postgres` service from the platform compose file.

Both compose files publish API port `8000` for development convenience if you choose to run the app container, but this is **not** a typical hardened deployment shape. Typical Docker deployments should expose only `8443` through `ecube-ui`.

### Option A: Dockerized PostgreSQL (Recommended)

Start the PostgreSQL container, then run the app and UI natively:

```bash
# Ensure local environment file exists and required postgres password is set
cp .env.example .env
sed -i.bak 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=ecube/' .env

# Start PostgreSQL only
docker compose -f docker-compose.ecube.yml up -d postgres

# Apply migrations (from your local venv)
alembic upgrade head

# Start the backend API with auto-reload (natively)
uvicorn app.main:app --reload

# In a separate terminal — start the frontend dev server (natively)
cd frontend && npm ci && npm run dev
```

The backend API is available at `http://localhost:8000` and the frontend at `http://localhost:5173`.

Windows command for postgres-only run:

```bash
docker compose -f docker-compose.ecube-win.yml up -d postgres
```

### Option B: Fully Local (No Docker)

If you prefer a system-installed PostgreSQL (Linux example):

```bash
sudo systemctl start postgresql

# Create database (first time only)
sudo -u postgres psql -c "CREATE USER ecube WITH PASSWORD 'ecube';"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"

alembic upgrade head
uvicorn app.main:app --reload
```

For macOS, use your PostgreSQL service manager (for example, Homebrew services) and create the same `ecube` user/database before running migrations.

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

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

Results are saved to `schemathesis-output.txt` in the project root. See the [Schemathesis Local Guide](../testing/04-schemathesis-local.md) for manual steps, environment variables, and troubleshooting.

### QA Test-Case Sync

The QA test-case spreadsheet in `docs/testing/` is generated from the markdown guide. After editing test cases:

```bash
python scripts/sync_qa_test_cases.py --sync
```

See the [QA Testing Guide](../testing/01-qa-testing-guide-baremetal.md) for manual test procedures.

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
| [testing/](../testing/01-qa-testing-guide-baremetal.md) | QA testing guide and test-case spreadsheet |
| [design/](../design/00-overview.md) | Architecture, data model, API specification, security design |
| [requirements/](../requirements/00-overview.md) | Requirements documents |

---

**End of Development Guide**
