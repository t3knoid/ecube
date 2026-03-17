# 5. Data Model — Design

## Modeling Approach

- Use normalized relational tables for core entities.
- Keep mutable operational state explicit (`status`, timestamps, assignment fields).
- Store high-variability audit details as `JSONB`.

## Table Design Notes

### Hardware Domain

- `usb_hubs` and `usb_ports` define stable topology references.
- `usb_drives` captures runtime device identity and current assignment/state.
- `usb_drives.filesystem_type` stores the detected filesystem label (e.g., `ext4`, `exfat`, `ntfs`, `fat32`, `unformatted`, `unknown`). Updated during discovery and after formatting operations. Nullable; `NULL` means detection has not yet been attempted.

### Mount Domain

- `network_mounts` tracks protocol type, remote path, local path, and health.

### Job Domain

- `export_jobs` stores job-level lifecycle and throughput counters.
- `export_files` stores per-file status/checksum for retries and verification.
- `manifests` stores generated artifact pointers.
- `drive_assignments` preserves assignment history over time.

### Audit Domain

- `audit_logs` provides append-only operation history with actor and context.

### User & System Domain

- `user_roles` stores explicit username→role assignments managed through the admin API.
- `system_initialization` is a single-row table (constrained by `CHECK (id = 1)`) that records when and by whom the system was first initialized, providing a cross-process guard against concurrent initialization attempts.

## Integrity & Constraints

- Foreign keys enforce hub→port→drive and job→file relationships.
- Enumerated statuses should be constrained by check/enum types.
- Index by `project_id`, `status`, and recent timestamps for UI queries.
