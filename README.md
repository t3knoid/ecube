# ecube

Evidence Copying &amp; USB Based Export

ECUBE is a secure evidence export platform designed to copy eDiscovery data onto encrypted USB drives from a Linux-based copy machine, with strict project isolation, full audit logging, hardware-aware drive management, and a trusted system-layer API that isolates the public UI from direct hardware and database access.

## Application Stack

- **System Layer API:** Python 3.11+, FastAPI
- **Data Layer:** PostgreSQL with SQLAlchemy + Alembic
- **Background Processing:** Celery or RQ workers for copy, verification, and manifest tasks
- **UI Layer:** React, Vue, or server-rendered templates (HTTPS-only)
- **Runtime Platform:** Linux-based copy machine with USB hub integration and NFS/SMB mount support
- **Planned/Optional Security:** LDAP identity provider mode and token-based API authentication (JWT or signed session token)

## PostgreSQL and Alembic Setup

ECUBE uses PostgreSQL as the system-of-record database and Alembic for database schema versioning.

### PostgreSQL (Data Layer)

#### What PostgreSQL is used for in ECUBE

PostgreSQL stores all persistent operational data for the system layer, including:

- USB hardware state (hubs, ports, drives)
- Mount records
- Export jobs and file-level copy metadata
- Audit logs

It is the authoritative source for security and lifecycle state across drive, mount, and job workflows.

#### Install PostgreSQL

Choose one install path:

- **Windows:** Download and run the installer from [PostgreSQL Windows Downloads](https://www.postgresql.org/download/windows/)
- **Ubuntu/Debian:**

  ```bash
  sudo apt update
  sudo apt install -y postgresql postgresql-contrib
  ```

- **RHEL/CentOS/Fedora:** use your distro package manager for `postgresql` and `postgresql-server`.

#### Create ECUBE database and user

After PostgreSQL is installed, create an application user and database:

```sql
CREATE USER ecube WITH PASSWORD 'ecube';
CREATE DATABASE ecube OWNER ecube;
GRANT ALL PRIVILEGES ON DATABASE ecube TO ecube;
```

#### Configure ECUBE connection

Set the database URL in environment (or `.env`) to match your local setup:

```env
DATABASE_URL=postgresql://ecube:ecube@localhost/ecube
```

---

### Alembic (Schema Migration Layer)

#### What Alembic is used for in ECUBE

Alembic manages database schema changes over time. In ECUBE it is used to:

- Create and evolve tables and constraints
- Keep schema aligned between local/dev/test/prod environments
- Apply versioned, auditable migration history

#### Install Alembic

Alembic is installed automatically with project dependencies:

```bash
pip install -e ".[dev]"
```

If needed, install directly:

```bash
pip install alembic
```

#### Initialize and run migrations

This repository already includes Alembic configuration (`alembic.ini` and `alembic/`).

Apply all pending migrations:

```bash
alembic upgrade head
```

Check current migration version:

```bash
alembic current
```

Create a new migration revision (when schema changes are added):

```bash
alembic revision -m "describe change"
```

#### Typical startup sequence

1. Start PostgreSQL and ensure `DATABASE_URL` is correct.
2. Run `alembic upgrade head`.
3. Start the API server (`uvicorn app.main:app --reload`).

## API Documentation

ECUBE provides interactive API documentation via OpenAPI (Swagger UI) and ReDoc. Once the API server is running, access the documentation at:

- **Swagger UI (Interactive):** `http://localhost:8000/docs`
- **ReDoc (Alternative UI):** `http://localhost:8000/redoc`
- **OpenAPI Schema (JSON):** `http://localhost:8000/openapi.json`

The Swagger UI allows you to:

- View all available endpoints with descriptions
- Understand request/response schemas
- Test API endpoints directly from the browser
- Explore authentication and role requirements

All application/API endpoints (except `/health` and documentation endpoints such as `/docs`, `/redoc`, and `/openapi.json`) require authentication via JWT bearer tokens. Full API specification and security role details are documented in:

- `documents/design/06-rest-api-specification.md`
- `documents/design/10-security-and-access-control.md`

---

## Build and Deployment

ECUBE build and deployment guidance (release artifacts, package deployment without Docker runtime, Docker image builds, and compose deployment) is documented in:

- `documents/design/13-build-and-deployment.md`

Choose one runtime path per environment: package deployment **or** Docker deployment.

## Documentation

- [Requirements Documents](documents/requirements)
- [ECUBE Requirements Overview](documents/requirements/00-overview.md)
- [Security & Access Control (Requirements)](documents/requirements/10-security-and-access-control.md)
- [Design Documents](documents/design)
- [ECUBE Design Overview](documents/design/00-overview.md)
- [Security & Access Control (Design)](documents/design/10-security-and-access-control.md)
- [Testing & Validation (Design)](documents/design/11-testing-and-validation.md)
- [Hardware HIL Testing (USB Hub/Devices)](documents/design/11-testing-and-validation.md#1110-hardware-hil-testing-usb-hub-and-devices)
- [Linux Host Deployment & USB Passthrough](documents/design/12-linux-host-deployment-and-usb-passthrough.md)
- [Build & Deployment (Design)](documents/design/13-build-and-deployment.md)
