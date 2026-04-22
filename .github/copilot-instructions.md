## 1. Global Principles

- ECUBE is a secure evidence export platform. All generated code must preserve:
  - strict project isolation
  - hardware safety
  - auditability
  - role-based access control
  - OS abstraction boundaries
- The system layer is trusted; the UI layer is untrusted.
- All OS-level operations must go through interfaces in `app/infrastructure`.
- Business logic must live in `services/`, not routers.
- All new behavior must include tests.
- Code must follow Black, Ruff, ESLint, and Prettier formatting.

## 2. Architecture & Trust Boundaries

### System Layer (trusted)
- Executes mounts, copies, verifications, manifests.
- Writes audit logs.
- Enforces project isolation and role checks.
- Only component allowed to touch hardware and the database.

### UI Layer (untrusted)
- Vue 3 SPA served by FastAPI.
- Communicates via HTTPS API only.
- Never touches hardware or the database.

### Database
- PostgreSQL in production; SQLite in-memory for tests.
- Only reachable from system-layer network segment.

### Roles
| Role | Permissions |
|------|-------------|
| admin | Unrestricted |
| manager | Drive lifecycle, mount management, job visibility |
| processor | Create/start jobs, view job/drive status |
| auditor | Read-only: audit logs, file hashes, job metadata |

Use `require_roles(*roles)` for every endpoint.

### Project Isolation (critical)
- Drives bind to `current_project_id` at initialization.
- All writes must enforce project isolation before any copy begins.
- Violations must be rejected and logged.

## 3. Security & Safety Rules

- All security-relevant events must be logged to `audit_logs`.
- Internal paths and credentials must not appear in API responses.
- All user input used in filesystem paths or shell commands must be sanitized.
- Directory traversal must be prevented (normalize paths).
- `eval`, `exec`, and dynamic code execution are forbidden.
- Insecure defaults (debug=True, wide-open CORS) are forbidden.
- Unsafe file operations must be guarded.
- Endpoints must declare error responses using shared `R_*` schemas.

## 4. Logging Rules (General Logging)

- Use `logger.info`, `logger.debug`, `logger.warning`, `logger.error`.
- Logging must use **message strings + structured context objects**.
- Printf-style formatting is forbidden unless explicitly supported.
- Logging wrappers must forward all arguments.
- Logging must not drop context or silently lose information.
- Do not pass multiple positional arguments unless supported.
- All new code must add appropriate logging for failure paths, degraded behavior, retry exhaustion, unexpected states, and logic inconsistencies that could otherwise fail silently.
- Do not rely only on unhandled-exception logging. Handled failures and suspicious outcomes must be logged at the point they are detected.
- Unexpected failures that can surface to operators or UI users must emit layered logs:
  - `logger.info` should record a safe failure classification, request or operation surface, and correlation identifier without exposing internal paths, raw SQL, credentials, or other unsafe host details.
  - `logger.debug` should record additional actionable diagnostic detail for troubleshooting, so an operator or end user working from debug logs can understand the likely remediation path without reading application code.
- For new failure handling, `logger.info` should make it easy to audit that an unexpected failure, silent bug, or logic error occurred even when the exception is caught or the operation only partially fails.
- Prefer classifying common operational failure categories when they can be derived safely, such as configuration errors, permission failures, unavailable dependencies, or schema drift.

### Debug logging (allowed to contain sensitive details)
Debug logs **may include**:
- system paths  
- device identifiers  
- raw provider errors  
- raw exception strings  

Examples:
```python
logger.debug("Provider error", {"raw_error": str(err)})
logger.debug("Resolved mount path", {"path": mount_path})
logger.debug("Device node", {"dev": "/dev/sdb1"})
