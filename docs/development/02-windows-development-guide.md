# ECUBE Windows Development Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Developers, Contributors (Windows)  
**Document Type:** Setup / How-To

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Environment Setup](#environment-setup)
4. [USB Passthrough with usbipd-win](#usb-passthrough-with-usbipd-win)
5. [Running the Application](#running-the-application)
6. [Database and Migrations](#database-and-migrations)
7. [Running Tests](#running-tests)
8. [Troubleshooting](#troubleshooting)
9. [Related Documentation](#related-documentation)

---

## Overview

ECUBE targets Linux for production, but day-to-day development can be done on Windows using Docker Desktop and WSL2. This guide covers everything you need to set up a full Windows development environment, including USB passthrough for hardware testing.

The `docker-compose.ecube-win.yml` file provides a Dockerized PostgreSQL instance for Windows development.

---

## Prerequisites

### System Requirements

- Windows 10 (build 19041+) or Windows 11
- At least 8 GB RAM (16 GB recommended — WSL2 and Docker share memory)

### Software

Install the following before proceeding:

| Software | Purpose | Install Command / Link |
|----------|---------|----------------------|
| **WSL2** | Linux kernel for Docker and USB passthrough | `wsl --install` (elevated PowerShell) |
| **Docker Desktop** | Containerized application and database | [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) |
| **Python 3.11+** | Running tests and local tooling | [python.org](https://www.python.org/downloads/) or `winget install Python.Python.3.11` |
| **Git** | Source control | `winget install Git.Git` |
| **usbipd-win** | USB device sharing with WSL2 (optional) | `winget install usbipd` |
| **VS Code** | Editor and debugger (recommended) | `winget install Microsoft.VisualStudioCode` |

### WSL2 Setup

1. Open an **elevated PowerShell** and run:

   ```powershell
   wsl --install
   ```

   This installs WSL2 with the default Ubuntu distribution. Restart if prompted.

2. After reboot, open **Ubuntu** from the Start menu and complete the initial user setup.

3. Verify Docker Desktop is configured to use the WSL2 backend:
   - Open Docker Desktop → **Settings** → **General**
   - Ensure **Use the WSL 2 based engine** is checked

---

## Environment Setup

### Clone and Install

Open a **PowerShell** or **Windows Terminal** prompt:

```powershell
# Clone the repository
git clone https://github.com/t3knoid/ecube.git
cd ecube

# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install the project with dev dependencies
pip install -e ".[dev]"
```

> **Note:** If you use **cmd.exe** instead of PowerShell, activate the venv with `.venv\Scripts\activate.bat`.

### Environment Configuration

ECUBE reads settings from environment variables or a `.env` file in the project root. All settings have defaults suitable for local development.

```powershell
# Optional: create a .env file to override defaults
Copy-Item .env.example .env
```

Key settings for development:

| Variable | Default | Notes |
|----------|---------|-------|
| `DATABASE_URL` | `postgresql://ecube:ecube@localhost/ecube` | Local PostgreSQL connection |
| `SECRET_KEY` | (built-in dev default) | JWT signing key; change in production |
| `ROLE_RESOLVER` | `local` | Uses OS group → role mapping |

See the [Configuration Reference](../operations/02-configuration-reference.md) for the full list.

---

## USB Passthrough with usbipd-win

USB passthrough is **optional** — it is only needed when testing USB hardware features. Unit tests and most development workflows do not require physical USB devices.

### Install usbipd-win

`usbipd-win` allows you to share locally connected USB devices with WSL2 (and therefore Docker containers running on the WSL2 backend).

1. **Install via winget (recommended):**

   ```powershell
   winget install usbipd
   ```

   Alternatively, download the latest `.msi` installer from the [usbipd-win releases page](https://github.com/dorssel/usbipd-win/releases).

2. **Install the USBIP tools inside your WSL2 distribution:**

   ```bash
   # From a WSL2 terminal (e.g., Ubuntu)
   sudo apt update
   sudo apt install linux-tools-generic hwdata
   sudo update-alternatives --install /usr/local/bin/usbip usbip \
     $(find /usr/lib/linux-tools/*/usbip | head -1) 20
   ```

3. **Verify the install** by listing USB devices from an elevated PowerShell prompt:

   ```powershell
   usbipd list
   ```

   You should see all USB devices connected to your Windows host with their bus IDs and descriptions.

### Sharing a USB Device with Docker

USB devices must be attached to WSL2 before the Docker container can see them. Run the following commands from an **elevated (Administrator) PowerShell** prompt:

1. **List available USB devices:**

   ```powershell
   usbipd list
   ```

   Example output:

   ```
   Connected:
   BUSID  VID:PID    DEVICE                          STATE
   1-2    0781:5581  SanDisk Ultra USB 3.0           Not shared
   1-7    8087:0029  Intel Bluetooth                 Not shared
   ```

2. **Bind the device** (one-time step — makes the device shareable):

   Open and run as administrator a command prompt.

   ```powershell
   usbipd bind --busid <BUSID>
   ```

   For example: `usbipd bind --busid 1-2`

3. **Attach the device to WSL2:**

   ```powershell
   usbipd attach --wsl --busid <BUSID>
   ```

   The device now appears inside WSL2 (and any Docker container with the appropriate volume mounts). You can verify from a WSL2 terminal:

   ```bash
   lsusb
   ```

   You may have to install the `usbutils` package with `sudo apt install usbutils`.

4. **Detach when done:**

   ```powershell
   usbipd detach --busid <BUSID>
   ```

> **Tip:** You must re-attach the device after every unplug/replug cycle or WSL2 restart. Consider scripting the `bind` + `attach` commands for convenience.

---

## Running the Application

The application runs natively on the host for the best development and debugging experience. Docker is used only for PostgreSQL.

### Start PostgreSQL and Run Locally

Use Docker Compose to run PostgreSQL, then start the application locally with auto-reload:

```powershell
# Start PostgreSQL
docker compose -f docker-compose.ecube-win.yml up -d postgres

# Apply migrations (from your local venv)
alembic upgrade head

# Start the dev server with auto-reload
uvicorn app.main:app --reload
```

The default `DATABASE_URL` (`postgresql://ecube:ecube@localhost/ecube`) matches the containerized Postgres, so no `.env` change is needed.

To stop or reset the database:

```powershell
# Stop PostgreSQL
docker compose -f docker-compose.ecube-win.yml down

# Stop and remove volumes (clean slate)
docker compose -f docker-compose.ecube-win.yml down -v
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Database and Migrations

Alembic manages all schema migrations. Run these commands from the project root with your virtual environment activated:

```powershell
# Apply all migrations
alembic upgrade head

# Check current migration version
alembic current

# Auto-generate a migration from model changes
alembic revision --autogenerate -m "describe change"

# Rollback one step
alembic downgrade -1
```

> **Note:** Migrations require a running PostgreSQL database. Start the Docker database first (see [Running the Application](#running-the-application)).

---

## Running Tests

### Unit Tests

Unit tests use an in-memory SQLite database and do **not** require Docker, PostgreSQL, or USB hardware:

```powershell
# Activate the virtual environment
.venv\Scripts\Activate.ps1

# Run all unit tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_drives.py -v

# Run a single test by name
python -m pytest tests/test_drives.py -v -k "test_list_drives"
```

### Integration Tests

Integration tests run against a real PostgreSQL database. Start just the Postgres service from the Windows compose file:

```powershell
# Start the integration database
docker compose -f docker-compose.ecube-win.yml up -d postgres

# Set the database URL and run integration tests
$env:DATABASE_URL="postgresql://ecube:ecube@localhost/ecube"
python -m pytest tests/ -v --run-integration

# Stop the integration database
docker compose -f docker-compose.ecube-win.yml down -v
```

### Hardware Tests

Hardware-in-the-loop tests require physical USB devices attached via usbipd-win (see [USB Passthrough](#usb-passthrough-with-usbipd-win)):

```powershell
python -m pytest tests/ -v --run-hardware
```

> **Debugging:** For command-line debugging, VS Code debugger setup, breakpoints, launch configurations, and troubleshooting debug issues, see the **[Debugging Guide](01-debugging-guide.md)**. It applies to all platforms including Windows.

---

## Troubleshooting

### General

| Symptom | Fix |
|---------|-----|
| `pip install -e ".[dev]"` fails on Windows | Ensure you are using Python 3.11+. Run `python --version` to verify. |
| `.venv\Scripts\Activate.ps1` is blocked | Run `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` first |
| `alembic upgrade head` connection refused | Start the PostgreSQL container first |
| `uvicorn` not found | Ensure the virtual environment is activated |

### Docker

| Symptom | Fix |
|---------|-----|
| `docker compose` command not found | Update Docker Desktop to a recent version (Compose v2 is built in) |
| Container fails to start | Check logs: `docker compose -f docker-compose.ecube-win.yml logs ecube-app-dev` |
| Port 8000 already in use | Stop other processes on that port, or change the port mapping in the compose file |
| PostgreSQL health check fails | Wait a few seconds and retry; or run `docker compose -f docker-compose.ecube-win.yml down -v` for a clean start |

### USB Passthrough

| Symptom | Fix |
|---------|-----|
| `usbipd list` shows no devices | Run PowerShell as Administrator |
| `usbipd attach` fails with "not shared" | Run `usbipd bind --busid <BUSID>` first |
| Device not visible inside Docker container | Ensure Docker Desktop is using the WSL2 backend and the device is attached to WSL2 |
| WSL2 `lsusb` shows the device but Docker does not | Restart Docker Desktop; ensure the container uses appropriate volume mounts for `/dev/bus/usb` |
| Permission errors accessing USB in WSL2 | Install `linux-tools-generic` and `hwdata` in your WSL2 distro |

> For debugging troubleshooting (breakpoints not hit, wrong interpreter, etc.), see the **[Debugging Guide](01-debugging-guide.md#tips-and-troubleshooting)**.

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [Development Guide](00-development-guide.md) | Main development guide (Linux-focused) |
| [Debugging Guide](01-debugging-guide.md) | Detailed debugging reference (cross-platform) |
| [Operational Guide](../operations/00-operational-guide.md) | Production deployment and operations |
| [Configuration Reference](../operations/02-configuration-reference.md) | All environment variables and settings |
| [QA Testing Guide](../testing/01-qa-testing-guide-baremetal.md) | Manual test procedures |

---

**End of Windows Development Guide**
