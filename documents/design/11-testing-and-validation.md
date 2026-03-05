# 11. Testing and Validation

This document defines how to run automated tests for ECUBE using `pytest`, including unit tests, integration tests, and hardware-in-the-loop validation.

## 11.1 Test Scope

### Unit Tests

Unit tests validate API routes and service behavior in isolation.

- Database: SQLite in-memory with `StaticPool`.
- External/system calls: mocked where applicable.
- Speed: fast; suitable for local rapid iteration and CI default runs.

Current unit tests live in `tests/`.

### Integration Tests

Integration tests validate behavior against real infrastructure components.

- Database: PostgreSQL test database.
- Migrations: applied with Alembic before execution.
- Optional system integrations: mount tooling, filesystem, and introspection dependencies.

Integration tests live in `tests/integration/` and are gated by `--run-integration`.

### Hardware HIL Tests

Hardware-in-the-loop tests validate behavior with a physical USB hub and devices.

- Tests are in `tests/hardware/`.
- Execution requires `--run-hardware`.

## 11.2 Prerequisites

### Common Requirements

- Python `3.11+`
- Virtual environment activated
- Development dependencies installed

Install dependencies:

```bash
pip install -e ".[dev]"
```

### Unit Test Requirements

- No PostgreSQL required.
- No mount/hardware privileges required.

### Integration Test Requirements

- PostgreSQL instance available and reachable.
- `DATABASE_URL` (or `INTEGRATION_DATABASE_URL`) set to integration DB.
- Schema migrated with Alembic.

## 11.3 Running Unit Tests

Run all unit tests:

```bash
python -m pytest tests -q
```

Run a single module:

```bash
python -m pytest tests/test_jobs.py -q
```

Run by keyword:

```bash
python -m pytest tests -q -k "mount or job"
```

## 11.4 Integration Test Setup

Use a dedicated PostgreSQL database for integration tests.

### Option A: Local Docker Compose (recommended)

Start PostgreSQL integration service:

```bash
docker compose -f docker-compose.integration.yml up -d
```

Set integration environment variables.

Bash:

```bash
export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"
export DATABASE_URL="$INTEGRATION_DATABASE_URL"
```

Windows PowerShell:

```powershell
$env:INTEGRATION_DATABASE_URL = "postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"
$env:DATABASE_URL = $env:INTEGRATION_DATABASE_URL
```

Apply migrations:

```bash
alembic upgrade head
```

Run integration tests:

```bash
python -m pytest tests/integration -q --run-integration
```

Shutdown when done:

```bash
docker compose -f docker-compose.integration.yml down
```

## 11.5 PostgreSQL Concurrency Scaffold

The repository includes a real row-lock contention scaffold:

- `tests/integration/test_concurrency_scaffold_integration.py`

What it validates:

- Session A acquires `FOR UPDATE` lock on a row.
- Session B attempts `FOR UPDATE NOWAIT` on the same row.
- Application-level conflict handling is surfaced correctly.

Run only this scaffold:

```bash
python -m pytest tests/integration/test_concurrency_scaffold_integration.py -q --run-integration
```

Run full integration suite including scaffold:

```bash
python -m pytest tests/integration -q --run-integration
```

Note: this scaffold requires PostgreSQL and auto-skips on non-PostgreSQL backends.

## 11.6 Local Debug Workflow (Integration)

1. Start local PostgreSQL:

   ```bash
   docker compose -f docker-compose.integration.yml up -d
   ```

2. Set integration environment variables.
3. Apply migrations: `alembic upgrade head`.
4. Run a focused integration test:

   ```bash
   python -m pytest tests/integration/test_smoke_integration.py -q --run-integration -s
   ```

## 11.7 Suggested CI Test Sequence

1. Install dependencies: `pip install -e ".[dev]"`.
2. Run unit tests: `python -m pytest tests -q`.
3. If integration infrastructure is available:

   ```bash
   alembic upgrade head
   python -m pytest tests/integration -q --run-integration
   ```

## 11.8 Integration Use-Case Coverage Matrix

- Authentication and access: `tests/integration/test_auth_use_cases_integration.py`
- Drive management: `tests/integration/test_drives_use_cases_integration.py`
- Mount management: `tests/integration/test_mounts_use_cases_integration.py`
- Job lifecycle: `tests/integration/test_jobs_use_cases_integration.py`
- Introspection: `tests/integration/test_introspection_use_cases_integration.py`
- Baseline smoke: `tests/integration/test_smoke_integration.py`

## 11.9 Hardware HIL Testing

Hardware test skeleton:

- `tests/hardware/test_usb_hub_hil.py`

Run explicitly:

```bash
python -m pytest tests/hardware/test_usb_hub_hil.py -s --run-hardware
```

Guidance:

- Use disposable media only.
- Keep host USB environment stable during execution.
- Run on dedicated hardware for CI-style execution.
