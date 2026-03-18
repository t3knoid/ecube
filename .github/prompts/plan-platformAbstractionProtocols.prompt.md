# Plan: Platform Abstraction Protocols (Issue #86)

## TL;DR
Define `typing.Protocol` interfaces at six platform-coupled seams, rename existing Linux implementations to `LinuxXxx` concrete classes, wire through DI where needed, and update introspection hardcoded paths. No behavioral changes; all tests must pass unmodified.

## Discovery Findings

### Already abstracted (no changes needed):
- `FilesystemDetector` Protocol + `LinuxFilesystemDetector` in `filesystem_detection.py`
- `DriveFormatter` Protocol + `LinuxDriveFormatter` in `drive_format.py`
- `RoleResolver` ABC in `auth_providers.py`
- `PamAuthenticator` Protocol in `pam_service.py` (but not wired through DI)
- `platform` setting already exists as `Literal["linux"]`
- `procfs_mounts_path`, `sysfs_usb_devices_path`, `sysfs_block_path` settings exist

### Needs work:
1. **CopyEngine** — module-level functions, no Protocol
2. **Authenticator** — Protocol exists but router hard-instantiates `LinuxPamAuthenticator()`; `get_user_groups` is a bare function
3. **DriveDiscovery** — `discover_usb_topology()` is a bare function, no Protocol
4. **DriveEject** — `sync_filesystem()`, `unmount_device()` are bare functions, no Protocol
5. **MountProvider** — `add_mount()` etc. in `mount_service.py` embed subprocess calls directly
6. **OsUserProvider** — bare functions in `os_user_service.py`, no Protocol
7. **Introspection** — 3 hardcoded paths (`/sys/bus/usb/devices`, `/proc/diskstats`, `/proc/mounts`)
8. **Config** — `platform` is `Literal["linux"]`, needs `"windows"` added

## Steps

### Phase 1: Config & Introspection (no test impact)

1. **Expand `platform` Literal** in `app/config.py` to `Literal["linux", "windows"]`
2. **Add `procfs_diskstats_path`** setting in `app/config.py` (default `/proc/diskstats`)
3. **Replace 3 hardcoded paths** in `app/routers/introspection.py` with `settings.xxx` references

### Phase 2: CopyEngine Protocol (*parallel with Phase 3-6*)

4. **Define `CopyEngine` Protocol** in `app/services/copy_engine.py` with methods: `scan_source_files`, `copy_file`, `checksum_only`
5. **Create `NativeCopyEngine` class** implementing the Protocol, wrapping the existing module-level functions
6. **Keep module-level functions** as-is (they delegate to standard library, not OS-specific) — the Protocol is for future overriding, existing callers (`run_copy_job`, `run_verify_job`) continue using them directly

### Phase 3: Authenticator DI Wiring

7. **Expand `PamAuthenticator` Protocol** in `pam_service.py` to include `authenticate` + `get_user_groups` (confirmed: both methods on a single Authenticator Protocol)
8. **Create `get_authenticator()` factory** in `pam_service.py` (or `app/infrastructure/__init__.py`)
9. **Wire auth router** through `Depends()` or factory call instead of `LinuxPamAuthenticator()` direct instantiation
   - Tests currently patch `app.routers.auth.LinuxPamAuthenticator` — the patch target must remain valid or tests break

### Phase 4: DriveDiscovery Protocol

10. **Define `DriveDiscoveryProvider` Protocol** in `app/infrastructure/usb_discovery.py` with `discover_topology() -> DiscoveredTopology`
11. **Rename `discover_usb_topology` to `LinuxDriveDiscovery.discover_topology`** (keep module-level function as a forward-compat alias)
12. **Add to registry** in `app/infrastructure/__init__.py` with `get_drive_discovery()` factory
13. **Update `discovery_service.py`** default `topology_source` to use the factory

### Phase 5: DriveEject Protocol

14. **Define `DriveEjectProvider` Protocol** in `app/infrastructure/drive_eject.py` with: `sync_filesystem`, `unmount_device`
15. **Create `LinuxDriveEject` class** wrapping existing functions
16. **Add to registry** in `app/infrastructure/__init__.py` with `get_drive_eject()` factory
17. **Update `drive_service.py`** imports to use factory (tests patch at `app.services.drive_service` level — must keep compatible)

### Phase 6: MountProvider Protocol

18. **Define `MountProvider` Protocol** in `app/services/mount_service.py` with: `os_mount`, `os_unmount`, `check_mounted`
19. **Create `LinuxMountProvider` class** wrapping the subprocess calls
20. **Refactor `mount_service.py`** functions to accept/use a MountProvider instead of embedding subprocess calls

### Phase 7: OsUserProvider Protocol

21. **Define `OsUserProvider` Protocol** in `app/services/os_user_service.py` with the public API surface
22. **Create `LinuxOsUserProvider` class** wrapping the existing functions
23. **Add `get_os_user_provider()` factory**
24. **Update router imports** in `admin.py` and `setup.py` (currently `from app.services import os_user_service` calling functions directly — must maintain backward compatibility)

### Phase 8: Verification

25. Run full test suite — all existing tests must pass without modification
26. Verify app loads: `python3 -c "from app.main import app"`

## Relevant Files

### To modify:
- `app/config.py` — expand platform Literal, add procfs_diskstats_path
- `app/routers/introspection.py` — replace 3 hardcoded paths with settings refs
- `app/services/copy_engine.py` — add CopyEngine Protocol + NativeCopyEngine class
- `app/services/pam_service.py` — expand PamAuthenticator Protocol (add get_user_groups)
- `app/routers/auth.py` — wire through factory instead of direct instantiation
- `app/infrastructure/usb_discovery.py` — add DriveDiscoveryProvider Protocol + LinuxDriveDiscovery class
- `app/infrastructure/drive_eject.py` — add DriveEjectProvider Protocol + LinuxDriveEject class
- `app/infrastructure/__init__.py` — add registries + factories for discovery, eject
- `app/services/discovery_service.py` — update default topology_source
- `app/services/drive_service.py` — update eject imports
- `app/services/mount_service.py` — add MountProvider Protocol + LinuxMountProvider
- `app/services/os_user_service.py` — add OsUserProvider Protocol + LinuxOsUserProvider

### Reference patterns:
- `app/infrastructure/filesystem_detection.py` — FilesystemDetector Protocol pattern
- `app/auth_providers.py` — RoleResolver ABC pattern + get_role_resolver() factory
- `app/infrastructure/__init__.py` — registry + factory pattern

## Verification
1. `python3 -m pytest tests/ -v` — all existing tests pass
2. `python3 -c "from app.main import app; print('OK')"` — app loads
3. `grep -rn "hardcoded" app/routers/introspection.py` — no /sys or /proc literals remain

## Decisions
- `get_user_groups` is part of the Authenticator Protocol (user confirmed — single Protocol with authenticate + get_user_groups)
- MountProvider and OsUserProvider confirmed as Protocols (user confirmed)
- Protocols defined in same module as implementation (user preference, matches existing pattern)
- Module-level functions kept as wrappers/aliases for backward compat (tests patch them)
- `typing.Protocol` preferred over ABC (simple interfaces, no shared state)
- Existing callers continue using module-level functions where changing would break test patches
- `platform` expanded to `Literal["linux", "windows"]` per AC

## Critical Constraint
**Tests must not be modified.** All test patch targets (e.g. `app.routers.auth.LinuxPamAuthenticator`, `app.services.drive_service.sync_filesystem`) must remain valid after refactoring. This constrains how we restructure imports.
