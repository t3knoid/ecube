# ECUBE — Running Schemathesis Locally

**Audience:** Developers, QA  
**See also:** [Security Scanning](03-security-scanning.md) (CI workflow reference)

---

## Overview

[Schemathesis](https://schemathesis.readthedocs.io/) reads the ECUBE OpenAPI schema and auto-generates requests to find server errors, schema violations, and status-code contradictions. The CI workflow (`.github/workflows/schemathesis-fuzz.yml`) runs this automatically.

For local development, `scripts/run_schemathesis.sh` is the recommended entrypoint. It uses a **smoke profile by default** (fast and stable):

- Starts/stops the ECUBE Docker Compose stack automatically.
- Waits for `/health` before testing.
- Generates an admin JWT automatically.
- Runs coverage with conservative checks and path filtering.

Use this profile for pre-commit validation. Use explicit overrides when you need broader coverage.

---

## Quick Start (Recommended)

The all-in-one script handles container startup, health checks, JWT generation,
Schemathesis execution, and teardown:

```bash
# Ensure host-side tools are installed
source .venv/bin/activate
pip install schemathesis PyJWT

# Run the default smoke scan
./scripts/run_schemathesis.sh
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_PORT` | `8000` | Host port the API is exposed on (also controls the Compose port mapping) |
| `POSTGRES_HOST_PORT` | `5432` | Host port for PostgreSQL; override to avoid conflicts with a local instance |
| `SECRET_KEY` | `change-me-in-production-…` | Must match the app's key |
| `SCHEMATHESIS_MAX_WAIT` | `60` | Seconds to wait for `/health` |
| `SCHEMATHESIS_MAX_EXAMPLES` | `5` | Default `--max-examples` value |
| `SCHEMATHESIS_REQUEST_TIMEOUT` | `10` | Request timeout in seconds |
| `SCHEMATHESIS_PHASES` | `coverage` | Test phases |
| `SCHEMATHESIS_WORKERS` | `1` | Concurrent workers |
| `SCHEMATHESIS_MAX_FAILURES` | `1` | Stop after first failure |
| `SCHEMATHESIS_CHECKS` | `not_a_server_error,status_code_conformance` | Enabled checks |
| `SCHEMATHESIS_EXCLUDE_CHECKS` | `unsupported_method,missing_required_header` | Disabled checks |
| `SCHEMATHESIS_INCLUDE_PATH_REGEX` | `^/(health\|introspection/version\|setup/status)$` | Path filter for smoke profile |
| `SCHEMATHESIS_WAIT_FOR_SCHEMA` | `30` | Seconds to wait for OpenAPI schema |
| `SCHEMATHESIS_SEED` | *(unset)* | Optional deterministic seed |

Results are saved to `schemathesis-output.txt` in the project root. Containers are
automatically torn down when the script exits (including on errors).

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker & Docker Compose | `docker compose` (v2 plugin) or `docker-compose` (legacy) |
| Python 3.11+ | Only needed to generate the JWT and run `st` |
| Schemathesis | `pip install schemathesis` (host only) |
| PyJWT | `pip install PyJWT` (for token generation) |

> **No local PostgreSQL, ECUBE install, or Alembic migrations required** — the
> containers handle everything.

---

## Expanding Beyond Smoke

The script forwards extra arguments directly to `st run`, so you can widen scope:

```bash
# More examples
SCHEMATHESIS_MAX_EXAMPLES=25 ./scripts/run_schemathesis.sh

# Broader path scope
SCHEMATHESIS_INCLUDE_PATH_REGEX='^/(drives|mounts|jobs|introspection)/' ./scripts/run_schemathesis.sh

# Reproducible run
SCHEMATHESIS_SEED=12345 ./scripts/run_schemathesis.sh
```

---

## Interpreting Results

| Exit Code | Meaning |
|-----------|---------|
| `0` | All checks passed |
| `1` | Test findings (schema violations, server errors, etc.) |
| `2+` | Invocation or runtime error (e.g. server unreachable, bad schema) |

Schemathesis prints a summary at the end of each run. Look for:

- **5xx errors** — Unhandled exceptions in ECUBE endpoint handlers.
- **Schema violations** — Response body doesn't match the declared OpenAPI schema.
- **Status code contradictions** — Endpoint returns a status code not declared in the schema.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `Connection refused` | Containers not running or not ready | Run `docker compose -p ecube-schemathesis -f docker-compose.ecube.yml ps` and wait for `/health` to return 200 |
| `401 Unauthorized` on every request | Token expired or wrong `SECRET_KEY` | Regenerate the token with the same `SECRET_KEY` the container is using |
| `403 Forbidden` | JWT roles don't map to `admin` | Verify the container's `LOCAL_GROUP_ROLE_MAP` includes `evidence-admins → admin` |
| Build fails | Docker not running or missing Dockerfile | Ensure Docker daemon is running and `deploy/ecube-host/Dockerfile` exists |
| Port 8000 in use | Another service on that port | Stop the conflicting service or set `HOST_PORT` to a different port (the script passes it through to the Compose port mapping) |
| `password authentication failed` | Database container unhealthy | Run `docker compose -p ecube-schemathesis -f docker-compose.ecube.yml logs postgres` to diagnose |
| Runs are too slow or noisy | Scope/checks too broad for local smoke | Keep default smoke profile, then widen with env vars incrementally |
