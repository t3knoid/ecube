## Backend Logging Taxonomy

Use stable message strings plus structured context in `extra` for backend application logs. Keep operator-safe summaries at `INFO`, `WARNING`, and `ERROR`. Reserve raw exception detail, host paths, provider text, and traceback context for `DEBUG`.

Severity mapping:

- `DEBUG`: Diagnostic detail that helps an engineer explain a failure after a safe higher-level event already exists. Include remediation hints, raw exception context, redacted dependency targets, and traceback data only here.
- `INFO`: Normal lifecycle and successful state transitions such as backend selection, reconciliation completion, job lifecycle progress, or other expected operational milestones.
- `WARNING`: Denials, fail-closed responses, and recoverable degradation. This includes authentication or authorization denials, validation-style request rejections that matter operationally, and dependency fallback paths such as Redis session failover to signed cookies.
- `ERROR`: Unhandled request failures, 5xx responses, and unrecoverable backend faults that require operator investigation.

Recommended shared context fields:

- `event_code`: Stable machine-readable event label such as `AUTHENTICATION_DENIED` or `SESSION_BACKEND_FALLBACK`.
- `trace_id`: Request correlation identifier when the log is tied to an API error response.
- `request_path` and `request_method`: Request surface for API denials and failures.
- `status_code`: HTTP status code when relevant.
- Domain identifiers such as `job_id`, `drive_id`, `mount_id`, `actor_id`, or `project_id` when they are already safe to expose in standard logs.

Current ticket coverage:

- Auth token validation failures emit `WARNING` logs with `AUTHENTICATION_DENIED` context.
- Role-based access denials emit `WARNING` logs with `AUTHORIZATION_DENIED` context.
- Redis session fallback emits a safe `WARNING` plus a `DEBUG` diagnostic record.
- Global unhandled exception handling in `app/main.py` continues to emit safe `INFO` and `ERROR` logs plus `DEBUG` remediation detail for 5xx paths.