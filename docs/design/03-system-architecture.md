# 3. System Architecture — Design

## Component View

- **UI Layer (untrusted):** Displays status, submits requests, never talks directly to DB/hardware.
- **System Layer (trusted):** Enforces policy, executes mounts/copies, writes audit logs.
- **PostgreSQL 14+ (private):** Stores source-of-truth state for jobs, drives, assignments, and logs.

## Interaction Pattern

1. UI calls authenticated API endpoint.
2. System layer validates authorization and project isolation.
3. System layer performs operation and persists transaction.
4. Response includes normalized state for UI rendering.

## Platform Abstraction Layer

All OS-specific operations are isolated behind abstract interfaces in `app/infrastructure/`.  Each interface defines a contract (using `typing.Protocol` or `abc.ABC`) that the service layer depends on; a concrete implementation satisfies the contract for a specific operating system.  This separation provides:

- **Cross-platform extensibility:** A new platform (e.g. macOS, Windows) only requires new concrete implementations — no service-layer changes.
- **Testability:** Tests inject lightweight fakes or mocks that satisfy the same interface, with no real hardware or OS dependency.
- **Dependency injection:** The active implementation is selected at startup (via settings or auto-detection) and injected into services, not imported directly.

### Interface Contracts

| Interface | Responsibility | Linux Reference Implementation |
|-----------|---------------|-------------------------------|
| `DriveDiscoveryBackend` | Enumerate USB hubs, ports, and drives | Reads `/sys/bus/usb/devices` (sysfs) |
| `FilesystemDetector` | Probe a block device for filesystem type | `blkid`, fallback `lsblk --json` |
| `DriveFormatter` | Format a block device with a specified filesystem | `mkfs.ext4`, `mkfs.exfat` |
| `MountManager` | Mount/unmount network shares and block devices | `mount`, `umount`, `/proc/mounts` |
| `DriveEjectBackend` | Flush writes and unmount all partitions of a device | `sync(1)`, `umount`, `/proc/mounts`, sysfs `/sys/block/*/slaves/` |
| `PamAuthenticator` | Validate local credentials | PAM via `python-pam` |
| `OSUserManager` | Create/delete OS users and groups | `useradd`, `userdel`, `groupadd` via sudo |

Concrete implementations live alongside the interface in `app/infrastructure/` (e.g. `linux_discovery.py`, `linux_formatter.py`).  Settings expose configurable binary paths and filesystem paths so even the Linux implementation is not hardcoded to default locations.

### Selection Strategy

The active platform backend is determined by `settings.platform` (default: `"linux"`) at application startup.  A factory function in `app/infrastructure/__init__.py` returns the appropriate concrete implementations.  Tests override these via FastAPI `dependency_overrides` or by supplying fakes to service functions directly.

## Startup Behavior

The FastAPI lifespan context manager executes the following steps during application startup, before the server begins accepting requests:

1. **Session backend initialization** — connects to Redis (if configured) for session storage.
2. **Audit log cleanup** — purges expired audit records per `AUDIT_LOG_RETENTION_DAYS`.
3. **Startup state reconciliation** — acquires a cross-process lock (`reconciliation_lock` single-row guard table), then corrects stale mounts, fails interrupted jobs, and re-runs USB discovery.  In multi-worker deployments only the first worker runs reconciliation; the others skip it.  See [§ 4.11 Startup State Reconciliation](04-functional-requirements.md#411-startup-state-reconciliation) for full specification.
4. **Periodic USB discovery loop** — background task that re-scans USB topology at `USB_DISCOVERY_INTERVAL` intervals.

Reconciliation runs in fixed order (mounts → jobs → drives) with per-pass error isolation, so a failure in one pass does not block the others.  The lock is released in a `finally` block regardless of success or failure.

## Security Design

- DB reachable only from system-layer network segment.
- Hardware access scoped to system-layer process user/group.
- API endpoints validate project ownership and allowed transitions.
