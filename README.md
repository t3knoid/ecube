# ecube

[![Tests](https://github.com/t3knoid/ecube/actions/workflows/run-tests.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/run-tests.yml)
[![Security Scan](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml)
[![Schemathesis API Fuzz](https://github.com/t3knoid/ecube/actions/workflows/schemathesis-fuzz.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/schemathesis-fuzz.yml)

Evidence Copying &amp; USB Based Export

ECUBE is a secure evidence export platform designed to copy eDiscovery data onto encrypted USB drives from a Linux-based copy machine, with strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Application Stack

- **System Layer API:** Python 3.11+, FastAPI
- **Data Layer:** PostgreSQL 14+ with SQLAlchemy + Alembic
- **Background Processing:** Celery or RQ workers for copy, verification, and manifest tasks
- **UI Layer:** React, Vue, or server-rendered templates (HTTPS-only)
- **Runtime Platform:** Linux-based copy machine with USB hub integration and NFS/SMB mount support

## Quick Start

> **Prerequisites:** PostgreSQL 14+ must be running and a database created for ECUBE.
> See the [Installation Guide](docs/operations/03-installation.md) for full setup instructions,
> or use the included Docker Compose file for a quick local database:
>
> ```bash
> docker compose -f docker-compose.ecube.yml up -d postgres
> ```

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the project and dev dependencies
pip install -e ".[dev]"

# Apply database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload

# Run tests (uses SQLite in-memory — no PostgreSQL needed)
python -m pytest tests/ -v
```

## API Documentation

Once the API server is running, interactive documentation is available at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI Schema:** `http://localhost:8000/openapi.json`

All endpoints (except `/health`, `/docs`, `/redoc`, `/openapi.json`) require authentication via JWT bearer tokens. See the [REST API Specification](docs/design/06-rest-api-specification.md) and [Security & Access Control](docs/design/10-security-and-access-control.md) for details.

A [Postman collection](postman/ecube-postman-collection.json) is also available for testing and exploring the API.

## Build and Deployment

Build and deployment guidance (release artifacts, package deployment, Docker images, and compose deployment) is documented in [Build and Deployment](docs/design/13-build-and-deployment.md).

## QA Test-Case Sync

The QA test-case spreadsheet (`docs/testing/ecube-qa-test-cases.xlsx`) is generated from the markdown guide (`docs/testing/01-qa-testing-guide-baremetal.md`). A sync script keeps them aligned:

```bash
# Check for drift (exits non-zero if out of sync)
python scripts/sync_qa_test_cases.py --check

# Regenerate the Excel from the markdown (preserves Status/Tester/Date/Notes)
python scripts/sync_qa_test_cases.py --sync
```

## Documentation

- [Operations Guide](docs/operations/00-operational-guide.md)
  - [Installation](docs/operations/03-installation.md)
  - [Configuration Reference](docs/operations/02-configuration-reference.md)
  - [Administration Guide](docs/operations/06-administration-guide.md) — identity providers, logging, user management
  - [API Quick Reference](docs/operations/08-api-quick-reference.md)
  - [Security Best Practices](docs/operations/07-security-best-practices.md)
- [Development Guide](docs/development/00-development-guide.md)
- [QA Testing Guide (Bare-Metal)](docs/testing/01-qa-testing-guide-baremetal.md)
- [Requirements Documents](docs/requirements)
- [Design Documents](docs/design)
- [Linux Host Deployment & USB Passthrough](docs/design/12-linux-host-deployment-and-usb-passthrough.md)
- [Build & Deployment (Design)](docs/design/13-build-and-deployment.md)
