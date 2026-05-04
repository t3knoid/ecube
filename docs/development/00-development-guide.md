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

```bash
cp .env.example .env
```

4. Create a PostgreSQL superuser login for the setup wizard (first time only)

```bash
sudo -u postgres psql -c "CREATE ROLE ecube WITH SUPERUSER LOGIN PASSWORD 'ecube';"
```

5. Install PAM service config (first time only)

```bash
sudo cp deploy/ecube-pam /etc/pam.d/ecube
```

6. Start backend

```bash
sudo .venv/bin/uvicorn app.main:app --reload
```

7. In a second terminal, install dependencies and run the development frontend

```bash
cd frontend && npm ci && npm run dev
```

If you are editing the in-app help during development, regenerate the packaged help file from the repository root after changing the source manual or help generator:

```bash
node scripts/build-help.mjs
```

Then open the setup wizard at `http://localhost:5173` to provision the application database/user, run migrations, and create the first ECUBE admin user. The wizard auto-fills superuser credentials from `PG_SUPERUSER_NAME`/`PG_SUPERUSER_PASS` in `.env` (defaulting to `ecube`/`ecube`).

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
cp .env.example .env
```

`DATABASE_URL` is written automatically by the setup wizard after provisioning. No manual edits to `.env` are required for a standard local dev setup.

Key settings for development:

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | (written by setup wizard) | Set automatically after the wizard provisions the database |
| `SECRET_KEY` | (built-in dev default) | JWT signing key; change in production |
| `ROLE_RESOLVER` | `local` | Uses OS group → role mapping |

See [02 — Configuration Reference](../operations/04-configuration-reference.md) for the full list.

### Pre-Commit Hook (Optional)

The versioned pre-commit hook blocks commits when generated documentation assets are stale. Today it enforces QA test-case spreadsheet sync, in-app help sync, and DBML schema sync.

```bash
git config core.hooksPath .githooks
```

When staged changes touch [docs/testing/03-qa-testing-guide.md](../testing/03-qa-testing-guide.md) or [docs/testing/ecube-qa-test-cases.xlsx](../testing/ecube-qa-test-cases.xlsx), the hook runs `python3 scripts/sync_qa_test_cases.py --check`.

When staged changes touch [docs/operations/13-user-manual.md](../operations/13-user-manual.md), [frontend/public/help/manual.html](../../frontend/public/help/manual.html), [scripts/build-help.mjs](../../scripts/build-help.mjs), or [frontend/package.json](../../frontend/package.json), the hook runs `npm --prefix frontend run build:help:check` and blocks the commit until the generated help file is refreshed and staged.

When staged changes touch [app/models](../../app/models) or [docs/database/ecube-schema.dbml](../../docs/database/ecube-schema.dbml), the hook runs `python3 scripts/generate_dbml_schema.py --check` and blocks the commit until you regenerate and stage the DBML file. Release-migration text and generator-script changes alone do not trigger this check because the DBML file is generated from SQLAlchemy model metadata, not directly from Alembic modules.

When staged changes touch [postman/ecube-postman-collection.json](../../postman/ecube-postman-collection.json), [scripts/check_postman_collection.py](../../scripts/check_postman_collection.py), [scripts/sync_postman_collection.py](../../scripts/sync_postman_collection.py), or API contract surfaces under [app/routers](../../app/routers), [app/schemas](../../app/schemas), [app/main.py](../../app/main.py), [app/auth.py](../../app/auth.py), or [app/dependencies.py](../../app/dependencies.py), the hook runs `python3 scripts/check_postman_collection.py` and blocks the commit if the collection references a method or route that no longer exists in the generated OpenAPI schema or if the generated OpenAPI sync folder is stale. Refresh it with `python3 scripts/sync_postman_collection.py`, then restage the collection.

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
  versions/            # Migration scripts
tests/
  conftest.py          # Shared fixtures (SQLite StaticPool, role-specific clients)
  test_*.py            # Unit and integration tests
  integration/         # Integration test suite (requires --run-integration)
  hardware/            # Hardware-in-the-loop tests (requires --run-hardware)
scripts/
  run_schemathesis.sh    # One-command Schemathesis API fuzz testing
  sync_qa_test_cases.py  # QA spreadsheet ↔ markdown sync tool
  check_postman_collection.py  # Postman collection ↔ OpenAPI route drift check
  sync_postman_collection.py  # Regenerate Postman OpenAPI sync entries
docs/
  design/              # Architecture and design specifications
  development/         # This folder — developer documentation
  operations/          # Production deployment and operations guides
  requirements/        # Requirements documents
  testing/             # QA testing guides and test-case tracking
```

---

## Running the Application

The ECUBE backend and frontend run natively on the host. PostgreSQL must be running before starting the backend.

### Start PostgreSQL

Linux:

```bash
sudo systemctl start postgresql
```

### Create the Setup Wizard Superuser (First Time Only)

The setup wizard connects to PostgreSQL using the credentials from `PG_SUPERUSER_NAME`/`PG_SUPERUSER_PASS` in `.env` (defaulting to `ecube`/`ecube`). Create this role once:

```bash
sudo -u postgres psql -c "CREATE ROLE ecube WITH SUPERUSER LOGIN PASSWORD 'ecube';"
```

