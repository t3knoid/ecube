# 5. Data Model (Updated)

## 5.1 Hardware Tables

### `usb_hubs`

- `id`
- `name`
- `system_identifier`
- `location_hint`

### `usb_ports`

- `id`
- `hub_id`
- `port_number`
- `system_path`
- `friendly_label`

### `usb_drives`

- `id`
- `port_id`
- `device_identifier`
- `filesystem_path`
- `capacity_bytes`
- `encryption_status`
- `current_state`
- `current_project_id`
- `last_seen_at`

## 5.2 Network Mounts

### `network_mounts`

- `id`
- `type` (NFS, SMB)
- `remote_path`
- `local_mount_point`
- `status`
- `last_checked_at`

## 5.3 Jobs

### `export_jobs`

- `id`
- `project_id`
- `evidence_number`
- `source_path`
- `target_mount_path`
- `status`
- `total_bytes`
- `copied_bytes`
- `file_count`
- `thread_count`
- `started_at`
- `completed_at`
- `created_by`

### `export_files`

- `id`
- `job_id`
- `relative_path`
- `size_bytes`
- `checksum`
- `status`
- `error_message`

### `manifests`

- `id`
- `job_id`
- `manifest_path`
- `format`
- `created_at`

### `drive_assignments`

- `id`
- `drive_id`
- `job_id`
- `assigned_at`
- `released_at`

### `audit_logs`

- `id`
- `timestamp`
- `user`
- `action`
- `job_id`
- `details` (JSONB)
