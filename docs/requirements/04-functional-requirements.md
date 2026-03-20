# 4. Functional Requirements

## 4.1 Drive Lifecycle Management

ECUBE must:

- Detect drive insertion/removal
- Determine drive state
- Detect filesystem type (ext4, exFAT, NTFS, FAT32, or unformatted/unknown)
- Format unformatted or incorrectly formatted drives on demand
- Initialize drive for a job
- Assign drive to a job
- Prepare drive for eject (flush + unmount)
- Track drive usage history

### 4.1.1 Filesystem Detection

On drive insertion or discovery refresh, ECUBE must:

- Probe the drive's filesystem type using OS tools (e.g., `blkid`, `lsblk`)
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

## 4.2 Project Isolation (Critical Requirement)

To prevent evidence contamination:

- Each drive is assigned a `project_id` upon initialization
- A drive cannot accept files from a different project
- ECUBE must block the operation and log an audit event if attempted
- UI must display the project associated with each `IN_USE` drive

## 4.3 Job Management

A job includes:

- Source path (local, NFS, SMB)
- Evidence number
- Project ID
- Assigned drive
- Thread count for copy engine
- File list and checksums
- Copy progress
- Manifest generation

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
- Job creation
- Copy start/stop
- File copy events
- Manifest creation
- Mount operations
- Project isolation violations
