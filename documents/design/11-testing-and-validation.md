# 11. Testing and Validation

This document defines how to run automated tests for ECUBE using `pytest`, including:

- Unit tests (fast, isolated, SQLite in-memory).
- Integration tests (real database and system integrations).
- Requirements and setup steps for each test type.

## 11.1 Test Scope

### Unit Tests

Unit tests validate API routes and service behavior in isolation.

- Database: SQLite in-memory with `StaticPool`.
- External/system calls: mocked (for example, mount and filesystem operations).
- Speed: fast; runs on every local change and CI run.

Current unit tests live in `tests/` (for example `tests/test_drives.py`, `tests/test_jobs.py`, `tests/test_mounts.py`, `tests/test_introspection.py`).

### Integration Tests

Integration tests validate end-to-end behavior against real infrastructure components.

- Database: PostgreSQL test database.
- Migrations: applied with Alembic before test execution.
- External dependencies: optional real system interactions (mount tooling, filesystem, hardware discovery) based on test scope.

Recommended location for integration tests: `tests/integration/`.

## 11.2 Prerequisites

### Common Requirements (Unit + Integration)

- Python `3.11+`
- Virtual environment activated
- Dev dependencies installed

Install dependencies:

```bash
pip install -e ".[dev]"
```

### Unit Test Requirements

- No PostgreSQL required.
- No system mount privileges required.
- Tests rely on in-memory SQLite and mocks.

### Integration Test Requirements

- PostgreSQL instance available and reachable.
- Dedicated test database and user credentials.
- Alembic available to migrate schema.
- Optional (only for mount/hardware integration cases):
  - Linux runtime with `/sys` and `/proc` visibility.
  - `mount`/`umount` tooling and suitable permissions.
  - Isolated test mount targets and disposable test data.

## 11.3 Running Unit Tests

Run all unit tests:

```bash
python -m pytest tests -q
```

Run a single test module:

```bash
python -m pytest tests/test_jobs.py -q
```

Run selected tests by keyword:

```bash
python -m pytest tests -q -k "mount or job"
```

## 11.4 Integration Test Setup

Use a separate PostgreSQL database for integration tests. Do not point integration tests at development or production databases.

### Option A: Automated local environment (recommended)

This repository includes `docker-compose.integration.yml` for local integration testing.

Start PostgreSQL integration service:

```bash
docker compose -f docker-compose.integration.yml up -d
```

The service exposes PostgreSQL on `localhost:5433` with:

- DB: `ecube_integration`
- User: `ecube_test`
- Password: `ecube_test`

Set integration DB URL:

```bash
export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"
export DATABASE_URL="$INTEGRATION_DATABASE_URL"
```

Windows PowerShell:

```powershell
$env:INTEGRATION_DATABASE_URL = "postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"
$env:DATABASE_URL = $env:INTEGRATION_DATABASE_URL
```

Apply schema migrations:

```bash
alembic upgrade head
```

Run integration tests explicitly:

```bash
python -m pytest tests/integration -q --run-integration
```

Stop environment when done:

```bash
docker compose -f docker-compose.integration.yml down
```

Remove DB volume for a fully clean re-run:

```bash
docker compose -f docker-compose.integration.yml down -v
```

### Step 1: Create integration database

Example (PostgreSQL):

```sql
CREATE DATABASE ecube_integration;
CREATE USER ecube_test WITH PASSWORD 'ecube_test';
GRANT ALL PRIVILEGES ON DATABASE ecube_integration TO ecube_test;
```

### Step 2: Configure environment for test run

Set `DATABASE_URL` for the integration session:

```bash
export DATABASE_URL="postgresql://ecube_test:ecube_test@localhost/ecube_integration"
```

Windows PowerShell:

```powershell
$env:DATABASE_URL = "postgresql://ecube_test:ecube_test@localhost/ecube_integration"
```

### Step 3: Apply schema migrations

```bash
alembic upgrade head
```

### Step 4: Run integration tests

```bash
python -m pytest tests/integration -q --run-integration
```

### Step 5: Cleanup (recommended)

- Drop and recreate the integration DB between full runs, or
- Use per-test transactional isolation and explicit teardown fixtures.

## 11.5 How to Add an Integration Test

1. Create a new test file under `tests/integration/`.
2. Use fixtures that connect to PostgreSQL (not SQLite `StaticPool`).
3. Ensure schema is migrated before the suite runs.
4. Isolate test data:
   - unique IDs per test,
   - cleanup in fixture teardown,
   - no shared mutable global state.
5. If system commands are exercised (`mount`, `umount`, hardware discovery), run only in controlled environments.

Recommended fixture pattern:

- `integration_engine` fixture bound to PostgreSQL `DATABASE_URL`.
- `integration_db_session` fixture with transaction rollback or schema teardown.
- `integration_client` fixture with FastAPI dependency override to integration session.

Current scaffold in this repository:

- `tests/integration/conftest.py`
- `tests/integration/test_smoke_integration.py`

## 11.6 Local Debug Workflow (Integration)

