# 11. Testing and Validation

This document defines how to run automated tests for ECUBE using `pytest`, including unit tests, integration tests, and hardware-in-the-loop validation.

## 11.1 Test Scope

### Unit Tests

Unit tests validate API routes and service behavior in isolation.

- Database: SQLite in-memory with `StaticPool`.
- External/system calls: mocked where applicable.
- Speed: fast; suitable for local rapid iteration and CI default runs.

Current unit tests live in `tests/`.

### Integration Tests

Integration tests validate behavior against real infrastructure components.

- Database: PostgreSQL test database.
- Migrations: applied with Alembic before execution.
- Optional system integrations: mount tooling, filesystem, and introspection dependencies.

Integration tests live in `tests/integration/` and are gated by `--run-integration`.

### Hardware HIL Tests

Hardware-in-the-loop tests validate behavior with a physical USB hub and devices.

- Tests are in `tests/hardware/`.
- Execution requires `--run-hardware`.

## 11.2 Prerequisites

### Common Requirements

- Python `3.11+`
- Virtual environment activated
- Development dependencies installed

Install dependencies:

```bash
pip install -e ".[dev]"
```

### Unit Test Requirements

- No PostgreSQL required.
- No mount/hardware privileges required.

### Integration Test Requirements

- PostgreSQL instance available and reachable.
- `DATABASE_URL` (or `INTEGRATION_DATABASE_URL`) set to integration DB.
- Schema migrated with Alembic.

## 11.3 Running Unit Tests

Run all unit tests:

```bash
python -m pytest tests -q
```

Run a single module:

```bash
python -m pytest tests/test_jobs.py -q
```

Run by keyword:

```bash
python -m pytest tests -q -k "mount or job"
```

### Drive Eject Unit Tests

The `tests/test_drive_eject.py` module validates the `/proc/mounts` parsing, device discovery, and unmount sequencing logic used by `prepare_eject`. This is the core of the filesystem-level safety:

**Test Coverage:**

- **Partition discovery:** Traditional (`sdb1`, `sdb2`), NVMe (`nvme0n1p1`), and MMC (`mmcblk0p1`) naming schemes.
- **Escape sequence handling:** Validates that mount points with spaces, tabs, and other POSIX escape sequences from `/proc/mounts` are properly decoded before being passed to `umount`.
- **Device-mapper (encrypted) support:** 
  - Validates `/dev/mapper/*` device symlink resolution to `/dev/dm-N` nodes via `os.path.realpath()`
  - Validates parent device discovery via `/sys/block/dm-N/slaves/` sysfs interface
  - Tests LUKS-encrypted volumes, LVM logical volumes, and direct dm-device paths
  - Confirms that mapper devices backed by a different device are correctly excluded
- **Safe unmount ordering:** Validates that nested mount points (e.g., `/media/usb` and `/media/usb/sub`) are unmounted in reverse depth order to prevent "target is busy" errors.
- **Error handling:** Validates graceful handling of `/proc/mounts` read failures, missing sysfs paths, and unmount failures.

Run drive eject tests:

```bash
python -m pytest tests/test_drive_eject.py -q
```

### Filesystem Detection & Drive Formatting Tests

Tests for filesystem type detection and drive formatting should cover:

**Filesystem Detection:**

- **`blkid` happy path:** Mock `blkid -o value -s TYPE` returning known types (`ext4`, `exfat`, `ntfs`, `fat32`, `xfs`) and verify the parsed value is stored correctly.
- **Unformatted drive:** Mock `blkid` returning empty output (no filesystem signature) and verify the result is `unformatted`.
- **Detection failure:** Mock `blkid` subprocess failure (non-zero exit, timeout, OSError) and verify the result is `unknown`.
- **Discovery integration:** Verify that a discovery cycle updates `usb_drives.filesystem_type` for newly inserted drives.

**Drive Formatting:**

- **Happy path:** Mock `mkfs.ext4` or `mkfs.exfat` succeeding and verify the drive's `filesystem_type` is updated and `DRIVE_FORMATTED` audit event is emitted.
- **Unsupported type:** Request format with an unsupported filesystem type and verify `400` response.
- **Precondition enforcement:** Verify `409` when drive is not in `AVAILABLE` state, when drive is currently mounted, or when drive is in `IN_USE` state.
- **Missing device path:** Verify `400` when the drive has no `filesystem_path`.
- **Format failure:** Mock `mkfs` failing and verify the drive state is unchanged, `DRIVE_FORMAT_FAILED` is audit-logged, and `500` is returned.
- **Device path validation:** Verify that invalid device paths (e.g., path traversal) are rejected before any subprocess is spawned.
- **Role enforcement:** Verify that `processor` and `auditor` roles receive `403`.

### OS User & Group Management Tests

The `tests/test_os_user_management.py` module validates the OS user and group management service layer and admin API endpoints.

**Test Coverage:**

- **Service layer:** `useradd`, `userdel`, `groupadd`, `groupdel`, `chpasswd`, and `usermod` subprocess calls are mocked and verified.
- **Group namespace enforcement:** Group create/delete rejects names without the `ecube-` prefix.
- **ECUBE-managed user guard:** Mutative user operations reject users who are not members of any `ecube-*` group.
- **Atomicity and compensation:** User creation validates groups before `useradd`; `usermod` failures trigger compensating `userdel`. Failed DB role seeding triggers compensating OS user deletion.
- **Password validation:** Rejects passwords containing newlines, carriage returns, and colons (chpasswd injection prevention).
- **Admin router endpoints:** All nine OS management endpoints tested via `TestClient`, including auth/role gating.
- **Non-local mode gating:** Verifies all OS endpoints return `404` when `role_resolver != "local"` (`LocalOnlyRoute`).
- **First-run setup wizard:** Setup initialization, recovery for pre-existing users (including users not yet in `ecube-*` groups), and cross-process locking.
- **Startup reconciliation lock:** Cross-process lock acquisition, stale lock reclaim, orchestrator skip-when-locked, and lock release on success/failure.
- **Audit logging:** Verifies structured audit records for all OS operations.

