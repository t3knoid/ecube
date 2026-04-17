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
- Drive states: `DISCONNECTED → AVAILABLE → IN_USE` (finite-state machine; transitions gated through a single service module).
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

## Architecture and Trust Boundaries

- UI code must never access hardware, the filesystem, or the database directly.
- All OS-level operations must go through interfaces in `app/infrastructure`.
- Business logic belongs in `services/`, not in routers.
- Routers validate input, enforce roles, and delegate to services.

## Security Requirements

- All security-relevant events must be logged to `audit_logs`.
- Internal paths, credentials, and hardware identifiers must not be exposed in API responses or logs.
- Endpoints must declare error responses using shared `R_*` schemas.
- Role checks must use `require_roles()`.
- All user input used in filesystem paths, shell commands, or API calls must be sanitized.
- Directory traversal risks must be eliminated (normalize paths before use).
- `eval`, `exec`, `Function()`, and dynamic code execution are forbidden.
- Insecure defaults (`debug=True`, wide-open CORS, permissive permissions) are forbidden.
- Unsafe file operations that could overwrite or delete data unintentionally must be guarded.

## Shell and Environment Safety

- `shell=True` is forbidden in Python.
- All environment variable expansions must be quoted (`"${VAR}"`).
- Forbid unquoted `$VAR` in `cp`, `mv`, `rm`, `mkdir`, `ln`, `tar`, `rsync`, `find`, `grep`, `sed`, `awk`, `cut`, `xargs`.
- `.env` files must not be parsed with whitespace-collapsing tools (e.g., `xargs`, `awk`, `cut` without quoting).
- Paths must be constructed using `printf '%s/%s'` or Python `pathlib`, never string concatenation.
- Bash scripts must use `set -euo pipefail`.
- POSIX `sh` scripts must use `|| exit 1` or equivalent for error handling.
- Forbid backticks; require `$(cmd)` for command substitution.
- Require safe parameter expansion: `${VAR}`, `${VAR:-default}`, `${VAR:?error}`.
- Scripts must run under `/bin/sh` unless bash-specific features are required and documented.
- Forbid GNU-only flags unless explicitly documented and validated.
- Reject ambiguous or unsafe operator input early with clear error messages.
- Forbid silent failures (e.g., `rm -f` without logging).

## Docker and Compose Safety

### Dockerfile

- Base images must be pinned to a specific version or digest (no `latest`).
- Multi-stage builds are required; production images must not include compilers or debugging tools.
- Prefer minimal base images (`python:3.11-slim`, `alpine`, `distroless`).
- Forbid `COPY . .` unless explicitly justified; prefer targeted `COPY`.
- `.dockerignore` must exclude `node_modules`, `venv`, build artifacts, secrets, `.git`.
- Require `--no-cache-dir` for `pip install`, `apt-get clean`, and removal of `/var/lib/apt/lists/*`.
- Require explicit `USER` directive; forbid running as root unless documented and required.
- Forbid embedding secrets, tokens, or credentials in Dockerfiles, `ENV`, or `ARG`.
- Forbid `chmod -R 777` or other overly permissive patterns.
- Require explicit file permissions for copied files.
- Require healthchecks for long-running services.

### Entrypoint Scripts

- Entrypoints must use exec form (`["python", "app.py"]`).
- Require `set -euo pipefail` in all bash entrypoints.
- Forbid unquoted `$VAR` in entrypoint scripts.
- Require explicit error messages for invalid configuration.
- Complex logic must live in separate tested scripts, not inline in Compose `command` fields.

### Docker Compose

- Docker Compose must not use nested variable interpolation (`${A:-${B}}`).
- Only single-level defaults are allowed: `${VAR:-default}`.
- All environment variables used in Compose must be documented in `.env.example`.
- Long-running services must define healthchecks and resource limits (`cpus`, `mem_limit`).
- All services must define a restart policy. `restart: always` is forbidden unless explicitly justified.
- All services must declare explicit networks.
- Services that depend on others must declare `depends_on` paired with healthchecks.
- Forbid mounting the Docker socket unless explicitly required and documented.
- Secrets must be mounted via Docker secrets, not environment variables or bind mounts.
- Forbid bind-mounting sensitive host paths.
- Shell-form `CMD` or `ENTRYPOINT` is forbidden; require exec form.
- Forbid using mutable tags in production.

## System Degradation Prevention

- No long-running synchronous operations in FastAPI endpoints.
- No CPU-heavy or IO-heavy work on the event loop.
- No unbounded loops, recursion, or polling that can degrade performance.
- No unbounded `ThreadPoolExecutor` or creation of new executors per request.
- No N+1 database queries or inefficient ORM patterns.
- No unnecessary re-renders or reactive explosions in Vue components.
- No large directory scans done repeatedly instead of cached or batched.
- No blocking filesystem operations inside Vue or frontend logic.
- No unbounded growth of logs, buffers, or in-memory collections.
- Background tasks and temporary files must have cleanup logic.
- Copy/verify/manifest tasks must not starve the system or block other operations.
- Drive lifecycle transitions must be handled safely and atomically.

## Logging Rules

- Logging helpers must not drop arguments.
- Printf-style formatting must not be used unless the logger supports it.
- Prefer structured logging with context objects.
- Logging calls must not silently lose information (e.g., extra args dropped, `statusText` lost).
- Logger wrapper signatures must match the underlying logger behavior.

## Pagination and Filesystem Safety

- Paginated endpoints must not materialize entire directories (no `list(os.scandir())`, no `sorted(os.scandir())`).
- Use streaming iteration (`os.scandir`) and incremental pagination.
- Avoid global sorting of large directory listings unless documented and justified.
- Return `has_more` instead of computing exact totals when totals are expensive.
- O(n) or O(n log n) work inside paginated endpoints must be avoided.
- No patterns that can cause memory blow-ups or DoS risk on large mount points.