1. Start local integration PostgreSQL:

   ```bash
   docker compose -f docker-compose.integration.yml up -d
   ```

2. Set integration environment variables:

   ```powershell
   $env:INTEGRATION_DATABASE_URL = "postgresql://ecube_test:ecube_test@localhost:5433/ecube_integration"
   $env:DATABASE_URL = $env:INTEGRATION_DATABASE_URL
   ```

3. Apply migrations:

   ```bash
   alembic upgrade head
   ```

4. Run one integration test while debugging:

   ```bash
   python -m pytest tests/integration/test_smoke_integration.py -q --run-integration -s
   ```

5. Tear down when finished:

   ```bash
   docker compose -f docker-compose.integration.yml down
   ```

### One-click VS Code debugging

This repository includes `.vscode/launch.json` with:

- `Pytest: Integration (all)`
- `Pytest: Integration (current file)`

Usage:

1. Ensure Docker PostgreSQL is running and migrations are applied.
2. Open Run and Debug in VS Code.
3. Select one of the integration debug profiles above.
4. Press `F5` to start and hit breakpoints.

## 11.7 Suggested CI Test Sequence

1. Install dependencies:

   ```bash
   pip install -e ".[dev]"
   ```

2. Run unit tests first:

   ```bash
   python -m pytest tests -q
   ```

3. If integration environment is available, run:

   ```bash
   alembic upgrade head
   python -m pytest tests/integration -q --run-integration
   ```

## 11.8 Quality and Safety Notes

- Keep unit tests deterministic and independent.
- Keep integration tests isolated from production-like resources.
- Never use real evidence data in tests.
- For mount and hardware integration tests, use disposable fixtures and restricted host environments.

## 11.9 Integration Use-Case Coverage Matrix

The following integration use cases are covered and mapped to tests.

### Authentication and Access

- Public health endpoint without token.
- Protected endpoints reject missing token.
- Protected endpoints reject invalid token.
- Protected endpoints accept valid token.

Tests: `tests/integration/test_auth_use_cases_integration.py`

### Drive Management

- List drives.
- Initialize drive for project assignment.
- Reject cross-project initialization conflict.
- Prepare drive for eject.
- Handle drive-not-found cases.
- Verify drive lifecycle audit events.

Tests: `tests/integration/test_drives_use_cases_integration.py`

### Mount Management

- List mounts.
- Add NFS mount (success path).
- Add mount (error path).
- Remove existing mount.
- Remove missing mount.
- Verify mount lifecycle audit events.

Tests: `tests/integration/test_mounts_use_cases_integration.py`

### Job Lifecycle

- Create job.
- Create job with drive assignment.
- Reject job creation on project mismatch drive.
- Get job and handle missing job.
- Start job and update thread count.
- Reject start on already-running job.
- Verify job workflow kickoff.
- Generate manifest and persist manifest record.
- Verify job lifecycle audit events.

Tests: `tests/integration/test_jobs_use_cases_integration.py`

### Introspection

- System health endpoint.
- USB topology endpoint.
- Block device endpoint.
- Mount table endpoint.
- Job debug endpoint (found and not found).

Tests: `tests/integration/test_introspection_use_cases_integration.py`

### Baseline Smoke

- Health endpoint reachability.
- System-health endpoint basic DB connectivity check.

Tests: `tests/integration/test_smoke_integration.py`

## 11.10 Hardware HIL Testing (USB Hub and Devices)

Hardware-in-the-loop (HIL) tests validate behavior with a physical USB hub and real USB devices connected to the test machine.

Current HIL test skeleton:

- `tests/hardware/test_usb_hub_hil.py`

### 11.10.1 Requirements

- Linux host with USB sysfs visibility (for example `/sys/bus/usb/devices`).
- Physical USB hub and at least one disposable test USB device.
- Interactive terminal session (operator prompts require input).
- API environment running with valid auth secret settings.

### 11.10.2 Execution

Run the hardware test explicitly:

```bash
python -m pytest tests/hardware/test_usb_hub_hil.py -s --run-hardware
```

Notes:

- `--run-hardware` is required because hardware tests are skipped by default.
- `-s` is required to display interactive operator prompts.

### 11.10.3 Operator-driven flow

The test guides the operator through these physical steps:

1. Start from baseline (hub disconnected, no test device connected).
2. Connect hub and one known test USB device.
3. Verify topology and block-device introspection responses.
4. Disconnect and reconnect test USB device.
5. Disconnect hub/device and verify near-baseline state.

### 11.10.4 Assertions performed by the test

- Introspection endpoints are reachable and return expected response shape.
- USB topology device count increases after connect.
- Block device endpoint returns structured list data.
- USB topology remains consistent through reconnect.
- Device count decreases after disconnect.

### 11.10.5 Safety and reliability guidance

- Use disposable test media only (never production evidence media).
- Keep host USB environment stable during execution (avoid unrelated hot-plug events).
- If run in CI, dedicate a hardware runner and isolate USB peripherals.
- Record OS-level diagnostics (`dmesg`, `lsusb`) alongside test output for troubleshooting.
