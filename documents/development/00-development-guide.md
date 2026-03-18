# ECUBE Development Guide

**Version:** 1.0  
**Last Updated:** March 2026  
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

This guide is the entry point for developers working on the ECUBE codebase. It covers local setup, project structure, testing practices, and key architectural patterns. For production deployment, see the [Operational Guide](../operations/00-operational-guide.md).

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

ECUBE reads settings from environment variables or a `.env` file in the project root. All settings have defaults suitable for local development.

```bash
# Optional: create a .env file to override defaults
cp .env.example .env
```

Key settings for development:

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql://ecube:ecube@localhost/ecube` | Local PostgreSQL connection |
| `SECRET_KEY` | (built-in dev default) | JWT signing key; change in production |
| `ROLE_RESOLVER` | `local` | Uses OS group → role mapping |

See [02 — Configuration Reference](../operations/02-configuration-reference.md) for the full list.

### Pre-Commit Hook (Optional)

A pre-commit hook ensures the QA test-case spreadsheet stays in sync with the markdown guide:

```bash
git config core.hooksPath .githooks
```

---

## Repository Layout

```text
docker-compose.ecube-host.yml  # Full-stack dev: app + PostgreSQL + USB passthrough
docker-compose.integration.yml # Isolated PostgreSQL for integration tests (port 5433)
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
  sync_qa_test_cases.py  # QA spreadsheet ↔ markdown sync tool
documents/
  design/              # Architecture and design specifications
  development/         # This folder — developer documentation
  operations/          # Production deployment and operations guides
  requirements/        # Requirements documents
  testing/             # QA testing guides and test-case tracking
```

---

## Running the Application

Two approaches are available: Docker Compose (recommended) or a manual local setup.

### Option A: Docker Compose — Full Stack (Recommended)

The `docker-compose.ecube-host.yml` file starts the ECUBE application and PostgreSQL together. It builds the app from the local `Dockerfile`, connects to a containerized Postgres, and automatically runs migrations on startup. USB passthrough is enabled via privileged mode and host device mounts.

```bash
# Start the full stack (builds the image on first run)
docker compose -f docker-compose.ecube-host.yml up -d

# Follow application logs
docker compose -f docker-compose.ecube-host.yml logs -f ecube-host

# Stop everything
docker compose -f docker-compose.ecube-host.yml down

# Stop and remove volumes (clean slate)
docker compose -f docker-compose.ecube-host.yml down -v
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

This is the best option when you want to test USB passthrough, full-stack behavior, or verify the Docker image builds correctly.

### Option B: Local Dev Server + Dockerized PostgreSQL

For faster iteration (with `--reload`), run the application locally but use Docker for PostgreSQL only:

```bash
# Start just PostgreSQL
docker compose -f docker-compose.ecube-host.yml up -d postgres

# Apply migrations (from your local venv)
alembic upgrade head

# Start the dev server with auto-reload
uvicorn app.main:app --reload
```

The default `DATABASE_URL` (`postgresql://ecube:ecube@localhost/ecube`) matches the containerized Postgres, so no `.env` change is needed.

### Option C: Fully Local (No Docker)

If you prefer a system-installed PostgreSQL:

```bash
sudo systemctl start postgresql

# Create database (first time only)
sudo -u postgres psql -c "CREATE USER ecube WITH PASSWORD 'ecube';"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"

alembic upgrade head
uvicorn app.main:app --reload
```

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

Integration tests run against a real PostgreSQL database. The `docker-compose.integration.yml` file provides an isolated Postgres instance specifically for this purpose — it uses a separate database (`ecube_integration`), user (`ecube_test`), and port (`5433`) so it never conflicts with your development database.

```bash
# Start the integration test database
docker compose -f docker-compose.integration.yml up -d

# Wait for it to be healthy (~5 seconds), then run integration tests
DATABASE_URL=postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration \
  python -m pytest tests/ -v --run-integration

# Stop the integration database when done
docker compose -f docker-compose.integration.yml down

# Stop and remove data (clean slate for next run)
docker compose -f docker-compose.integration.yml down -v
```

The integration database container can be left running across test runs. Use `down -v` when you want a completely fresh database.

### QA Test-Case Sync

The QA test-case spreadsheet in `documents/testing/` is generated from the markdown guide. After editing test cases:

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

---

## Related Documentation

| Folder | Description |
|--------|-------------|
| [operations/](../operations/00-operational-guide.md) | Production deployment, configuration, user manual, security hardening |
| [testing/](../testing/01-qa-testing-guide-baremetal.md) | QA testing guide and test-case spreadsheet |
| [design/](../design/00-overview.md) | Architecture, data model, API specification, security design |
| [requirements/](../requirements/00-overview.md) | Requirements documents |

---

**End of Development Guide**
