# ECUBE — Running Schemathesis Locally

**Audience:** Developers, QA  
**See also:** [Security Scanning](03-security-scanning.md) (CI workflow reference)

---

## Overview

[Schemathesis](https://schemathesis.readthedocs.io/) reads the ECUBE OpenAPI schema and auto-generates randomised requests to find server errors, schema violations, content-type mismatches, and status-code contradictions. The CI workflow (`.github/workflows/schemathesis-fuzz.yml`) runs this automatically, but you can also run the same scan on your local machine for faster feedback during development.

This guide uses the standard **`docker-compose.ecube.yml`** stack (API server + PostgreSQL) so no local services are needed. A helper script (`scripts/run_schemathesis.sh`) automates the full workflow. The API is exposed on **port 8000** by default (override with `HOST_PORT`).

---

## Quick Start (Recommended)

The all-in-one script handles everything — building containers, waiting for health,
generating a JWT, running Schemathesis, and tearing down afterwards:

```bash
# Ensure host-side tools are installed
source .venv/bin/activate
pip install schemathesis PyJWT

# Run the full scan
./scripts/run_schemathesis.sh
```

Extra arguments are forwarded to `st run`:

```bash
# Target a single endpoint
./scripts/run_schemathesis.sh --endpoint "/drives"

# Override example count
./scripts/run_schemathesis.sh --max-examples 100
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST_PORT` | `8000` | Host port the API is exposed on (also controls the Compose port mapping) |
| `POSTGRES_HOST_PORT` | `5432` | Host port for PostgreSQL; override to avoid conflicts with a local instance |
| `SECRET_KEY` | `change-me-in-production-…` | Must match the app's key |
| `SCHEMATHESIS_MAX_WAIT` | `60` | Seconds to wait for `/health` |
| `SCHEMATHESIS_MAX_EXAMPLES` | `50` | Default `--max-examples` value |

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

## Manual Step-by-Step

If you prefer to run each step individually (e.g. for debugging), follow the
sections below.

### Step 1 — Install Schemathesis

```bash
source .venv/bin/activate
pip install schemathesis PyJWT
```

### Step 2 — Start the Containers

The `docker-compose.ecube.yml` uses `${VAR:-default}` interpolation for
`HOST_PORT`, `POSTGRES_HOST_PORT`, `SECRET_KEY`, `LOCAL_GROUP_ROLE_MAP`, and
`USB_DISCOVERY_INTERVAL`, so you can override them via shell environment
variables:

```bash
HOST_PORT=8000 \
USB_DISCOVERY_INTERVAL=0 \
LOCAL_GROUP_ROLE_MAP='{"evidence-admins": ["admin"]}' \
SECRET_KEY="${SECRET_KEY:-change-me-in-production-please-rotate-32b}" \
docker compose -p ecube-schemathesis -f docker-compose.ecube.yml up -d --build --force-recreate
```

Wait for the API to be ready:

```bash
for i in $(seq 1 30); do
  curl -sf http://localhost:8000/health && break
  echo "Waiting for API… attempt $i/30"
  sleep 2
done
```

### Step 3 — Generate an Admin JWT

```bash
export SECRET_KEY="${SECRET_KEY:-change-me-in-production-please-rotate-32b}"

TOKEN=$(python - <<'PY'
import jwt, time, os
payload = {
    "sub": "dev-admin",
    "username": "dev-admin",
    "groups": ["evidence-admins"],
    "roles": ["admin"],
    "exp": int(time.time()) + 3600,
}
print(jwt.encode(payload, os.environ["SECRET_KEY"], algorithm="HS256"))
PY
)

echo "Token: $TOKEN"
```

> **Tip:** The token is valid for 1 hour. The `SECRET_KEY` must match the value
> passed to the container. The default above matches the built-in development
> default in `app/config.py`.

### Step 4 — Run Schemathesis

#### Basic Run

```bash
st run http://localhost:8000/openapi.json \
  --header "Authorization: Bearer $TOKEN" \
  --checks all \
  --max-examples 50 \
  --request-timeout 10
```

#### Full Run (Matching CI)

```bash
st run http://localhost:8000/openapi.json \
  --header "Authorization: Bearer $TOKEN" \
  --checks all \
  --max-examples 50 \
  --request-timeout 10 \
  --phases coverage,fuzzing \
  2>&1 | tee schemathesis-output.txt
```

#### Targeting a Single Endpoint

```bash
st run http://localhost:8000/openapi.json \
  --header "Authorization: Bearer $TOKEN" \
  --checks all \
  --max-examples 50 \
  --endpoint "/drives"
```

### Step 5 — Tear Down

```bash
docker compose -p ecube-schemathesis -f docker-compose.ecube.yml down -v
```

Omit `-v` if you want to keep the database state between runs.

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
