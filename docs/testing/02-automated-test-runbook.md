# ECUBE — Automated Test Runbook

| Field | Value |
|---|---|
| Title | Automated Test Runbook |
| Purpose | Explains how to install dependencies, run all automated test suites, and reproduce CI behavior locally. |
| Updated on | 04/08/26 |
| Audience | Developers, contributors, QA. |

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [Install Dependencies](#2-install-dependencies)
3. [Run Test Suites](#3-run-test-suites)
4. [Integration Tests with Docker](#4-integration-tests-with-docker)
5. [Frontend E2E Notes](#5-frontend-e2e-notes)
6. [Snapshot Update Procedures](#6-snapshot-update-procedures)
7. [CI Workflow Mapping](#7-ci-workflow-mapping)

---

## 1. Quick Start

From repository root:

```bash
pip install -e ".[dev]"
cd frontend
npm ci
npx playwright install --with-deps chromium webkit
```

Then run:

```bash
# backend unit
cd /path/to/ecube
python -m pytest tests/ --ignore=tests/integration --ignore=tests/hardware -v

# frontend unit
cd frontend
npm run test:unit

# frontend e2e
npm run build
npx playwright test
```

---

## 2. Install Dependencies

### 2.1 Backend

```bash
pip install -e ".[dev]"
```

### 2.2 Frontend

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium webkit
```

---

## 3. Run Test Suites

### 3.1 Backend unit tests (default)

```bash
python -m pytest tests/ \
  --ignore=tests/integration \
  --ignore=tests/hardware \
  -v
```

Equivalent command where integration/hardware are marker-skipped by default:

```bash
python -m pytest tests/ -v
```

### 3.2 Backend integration tests

```bash
export INTEGRATION_DATABASE_URL="postgresql://ecube:ecube@localhost:5432/ecube"
python -m pytest tests/integration/ -v --run-integration
```

CI-equivalent local DB URL (matches GitHub Actions postgres service in `run-tests.yml`):

```bash
export INTEGRATION_DATABASE_URL="postgresql://ecube_test:ecube_test@localhost:5432/ecube_integration"
python -m pytest tests/integration/ -v --run-integration
```

Note: `tests/integration/conftest.py` default URL uses `localhost:5433`, so set
`INTEGRATION_DATABASE_URL` explicitly when matching CI.

### 3.3 Hardware-in-the-loop tests

```bash
python -m pytest tests/hardware/ -v --run-hardware
```

### 3.4 Frontend unit tests

```bash
cd frontend
npm run test:unit
```

### 3.5 Frontend E2E tests

```bash
cd frontend
npm run build
npx playwright test
```

Interactive mode:

```bash
npx playwright test --ui
```

### 3.6 Quick smoke check

```bash
python -m pytest tests/ -q
```

---

## 4. Integration Tests with Docker

### 4.1 Start PostgreSQL container

Linux/macOS:

```bash
docker compose -f docker-compose.ecube.yml up -d postgres
```

Windows:

```bash
docker compose -f docker-compose.ecube-win.yml up -d postgres
```

### 4.2 Run integration tests

```bash
INTEGRATION_DATABASE_URL=postgresql://ecube:ecube@localhost:5432/ecube \
  python -m pytest tests/integration/ -v --run-integration
```

### 4.3 Tear down and clean DB volume

Linux/macOS:

```bash
docker compose -f docker-compose.ecube.yml down -v
```

Windows:

```bash
docker compose -f docker-compose.ecube-win.yml down -v
```

---

## 5. Frontend E2E Notes

- Playwright base URL is `http://localhost:4173` (`frontend/playwright.config.js`).
- In CI, Playwright uses `npm run preview` as web server command.
- Locally, Playwright runs `npm run build && npm run preview` through `webServer` config.
- Playwright HTML report output directory: `frontend/playwright-report/`.
- Include help-system coverage in frontend E2E when help functionality changes (for example, `frontend/e2e/help.spec.js`).

### 5.1 Help Generation QA Preflight

When validating help-system changes, run the dedicated help-generation script before E2E execution so QA checks the same generated artifact expected in CI packaging.

Example sequence:

```bash
# from repository root
bash scripts/build-help.sh

cd frontend
npm run build
npx playwright test frontend/e2e/help.spec.js
```

If the repository uses a JavaScript variant of the generator, replace the script call with the project-standard equivalent (for example, `node scripts/build-help.mjs`).

---

## 6. Snapshot Update Procedures

### 6.1 Local script (recommended)

From repo root:

```bash
./scripts/update-e2e-snapshots.sh
```

Script behavior:

1. `npm ci`
2. `npx playwright install --with-deps chromium webkit`
3. `npm run build`
4. `npx playwright test --update-snapshots --reporter=line`
5. stage snapshot changes under `frontend/e2e/*.spec.js-snapshots/`
6. commit and push if changed

Optional environment variables:

- `NO_PUSH=1` to skip push
- `COMMIT_MSG="..."` to override commit message

### 6.2 GitHub manual workflow

Use `.github/workflows/update-e2e-snapshots.yml` (`workflow_dispatch`) to regenerate and commit Linux baselines in CI.

---

## 7. CI Workflow Mapping

For installer-oriented package artifact generation details, see:
[docs/development/03-ci-build-and-installer-artifacts.md](docs/development/03-ci-build-and-installer-artifacts.md)

| Workflow | Trigger | What runs |
|----------|---------|----------|
| `run-tests.yml` — backend unit tests | manual (`workflow_dispatch`) and push to `main` when `app/**`, `frontend/**`, or `tests/**` changes | `python -m pytest tests/ --ignore=tests/integration --ignore=tests/hardware -v` on ubuntu-latest |
| `run-tests.yml` — backend integration tests | manual (`workflow_dispatch`) and push to `main` with same path filter | postgres service + `alembic upgrade head` + `python -m pytest tests/integration/ -v --run-integration` |
| `run-tests.yml` — frontend unit tests | manual (`workflow_dispatch`) and push to `main` with same path filter | `npm run test:unit` |
| `run-tests.yml` — frontend E2E tests | manual (`workflow_dispatch`) and push to `main` with same path filter | `npm run build` + `npx playwright test` (Chromium + WebKit), upload `frontend/playwright-report/` artifact |
| `update-e2e-snapshots.yml` | manual (`workflow_dispatch`) | `npx playwright test --update-snapshots --reporter=line`, then commit and push snapshots |
| `docker-build.yml` — build and smoke | manual (`workflow_dispatch`), push to `main`, tag push (`v*`) | build images, bring stack up, smoke-check `/health` |
| `docker-build.yml` — publish | release published | push images to GHCR, attach generated `docker-compose.yml` release asset |

## References

- [docs/testing/01-automated-test-requirements.md](01-automated-test-requirements.md)
