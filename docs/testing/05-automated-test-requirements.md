# ECUBE — Automated Test Requirements

**Audience:** Developers, Contributors  
**Scope:** Unit tests, integration tests, hardware-in-the-loop (HIL) tests

---

## Table of Contents

1. [Overview](#1-overview)
2. [Test Suite Layout](#2-test-suite-layout)
3. [Tooling and Dependencies](#3-tooling-and-dependencies)
4. [Running the Tests](#4-running-the-tests)
5. [Test Infrastructure and Fixtures](#5-test-infrastructure-and-fixtures)
6. [Coding Conventions](#6-coding-conventions)
7. [Platform Compatibility Rules](#7-platform-compatibility-rules)
8. [Test Coverage Areas](#8-test-coverage-areas)
9. [Writing New Tests](#9-writing-new-tests)

---

## 1. Overview

ECUBE has three tiers of automated tests:

| Tier | Location | Marker | External Requirements |
|------|----------|--------|-----------------------|
| **Unit** | `tests/` (top-level files) | *(none — runs by default)* | None — uses in-memory SQLite |
| **Integration** | `tests/integration/` | `@pytest.mark.integration` | PostgreSQL database |
| **Hardware-in-the-loop (HIL)** | `tests/hardware/` | `@pytest.mark.hardware` | Physical USB hardware |

Unit tests are the primary automated quality gate. They use an in-memory SQLite database with `StaticPool` and mock all OS-level calls so they run on any platform without external services.

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
```

---

## 3. Tooling and Dependencies

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
export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5432/ecube_integration"
python -m pytest tests/integration/ -v --run-integration
```

Create the test database first if it does not exist:

```sql
CREATE USER ecube_test WITH PASSWORD 'ecube_test';
CREATE DATABASE ecube_integration OWNER ecube_test;
```

### 4.3 Hardware-in-the-loop (HIL) tests

Requires physical USB hub hardware attached to the machine. Must run on Linux.

```bash
python -m pytest tests/hardware/ -v --run-hardware
```

### 4.4 Quick smoke check

```bash
python -m pytest tests/ -q
# Expected output: N passed, M skipped
```

---

## 5. Test Infrastructure and Fixtures

### 5.1 Database

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

### 5.2 Standard Fixtures

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

### 5.3 Custom Pytest Options

| Option | Effect |
|--------|--------|
| `--run-integration` | Enables tests marked `@pytest.mark.integration` |
| `--run-hardware` | Enables tests marked `@pytest.mark.hardware` |

---

## 6. Coding Conventions

### 6.1 SQLAlchemy / SQLite compatibility

All `Enum` columns in ORM models **must** use `native_enum=False`:

```python
# Correct
status = Column(Enum(DriveState, native_enum=False), ...)

# Wrong — breaks SQLite in tests
status = Column(Enum(DriveState), ...)
```

### 6.2 JSON columns

ORM models must use SQLAlchemy's `JSON` type (not `JSONB`). The Alembic migration
may use `JSONB` for the PostgreSQL-specific schema; the ORM model must be portable:

```python
# ORM model — portable, SQLite-compatible
details = Column(JSON, nullable=True)
```

### 6.3 Async tests

The project uses `asyncio_mode = "strict"` (set in `[tool.pytest.ini_options]`).
Async tests must be explicitly decorated:

```python
@pytest.mark.asyncio
async def test_something():
    ...
```

### 6.4 Dependency injection

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

### 6.5 Audit log assertions

Many tests assert that a specific audit event was emitted. Pass the live `db` session to
the endpoint's dependency override so the same session is visible to both the service
and the test assertion:

```python
log = db.query(AuditLog).filter_by(action="DRIVE_INITIALIZED").first()
assert log is not None
assert log.actor == "test-user"
```

---

## 7. Platform Compatibility Rules

The CI target platform is Linux, but tests must also **pass on Windows** (developer
workstations). The following rules apply.

### 7.1 POSIX-only modules (`pwd`, `grp`, `os.geteuid`)

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

### 7.2 Optional packages (`redis`)

Tests that exercise the Redis session backend require the `redis` package, which may
not be installed in all environments. Use `pytest.importorskip` at the top of each
such test:

```python
def test_redis_backend():
    pytest.importorskip("redis", reason="redis package required for this test")
    ...
```

### 7.3 File I/O in tests

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

### 7.4 File handles and temp directories

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

## 8. Test Coverage Areas

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
| Configuration | `test_config_settings.py` |
| Logging | `test_logging.py` |
| Migrations | `test_migrations.py` |
| Database provisioning API | `test_database_setup.py` |
| Startup reconciliation | `test_reconciliation.py` |
| Repository layer | `test_repositories.py` |
| Exception handlers | `test_exception_handlers.py`, `test_db_exception_handling.py` |
| OpenAPI structure | `test_endpoint_structure.py` |
| Client IP extraction | `test_client_ip.py` |

---

## 9. Writing New Tests

### Checklist for new unit tests

- [ ] Use the `db`, `client`, or role-specific fixture from `conftest.py` rather than
  creating a new engine or `TestClient`.
- [ ] Do not connect to a real PostgreSQL database, filesystem, or USB device.
- [ ] Mock **all** OS-level calls (`subprocess`, `shutil`, `os.path`, PAM, `grp`, `pwd`).
- [ ] If the test is POSIX-only, apply the platform guard from [section 7.1](#71-posix-only-modules-pwd-grp-osgeteuid).
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
