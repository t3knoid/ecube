# ECUBE — Running Newman Smoke Tests Locally

**Audience:** Developers, QA  
**See also:** [Schemathesis Local Guide](04-schemathesis-local.md), [Security Scanning](03-security-scanning.md)

---

## Overview

Newman runs the ECUBE Postman collection as a lightweight API smoke test.

Use `scripts/run_newman_smoke.sh` for a fast local confidence check before commits.
The script is aligned with the Schemathesis runner and will:

- Start the ECUBE Docker Compose stack (`docker-compose.ecube.yml`).
- Wait for `/health`.
- Generate an admin JWT automatically (unless you pass `ECUBE_TOKEN`).
- Run smoke requests from the Postman collection.
- Tear down containers on exit.

---

## Quick Start

```bash
cd /Users/frank/ecube
./scripts/run_newman_smoke.sh
```

This runs authenticated smoke folders from `postman/ecube-postman-collection.json`:

- Health & Version
- Introspection
- Audit

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Docker & Docker Compose | `docker compose` (v2 plugin) or `docker-compose` |
| Node.js + npx | Needed to run Newman |
| Python 3.11+ | Used to generate JWT |
| PyJWT | Install with `pip install PyJWT` (or in `.venv`) |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BASE_URL` | `http://localhost:8000` | Base URL used by Newman requests |
| `HOST_PORT` | `8000` | Host port mapped to ECUBE API container |
| `POSTGRES_HOST_PORT` | `5432` | Host port mapped to PostgreSQL container |
| `SECRET_KEY` | `change-me-in-production-…` | Used for JWT generation; must match service key |
| `NEWMAN_MAX_WAIT` | `60` | Seconds to wait for API health |
| `ECUBE_TOKEN` | *(unset)* | Optional pre-generated JWT (skips token generation) |
| `ECUBE_ADMIN_USERNAME` | `ecube-admin` | Collection variable for login payloads |
| `ECUBE_ADMIN_PASSWORD` | `s3cret` | Collection variable for login payloads |

---

## Examples

Use a pre-generated token:

```bash
ECUBE_TOKEN="<jwt>" ./scripts/run_newman_smoke.sh
```

Run on alternate ports:

```bash
HOST_PORT=18000 POSTGRES_HOST_PORT=15432 ./scripts/run_newman_smoke.sh
```

Use custom base URL (must match your port mapping):

```bash
HOST_PORT=18000 BASE_URL=http://localhost:18000 ./scripts/run_newman_smoke.sh
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `API did not become healthy` | Containers not ready, or port collision | Check `docker compose -p ecube-newman-smoke -f docker-compose.ecube.yml ps`; change `HOST_PORT` if needed |
| `ERROR: npx is required` | Node.js not installed | Install Node.js and retry |
| `PyJWT is required` | Missing `jwt` module in Python env | `source .venv/bin/activate && pip install PyJWT` |
| 401/403 responses | Invalid token/key mismatch | Ensure `SECRET_KEY` matches runtime key or pass a valid `ECUBE_TOKEN` |
| Newman request timeouts | Local app overloaded or blocked | Retry after stack restart; increase `--timeout-request` in script if necessary |
