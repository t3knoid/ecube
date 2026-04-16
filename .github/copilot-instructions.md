# ECUBE — Copilot Coding Agent Instructions

## Project Summary

ECUBE (Evidence Copying & USB Based Export) is a secure evidence export platform that copies eDiscovery data onto encrypted USB drives from a Linux-based copy machine. It enforces strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Technology Stack

- **Language:** Python 3.11+
- **Web framework:** FastAPI (REST API + OpenAPI generation)
- **ORM:** SQLAlchemy with Alembic migrations
- **Database:** PostgreSQL 14+ (production), SQLite in-memory (tests)
- **Background jobs:** FastAPI `BackgroundTasks` + bounded `ThreadPoolExecutor` (copy/verify/manifest tasks)
- **UI layer:** Vue 3 SPA (Vite build); bundled into the `ecube-app` Docker image and served by FastAPI in both native and Docker deployments. Communicates via HTTPS API only.
- **Testing:** pytest with SQLite `StaticPool` in-memory database

## Repository Layout

```
.github/
  copilot-instructions.md   # This file
docs/
  requirements/             # Requirements documents (00–10)
  design/                   # Design documents (00–10, mirrors requirements)
app/
  routers/        # FastAPI routers (one per domain: drives, jobs, mounts, browse, audit, …)
  models/         # SQLAlchemy ORM models
  services/       # Domain service modules (business logic, state machines)
  schemas/        # Pydantic request/response schemas
  repositories/   # Data-access layer (one class per aggregate)
  infrastructure/ # Platform abstraction interfaces + concrete implementations (Linux reference)
  utils/          # Shared helpers (sanitize, client_ip, docker detection)
alembic/
  versions/       # Alembic migration scripts
tests/
  conftest.py     # Shared fixtures; uses SQLite StaticPool
frontend/         # Vue 3 SPA (Vite build)
install.sh        # Automated native Linux installer
pyproject.toml    # Project metadata and dependencies
```

## Bootstrap & Development Setup

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

Use the `require_roles(*roles)` decorator pattern (see `docs/design/10-security-and-access-control.md`) to gate every endpoint.

### Project Isolation (Critical)

- A drive's `current_project_id` is bound on initialization and **must** be enforced on every write.
- Mismatched project writes must be rejected **before** any copy begins.
- Every denial must be recorded in `audit_logs` with actor, drive, requested project, and reason.

### Platform Abstraction

- All OS-specific operations (drive discovery, filesystem detection, formatting, drive mounting, mount/unmount of network shares, eject, user management) are defined as `typing.Protocol` or `abc.ABC` interfaces in `app/infrastructure/`.
- Concrete implementations satisfy those interfaces for a specific platform. Linux is the reference implementation.
- Services depend on the interface, not the implementation. Tests inject fakes/mocks via `dependency_overrides` or constructor arguments.
- When adding new OS-level functionality, define the interface first, then implement the Linux concrete class.

## Domain Model Overview

| Domain | Key Tables |
|--------|-----------|
| Hardware | `usb_hubs`, `usb_ports`, `usb_drives` (includes `mount_path` for auto-mounted drives) |
| Mounts | `network_mounts` |
| Jobs | `export_jobs`, `export_files`, `manifests`, `drive_assignments` |
| Audit | `audit_logs` (append-only, immutable timestamps) |
| System | `system_initialization`, `reconciliation_lock` (single-row guard tables) |
- Drive states: `EMPTY → AVAILABLE → IN_USE` (finite-state machine; transitions gated through a single service module).
- All enum columns use `native_enum=False`.
- Index tables by `project_id`, `status`, and recent timestamps.

## Key Design Documents

All design details live under `docs/design/`:

- `03-system-architecture.md` — component view and interaction pattern
- `04-functional-design.md` — drive FSM, project isolation, copy engine, audit
- `05-data-model.md` — table design notes and integrity constraints
- `06-rest-api-design.md` — normative API behavior, role expectations, constraints, and acceptance criteria
- `10-security-and-access-control.md` — role model, authorization matrix, `require_roles` pattern

## Coding Conventions

- Every security-relevant event (auth success/failure, role denials, drive init, file ops) must emit a structured JSON record to `audit_logs`.
- Introspection endpoints (`/introspection/*`) are **read-only** and must redact sensitive path or credential-like fields.
- API returns `401` for missing/invalid/expired tokens and `403` for role or project isolation violations.
- All error responses use the `ErrorResponse` schema (`app/schemas/errors.py`). Declare error responses on every route decorator using reusable response dicts (`R_400`, `R_401`, `R_403`, `R_404`, `R_409`, `R_422`, `R_500`, `R_503`, `R_504`) combined via `responses={**R_401, **R_403}`.
- Path-like fields use `StrictSafeStr` (rejects malformed Unicode with 422); non-path string fields use `SafeStr` (silently strips null bytes/surrogates). Both are defined in `app/utils/sanitize.py`.
- Background copy workers use bounded thread pools; progress updates (`copied_bytes`, file status) must be atomic.

## Continuous Integration

CI workflows are configured in `.github/workflows/`. Key pipelines:

1. **Tests** — backend (pytest), frontend (Vitest), integration (PostgreSQL), E2E (Playwright)
2. **Docker Build** — `ghcr.io/t3knoid/ecube-app`
3. **Security Scan** — static analysis and dependency vulnerability checks
4. **Schemathesis API Fuzz** — auto-generated requests from the OpenAPI schema
5. **Newman API Smoke** — Postman collection-based API smoke validation
