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

Got it, Frank — you’re absolutely right to call out that the section I generated **did not match the formatting style** of your existing `copilot‑instructions.md`.

Your file uses:

- **H2 headers (`##`)** for major sections  
- **H3 headers (`###`)** sparingly  
- **Bullet lists** with short, declarative rules  
- **No emoji, no bold section titles, no callouts**  
- A clean, documentation‑style tone  
- No “marketing” language — just facts and constraints  

So the new section must follow that exact style.

Below is the **correctly formatted version**, rewritten to match your file *perfectly*.

You can paste this **directly at the bottom** of `copilot-instructions.md`.

---

## Architecture and Trust Boundaries

- UI code must never access hardware, the filesystem, or the database directly.  
- All OS-level operations must go through interfaces in `app/infrastructure`.  
- Business logic belongs in `services/`, not in routers.  
- Routers validate input, enforce roles, and delegate to services.

## Security Requirements

- All security‑relevant events must be logged to `audit_logs`.  
- Internal paths, credentials, and hardware identifiers must not be exposed.  
- Endpoints must declare error responses using shared `R_*` schemas.  
- Role checks must use `require_roles()`.

## Shell and Environment Safety

- `shell=True` is not allowed.  
- All environment variable expansions must be quoted (`"${VAR}"`).  
- `.env` files must not be parsed with whitespace‑collapsing tools.  
- Paths must be constructed using `printf '%s/%s'` or Python `pathlib`.  
- Bash scripts must use `set -euo pipefail`.

## Docker and Compose Safety

- Docker images must be pinned to a specific version (no `latest`).  
- Multi‑stage builds are required; production images must not include compilers or debugging tools.  
- Entrypoints must use exec form (`["python", "app.py"]`).  
- Docker Compose must not use nested variable interpolation (`${A:-${B}}`).  
- Long‑running services must define healthchecks and resource limits.

## Logging Rules

- Logging helpers must not drop arguments.  
- Printf‑style formatting must not be used unless the logger supports it.  
- Prefer structured logging with context objects.

## Pagination and Filesystem Safety

- Paginated endpoints must not materialize entire directories.  
- Use streaming iteration (`os.scandir`) and incremental pagination.  
- Avoid global sorting of large directory listings.

## Test Requirements

- Tests must use pytest, not `unittest.TestCase`.  
- Fixtures must be used instead of `setUp`/`tearDown`.  
- Tests must use bare `assert` statements, not `self.assert*`.  
- Exception assertions must use `pytest.raises`.  
- Tests must not contain unused imports, fixtures, helpers, or unreachable code.  
- Test names must use snake_case and must match the behavior being tested.

## Frontend Rules

- CSS selectors must not be defined unless they are used in the template.  
- All interactive elements must meet WCAG 2.1 A/AA requirements.  
- Clickable elements must not use `<div>` or `<span>` without proper roles, tabindex, and keyboard handlers.  
- Vue components must expose correct semantics and keyboard accessibility.

## Code Quality
- No dead code, commented‑out blocks, or unused imports.  
- Duplicated logic must be extracted into utilities or composables.  
- Code must follow Black, Ruff, ESLint, and Prettier formatting rules.  
- All new behavior must include tests.
