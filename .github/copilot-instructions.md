# ECUBE — Copilot Coding Agent Instructions

## Project Summary

ECUBE (Evidence Copying & USB Based Export) is a secure evidence export platform that copies eDiscovery data onto encrypted USB drives from a Linux-based copy machine. It enforces strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Technology Stack

- **Language:** Python 3.11+
- **Web framework:** FastAPI (REST API + OpenAPI generation)
- **ORM:** SQLAlchemy with Alembic migrations
- **Database:** PostgreSQL 14+ (production), SQLite in-memory (tests)
- **Background jobs:** Celery or RQ (copy/verify/manifest tasks)
- **UI layer:** React/Vue or server-rendered templates (presentation only; communicates via HTTPS API)
- **Testing:** pytest with SQLite `StaticPool` in-memory database

## Repository Layout

```
.github/
  copilot-instructions.md   # This file
documents/
  requirements/             # Requirements documents (00–10)
  design/                   # Design documents (00–10, mirrors requirements)
README.md
```

> **Note:** The application source code has not yet been scaffolded. When implementation begins, the expected layout is:
>
> ```
> app/
>   api/          # FastAPI routers (one per domain: mounts, drives, jobs, audit, introspection)
>   models/       # SQLAlchemy ORM models
>   services/     # Domain service modules (business logic, state machines)
>   schemas/      # Pydantic request/response schemas
>   infrastructure/  # Platform abstraction interfaces + concrete implementations (Linux reference)
>   migrations/   # Alembic migration scripts
> tests/
>   conftest.py   # Shared fixtures; uses SQLite StaticPool
> pyproject.toml  # Project metadata and dependencies
> ```

## Bootstrap & Development Setup

> Until `pyproject.toml` exists, use `pip install fastapi sqlalchemy alembic pytest httpx` to bootstrap.

Once `pyproject.toml` is present:

```bash
# Install the project and all dev dependencies
pip install -e ".[dev]"

# Apply database migrations
alembic upgrade head

# Run the development server
uvicorn app.main:app --reload

# Run all tests
python -m pytest tests/ -v
```

## Testing Conventions

- Tests use a **SQLite in-memory database** with `StaticPool` (never PostgreSQL).
- All SQLAlchemy `Enum` columns must use `native_enum=False` for SQLite compatibility.
- `AuditLog` (and any similar structured metadata) must use SQLAlchemy's portable `JSON` column type in **ORM models** so tests work with SQLite. In Alembic migrations, use PostgreSQL `JSONB` for the production schema and plain `JSON` for the SQLite test schema; when design/docs say "JSONB", implement this as `JSON` in models + `JSONB` in Postgres migrations.
- Test fixtures are defined in `tests/conftest.py`.

## Architecture & Security Model

### Trust Boundary

- **System Layer (trusted):** FastAPI service — enforces policy, executes mounts/copies, writes audit logs. Only component that touches the database and hardware.
- **UI Layer (untrusted):** Consumes HTTPS API only; never directly accesses the database or hardware.
- **Database:** Reachable only from the system-layer network segment.

### Roles

| Role        | Key Permissions |
|-------------|-----------------|
| `admin`     | Unrestricted |
| `manager`   | Drive lifecycle, mount management, job visibility |
| `processor` | Create/start jobs, view job/drive status |
| `auditor`   | Read-only: audit logs, file hashes, job metadata |

Use the `require_roles(*roles)` decorator pattern (see `documents/design/10-security-and-access-control.md`) to gate every endpoint.

### Project Isolation (Critical)

- A drive's `current_project_id` is bound on initialization and **must** be enforced on every write.
- Mismatched project writes must be rejected **before** any copy begins.
- Every denial must be recorded in `audit_logs` with actor, drive, requested project, and reason.

### Platform Abstraction

- All OS-specific operations (drive discovery, filesystem detection, formatting, mount/unmount, eject, user management) are defined as `typing.Protocol` or `abc.ABC` interfaces in `app/infrastructure/`.
- Concrete implementations satisfy those interfaces for a specific platform. Linux is the reference implementation.
- Services depend on the interface, not the implementation. Tests inject fakes/mocks via `dependency_overrides` or constructor arguments.
- When adding new OS-level functionality, define the interface first, then implement the Linux concrete class.

## Domain Model Overview

| Domain | Key Tables |
|--------|-----------|
| Hardware | `usb_hubs`, `usb_ports`, `usb_drives` |
| Mounts | `network_mounts` |
| Jobs | `export_jobs`, `export_files`, `manifests`, `drive_assignments` |
| Audit | `audit_logs` (append-only, immutable timestamps) |

- Drive states: `EMPTY → AVAILABLE → IN_USE` (finite-state machine; transitions gated through a single service module).
- All enum columns use `native_enum=False`.
- Index tables by `project_id`, `status`, and recent timestamps.

## Key Design Documents

All design details live under `documents/design/`:

- `03-system-architecture.md` — component view and interaction pattern
- `04-functional-requirements.md` — drive FSM, project isolation, copy engine, audit
- `05-data-model.md` — table design notes and integrity constraints
- `06-rest-api-specification.md` — all endpoints with required roles
- `10-security-and-access-control.md` — role model, authorization matrix, `require_roles` pattern

## Coding Conventions

- Every security-relevant event (auth success/failure, role denials, drive init, file ops) must emit a structured JSON record to `audit_logs`.
- Introspection endpoints (`/introspection/*`) are **read-only** and must redact sensitive path or credential-like fields.
- API returns `401` for missing/invalid/expired tokens and `403` for role or project isolation violations.
- Background copy workers use bounded thread pools; progress updates (`copied_bytes`, file status) must be atomic.

## Continuous Integration

No CI pipeline is configured yet. When adding one, validate:
1. `pip install -e ".[dev]"`
2. `alembic upgrade head` (against a test SQLite or PostgreSQL instance)
3. `python -m pytest tests/ -v`
4. A linter such as `ruff` or `flake8`
