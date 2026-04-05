# ECUBE — Automated Test Requirements

**Audience:** Developers, Contributors  
**Scope:** Backend unit tests, backend integration tests, hardware-in-the-loop (HIL) tests, frontend unit tests, frontend E2E tests
**Last Updated:** April 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [Test Suite Layout](#2-test-suite-layout)
3. [Tooling and Dependencies](#3-tooling-and-dependencies)
4. [Running the Tests](#4-running-the-tests)
5. [Cross-Platform Testing Strategy](#5-cross-platform-testing-strategy)
6. [Test Infrastructure and Fixtures](#6-test-infrastructure-and-fixtures)
7. [Coding Conventions](#7-coding-conventions)
8. [Platform Compatibility Rules](#8-platform-compatibility-rules)
9. [Test Coverage Areas](#9-test-coverage-areas)
10. [Writing New Tests](#10-writing-new-tests)

---

## 1. Overview

ECUBE has five tiers of automated tests:

| Tier | Location | Tool | External Requirements |
|------|----------|------|-----------------------|
| **Backend unit** | `tests/` (top-level files) | pytest | None — uses in-memory SQLite |
| **Backend integration** | `tests/integration/` | pytest (`@pytest.mark.integration`) | PostgreSQL database |
| **Hardware-in-the-loop (HIL)** | `tests/hardware/` | pytest (`@pytest.mark.hardware`) | Physical USB hardware |
| **Frontend unit** | `frontend/src/**/__tests__/` | Vitest (jsdom) | Node.js |
| **Frontend E2E** | `frontend/e2e/` | Playwright (Chromium + WebKit) | Node.js + built frontend |

Backend unit tests are the primary automated quality gate. They use an in-memory SQLite database with `StaticPool` and mock all OS-level calls so they run on any platform (Linux, macOS, Windows) without external services.

Backend integration tests require only a PostgreSQL instance. Docker provides a portable way to supply that dependency on every platform without installing PostgreSQL natively. See [section 5](#5-cross-platform-testing-strategy) for the full strategy.

Frontend unit tests run in a jsdom environment via Vitest and cover Vue components, stores, composables, and the API client in isolation. Frontend E2E tests run against a locally built and previewed frontend using Playwright across Chromium and WebKit.

---

## 2. Test Suite Layout

```
tests/
  conftest.py                      # Shared fixtures and pytest hooks
  test_audit.py                    # Audit log API endpoints
  test_audit_logging.py            # Audit emission for all domain events
  test_auth.py                     # JWT token validation middleware
  test_auth_integration.py         # Auth middleware through real request cycle
  test_auth_login.py               # POST /auth/token (local PAM login)
  test_authorization.py            # Role-based access control (all roles × endpoints)
  test_callback.py                 # Async callback URL notifications
  test_client_ip.py                # Client IP extraction
  test_configuration_api.py        # Admin configuration API
  test_concurrency.py              # Thread-safe progress updates in copy engine
  test_config_settings.py          # Configuration loading and validation
  test_copy_engine.py              # File copy worker (hash, progress, threading)
  test_database_setup.py           # Database provisioning API
  test_db_exception_handling.py    # Database error → HTTP response mapping
  test_discovery.py                # USB drive discovery service
  test_drive_eject.py              # Drive eject (prepare-eject, finalize-eject)
  test_drives.py                   # Drive CRUD and state machine transitions
  test_endpoint_structure.py       # OpenAPI structure and response schema contracts
  test_exception_handlers.py       # Global exception handler middleware
  test_files.py                    # File hashes and compare endpoints
  test_filesystem_format.py        # Drive formatting operations
  test_hub_port_enrichment.py      # USB hub/port metadata enrichment
  test_introspection.py            # /introspection/* read-only endpoints
  test_jobs.py                     # Job CRUD, start, verify, manifest
  test_logging.py                  # Structured logging and log-file endpoints
  test_migrations.py               # Alembic schema upgrade/downgrade
  test_mounts.py                   # Network mount management
  test_oidc_service.py             # OIDC role resolver
  test_os_user_management.py       # OS user/group operations and admin endpoints
  test_port_enablement.py          # USB port enable/disable
  test_reconciliation.py           # Startup reconciliation (stale job recovery)
  test_repositories.py             # Repository layer (SQLAlchemy queries)
  test_role_resolver.py            # Role resolver factory
  test_session_management.py       # Session storage (cookie / Redis)
  test_thread_count_validation.py  # thread_count input validation
  test_ui_telemetry.py             # Frontend UI telemetry ingestion
  test_unicode_sanitization.py     # SafeStr / StrictSafeStr input sanitization
  test_user_roles.py               # DB-backed user-role assignments
  integration/
    conftest.py                    # Integration-specific fixtures
    test_auth_use_cases_integration.py
    test_concurrency_scaffold_integration.py
    test_drives_use_cases_integration.py
    test_introspection_use_cases_integration.py
    test_jobs_use_cases_integration.py
    test_mounts_use_cases_integration.py
    test_smoke_integration.py
  hardware/
    test_usb_hub_hil.py            # Physical USB hub detection and ports

frontend/
  src/
    api/
      __tests__/
        client.spec.js             # Axios API client
    components/
      common/
        __tests__/
          ConfirmDialog.spec.js    # Modal component
          DataTable.spec.js        # Sortable/paginated table
          ProgressBar.spec.js      # Job progress indicator
          StatusBadge.spec.js      # Drive/job state badge
      __tests__/
        HelloWorld.spec.js
    composables/
      __tests__/
        usePolling.spec.js         # Periodic refresh composable
        useRoleGuard.spec.js       # Role-based navigation guard
    utils/
      __tests__/
        navigationTrace.spec.js    # Navigation tracing and telemetry filters
    stores/
      __tests__/
        auth.spec.js               # Pinia auth store
        theme.spec.js              # Pinia theme store
  e2e/
    audit.spec.js                  # Audit log view
    dashboard.spec.js              # Dashboard / home page
    drives.spec.js                 # Drive management flows
    jobs.spec.js                   # Job creation and monitoring
    keyboard.spec.js               # Keyboard accessibility
    login.spec.js                  # Authentication flow
    mounts.spec.js                 # Network mount management
    role-gating.spec.js            # Role-based UI gating
    setup-wizard.spec.js           # First-run setup wizard
    theme.spec.js                  # Theme switching
    users.spec.js                  # User management
    vue.spec.js
```

---

## 3. Tooling and Dependencies

### 3.1 Backend

Test dependencies are declared under `[project.optional-dependencies] dev` in `pyproject.toml`:

| Package | Purpose |
|---------|---------|
| `pytest>=8.0.0` | Test runner |
| `pytest-asyncio>=0.23.0` | `async` test support (mode: `STRICT`) |
| `pytest-mock>=3.12.0` | `mocker` fixture and `@patch` helpers |
| `httpx>=0.27.0` | `TestClient` for ASGI request simulation |
| `redis>=4.2.0` | Required for session-management tests that exercise the Redis backend |
| `openpyxl>=3.1.0` | QA test case spreadsheet tooling |

Install all dev dependencies:

```bash
pip install -e ".[dev]"
```

### 3.2 Frontend

Frontend test dependencies are declared in `frontend/package.json` (dev dependencies):

| Package | Purpose |
|---------|---------|
| `vitest` | Unit test runner (Jest-compatible API) |
| `@vitest/coverage-v8` | V8-based code coverage |
| `jsdom` | DOM environment for component rendering |
| `@vue/test-utils` | Vue component mounting and interaction helpers |
| `@playwright/test` | E2E test runner |
| `@axe-core/playwright` | Accessibility assertions in E2E tests |

Install frontend dependencies:

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium webkit  # first-time E2E setup
```

---

## 4. Running the Tests

### 4.1 Unit tests (default)

Runs all top-level tests in `tests/`, excluding integration and hardware tiers.

```bash
python -m pytest tests/ \
  --ignore=tests/integration \
  --ignore=tests/hardware \
  -v
```

Or equivalently (integration and hardware tests are **skipped by default** unless their flag is supplied):

```bash
python -m pytest tests/ -v
```

### 4.2 Integration tests

Requires a running PostgreSQL instance. Set `INTEGRATION_DATABASE_URL` before running.

```bash
export INTEGRATION_DATABASE_URL="postgresql://ecube:ecube@localhost:5432/ecube"
python -m pytest tests/integration/ -v --run-integration
```

CI-equivalent local run (matches `run-tests.yml` service defaults):

```bash
export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"
python -m pytest tests/integration/ -v --run-integration
```

If you are using the default platform compose postgres service, the database/user already exist. For manual PostgreSQL setup, create the database first if it does not exist:

```sql
CREATE USER ecube WITH PASSWORD 'ecube';
CREATE DATABASE ecube OWNER ecube;
```

### 4.3 Hardware-in-the-loop (HIL) tests

Requires physical USB hub hardware attached to the machine. Must run on Linux.

```bash
python -m pytest tests/hardware/ -v --run-hardware
```

### 4.4 Frontend unit tests

Runs all Vitest unit tests under `frontend/src/` with coverage:

```bash
cd frontend
npm run test:unit
```

Coverage thresholds are enforced for stores and composables (≥ 80 % lines). Coverage reports are written to `frontend/coverage/`.

### 4.5 Frontend E2E tests

Requires a built and previewed frontend. Playwright runs against `http://localhost:4173` (Vite preview):

```bash
cd frontend
npm run build
npx playwright test
```

The report is written to `frontend/playwright-report/`. To run interactively:

```bash
npx playwright test --ui
```

### 4.6 Quick smoke check

```bash
python -m pytest tests/ -q
# Expected output: N passed, M skipped
```

---

## 5. Cross-Platform Testing Strategy

### 5.1 Why Docker for integration tests

Unit tests run natively on Linux, macOS, and Windows without Docker — they need no external services. Integration tests, however, require PostgreSQL. Rather than requiring each developer to install PostgreSQL locally, use the platform compose file and start only the `postgres` service.

```text
needs Docker?   unit tests     integration tests    hardware tests
─────────────   ──────────     ─────────────────    ──────────────
Linux           no             yes (postgres only)  yes (+ USB HW)
macOS           no             yes (postgres only)  not supported
Windows         no             yes (postgres only)  not supported
```

### 5.2 Compose file roles

| File | Purpose | Exposes |
|------|---------|--------|
| `docker-compose.ecube.yml` | Linux/macOS compose file; use `up -d postgres` for dev/integration DB | `localhost:5432` (postgres), `localhost:8000` (API if app container is started) |
| `docker-compose.ecube-win.yml` | Windows compose file; use `up -d postgres` for dev/integration DB | `localhost:5432` (postgres), `localhost:8000` (API if app container is started) |

### 5.3 Running integration tests with Docker

**Step 1 — start the PostgreSQL container (Linux/macOS):**

```bash
docker compose -f docker-compose.ecube.yml up -d postgres
```

Windows equivalent:

```bash
docker compose -f docker-compose.ecube-win.yml up -d postgres
```

**Step 2 — run integration tests:**

```bash
INTEGRATION_DATABASE_URL=postgresql://ecube:ecube@localhost:5432/ecube \
  python -m pytest tests/integration/ -v --run-integration
```

**Step 3 — tear down (also removes the test data volume):**

```bash
docker compose -f docker-compose.ecube.yml down -v
```

On Windows, run `down -v` with `docker-compose.ecube-win.yml` instead.

`tests/integration/conftest.py` defaults to `postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration`. Set `INTEGRATION_DATABASE_URL` explicitly as shown above when using the platform compose files or when matching CI locally.

### 5.4 Exposing the API port for local development

Both platform compose files publish FastAPI port `8000` for development convenience when the app container is started. This is not a typical hardened deployment shape.

For production-style Docker deployments, expose only `8443` through `ecube-ui` and avoid direct host exposure of `8000`.

### 5.5 CI strategy

For installer-oriented package artifact generation details (including workflow triggers, tarball contents, and naming contract), see [CI Build and Installer Artifact Contract](../development/03-ci-build-and-installer-artifacts.md).

| Workflow | Trigger | What runs |
|----------|---------|----------|
| `run-tests.yml` — backend unit tests | push / PR | pytest unit tests on **Linux, macOS, Windows** matrix (no Docker) |
| `run-tests.yml` — backend integration tests | push / PR | pytest integration tests on Linux with a GitHub Actions PostgreSQL service container |
| `run-tests.yml` — frontend unit tests | push / PR | `npm run test:unit` (Vitest + coverage) on ubuntu-latest |
| `run-tests.yml` — frontend E2E tests | push / PR | `npx playwright test` (Chromium + WebKit) on ubuntu-latest; Playwright report uploaded as artifact |
| `docker-build.yml` — build & smoke test | push to main / PR / release | Builds both images, starts full stack, verifies `/health` |
| `docker-build.yml` — publish | GitHub Release only | Pushes images to GHCR, attaches production `docker-compose.yml` to the release |

### 5.6 Production release artifact

When a GitHub Release is published, the `docker-build.yml` workflow:

1. Builds and pushes `ecube-app` and `ecube-ui` to `ghcr.io/t3knoid/`.
2. Runs `scripts/generate_release_compose.py` to produce a `docker-compose.yml` that references the pushed images by tag (no `build:` directives).
3. Attaches that file to the GitHub Release so operators can deploy without a source checkout.

---

## 6. Test Infrastructure and Fixtures

### 6.1 Database

Unit tests use SQLite in-memory with `StaticPool` — no PostgreSQL instance is needed:

```python
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
```

`_app_database.SessionLocal` is replaced before `app.main` is imported so that modules that bind `SessionLocal` at import time (such as the copy engine) receive the test session factory.

Each test function gets a **fresh schema** (tables created on entry, dropped on exit) via the `db` fixture in `conftest.py`.

### 6.2 Standard Fixtures

Defined in `tests/conftest.py`:

| Fixture | Description |
|---------|-------------|
| `db` | SQLAlchemy session backed by in-memory SQLite. Schema is created/dropped per test. |
| `client` | `TestClient` authenticated as `processor` (default authenticated role). |
| `unauthenticated_client` | `TestClient` with no `Authorization` header. |
| `admin_client` | `TestClient` authenticated as `admin`. |
| `manager_client` | `TestClient` authenticated as `manager`. |
| `auditor_client` | `TestClient` authenticated as `auditor`. |
| `auth_headers` | `{"Authorization": "Bearer <token>"}` dict for `processor` role. |

All role-bearing clients inject a JWT signed with `settings.secret_key` directly — no PAM or OIDC call is made.

### 6.3 Custom Pytest Options

| Option | Effect |
|--------|--------|
| `--run-integration` | Enables tests marked `@pytest.mark.integration` |
| `--run-hardware` | Enables tests marked `@pytest.mark.hardware` |

---

## 7. Coding Conventions

### 7.1 SQLAlchemy / SQLite compatibility

All `Enum` columns in ORM models **must** use `native_enum=False`:

```python
# Correct
status = Column(Enum(DriveState, native_enum=False), ...)

# Wrong — breaks SQLite in tests
status = Column(Enum(DriveState), ...)
```

### 7.2 JSON columns

ORM models must use SQLAlchemy's `JSON` type (not `JSONB`). The Alembic migration
may use `JSONB` for the PostgreSQL-specific schema; the ORM model must be portable:

```python
# ORM model — portable, SQLite-compatible
details = Column(JSON, nullable=True)
```

### 7.3 Async tests

The project uses `asyncio_mode = "strict"` (set in `[tool.pytest.ini_options]`).
Async tests must be explicitly decorated:

```python
@pytest.mark.asyncio
async def test_something():
    ...
```

### 7.4 Dependency injection

Override FastAPI dependencies using `app.dependency_overrides` within the test, and
**always** clear them on teardown to avoid leaking state between tests:

```python
app.dependency_overrides[get_db] = override_get_db
# ... test body ...
app.dependency_overrides.clear()   # or use the fixture pattern in conftest.py
```

When a test needs to exercise a code path that calls a POSIX-only service (PAM, OS user
management), inject a `MagicMock` via `dependency_overrides` instead of skipping the test:

```python
from unittest.mock import MagicMock
from app.routers.auth import _get_pam

mock_pam = MagicMock()
mock_pam.authenticate.return_value = False
app.dependency_overrides[_get_pam] = lambda: mock_pam
```

### 7.5 Audit log assertions

Many tests assert that a specific audit event was emitted. Pass the live `db` session to
the endpoint's dependency override so the same session is visible to both the service
and the test assertion:

```python
log = db.query(AuditLog).filter_by(action="DRIVE_INITIALIZED").first()
assert log is not None
assert log.actor == "test-user"
```

---

## 8. Platform Compatibility Rules

The CI target platform is Linux, but tests must also **pass on Windows** (developer
workstations). The following rules apply.

### 8.1 POSIX-only modules (`pwd`, `grp`, `os.geteuid`)

`app/services/os_user_service.py` imports `pwd` and `grp` at module level with a
try/except that sets them to `None` on Windows. Any test that would directly import
these modules or exercise code paths that call `_require_posix()` **must** be guarded.

**Preferred approach — mock the modules at the service level:**

```python
@patch("app.services.os_user_service.pwd")
@patch("app.services.os_user_service.grp")
def test_something(mock_grp, mock_pwd):
    mock_pwd.getpwnam.side_effect = KeyError("no such user")
    ...
```

Both `pwd` **and** `grp` must be patched together — patching only one leaves the other
as `None`, which causes `_require_posix()` to raise on Windows.

**When direct import is unavoidable** — skip the test on Windows:

```python
import sys
import pytest

@pytest.mark.skipif(sys.platform == "win32", reason="requires POSIX grp/pwd modules")
def test_posix_only():
    import grp
    ...
```

### 8.2 Optional packages (`redis`)

Tests that exercise the Redis session backend require the `redis` package, which may
not be installed in all environments. Use `pytest.importorskip` at the top of each
such test:

```python
def test_redis_backend():
    pytest.importorskip("redis", reason="redis package required for this test")
    ...
```

### 8.3 File I/O in tests

When writing files and comparing their content in tests, use binary mode to avoid
Windows CRLF translation:

```python
# Correct
with open(path, "wb") as f:
    f.write(b"test content\n")
assert response.content == b"test content\n"

# Wrong — Windows converts \n → \r\n in text mode
with open(path, "w") as f:
    f.write("test content\n")
```

### 8.4 File handles and temp directories

Close any `RotatingFileHandler` (or other file handles) **before** the enclosing
`TemporaryDirectory` context exits. Windows cannot delete a file while a handle is
open.

```python
handler = RotatingFileHandler(log_path)
try:
    # ... test body ...
finally:
    handler.close()
    logging.getLogger().removeHandler(handler)
# TemporaryDirectory.__exit__ can now safely clean up
```

---

## 9. Test Coverage Areas

| Area | Key Test Files |
|------|---------------|
| Authentication (JWT middleware) | `test_auth.py`, `test_auth_integration.py` |
| Local login (PAM) | `test_auth_login.py` |
| OIDC role resolution | `test_oidc_service.py`, `test_role_resolver.py` |
| Role-based access control | `test_authorization.py` |
| Audit log API | `test_audit.py` |
| Audit emission (all events) | `test_audit_logging.py` |
| Drive state machine | `test_drives.py` |
| Drive discovery | `test_discovery.py` |
| Drive eject | `test_drive_eject.py` |
| Drive formatting | `test_filesystem_format.py` |
| USB port enablement | `test_port_enablement.py` |
| USB hub/port enrichment | `test_hub_port_enrichment.py` |
| Network mounts | `test_mounts.py` |
| Job lifecycle | `test_jobs.py` |
| Copy engine | `test_copy_engine.py`, `test_concurrency.py`, `test_thread_count_validation.py` |
| File hashes and comparison | `test_files.py` |
| Manifest generation | `test_jobs.py` |
| Introspection endpoints | `test_introspection.py` |
| Callback notifications | `test_callback.py` |
| OS user management | `test_os_user_management.py` |
| DB-backed user roles | `test_user_roles.py` |
| Session management (cookie/Redis) | `test_session_management.py` |
| Input sanitization | `test_unicode_sanitization.py` |
| Configuration (settings + admin API) | `test_config_settings.py`, `test_configuration_api.py` |
| Logging | `test_logging.py` |
| Migrations | `test_migrations.py` |
| Database provisioning API | `test_database_setup.py` |
| UI telemetry ingestion | `test_ui_telemetry.py` |
| Startup reconciliation | `test_reconciliation.py` |
| Repository layer | `test_repositories.py` |
| Exception handlers | `test_exception_handlers.py`, `test_db_exception_handling.py` |
| OpenAPI structure | `test_endpoint_structure.py` |
| Client IP extraction | `test_client_ip.py` |

---

## 10. Writing New Tests

### Checklist for new unit tests

- [ ] Use the `db`, `client`, or role-specific fixture from `conftest.py` rather than
  creating a new engine or `TestClient`.
- [ ] Do not connect to a real PostgreSQL database, filesystem, or USB device.
- [ ] Mock **all** OS-level calls (`subprocess`, `shutil`, `os.path`, PAM, `grp`, `pwd`).
- [ ] If the test is POSIX-only, apply the platform guard from [section 8.1](#81-posix-only-modules-pwd-grp-osgeteuid).
- [ ] Assert the audit log entry for every security-relevant operation.
- [ ] Use `native_enum=False` on any new `Enum` column.
- [ ] Use `JSON` (not `JSONB`) in ORM models.
- [ ] Clear `app.dependency_overrides` after the test (the fixtures do this automatically).

### Checklist for new integration tests

- [ ] Decorate with `@pytest.mark.integration`.
- [ ] Place the file under `tests/integration/`.
- [ ] Read `INTEGRATION_DATABASE_URL` from the environment via the integration `conftest.py`.
- [ ] Do not rely on a specific database state — seed all required data in the test or fixture.

### Checklist for new hardware tests

- [ ] Decorate with `@pytest.mark.hardware`.
- [ ] Place the file under `tests/hardware/`.
- [ ] Document the physical setup required in the test module docstring.
- [ ] Never run destructively (no drive wipe) without a confirmation guard or explicit skip condition.

### Checklist for new frontend unit tests

- [ ] Place the file under `src/<module>/__tests__/` alongside the source file it tests.
- [ ] Use `@vue/test-utils` `mount`/`shallowMount` for component tests; use Vitest directly for stores and composables.
- [ ] Mock API calls via `vi.mock` — do not make real HTTP requests.
- [ ] Assert both the happy path and error/empty states.
- [ ] Ensure coverage thresholds (≥ 80 % lines/statements for stores and composables) are maintained.

### Checklist for new frontend E2E tests

- [ ] Place the file under `frontend/e2e/` with a `.spec.js` extension.
- [ ] Use Playwright `page` fixtures — do not import Vue or Vitest APIs.
- [ ] Set up required backend state (drives, jobs, mounts) via API calls in a `beforeEach` / `test.beforeAll` hook or use a test-specific mock server.
- [ ] Add accessibility assertions using `@axe-core/playwright` where appropriate.
- [ ] Keep tests isolated — reset state in `afterEach` so test order does not matter.