`SUPERUSER` is required on PostgreSQL 16+ because `CREATEROLE` alone no longer grants implicit `SET ROLE` access to roles it creates.

### PAM Service Config

The `POST /auth/token` login endpoint authenticates OS credentials via Linux PAM. Two one-time setup steps are required.

```bash
sudo cp deploy/ecube-pam /etc/pam.d/ecube
```

### Backend Execution

Run from the repository root (with your virtual environment activated):

```bash
Fallback failed-job diagnostics to audit events

Use the latest sanitized JOB_FAILED or JOB_TIMEOUT audit entry
when file-based log correlation is unavailable, so Job Detail
still shows a related failure event in console-only deployments.
```

Without root, all login attempts return `401 Unauthorized` regardless of credentials. In production, the service runs as root via systemd — the same restriction applies.

### Frontend Execution

Run in a separate terminal:

```bash
cd frontend
npm ci
npm run dev
```

To access the frontend from another machine, browse to `http://<host-ip>:5173`.

### In-App Help Development

ECUBE's packaged in-app help is generated static HTML, not handwritten frontend component markup.

The development workflow uses these files and tools:

- Canonical source content: `docs/operations/13-user-manual.md`
- Generator: `scripts/build-help.mjs`
- Generated output: `frontend/public/help/manual.html`
- Frontend build hook: `frontend/package.json` scripts `build:help`, `build:help:check`, and `build`
- Frontend consumption point: `frontend/src/components/layout/AppHeader.vue` loads `/help/manual.html` in the Help modal iframe

Typical workflow while developing help content:

1. Edit `docs/operations/13-user-manual.md` when the canonical user-facing content changes.
2. Edit `scripts/build-help.mjs` when the curated in-app help output, styling, numbering, filtering, or theme behavior needs to change.
3. Regenerate the packaged help file from the repository root:

```bash
node scripts/build-help.mjs
```

4. Open the frontend and review the Help modal against the regenerated `frontend/public/help/manual.html` output.
5. Before committing or packaging, verify the generated help file is current:

```bash
node scripts/build-help.mjs --check
```

6. When validating frontend packaging behavior, use the existing frontend build/test hooks:

```bash
npm --prefix frontend run build:help
npm --prefix frontend run build:help:check
npm --prefix frontend run test:unit -- --run src/build/__tests__/helpAsset.spec.js
```

Important workflow notes:

- `npm run dev` serves the generated file from `frontend/public/`, but it does not regenerate help automatically when the manual changes.
- `npm --prefix frontend run build` runs `build:help:check` before `vite build`, so local builds fail fast if the checked-in help file is stale instead of regenerating it implicitly.
- `scripts/package-local.sh` also runs `npm run build:help:check`, keeping local packaging and CI packaging on the same verification-only behavior.
- `.githooks/pre-commit` and `.github/workflows/help-sync-check.yml` enforce the same help-sync rule before commits and in CI.
- The in-app help is curated from the user manual rather than mirroring it verbatim; generator logic controls which sections are excluded, renumbered, or restyled for the modal experience.

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
# Ensure the current release-scoped migration exists (or print its path)
ecube-release-migration ensure

# Create the current release-scoped migration once when a new unreleased
# ECUBE version starts and no versioned migration file exists yet
ecube-release-migration create

# Refresh the current release-scoped migration from model metadata
ecube-release-migration autogenerate

# Apply
alembic upgrade head

# Check current version
alembic current

# Rollback one step
alembic downgrade -1
```

For ECUBE's pre-release workflow, all schema changes for the current app version accumulate in a single Alembic module named from `project.version`, for example `alembic/versions/v0_2_0.py`. Run `ecube-release-migration ensure` first, use `ecube-release-migration create` only when a new unreleased version starts, and use `ecube-release-migration autogenerate` to refresh that one file from current model metadata instead of creating additional unreleased revisions.

### Reset PostgreSQL Database (Start Fresh)

For local PostgreSQL installs, run a single command block:

```bash
sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'ecube' AND pid <> pg_backend_pid();"
sudo -u postgres psql -c "DROP DATABASE IF EXISTS ecube;"
sudo -u postgres psql -c "DROP OWNED BY ecube; DROP ROLE IF EXISTS ecube;"
sudo -u postgres psql -c "CREATE ROLE ecube WITH SUPERUSER LOGIN PASSWORD 'ecube';"
sudo -u postgres psql -c "CREATE DATABASE ecube OWNER ecube;"
```

After recreating the database, apply migrations again:

```bash
alembic upgrade head
```

### Remove ecube role

Run this only after the `ecube` database has already been dropped or reassigned.
```bash
sudo -u postgres psql -c "DROP OWNED BY ecube; DROP ROLE IF EXISTS ecube;"
```

### Migration Naming

Release-scoped migration filenames use `v<major>_<minor>_<patch>.py`, derived from `[project].version` in `pyproject.toml`. While a version remains unreleased, ECUBE keeps exactly one mutable migration module for that version, and `ecube-release-migration create` fails clearly if that file already exists. Once the version ships, that file becomes immutable and the next unreleased version gets its own release-scoped migration module.

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