## Test Requirements

### Pytest Style

- Tests must use pytest, not `unittest.TestCase`.
- Fixtures must be used instead of `setUp`/`tearDown`.
- Tests must use bare `assert` statements, not `self.assert*`.
- Exception assertions must use `pytest.raises`.
- Test names must use snake_case and must match the behavior being tested.
- Mixing unittest and pytest styles is forbidden.
- Tests must avoid shared mutable state; prefer fixture injection.

### Test Coverage

- Every new API endpoint must include corresponding automated tests.
- Tests must cover: role-based access control, input validation, pagination/limit parameters, redaction of sensitive fields, derived/aggregated fields, error conditions, and edge cases.
- New behavior (aggregation, redaction, derived fields) must have explicit correctness tests.
- New endpoints must match or exceed the coverage level of existing endpoints in the same family.
- Tests must verify that sensitive fields are redacted, omitted, or transformed per ECUBE policy.

### Test Hygiene

- Tests must not contain unused imports, fixtures, helpers, or unreachable code.
- Tests must not include unused parameters or dead code paths.
- Test names and docstrings must accurately describe what the test exercises.
- No leftover debug statements (`print`, `pdb`, `debugger`).

## Frontend Rules

### Accessibility (WCAG 2.1 A/AA)

- All interactive UI elements must be operable with keyboard only.
- Clickable elements must not use `<div>` or `<span>` without `tabindex="0"`, `@keydown.enter`/`@keydown.space` handlers, and `role="button"` or `role="link"`.
- Prefer native interactive elements (`<button>`, `<a>`, `<input>`) over custom widgets.
- Focus order must be logical and preserved. Focus styles must never be removed.
- ARIA roles, labels, and attributes must be used correctly and only when needed.
- Every input must have a visible label or `aria-label`.
- Error messages must be programmatically associated with inputs.
- Required fields must be indicated visually and programmatically.
- Text must meet minimum contrast ratios. Color must not be the only means of conveying meaning.
- Icons used as buttons must have accessible labels.
- Focus must be moved intentionally after: opening dialogs, closing dialogs, navigating directories, triggering destructive actions.
- Modals must trap focus correctly and restore focus on close.
- Vue components emitting click events must also support keyboard activation.
- Vue props controlling interactivity (`disabled`, `active`, `selected`) must be reflected in ARIA attributes.

### Directory Browser and Tree View

- Directory rows, tree items, and file browser entries must be fully keyboard accessible.
- Do not use `<tr @click>` or `<div @click>` for navigation without `tabindex` and keyboard handlers.
- Prefer rendering directory names as `<button>` or `<a>` elements inside table cells.
- Arrow key navigation must be supported where appropriate (tree view).
- Focus must move predictably when expanding/collapsing tree nodes.
- Screen readers must be able to identify directory vs file items.

### CSS and Template Consistency

- CSS selectors must not be defined unless they are used in the template.
- Orphaned or stale styles left behind after refactors must be removed.
- All defined classes must correspond to actual rendered states or documented variants.
- Mismatches between template class names and style selectors must be corrected.

## Code Quality

- No dead code, commented-out blocks, or unused imports.
- No leftover debug statements (`console.log`, `print`, `pdb`, `debugger`).
- Duplicated logic must be extracted into utilities or composables.
- Constants, enums, and shared values must not be duplicated across files.
- Consistent naming conventions across backend and frontend.
- Error messages and exceptions must be consistent and meaningful.
- Code must follow Black, Ruff, ESLint, and Prettier formatting rules.
- All new behavior must include tests.

## Behavior-Comment Consistency

- All comments, docstrings, and inline explanations must accurately describe the actual implementation.
- Do not write comments that describe stricter behavior than the code enforces.
- Do not write comments that describe looser behavior than the code enforces.
- Do not write comments that imply constraints the code does not validate (e.g., "direct child" when nesting is allowed).
- Do not write comments that describe security or safety guarantees the code does not implement.
- When changing behavior, update all related comments in the same change.
- When a mismatch is found, either tighten the code to match the comment or update the comment to match the actual behavior.

## Audit Log Redaction & Provider Error Safety

- Provider errors, OS errors, and mount/drive/mountpoint failures must **never** be logged verbatim.  
- Raw error strings often contain internal paths (e.g., `/dev/...`, `/mnt/...`, `/run/media/...`) or system details that must not appear in `audit_logs`.
- All audit log entries must use **sanitized**, **redacted**, or **structured** error information.
- When generating code that logs failures (e.g., `DRIVE_MOUNT_FAILED`, `NETWORK_MOUNT_FAILED`, `DRIVE_EJECT_FAILED`), Copilot must:
  - redact or strip path-like substrings  
  - avoid persisting raw exception messages  
  - prefer structured fields: `{ error_code, message, details }`  
  - ensure messages contain **no filesystem paths**, **no device identifiers**, and **no sensitive OS details**

### Required patterns
- Use a helper such as `sanitize_error_message(err)` before logging.
- Or extract a safe error code and a human-readable message.
- Or map provider errors to internal error enums.

### Forbidden patterns
- `audit_logs.create(..., details=str(err))`
- Logging raw exceptions that include `/dev/`, `/mnt/`, `/media/`, `/run/`, or absolute paths.
- Passing provider error objects directly into audit log schemas.

### When in doubt
- Prefer:  
  `{"error_code": "MOUNT_FAILED", "message": "Provider mount operation failed", "details": redacted_details}`  
- Never:  
  `{"details": str(err)}`