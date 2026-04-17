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
- Internal paths, credentials, and hardware identifiers must not appear in API responses.
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
