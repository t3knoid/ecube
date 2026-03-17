# 2. Hardware Requirements — Design

## 2.1 Copy Machine Design

- Primary target platform is Linux; all OS-specific operations are accessed through abstract interfaces (see §3 Platform Abstraction Layer) so alternative platform implementations can be added without modifying the service layer.
- Local storage is used for manifests, temporary metadata, and queues.
- USB subsystem events are consumed through the `DriveDiscoveryBackend` interface (Linux reference: udev/sysfs polling).

## 2.2 USB Hub & Port Mapping Design

### Port Identity Strategy

- Persist hub `system_identifier` and port number as stable logical keys.
- Resolve runtime block device names dynamically (avoid relying on `/dev/sdX`).

### State Model

- `EMPTY` when no drive is present.
- `AVAILABLE` when mounted/validated and not assigned.
- `IN_USE` when actively assigned to a project/job.

### Event Handling

- On insertion: detect, identify encryption status, detect filesystem type, validate mountability, update state.
- On removal: invalidate mount/device references, mark port `EMPTY`, emit audit record.

### Filesystem Detection

- Probe inserted drives for filesystem type through the `FilesystemDetector` interface (Linux reference: `blkid`, `lsblk --json`).
- Recognized types: `ext4`, `exfat`, `ntfs`, `fat32`, `xfs`, and others reported by the OS.
- Drives with no recognizable filesystem are labelled `unformatted`.
- Detection failures (permission errors, I/O errors) are labelled `unknown`.
- Store the result in `usb_drives.filesystem_type` on each discovery cycle.
- The interface returns a canonical string; mapping OS-specific tool output to canonical values is the responsibility of each concrete implementation.
