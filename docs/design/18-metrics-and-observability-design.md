# 18. Metrics and Observability Design

| Field | Value |
|---|---|
| Title | Metrics and Observability Design |
| Purpose | Defines the implementation contract for the Prometheus-compatible `GET /metrics` endpoint, including metric families, names, types, labels, units, and sampling behavior. |
| Updated on | 04/10/26 |
| Audience | Engineers, implementers, maintainers, SRE/operations, and technical reviewers. |

## Scope

This document captures the concrete metrics contract for issue #171 and is intended to make implementation straightforward and testable.

Design goals:

- Expose Prometheus text format at `GET /metrics`.
- Provide stable metric names and bucket definitions.
- Enforce low-cardinality labels suitable for production scraping.
- Include periodic sampling for live copy-throughput observability.

## Label and Cardinality Rules

Allowed labels:

- `method`
- `route`
- `status_class`
- `result`
- `state`
- `mount_type`
- `filesystem_type`
- `thread_count_bucket`
- `operation`
- `outcome`
- `pass`

Forbidden high-cardinality labels:

- `job_id`
- `project_id`
- `drive_id`
- `drive_sn`
- `username`
- `trace_id`
- raw filesystem paths

## Concrete Metric Catalog (v1)

### HTTP / API

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_http_requests_total` | Counter | requests | `method`, `route`, `status_class` | `route` must be template form (for example `/jobs/{job_id}`) |
| `ecube_http_request_duration_seconds` | Histogram | seconds | `method`, `route` | Buckets: `[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]` |
| `ecube_http_requests_in_progress` | Gauge | requests | `method`, `route` | Increment on request start, decrement on finish |

### Authentication / Authorization

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_auth_attempts_total` | Counter | attempts | `result` | `result`: `success`, `invalid_credentials`, `token_invalid`, `token_expired` |
| `ecube_role_denials_total` | Counter | denials | `route` | Count 403 authorization denials |

### Jobs / Copy Engine

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_jobs_created_total` | Counter | jobs | none | Increment on job creation |
| `ecube_jobs_running` | Gauge | jobs | none | Current `RUNNING` jobs |
| `ecube_jobs_completed_total` | Counter | jobs | none | Terminal completed jobs |
| `ecube_jobs_failed_total` | Counter | jobs | none | Terminal failed jobs |
| `ecube_job_copy_duration_seconds` | Histogram | seconds | `outcome`, `thread_count_bucket` | `outcome`: `completed`, `failed`; buckets: `[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600, 7200]` |
| `ecube_job_files_copied_total` | Counter | files | none | Increment on successful file copy |
| `ecube_job_bytes_copied_total` | Counter | bytes | none | Increment by bytes copied |
| `ecube_job_copy_errors_total` | Counter | errors | `outcome` | `outcome`: `retry`, `failed` |
| `ecube_job_copy_throughput_bytes_per_second` | Gauge | bytes/sec | `thread_count_bucket` | Sampled live throughput |
| `ecube_job_verify_duration_seconds` | Histogram | seconds | `outcome` | Buckets: `[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300]` |

### Periodic Sampling

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_metrics_sampling_runs_total` | Counter | runs | `outcome` | `outcome`: `ok`, `skipped`, `error` |
| `ecube_metrics_sampling_lag_seconds` | Gauge | seconds | none | Lag from target interval |

Sampling behavior:

- Sampling interval target: every 5-10 seconds.
- Throughput calculation per sample window:
  - `delta_bytes = copied_bytes_now - copied_bytes_prev`
  - `delta_seconds = t_now - t_prev`
  - `throughput = delta_bytes / delta_seconds`
- Export aggregated instantaneous throughput for active jobs via `ecube_job_copy_throughput_bytes_per_second`.
- Sampling delays/skips must degrade gracefully and never block copy execution.

### Drive / USB / Mount

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_usb_hubs_total` | Gauge | hubs | none | From discovery snapshot |
| `ecube_usb_ports_total` | Gauge | ports | none | From discovery snapshot |
| `ecube_usb_drives_present` | Gauge | drives | none | Physically present drives |
| `ecube_usb_drives_state` | Gauge | drives | `state` | `state`: `disconnected`, `available`, `in_use` |
| `ecube_port_enabled_total` | Gauge | ports | none | Administratively enabled ports |
| `ecube_network_mounts_state` | Gauge | mounts | `state`, `mount_type` | `state`: `mounted`, `unmounted`, `error`; `mount_type`: `nfs`, `smb` |
| `ecube_drive_format_total` | Counter | operations | `filesystem_type`, `outcome` | `outcome`: `success`, `error` |
| `ecube_drive_eject_total` | Counter | operations | `outcome` | `outcome`: `prepared`, `failed` |

### Database / Persistence

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_db_connection_pool_size` | Gauge | connections | none | Pool size |
| `ecube_db_connection_pool_in_use` | Gauge | connections | none | Checked-out connections |
| `ecube_db_connection_pool_idle` | Gauge | connections | none | Idle connections |
| `ecube_db_connection_pool_overflow` | Gauge | connections | none | Overflow connections |
| `ecube_db_query_duration_seconds` | Histogram | seconds | `operation` | `operation`: `select`, `insert`, `update`, `delete`; buckets: `[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5]` |
| `ecube_db_connections_created_total` | Counter | connections | none | Created since startup |
| `ecube_db_connections_closed_total` | Counter | connections | none | Closed since startup |

### Startup Reconciliation

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_reconciliation_runs_total` | Counter | runs | `pass`, `outcome` | `pass`: `mounts`, `jobs`, `drives`; `outcome`: `success`, `error`, `skipped` |
| `ecube_reconciliation_duration_seconds` | Histogram | seconds | `pass`, `outcome` | Buckets: `[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30]` |

### Process / Runtime

| Metric | Type | Unit | Labels | Notes |
|---|---|---|---|---|
| `ecube_uptime_seconds` | Counter | seconds | none | Monotonic process uptime |
| `process_resident_memory_bytes` | Gauge | bytes | none | Standard process metric |
| `process_virtual_memory_bytes` | Gauge | bytes | none | Standard process metric |
| `ecube_python_gc_collections_total` | Counter | collections | none | Python GC collection count |

## Exposition and Naming Rules

- Exposition format must be Prometheus text format.
- Counters must use `_total` suffix.
- Duration metrics must use `_seconds` suffix.
- Byte metrics must use `_bytes` or `_bytes_per_second` suffix.
- Histograms must export `_bucket`, `_sum`, and `_count` series.

## Testability Contract

Implementation is considered complete when:

- `GET /metrics` returns valid Prometheus text exposition.
- Catalog metrics above are present with matching names/types/labels.
- Histogram bucket boundaries match this document.
- Label constraints are enforced (no forbidden high-cardinality labels).
- Periodic sampling metrics are emitted while jobs are actively copying.
- No regressions occur in existing API behavior.

## References

- [docs/operations/08-operational-readiness.md](../operations/08-operational-readiness.md)
- [docs/design/07-introspection-design.md](07-introspection-design.md)
- [docs/design/11-testing-and-validation.md](11-testing-and-validation.md)
- [Issue #171](https://github.com/t3knoid/ecube/issues/171)