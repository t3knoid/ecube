# ECUBE — Automated Test Requirements

| Field | Value |
|---|---|
| Title | Automated Test Requirements |
| Purpose | Defines required standards for ECUBE backend unit, integration, HIL, frontend unit, and end-to-end automated testing. |
| Updated on | 04/08/26 |
| Audience | Developers, contributors. |

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Required Test Tiers](#2-required-test-tiers)
3. [Test Suite Layout](#3-test-suite-layout)
4. [Required Tooling](#4-required-tooling)
5. [Required Test Infrastructure](#5-required-test-infrastructure)
6. [Code-Level Test Requirements](#6-code-level-test-requirements)
7. [Platform Compatibility Requirements](#7-platform-compatibility-requirements)
8. [Coverage Requirements](#8-coverage-requirements)
9. [Coverage Areas](#9-coverage-areas)
10. [Requirements for New Tests](#10-requirements-for-new-tests)

---

## 1. Purpose and Scope

This document defines what must be true for ECUBE automated tests to be considered compliant.
It is normative and requirement-focused.

Execution procedures (commands, Docker steps, and CI workflow run details) are intentionally separated into the runbook document:
[docs/testing/02-automated-test-runbook.md](docs/testing/02-automated-test-runbook.md)

---

## 2. Required Test Tiers

ECUBE has five required tiers of automated tests:

| Tier | Location | Tool | Required Environment |
|------|----------|------|----------------------|
| **Backend unit** | `tests/` (top-level files) | pytest | In-memory SQLite only |
| **Backend integration** | `tests/integration/` | pytest (`@pytest.mark.integration`) | PostgreSQL |
| **Hardware-in-the-loop (HIL)** | `tests/hardware/` | pytest (`@pytest.mark.hardware`) | Physical USB hardware (Linux) |
| **Frontend unit** | `frontend/src/**/__tests__/` | Vitest (jsdom) | Node.js |
| **Frontend E2E** | `frontend/e2e/` | Playwright (Chromium + WebKit) | Node.js + built frontend |

Backend unit tests are the primary quality gate and must remain platform-portable through SQLite and mocking.

---

## 3. Test Suite Layout

```text
tests/
  conftest.py
  integration/
  hardware/
  test_*.py

frontend/
  src/**/__tests__/*.spec.js
  e2e/*.spec.js
```

Required active frontend E2E specs:

- `frontend/e2e/audit.spec.js`
- `frontend/e2e/dashboard.spec.js`
- `frontend/e2e/drives.spec.js`
- `frontend/e2e/jobs.spec.js`
- `frontend/e2e/keyboard.spec.js`
- `frontend/e2e/login.spec.js`
- `frontend/e2e/mounts.spec.js`
- `frontend/e2e/role-gating.spec.js`
- `frontend/e2e/setup-wizard.spec.js`
- `frontend/e2e/theme.spec.js`
- `frontend/e2e/users.spec.js`
- `frontend/e2e/vue.spec.js`

---

## 4. Required Tooling

### 4.1 Backend requirements

Test-related backend dependencies are sourced from:

- `pyproject.toml` `[project.dependencies]`
- `pyproject.toml` `[project.optional-dependencies].dev`

Required packages include:

- `pytest`
- `pytest-asyncio` (strict mode)
- `pytest-mock`
- `httpx`
- `redis` (for Redis-session test paths)
- `openpyxl`

### 4.2 Frontend requirements

Frontend test dependencies are defined in `frontend/package.json`.

Required packages include:

- `vitest`
- `@vitest/coverage-v8`
- `jsdom`
- `@vue/test-utils`
- `@playwright/test`
- `@axe-core/playwright`

---

## 5. Required Test Infrastructure

### 5.1 Unit database model

Unit tests must use SQLite in-memory with `StaticPool`.

### 5.2 Session factory override

`app.database.SessionLocal` must be overridden for tests before importing `app.main` so modules binding `SessionLocal` at import time (for example copy-engine paths) use test sessions.

### 5.3 Marker-gated suites

The following marker gating requirements must remain in place:

- `@pytest.mark.integration` only runs with `--run-integration`
- `@pytest.mark.hardware` only runs with `--run-hardware`

### 5.4 Standard fixtures

`tests/conftest.py` fixtures (`db`, `client`, `unauthenticated_client`, `admin_client`, `manager_client`, `auditor_client`, `auth_headers`) are required shared fixtures and should be reused, not bypassed.

---

## 6. Code-Level Test Requirements

### 6.1 SQLAlchemy / SQLite compatibility

All ORM `Enum` columns must use `native_enum=False`.

### 6.2 JSON portability

ORM models must use SQLAlchemy `JSON` (not `JSONB`) for cross-database compatibility.

### 6.3 Async strictness

`pytest-asyncio` runs in strict mode; async tests must be explicitly decorated with `@pytest.mark.asyncio`.

### 6.4 Dependency override hygiene

Tests overriding FastAPI dependencies must clear `app.dependency_overrides` on teardown.

### 6.5 Security-event verification

Security-relevant operations must have corresponding audit-log assertions in tests.

---

## 7. Platform Compatibility Requirements

CI currently runs automated test jobs on ubuntu-latest. Tests must still remain portable for local development, especially on Windows.

### 7.1 POSIX module handling

For POSIX-specific paths (`pwd`, `grp`, `os.geteuid`):

- prefer mocking service-level imports
- if unavoidable, use explicit Windows skip guards

### 7.2 Optional dependencies

For optional packages (for example Redis), tests must use guarded imports (for example `pytest.importorskip`) where applicable.

### 7.3 Cross-platform file behavior

- use binary file mode in tests where line-ending preservation matters
- close file handlers before temporary directory teardown

---

## 8. Coverage Requirements

Frontend unit coverage thresholds (Vitest) are mandatory:

- `src/stores/**/*.js`: lines 80, statements 80, functions 75, branches 70
- `src/composables/**/*.js`: lines 80, statements 80, functions 50, branches 60

Backend coverage is enforced through breadth and critical path assertions across service, API, security, and data-layer tests.

---

## 9. Coverage Areas

| Area | Key Test Files |
|------|---------------|
| Authentication (JWT middleware) | `test_auth.py`, `test_auth_integration.py` |
| Local login (PAM) | `test_auth_login.py` |
| OIDC role resolution | `test_oidc_service.py`, `test_role_resolver.py` |
| Role-based access control | `test_authorization.py` |
| Audit log API and emission | `test_audit.py`, `test_audit_logging.py` |
| Drive lifecycle and discovery | `test_drives.py`, `test_discovery.py`, `test_drive_eject.py`, `test_filesystem_format.py` |
| Mounts and jobs | `test_mounts.py`, `test_jobs.py` |
| Copy engine and concurrency | `test_copy_engine.py`, `test_concurrency.py`, `test_thread_count_validation.py` |
| Introspection and callbacks | `test_introspection.py`, `test_callback.py` |
| User/session/logging/config/migrations | `test_os_user_management.py`, `test_session_management.py`, `test_logging.py`, `test_config_settings.py`, `test_migrations.py` |
| UI telemetry and sanitization | `test_ui_telemetry.py`, `test_unicode_sanitization.py` |

---

## 10. Requirements for New Tests

### 10.1 New unit tests

- use shared fixtures from `tests/conftest.py`
- do not depend on external PostgreSQL, real USB hardware, or unmocked OS calls
- assert audit events for security-relevant operations
- preserve ORM portability rules (`native_enum=False`, `JSON`)

### 10.2 New integration tests

- include `@pytest.mark.integration`
- place under `tests/integration/`
- source DB connection from environment (`INTEGRATION_DATABASE_URL`)
- seed required data explicitly

### 10.3 New hardware tests

- include `@pytest.mark.hardware`
- place under `tests/hardware/`
- document required physical setup in the module
- avoid destructive actions without explicit safety guards

### 10.4 New frontend unit tests

- place under `src/<module>/__tests__/`
- mock API I/O (`vi.mock`)
- cover happy path and error/empty states
- maintain configured coverage thresholds

### 10.5 New frontend E2E tests

- place under `frontend/e2e/` and use `.spec.js`
- use Playwright fixtures only
- ensure state isolation between tests
- add accessibility assertions (`@axe-core/playwright`) where appropriate

## References

- [docs/testing/02-automated-test-runbook.md](02-automated-test-runbook.md)
- [docs/design/11-testing-and-validation.md](../design/11-testing-and-validation.md)