Run OS user and group management tests:

```bash
python -m pytest tests/test_os_user_management.py -v
```

### Role Resolution and OIDC Tests

The `tests/test_role_resolver.py` and `tests/test_oidc_service.py` modules validate identity provider integration.

#### Role Resolver Tests

Coverage includes:

- **LocalGroupRoleResolver**: maps local OS/app groups to ECUBE roles
- **LdapGroupRoleResolver**: maps LDAP group DNs to ECUBE roles
- **OidcGroupRoleResolver**: maps OIDC provider group claims to ECUBE roles
- **Deny-by-default semantics**: unmapped groups contribute no roles
- **Deduplication**: multiple groups mapping to overlapping roles are deduplicated
- **Factory pattern**: `get_role_resolver()` selects the correct provider based on `settings.role_resolver`

Run role resolver tests:

```bash
python -m pytest tests/test_role_resolver.py -v
```

#### OIDC Service Tests

Coverage includes:

- **Token validation**: RSA-256/384/512 and EC-256/384/512 signature verification
- **Expiration checking**: strict enforcement of `exp` claim
- **Audience validation**: optional `aud` claim validation when `OIDC_AUDIENCE` is configured
- **JWKS discovery and caching**: fetches from provider discovery URL; caches for process lifetime
- **Discovery failures**: network errors, malformed discovery documents, missing JWKS URI
- **Group claim extraction**: custom claim names (e.g., `org_groups` instead of `groups`)
- **Error handling**: proper error propagation (`OidcTokenError` → HTTP 401)

Tests use mocked RSA keypairs and don't require access to actual OIDC providers.

Run OIDC tests:

```bash
python -m pytest tests/test_oidc_service.py -v
```

#### Integration Tests for OIDC

Integration tests validate the end-to-end flow of OIDC token validation and role resolution within the authentication layer (`get_current_user()`).

- **Token with valid groups** → roles correctly resolved
- **Token without groups** → empty roles (deny-by-default)
- **Mixed mapped/unmapped groups** → only mapped groups contribute roles
- **Validation failures** → HTTP 401 with appropriate error message
- **Fallback to sub/email** → when `preferred_username` is absent

Run OIDC integration tests:

```bash
python -m pytest tests/test_role_resolver.py::TestGetCurrentUserWithOidcResolver -v
```

Run specific device-mapper tests:

```bash
python -m pytest tests/test_drive_eject.py::TestResolveMapperDevice -q
```

## 11.4 Integration Test Setup

Use a dedicated PostgreSQL database for integration tests.

### Option A: Local Docker Compose (recommended)

Start just the PostgreSQL service:

```bash
docker compose -f docker-compose.ecube.yml up -d postgres
```

Set integration environment variables.

```bash
export DATABASE_URL="postgresql://ecube:ecube@localhost/ecube"
```

Apply migrations:

```bash
alembic upgrade head
```

Run integration tests:

```bash
python -m pytest tests/integration -q --run-integration
```

Run integration tests with live stdout/stderr output:

```bash
python -m pytest tests/integration -q -s --run-integration
```

Shutdown when done:

```bash
docker compose -f docker-compose.ecube.yml down
```

## 11.5 PostgreSQL Concurrency Scaffold

The repository includes a real row-lock contention scaffold:

- `tests/integration/test_concurrency_scaffold_integration.py`

What it validates:

- Session A acquires `FOR UPDATE` lock on a row.
- Session B attempts `FOR UPDATE NOWAIT` on the same row.
- Application-level conflict handling is surfaced correctly.

Run only this scaffold:

```bash
python -m pytest tests/integration/test_concurrency_scaffold_integration.py -q --run-integration
```

Run full integration suite including scaffold:

```bash
python -m pytest tests/integration -q --run-integration
```

Note: this scaffold requires PostgreSQL and auto-skips on non-PostgreSQL backends.

## 11.6 Local Debug Workflow (Integration)

1. Start local PostgreSQL:

   ```bash
   docker compose -f docker-compose.ecube.yml up -d postgres
   ```

2. Set integration environment variables.
3. Apply migrations: `alembic upgrade head`.
4. Run a focused integration test:

   ```bash
   python -m pytest tests/integration/test_smoke_integration.py -q --run-integration -s
   ```

## 11.7 Suggested CI Test Sequence

1. Install dependencies: `pip install -e ".[dev]"`.
2. Run unit tests: `python -m pytest tests -q`.
3. If integration infrastructure is available:

   ```bash
   alembic upgrade head
   python -m pytest tests/integration -q --run-integration
   ```

## 11.8 Integration Use-Case Coverage Matrix

- Authentication and access: `tests/integration/test_auth_use_cases_integration.py`
- Drive management: `tests/integration/test_drives_use_cases_integration.py`
- Mount management: `tests/integration/test_mounts_use_cases_integration.py`
- Job lifecycle: `tests/integration/test_jobs_use_cases_integration.py`
- Introspection: `tests/integration/test_introspection_use_cases_integration.py`
- Baseline smoke: `tests/integration/test_smoke_integration.py`

## 11.9 Hardware HIL Testing

Hardware test skeleton:

- `tests/hardware/test_usb_hub_hil.py`

Run explicitly:

```bash
python -m pytest tests/hardware/test_usb_hub_hil.py -s --run-hardware
```

Guidance:

- Use disposable media only.
- Keep host USB environment stable during execution.
- Run on dedicated hardware for CI-style execution.
