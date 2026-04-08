# 4. Functional Requirements

## 4.1 Drive Lifecycle Management

ECUBE must:

- Detect drive insertion/removal
- Determine drive state
- Persist drive state as a finite-state machine
- Detect filesystem type (ext4, exFAT, NTFS, FAT32, or unformatted/unknown)
- Format unformatted or incorrectly formatted drives on demand
- Initialize drive for a job
- Assign drive to a job
- Prepare drive for eject (flush + unmount)
- Finalize a drive for custody handoff / export completion
- Allow an explicitly audited reopen of a finalized drive when additional data must be exported
- Track drive usage history

Drive states must include:

- `EMPTY`
- `AVAILABLE`
- `IN_USE`
- `FINALIZED`

State intent:

- `AVAILABLE` means writable and eligible for initialization or job assignment.
- `FINALIZED` means logically sealed against additional writes until explicitly reopened.

Legal transitions must include:

- `EMPTY → AVAILABLE`
- `AVAILABLE → IN_USE`
- `IN_USE → AVAILABLE`
- `IN_USE → FINALIZED`
- `AVAILABLE → FINALIZED`
- `FINALIZED → AVAILABLE`
- `AVAILABLE → EMPTY`

Illegal transitions must be rejected with `409 Conflict`.

### 4.1.1 Filesystem Detection

On drive insertion or discovery refresh, ECUBE must:

- Probe the drive's filesystem type
- Store the detected filesystem type in the `usb_drives` record
- Report unformatted (no recognizable filesystem) drives as `unformatted`
- Update the filesystem type whenever a drive is reformatted or re-detected

### 4.1.2 Drive Formatting

ECUBE must provide an API to format a drive with a specified filesystem:

- Supported filesystem types: `ext4`, `exfat`
- Formatting must only be allowed on drives in `AVAILABLE` state
- The drive must not be mounted before formatting begins
- After successful formatting, the `filesystem_type` field must be updated
- All format operations must be audit-logged with actor, drive, and filesystem type
- Format failures must be audit-logged with error details

### 4.1.3 Prepare-Eject, Finalize, and Reopen

ECUBE must distinguish between operational safe removal and custody finalization:

- `prepare-eject` must flush writes, unmount the drive, and transition the drive from `IN_USE` to `AVAILABLE`
- `prepare-eject` must not imply export completion or write protection
- `prepare-eject` must not clear the drive's `current_project_id`

ECUBE must provide a finalization capability with the following requirements:

- Finalization must be a separate operation from prepare-eject
- Finalization must transition the drive to `FINALIZED`
- Finalization must only be allowed for project-bound drives
- Finalization must reject requests while copy/verify/manifest work is still active for the drive
- If finalization begins from `IN_USE`, ECUBE must perform the same safe-eject behavior required by prepare-eject before committing the `FINALIZED` state
- Finalization must record audit data including actor, drive, project, and finalization metadata
- Finalized drives must not be eligible for new job creation, auto-assignment, implicit return to `IN_USE`, formatting, or reinitialization

ECUBE must provide a reopen/unfinalize capability with the following requirements:

- Reopen must only be allowed when the drive is in `FINALIZED` state
- Reopen must require elevated privileges
- Reopen must require an explicit operator-provided reason
- Reopen must transition the drive from `FINALIZED` to `AVAILABLE`
- Reopen must preserve `current_project_id` by default
- Reopen must emit a dedicated audit event recording actor, reason, drive, and project context
- Reopen must never occur implicitly during discovery, initialization, or job creation

## 4.2 Project Isolation (Critical Requirement)

To prevent evidence contamination:

- Each drive is assigned a `project_id` upon initialization
- A drive cannot accept files from a different project
- ECUBE must block the operation and log an audit event if attempted
- UI must display the project associated with each `IN_USE` drive
- Finalization must not clear project binding
- A finalized drive must remain bound to its project until explicitly reopened or reset

## 4.3 Job Management

A job includes:

- Source path (local, NFS, SMB)
- Evidence number
- `project_id`
- `drive_id`
- Thread count for copy engine
- File list and checksums
- Copy progress
- Manifest generation

Job and drive assignment rules must additionally enforce:

- Only `AVAILABLE` drives may be assigned to new jobs
- `FINALIZED` drives must be excluded from auto-assignment and explicit job targeting
- Additional data export to a finalized drive must require an explicit reopen operation first

## 4.4 Multi-threaded Copy Engine

ECUBE must support:

- Multi-threaded copying (user-configurable thread count)
- Behavior similar to Windows robocopy `/MT:n`
- Resume-on-error behavior
- Per-file status tracking
- Checksum verification

### 4.4.1 Linux robocopy equivalent

If a Linux robocopy-like tool exists (for example, `rclone` or `rsync` with parallelization), ECUBE may use it.

If not, ECUBE must implement:

- Thread pool
- Chunked file copying
- Queue-based file distribution
- Retry logic
- Atomic status updates

## 4.5 Network Mount Support

ECUBE must support:

- NFS mounts
- SMB/CIFS mounts

### 4.5.1 Mount API

- Add mount
- Remove mount
- List mounts
- Validate mount accessibility

### 4.5.2 Mount lifecycle

- ECUBE System Layer mounts the share
- Validates read access
- Exposes mount in job creation UI
- Unmounts when no longer needed

## 4.6 Manifest Generation

Manifest includes:

- Evidence number
- Project metadata
- Source path
- File list with checksums
- Total size
- Timestamp

## 4.7 Audit Logging

Every operation must be logged:

- Drive initialization
- Drive prepare-eject success/failure
- Drive finalization
- Drive reopen/unfinalize
- Job creation
- Copy start/stop
- File copy events
- Manifest creation
- Mount operations
- Project isolation violations

## 4.8 Discovery and Reconciliation Behavior

Discovery and refresh behavior must preserve protected drive states:

- Reconnecting drives may transition `EMPTY → AVAILABLE`
- `AVAILABLE` drives may transition to `EMPTY` when removed or when policy disables their port
- `IN_USE` drives must not be demoted by discovery refresh while project isolation is active
- `FINALIZED` drives must not be demoted or implicitly reopened by discovery refresh
- A finalized drive that is physically removed and later reinserted must remain `FINALIZED` until an explicit reopen occurs
