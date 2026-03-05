# 11. Testing and Validation

This document provides quick execution guidance for ECUBE automated tests.

## 11.1 Integration Test Prerequisites

- PostgreSQL integration database is running and reachable.
- `DATABASE_URL` (and optionally `INTEGRATION_DATABASE_URL`) points to the integration DB.
- Migrations are applied before running tests:

```bash
alembic upgrade head
```

## 11.2 Running Integration Tests

Run all integration tests:

```bash
python -m pytest tests/integration -q --run-integration
```

Run one integration file:

```bash
python -m pytest tests/integration/<file>.py -q --run-integration
```

## 11.3 PostgreSQL Concurrency Scaffold

The repository includes a real row-lock concurrency scaffold test:

- `tests/integration/test_concurrency_scaffold_integration.py`

What it validates:

- Two independent DB sessions target the same row.
- Session A acquires `FOR UPDATE` lock.
- Session B attempts `FOR UPDATE NOWAIT` and must surface application-level conflict handling.

Run only the concurrency scaffold:

```bash
python -m pytest tests/integration/test_concurrency_scaffold_integration.py -q --run-integration
```

Run full integration suite including scaffold:

```bash
python -m pytest tests/integration -q --run-integration
```

Note: this scaffold requires PostgreSQL and auto-skips on non-PostgreSQL backends.
