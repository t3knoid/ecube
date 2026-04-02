# ecube

[![Tests](https://github.com/t3knoid/ecube/actions/workflows/run-tests.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/run-tests.yml)
[![Security Scan](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml)
[![Schemathesis API Fuzz](https://github.com/t3knoid/ecube/actions/workflows/schemathesis-fuzz.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/schemathesis-fuzz.yml)

Evidence Copying &amp; USB Based Export

ECUBE is a secure evidence export platform designed to copy eDiscovery data onto encrypted USB drives from a Linux-based copy machine, with strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Application Stack

- **System Layer API:** Python 3.11+, FastAPI
- **Data Layer:** PostgreSQL 14+ with SQLAlchemy + Alembic
- **Background Processing:** FastAPI `BackgroundTasks` with a bounded `ThreadPoolExecutor` for copy, verification, and manifest tasks
- **UI Layer:** React, Vue, or server-rendered templates (HTTPS-only)
- **Runtime Platform:** Linux-based copy machine with USB hub integration and NFS/SMB mount support

## Quick Start

### Bare-metal installation (Debian/Ubuntu)

Download a release package, extract it, and run the installer:

```bash
tar -xzf ecube-package-<version>.tar.gz
cd ecube-package-<version>
sudo ./install.sh
```

The installer handles Python dependencies, TLS certificates, systemd unit configuration, and optional nginx setup. See the [Installation Guide](docs/operations/03-installation.md) for all available options (`--backend-only`, `--frontend-only`, `--api-port`, `--uninstall`, etc.).

### Docker Compose

> **Prerequisites:** Docker and Docker Compose must be installed.

```bash
# Generate self-signed TLS certs for local testing
mkdir -p deploy/certs deploy/themes
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout deploy/certs/key.pem \
  -out deploy/certs/cert.pem \
  -subj "/CN=localhost"

# Start all services (postgres, ecube-app, ecube-ui)
docker compose -f docker-compose.ecube.yml up -d
```

The UI is available at **https://localhost:8443** and the API at **https://localhost:8443/api**.

To run the backend tests (uses SQLite in-memory — no PostgreSQL needed):

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the project and dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v
```

## API Documentation

Once running, interactive documentation is available through the nginx reverse proxy at:

- **Swagger UI:** `https://localhost:8443/docs`
- **ReDoc:** `https://localhost:8443/redoc`
- **OpenAPI Schema:** `https://localhost:8443/openapi.json`

> **Note:** Port 8000 (FastAPI) is not published to the host in the default compose setup — all traffic routes through the nginx proxy on port 8443. To expose port 8000 directly for local development, add the `docker-compose.dev.yml` overlay (see that file for details).

All endpoints (except `/health`, `/docs`, `/redoc`, `/openapi.json`) require authentication via JWT bearer tokens. See the [REST API Specification](docs/design/06-rest-api-specification.md) and [Security & Access Control](docs/design/10-security-and-access-control.md) for details.

A [Postman collection](postman/ecube-postman-collection.json) is also available for testing and exploring the API.

## Build and Deployment

Build and deployment guidance (release artifacts, package deployment, Docker images, and compose deployment) is documented in [Build and Deployment](docs/design/13-build-and-deployment.md).

## CI Status

The three badges at the top of this file reflect the current state of automated CI workflows:

- **Tests** — four test suites run on every push: backend unit tests (pytest, SQLite in-memory, cross-platform), backend integration tests (pytest against a live PostgreSQL instance), frontend unit tests (Vitest with coverage), and frontend end-to-end tests (Playwright). See [docs/testing/05-automated-test-requirements.md](docs/testing/05-automated-test-requirements.md) for test conventions.
- **Security Scan** — static analysis and dependency vulnerability checks. Triggered manually via GitHub Actions (`workflow_dispatch`). See [docs/testing/03-security-scanning.md](docs/testing/03-security-scanning.md) for details.
- **Schemathesis API Fuzz** — auto-generated requests from the OpenAPI schema to detect schema violations, server errors, and undocumented status codes. Triggered manually via GitHub Actions (`workflow_dispatch`). See the [Schemathesis Local Guide](docs/testing/04-schemathesis-local.md) for running the scan locally.

## Contributors

**Testing** — see [docs/testing/05-automated-test-requirements.md](docs/testing/05-automated-test-requirements.md) for test conventions, fixture patterns, and how to run the backend and frontend suites locally. For manual QA, the bare-metal guide and test-case spreadsheet are in [docs/testing/](docs/testing/).

**Development** — the [Development Guide](docs/development/00-development-guide.md) covers local setup, debugging, and Windows-specific notes. Design documents (architecture, data model, REST API, security) are in [docs/design/](docs/design/).

**Documentation** — operational docs (installation, configuration, administration, security) live in [docs/operations/](docs/operations/). Requirements source documents are in [docs/requirements/](docs/requirements/).

## Documentation

- [Operations Guide](docs/operations/00-operational-guide.md)
  - [Installation](docs/operations/03-installation.md)
  - [Configuration Reference](docs/operations/02-configuration-reference.md)
  - [Administration Guide](docs/operations/06-administration-guide.md) — identity providers, logging, user management
  - [API Quick Reference](docs/operations/08-api-quick-reference.md)
  - [Security Best Practices](docs/operations/07-security-best-practices.md)
- [Development Guide](docs/development/00-development-guide.md)
- [QA Testing Guide (Bare-Metal)](docs/testing/01-qa-testing-guide-baremetal.md)
- [Schemathesis Local Fuzz Testing](docs/testing/04-schemathesis-local.md)
- [Security Scanning (CI)](docs/testing/03-security-scanning.md)
- [Requirements Documents](docs/requirements)
- [Design Documents](docs/design)
- [Linux Host Deployment & USB Passthrough](docs/design/12-linux-host-deployment-and-usb-passthrough.md)
- [Build & Deployment (Design)](docs/design/13-build-and-deployment.md)

## License

ECUBE is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International** license (CC BY-NC 4.0).

In plain terms this means you are free to:

- **Share** — copy and redistribute the material in any medium or format.
- **Adapt** — remix, transform, and build upon the material.

Under the following conditions:

- **Attribution** — You must give appropriate credit to the original author (Frank Refol), provide a link to the license, and indicate if changes were made.
- **NonCommercial** — You may not use the material for commercial purposes without separate written permission from the copyright holder.

No additional restrictions — you may not apply legal terms or technological measures that legally restrict others from doing anything the license permits.

See [LICENSE](LICENSE) for the full license text, [COPYRIGHT](COPYRIGHT) for the copyright notice, and [NOTICE](NOTICE) for third-party attributions. For commercial licensing inquiries, contact the copyright holder.
