# ECUBE Operational Readiness

| Field | Value |
|---|---|
| Title | Operational Readiness |
| Purpose | Specifies monitoring, observability, health checks, alerting requirements, and performance baselines for ECUBE in production environments. |
| Updated on | 04/08/26 |
| Audience | Operations engineers, DevOps, support teams, security officers. |

## Overview

This document specifies the monitoring, observability, health checks, and alerting requirements for ECUBE in production environments. It establishes baselines, metrics definitions, and support procedures to ensure safe, observable operation.

---

## Table of Contents

1. [Health Checks](#health-checks)
2. [Metrics & Telemetry](#metrics--telemetry)
3. [Logging & Log Aggregation](#logging--log-aggregation)
4. [Alerting & On-Call](#alerting--on-call)
5. [Performance Baselines](#performance-baselines)
6. [Readiness Checklist](#readiness-checklist)

---

## Health Checks

### Liveness Probe

The application must expose an HTTP `GET /health/live` endpoint that returns `200 OK` if the service is running and responding to requests.

**Response body (200):**

```json
{
  "status": "alive",
  "timestamp": "2026-04-05T20:00:00Z"
}
```

**Purpose:** Used by container orchestrators (Kubernetes, Docker Swarm) and load balancers to detect process crashes or hangs.

**Expected behavior:**
- Returns immediately (< 500ms).
- Requires no database access.
- Does not validate dependencies (database, mounts).

### Readiness Probe

The application must expose an HTTP `GET /health/ready` endpoint that returns `200 OK` only if the service is ready to accept traffic.

**Response body (200):**

```json
{
  "status": "ready",
  "timestamp": "2026-04-05T20:00:00Z",
  "checks": {
    "database": "healthy",
    "file_system": "mounted",
    "usb_discovery": "initialized"
  }
}
```

**Response body (503):**

```json
{
  "status": "not_ready",
  "reason": "database_connection_failed",
  "details": "Database connectivity check failed.",
  "timestamp": "2026-04-05T20:00:00Z",
  "checks": {
    "database": "unhealthy",
    "file_system": "unknown",
    "usb_discovery": "unknown"
  }
}
```

**Purpose:** Used by load balancers and orchestrators to determine when a service can receive traffic.

**Expected behavior:**
- Validates critical dependencies: PostgreSQL connectivity, filesystem mounts, USB discovery subsystem.
- Fails fast (< 1 second) if any dependency fails.
- Filesystem mount checks for this endpoint are controlled by `READINESS_MOUNT_CHECK_TIMEOUT_SECONDS` (per-mount timeout) and `READINESS_MOUNT_CHECKS_TOTAL_TIMEOUT_SECONDS` (total timeout budget); see [Configuration Reference](04-configuration-reference.md).
- USB discovery readiness checks are optimized with `READINESS_USB_DISCOVERY_CACHE_TTL_SECONDS`, which caches successful readiness probes briefly to reduce steady-state probe CPU/IO load; see [Configuration Reference](04-configuration-reference.md).
- Returned `503 Service Unavailable` if not ready.
- During startup, the service may return `503` until initialization completes (§ [docs/design/04-functional-design.md](../design/04-functional-design.md#startup-initialization) Startup Reconciliation).

### Startup Initialization Timeout

During initial deployment, the readiness probe may fail for up to **5 minutes** while the service:
- Runs database migrations (`alembic upgrade head`).
- Discovers USB topology and reconciles drive state.
- Mounts network shares and validates accessibility.

Orchestrators must be configured with a **startupPeriod** or **initialDelaySeconds** of at least **5 minutes** to avoid premature restarts during initialization.

---

## Metrics & Telemetry

### Application Metrics

ECUBE must expose Prometheus-style metrics at `GET /metrics` in the format defined by the [Prometheus text exposition format](https://prometheus.io/docs/instrumenting/exposition_formats/).

#### Hardware Metrics

| Metric Name | Type | Description | Example |
|-------------|------|-------------|---------|
| `ecube_usb_hubs_total` | Gauge | Number of USB hubs detected on this host | `2` |
| `ecube_usb_ports_total` | Gauge | Number of USB ports across all hubs | `16` |
| `ecube_usb_drives_present` | Gauge | Number of USB drives currently inserted (not necessarily `AVAILABLE`) | `3` |
| `ecube_usb_drives_available` | Gauge | Number of drives ready for assignment (`AVAILABLE` state) | `2` |
| `ecube_usb_drives_in_use` | Gauge | Number of drives actively assigned to projects (`IN_USE` state) | `1` |
| `ecube_port_enabled_total` | Gauge | Number of ports that are administratively enabled | `12` |
| `ecube_network_mounts_mounted` | Gauge | Number of network mounts in `MOUNTED` state | `2` |
| `ecube_network_mounts_failed` | Gauge | Number of network mounts in `ERROR` state | `0` |

#### Job Metrics

| Metric Name | Type | Description |
|-------------|------|-------------|
| `ecube_jobs_created_total` | Counter | Total jobs created since startup |
| `ecube_jobs_running` | Gauge | Jobs currently in `RUNNING` state |
| `ecube_jobs_completed_total` | Counter | Total jobs that reached `COMPLETED` state |
| `ecube_jobs_failed_total` | Counter | Total jobs that reached `FAILED` state |
| `ecube_job_copy_duration_seconds` | Histogram | Observed duration (seconds) of copy phase for completed jobs; buckets: [1, 10, 60, 300, 600, 1800, 3600] |
| `ecube_job_files_copied_total` | Counter | Total files successfully copied across all jobs |
| `ecube_job_bytes_copied_total` | Counter | Total bytes successfully copied across all jobs |
| `ecube_job_bytes_copied_per_second` | Gauge | Instantaneous copy throughput (rolling average over last 10 seconds) |
| `ecube_job_copy_errors_total` | Counter | Total file-copy errors (retry attempts) across all jobs |

#### Database Metrics

| Metric Name | Type | Description |
|-------------|------|-------------|
| `ecube_db_connection_pool_size` | Gauge | Current number of active database connections |
| `ecube_db_connection_pool_max` | Gauge | Maximum size of the connection pool (configuration) |
| `ecube_db_query_duration_seconds` | Histogram | Observed duration of database queries; buckets: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0] |
| `ecube_db_connections_created_total` | Counter | Total database connections created since startup |
| `ecube_db_connections_closed_total` | Counter | Total database connections closed since startup |

#### API Metrics

| Metric Name | Type | Description |
|-------------|------|-------------|
| `ecube_http_requests_total` | Counter | Total HTTP requests (includes method, endpoint, status code) |
| `ecube_http_request_duration_seconds` | Histogram | Observed duration of HTTP requests; buckets: [0.01, 0.05, 0.1, 0.5, 1.0, 5.0] |
| `ecube_http_requests_in_progress` | Gauge | Number of HTTP requests currently being processed |
| `ecube_auth_failures_total` | Counter | Total authentication failures (invalid credentials, expired token) |
| `ecube_auth_successes_total` | Counter | Total successful authentications |
| `ecube_role_denials_total` | Counter | Total requests denied due to insufficient roles |

#### System Metrics

| Metric Name | Type | Description |
|-------------|------|-------------|
| `ecube_uptime_seconds` | Counter | Time since process started |
| `ecube_python_gc_collections_total` | Counter | Garbage collection cycles |
| `process_resident_memory_bytes` | Gauge | Process resident memory (standard Python metric) |
| `process_virtual_memory_bytes` | Gauge | Process virtual memory (standard Python metric) |

### Metric Export Format

- **Prometheus:** Expose metrics at `GET /metrics` in Prometheus text format.
- **Interval:** Metrics are updated in real-time; Prometheus scrapes at configured intervals (default: 30 seconds).
- **Retention:** Metrics are kept in memory; long-term storage depends on the Prometheus deployment.

### Alerting Thresholds (Recommended)

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| **High Memory Usage** | `process_resident_memory_bytes > 2GB` | warning | Check for memory leaks; consider restart |
| **Database Connection Pool Exhaustion** | `ecube_db_connection_pool_size >= ecube_db_connection_pool_max * 0.9` | critical | Page on-call; investigate slow queries |
| **High Job Copy Error Rate** | `rate(ecube_job_copy_errors_total[5m]) > 10 errors/sec` | warning | Investigate filesystem or network issues |
| **API Response Time Degradation** | `histogram_quantile(0.95, ecube_http_request_duration_seconds) > 5s` | warning | Check database load; consider scaling |
| **Authentication Failures** | `rate(ecube_auth_failures_total[1m]) > 5/min` | info | Monitor for brute-force; log for security review |
| **No USB Drives Available** | `ecube_usb_drives_available == 0` | warning | Notify storage team; may impact operations |
| **Network Mount Failures** | `ecube_network_mounts_failed > 0` | critical | Page on-call; check mount status |
| **Job Failure Rate** | `rate(ecube_jobs_failed_total[1h]) > 10%` | warning | Investigate failure causes in logs |

---

## Logging & Log Aggregation

### Log Levels

ECUBE logs are structured as JSON with the following levels:

- **DEBUG:** Development/troubleshooting details (disabled in production by default).
- **INFO:** General operational events (startup, job creation, drive initialization).
- **WARNING:** Recoverable errors or unusual conditions (retry attempts, drive ejection failures).
- **ERROR:** Unrecoverable errors requiring investigation (database errors, system call failures).
- **CRITICAL:** System-level failures requiring immediate action (service unable to start).

### Structured Log Format

All logs must be emitted as JSON with these fields:

```json
{
  "timestamp": "2026-04-05T20:00:00.123456Z",
  "level": "INFO",
  "logger": "app.services.drives",
  "message": "Drive initialization started",
  "context": {
    "drive_id": "d-12345",
    "project_id": "p-67890",
    "user": "alice@example.com"
  },
  "trace_id": "req-abc123",
  "request_id": "http-xyz789"
}
```

**Required fields:**
- `timestamp` — ISO 8601 format with millisecond precision
- `level` — One of DEBUG, INFO, WARNING, ERROR, CRITICAL
- `logger` — Module name (e.g., `app.services.drives`)
- `message` — Short human-readable summary
- `context` — Dictionary of relevant context (drive_id, user, job_id, etc.)

**Optional fields:**
- `trace_id` — Distributed trace ID (if using OpenTelemetry)
- `request_id` — HTTP request ID for correlation
- `exception` — Stack trace if an exception occurred
- `duration_ms` — Elapsed time for long operations

### Log Aggregation

ECUBE logs must be sent to a centralized log aggregation platform:

**Supported destinations:**

- **ELK Stack (Elasticsearch, Logstash, Kibana):** Ship logs via Logstash or Filebeat.
- **Datadog:** Use the Datadog Python agent for automatic log collection.
- **Splunk:** Forward logs to Splunk via syslog or HTTP Event Collector.
- **CloudWatch (AWS):** Stream logs to CloudWatch Logs.
- **Stackdriver (Google Cloud):** Stream logs to Cloud Logging.

**Configuration:**

```yaml
logging:
  level: "INFO"
  format: "json"
  outputs:
    - type: "stdout"
      level: "INFO"
    - type: "syslog"
      host: "logs.example.com"
      port: 514
      facility: "local0"
    - type: "http"
      endpoint: "https://logs.example.com/api/logs"
      batch_size: 100
      flush_interval: 5
```

### Audit Logging

See [docs/requirements/10-security-and-access-control.md](../requirements/10-security-and-access-control.md) and [docs/design/10-security-and-access-control.md](../design/10-security-and-access-control.md) for audit logging requirements. Audit logs are written to the `audit_logs` database table and must be included in log aggregation exports.

---

## Alerting & On-Call

### Alert Routing

Alerts must be routed to an on-call rotation via a service such as:

- **PagerDuty**
- **Opsgenie**
- **Incident.io**
- **VictorOps**

Configuration example:

```yaml
alerting:
  provider: "pagerduty"
  integration_key: "${PAGERDUTY_INTEGRATION_KEY}"
  severity_mapping:
    critical: "critical"
    warning: "warning"
    info: "info"
  on_call_schedule: "ecube-production"
```

### Alert Acknowledgment & Resolution

1. On-call engineer acknowledges alert in alert management platform.
2. Logger message includes runbook link: `runbook: https://wiki.example.com/ecube/alerts/database-pool-exhaustion`
3. Engineer follows runbook or escalates based on severity.
4. Once resolved, on-call marks incident as resolved; maintains incident record for post-mortems.

### Service-Level Indicators (SLIs)

The following SLIs are recommended for ECUBE:

| SLI | Measurement | Target |
|-----|------------|--------|
| **Availability** | Percentage of time `/health/ready` returns 200 | 99.5% |
| **Copy Job Success Rate** | Percentage of jobs that complete successfully | 99% |
| **API Response Time (p95)** | 95th percentile latency for API requests | < 1 second |
| **Job Copy Throughput** | Average bytes copied per second during job | > 50 MB/s on typical hardware |
| **Mean Time to Recovery (MTTR)** | Average time to restore service after failure | < 15 minutes |

---

## Performance Baselines

### Hardware Reference Configuration

**Tested on:**
- CPU: 8-core Intel Xeon (≈2.5 GHz)
- RAM: 16 GB
- Storage: 512 GB SSD
- USB Hub: Commercial 7-port USB 3.0 hub
- Network: Gigabit Ethernet

### Baseline Performance Metrics

#### Copy Performance

- **Single-file copy (1 GB file):** ~100 MB/s
- **Multi-file copy (1000 small files, 1 GB total):** ~80 MB/s
- **Full 32 GB drive (8-thread copy):** ~90 MB/s sustained
- **Thread overhead:** Diminishing returns beyond 8 threads on reference hardware

#### API Response Times

| Endpoint | p50 | p95 | p99 |
|----------|-----|-----|-----|
| `GET /drives` | 50 ms | 200 ms | 500 ms |
| `POST /jobs` | 100 ms | 300 ms | 800 ms |
| `POST /jobs/{job_id}/start` | 150 ms | 400 ms | 1000 ms |
| `GET /jobs/{job_id}` | 50 ms | 150 ms | 400 ms |
| `GET /audit` (1000 records) | 200 ms | 600 ms | 1500 ms |

#### Database Metrics

- **Connection establishment:** ~50 ms
- **Simple query (e.g., SELECT from drives):** ~5 ms
- **Complex query (e.g., audit log with filters):** ~50 ms
- **Concurrent connections supported:** 20–50 (configurable pool size)

### Tuning Recommendations

**For high-throughput environments (> 100 GB/day):**

1. Increase database connection pool: `DB_POOL_SIZE=50` (default: 20)
2. Increase thread count per job: `DEFAULT_COPY_THREADS=16` (default: 8)
3. Enable read replicas for audit log queries (not yet implemented)
4. Increase file descriptor limit: `ulimit -n 4096` (default: typically 1024)

**For memory-constrained environments (< 4 GB RAM):**

1. Reduce database connection pool: `DB_POOL_SIZE=10`
2. Reduce default thread count: `DEFAULT_COPY_THREADS=4`
3. Enable log rotation: `LOG_MAX_BYTES=100M LOG_BACKUP_COUNT=5`
4. Monitor memory usage; restart service if approaching 70% of available RAM

---

## Readiness Checklist

Before moving ECUBE to production, verify:

### Infrastructure

- [ ] PostgreSQL 14+ is deployed and accessible from the ECUBE host
- [ ] PostgreSQL backups are automated and tested (see [production-support-procedures.md](production-support-procedures.md#database-backup--recovery))
- [ ] Database connection string is secure (TLS, no hardcoded credentials)
- [ ] Filesystem mounts (NFS/SMB) are tested and documented
- [ ] USB hubs are physically installed and recognized by the host
- [ ] All USB ports have been power-cycled and discovered
- [ ] Monitoring stack (Prometheus, Datadog, etc.) is deployed and scraping metrics

### Application

- [ ] Alembic migrations are up-to-date: `alembic current` shows latest revision
- [ ] Environment variables are configured (see [Configuration Reference](#configuration-reference) below)
- [ ] Application starts cleanly: `docker-compose up` or native startup shows "Ready to accept requests"
- [ ] Health check `/health/live` returns 200 OK
- [ ] Readiness check `/health/ready` returns 200 OK
- [ ] Metrics endpoint `/metrics` returns valid Prometheus format
- [ ] Logs are JSON-formatted and forwarded to aggregation service

### Security

- [ ] TLS certificates are installed and valid (check expiry)
- [ ] JWT signing key is securely generated and stored (see [production-support-procedures.md](production-support-procedures.md#secrets--key-rotation))
- [ ] ECUBE service account has minimal OS privileges (least privilege principle)
- [ ] Initial RBAC roles are assigned via `user_roles` table or group mappings
- [ ] Audit logging is enabled and forwarded to secure storage
- [ ] SSH/VPN access to ECUBE host is restricted to authorized operators

### Compliance

- [ ] Compliance mappings are reviewed (see [compliance-and-evidence-handling.md](compliance-and-evidence-handling.md))
- [ ] Chain-of-custody procedures are documented and practiced
- [ ] Encryption at rest is enabled for sensitive data
- [ ] Data retention policies are configured and documented
- [ ] Incident response playbook is created and shared with support team

### Testing

- [ ] End-to-end export job is completed and verified (20+ GB dataset recommended)
- [ ] Manifest verification is tested (hashes computed and validated)
- [ ] Eject and re-insert USB drive workflow is tested
- [ ] Network mount failover is tested
- [ ] Error scenarios are tested: disk full, network timeout, permission denied
- [ ] Load test with multiple concurrent jobs (target: 3+ simultaneous exports)
- [ ] Accessibility scanning completed (WAVE, axe, Lighthouse)

### Documentation

- [ ] Operations runbook is updated with ECUBE-specific procedures
- [ ] Troubleshooting guide is complete and shared with support team (see [production-support-procedures.md](production-support-procedures.md))
- [ ] Disaster recovery plan is documented and tested
- [ ] API documentation (OpenAPI/Swagger) is generated and accessible
- [ ] Change log is updated with release notes

### Support

- [ ] On-call rotation is configured and tested
- [ ] Escalation procedures are documented
- [ ] Alert thresholds are tuned to your environment
- [ ] Support team has read-only access to logs and metrics
- [ ] Incident post-mortem template is created

---

## Configuration Reference

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `ECUBE_HOST` | String | `0.0.0.0` | IP address to listen on |
| `ECUBE_PORT` | Integer | `8000` | Port to listen on |
| `DATABASE_URL` | String | (required) | PostgreSQL connection string: `postgresql://user:password@host:port/dbname` |
| `DB_POOL_SIZE` | Integer | `20` | Maximum database connections |
| `DB_POOL_RECYCLE` | Integer | `3600` | Recycle connections after N seconds (avoid stale connections) |
| `TOKEN_EXPIRE_MINUTES` | Integer | `60` | JWT token expiration time in minutes |
| `TOKEN_SECRET_KEY` | String | (required) | Secret key for signing JWTs (use strong random value) |
| `TLS_CERT_PATH` | String | (optional) | Path to TLS certificate for HTTPS |
| `TLS_KEY_PATH` | String | (optional) | Path to TLS private key for HTTPS |
| `LOG_LEVEL` | String | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `LOG_FORMAT` | String | `json` | Log format: `json` or `text` |
| `METRICS_ENABLED` | Boolean | `true` | Enable Prometheus metrics endpoint |
| `AUDIT_ENABLED` | Boolean | `true` | Enable audit logging to database |
| `DEFAULT_COPY_THREADS` | Integer | `8` | Default thread count for copy jobs |
| `DEFAULT_COPY_RETRIES` | Integer | `3` | Retry failed file copies N times |
| `COPY_TIMEOUT_SECONDS` | Integer | `300` | Timeout (seconds) for individual file copy |
| `NFS_MOUNT_TIMEOUT` | Integer | `30` | Timeout (seconds) for NFS mount attempts |
| `SMB_MOUNT_TIMEOUT` | Integer | `30` | Timeout (seconds) for SMB mount attempts |
| `USB_DISCOVERY_INTERVAL` | Integer | `5` | USB hub discovery interval (seconds) |
| `READINESS_USB_DISCOVERY_CACHE_TTL_SECONDS` | Float | `5.0` | Cache TTL (seconds) for successful USB readiness checks to avoid full discovery on every probe |
| `STARTUP_WAIT_TIMEOUT` | Integer | `300` | Max time (seconds) to wait for startup reconciliation |

---

## Related Documents

- [docs/requirements/04-functional-requirements.md](../requirements/04-functional-requirements.md) — Functional requirements and system behaviors
- [docs/design/04-functional-design.md](../design/04-functional-design.md) — Implementation patterns for recovery and reconciliation
- [docs/design/11-testing-and-validation.md](../design/11-testing-and-validation.md) — Testing strategy and validation approach
- [production-support-procedures.md](production-support-procedures.md) — Troubleshooting, upgrade, backup, and patching
- [compliance-and-evidence-handling.md](compliance-and-evidence-handling.md) — Compliance mappings and chain-of-custody requirements

## References

- [docs/requirements/08-operational-readiness.md](../requirements/08-operational-readiness.md)
- [docs/operations/10-production-support-procedures.md](10-production-support-procedures.md)
