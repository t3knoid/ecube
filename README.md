# ecube

[![Tests](https://github.com/t3knoid/ecube/actions/workflows/run-tests.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/run-tests.yml)
[![Docker Build](https://github.com/t3knoid/ecube/actions/workflows/docker-build.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/docker-build.yml)
[![Security Scan](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/security-scan.yml)
[![Schemathesis API Fuzz](https://github.com/t3knoid/ecube/actions/workflows/schemathesis-fuzz.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/schemathesis-fuzz.yml)
[![Newman API Smoke](https://github.com/t3knoid/ecube/actions/workflows/newman-smoke.yml/badge.svg)](https://github.com/t3knoid/ecube/actions/workflows/newman-smoke.yml)

Evidence Copying &amp; USB Based Export

ECUBE is a secure evidence export platform designed to copy eDiscovery data onto encrypted USB drives from a Linux-based copy machine, with strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Application Stack

- **System Layer API:** Python 3.11+, FastAPI
- **Data Layer:** PostgreSQL 14+ with SQLAlchemy + Alembic
- **Background Processing:** FastAPI `BackgroundTasks` with a bounded `ThreadPoolExecutor` for copy, verification, and manifest tasks
- **UI Layer:** React, Vue, or server-rendered templates (HTTPS-only)
- **Runtime Platform:** Linux-based copy machine with USB hub integration and NFS/SMB mount support

## Quick Start

### Installation (Debian/Ubuntu)

Download a release package from [GitHub Releases](https://github.com/t3knoid/ecube/releases/latest), extract it, and run the installer as root.

For CI packaging details and installer artifact naming/content requirements, see [CI Build and Installer Artifact Contract](docs/development/03-ci-build-and-installer-artifacts.md).

To locally preflight the same packaging path used by CI workflows, run:

```bash
bash scripts/package-local.sh --sha "$(git rev-parse --short=8 HEAD)"
```

```bash
tar -xzf ecube-package-<version>.tar.gz
cd ecube-package-<version>
sudo ./install.sh
```

Before running the installer, ensure PostgreSQL is installed and running. The installer does not install the PostgreSQL server itself.

The installer performs pre-flight checks, creates/updates a PostgreSQL superuser for setup-wizard provisioning, writes `.env` (with `DATABASE_URL` left blank and `SECRET_KEY` generated), configures `ecube.service`, deploys the frontend to `<install-dir>/www`, and optionally configures the host firewall.

Immediate next step: open the ECUBE web UI and complete setup at `https://<hostname>:<ui-port>/setup`.

See the [Installation Guide](docs/operations/01-installation.md) for full installer behavior and all options (`--backend-only`, `--frontend-only`, `--api-port`, `--uninstall`, etc.).

### Docker Compose (Development PostgreSQL)

> **Prerequisites:** Docker and Docker Compose must be installed.

```bash
# Create environment file from the working example.
# .env.example includes required settings for a local full-stack run,
# including PostgreSQL service variables.
cp .env.example .env

# Optional: override the default postgres password (default is "ecube")
sed -i.bak 's/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=mysecretpassword/' .env
```

```powershell
# Windows (pwsh) equivalent
Copy-Item .env.example .env
# Optional: override the default postgres password
(Get-Content .env) -replace '^POSTGRES_PASSWORD=.*', 'POSTGRES_PASSWORD=mysecretpassword' | Set-Content .env
```

```bash
# Generate a self-signed TLS certificate for local development.
# The nginx UI container will not start without cert.pem and key.pem.
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout deploy/certs/key.pem \
  -out deploy/certs/cert.pem \
  -subj "/CN=localhost"
```

```powershell
# Windows: run the openssl command above in Git Bash, WSL, or any shell
# that has openssl available.  Docker Desktop with WSL2 includes openssl
# inside the WSL environment.
```

```bash
# Linux/macOS: start full stack (postgres, ecube-app, ecube-ui)
docker compose -f docker-compose.ecube.yml up -d --build
```

```powershell
# Windows: start full stack (postgres, ecube-app, ecube-ui)
docker compose -f docker-compose.ecube-win.yml up -d --build
```

After startup, open the web frontend and complete first-run setup:

- UI: `https://localhost:8443`
- Run the Setup Wizard to verify database settings and create the initial admin account.

### Docker Compose (Pre-built release images)

ECUBE release images are published to GitHub Container Registry (GHCR):

- `ghcr.io/t3knoid/ecube-app`
- `ghcr.io/t3knoid/ecube-ui`

For each published GitHub Release, both images are tagged with the release version (for example `v0.2.0`) and with `latest`.

The easiest production-like path is to download the release `docker-compose.yml` asset from [GitHub Releases](https://github.com/t3knoid/ecube/releases/latest), place it in an empty deployment directory with your `.env` file, and start the stack:

```bash
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d
```

If you want to pull specific tags manually:

```bash
docker pull ghcr.io/t3knoid/ecube-app:v0.2.0
docker pull ghcr.io/t3knoid/ecube-ui:v0.2.0
```

## API Documentation

For native development (recommended), interactive API docs are available at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI Schema:** `http://localhost:8000/openapi.json`

If you run the full Docker app + UI stack, docs are available through the nginx proxy at `https://localhost:8443/docs`.

> **Note:** In the full-stack compose setup, API port 8000 is published for development convenience. This is not a typical hardened deployment shape; production-style Docker should expose only port 8443 through the nginx UI proxy.

All endpoints except the public routes (`/health`, `/health/live`, `/health/ready`, `/auth/token`, `/setup/status`, `/setup/initialize`, `/introspection/version`, `/setup/database/system-info`) and documentation routes (`/docs`, `/redoc`, `/openapi.json`) require authentication via JWT bearer tokens. During initial setup, `/setup/database/test-connection`, `/setup/database/provision`, and `/setup/database/provision-status` also allow unauthenticated access; after setup, these endpoints require an `admin` token. See the [REST API Design](docs/design/06-rest-api-design.md) and [Security & Access Control](docs/design/10-security-and-access-control.md) for details.

A [Postman collection](postman/ecube-postman-collection.json) is also available for testing and exploring the API.

## Build and Deployment

Build and deployment guidance (release artifacts, package deployment, Docker images, and compose deployment) is documented in [Build and Deployment](docs/design/13-build-and-deployment.md).

## CI Status

The five badges at the top of this file reflect the current state of automated CI workflows:

Installer/package artifact workflows (`build-artifact.yml` and `tag-release.yml`) now call the shared script `scripts/package-local.sh` so local and CI packaging behavior stays aligned.

- **Tests** — four test suites run on every push: backend unit tests (pytest, SQLite in-memory, cross-platform), backend integration tests (pytest against a live PostgreSQL instance), frontend unit tests (Vitest with coverage), and frontend end-to-end tests (Playwright). See [docs/testing/01-automated-test-requirements.md](docs/testing/01-automated-test-requirements.md) for test conventions.
- **Docker Build** — container images are built and smoke-tested on version bumps (when `pyproject.toml` version changes), `workflow_dispatch`, or release events. Pre-built images are pushed to `ghcr.io/t3knoid/ecube-app` and `ghcr.io/t3knoid/ecube-ui`. See [Using Pre-built Release Images](docs/operations/03-docker-deployment.md#using-pre-built-release-images) for deployment options.
- **Security Scan** — static analysis and dependency vulnerability checks. Triggered manually via GitHub Actions (`workflow_dispatch`). See [docs/testing/05-security-scanning.md](docs/testing/05-security-scanning.md) for details.
- **Schemathesis API Fuzz** — auto-generated requests from the OpenAPI schema to detect schema violations, server errors, and undocumented status codes. Triggered manually via GitHub Actions (`workflow_dispatch`). See the [Schemathesis Local Guide](docs/testing/06-schemathesis-local.md) for running the scan locally.
- **Newman API Smoke** — Postman collection-based API smoke validation. Triggered manually via GitHub Actions (`workflow_dispatch`). See the [Newman Local Guide](docs/testing/07-newman-local.md) for local usage.

## Contributors

- **Testing** — see [docs/testing/01-automated-test-requirements.md](docs/testing/01-automated-test-requirements.md) for test conventions, fixture patterns, and backend/frontend suite execution. For manual QA procedures and test-case assets, use [docs/testing/](docs/testing/).
- **Development** — start with [docs/development/00-development-guide.md](docs/development/00-development-guide.md) for local setup and workflow. Windows-specific development guidance is in [docs/development/02-windows-development-guide.md](docs/development/02-windows-development-guide.md).
- **Documentation** — operational and end-user documentation is in [docs/operations/](docs/operations/). System design and requirement sources are in [docs/design/](docs/design/) and [docs/requirements/](docs/requirements/).

## Documentation

- [Operations Guide](docs/operations/00-operational-guide.md) — production deployment and operations index
- [User Manual](docs/operations/10-user-manual.md) — operator and end-user workflows
- [Installation](docs/operations/01-installation.md) — native install and installer options
- [Configuration Reference](docs/operations/04-configuration-reference.md) — environment variables and runtime settings
- [API Quick Reference](docs/operations/08-api-quick-reference.md) — high-value endpoints for operators and automation
- [REST API Design](docs/design/06-rest-api-design.md) — endpoint contracts and response behavior
- [Security and Access Control](docs/design/10-security-and-access-control.md) — roles, trust boundary, and authorization model
- [Build and Deployment](docs/design/13-build-and-deployment.md) — release artifacts and deployment model

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
