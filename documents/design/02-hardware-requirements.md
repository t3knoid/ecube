# 2. Hardware Requirements — Design

## 2.1 Copy Machine Design

- Linux host runs ECUBE API service and background worker processes.
- Local storage is used for manifests, temporary metadata, and queues.
- USB subsystem events are consumed via udev/sysfs polling or event hooks.

## 2.2 USB Hub & Port Mapping Design

### Port Identity Strategy

- Persist hub `system_identifier` and port number as stable logical keys.
- Resolve runtime block device names dynamically (avoid relying on `/dev/sdX`).

### State Model

- `EMPTY` when no drive is present.
- `AVAILABLE` when mounted/validated and not assigned.
- `IN_USE` when actively assigned to a project/job.

### Event Handling

- On insertion: detect, identify encryption status, validate mountability, update state.
- On removal: invalidate mount/device references, mark port `EMPTY`, emit audit record.
