# ECUBE Copilot Instructions

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
- ECUBE uses a release-scoped Alembic workflow: during an unreleased app cycle, update the current release migration in `alembic/versions` instead of creating a second migration file.
- When extending an existing UI surface, inspect the closest existing component that already solves the same visual or interaction problem and match its styling patterns before introducing a new variant.
- For UI styling work, prefer reusing the same tokens, spacing, scrollbar, button, panel, and state treatments from the existing component unless the task explicitly requires a different design.

### 1.1 Code Review Global Expectations

Copilot must evaluate and generate code consistent with the following enterprise review principles:

- Maintain strict separation of concerns:
  - routers → thin
  - services → business logic
  - infrastructure → OS, USB, SMB/NFS, subprocess, mounts
  - persistence → DB access only
- Never introduce blocking I/O inside async FastAPI endpoints.
- Never leak raw OS errors, device identifiers, or absolute paths outside debug logs.
- All new code must be safe under concurrency, retries, and partial failures.
- All new code must be observable: structured logs, metrics, and clear failure paths.
- All new code must be secure by default: sanitized inputs, validated paths, safe mount options, no shell injection, no traversal.
- All new code must preserve chain‑of‑custody integrity and auditability.

## 1.2 Alembic Release Migration Workflow

- Treat issue 280 as a binding repository workflow rule.
- Do not run `alembic revision` directly for normal ECUBE feature work.
- Resolve the current release migration filename from `[project].version` in `pyproject.toml`.
- For the current unreleased version `0.2.0`, the only supported unreleased migration file is `alembic/versions/v0_2_0.py`.
- If a schema change is required, update the current release migration in place.
- Use the repo wrapper `ecube-release-migration ensure`, `ecube-release-migration create`, or `ecube-release-migration autogenerate` instead of creating a second Alembic revision file.
- If a task appears to require a second unreleased migration file, stop and explain that the request conflicts with the ECUBE release-scoped migration workflow.

## 2. Architecture & Trust Boundaries

### System Layer (trusted)
- Executes mounts, copies, verifications, manifests.
- Writes audit logs.
- Enforces project isolation and role checks.
- Only component allowed to touch hardware and the database.
- Must expose stable, minimal interfaces; no business logic leakage upward.
- Must validate all mount paths, device identities, and OS interactions before execution.

### UI Layer (untrusted)
- Vue 3 SPA served by FastAPI.
- Communicates via HTTPS API only.
- Never touches hardware or the database.
- Must not assume backend invariants; must handle all error states gracefully.
- Must not hard‑code API URLs inside components; use centralized API client.

### Database
- PostgreSQL in production; SQLite in-memory for tests.
- Only reachable from system-layer network segment.
- Schema must use strong types, constraints, and foreign keys.
- Migrations must match models; no drift allowed.

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

### 3.1 Additional Security Review Rules

- All filesystem paths must be normalized and validated as direct children of allowed base directories.
- All subprocess calls must use explicit argument lists; never build shell strings.
- All SMB/NFS mounts must use safe options (`noexec`, `nodev`, `nosuid`).
- All USB device identities must be composite (VID/PID/serial/port‑path/fs‑UUID).
- All endpoints must enforce role checks using `require_roles`.
- No endpoint may return internal OS details, raw exceptions, or sensitive metadata.
- Installer and host-bootstrap helpers must not assume `PYTHON_BIN` was already resolved; any Python-backed helper that can run before the main interpreter setup path must resolve a compatible interpreter locally or fail with an explicit remediation path.
- Installer `.env` mutations must preserve unrelated keys, remain idempotent on re-run, and honor explicitly supplied local paths such as test-provided `LOG_FILE` or install-root-local environment files instead of hardcoding privileged host paths.

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
  - `logger.debug` should record additional actionable diagnostic detail for troubleshooting.
- Prefer classifying common operational failure categories when they can be derived safely.

### Debug logging (allowed to contain sensitive details)
Debug logs **may include**:
- system paths
- device identifiers
- raw provider errors
- raw exception strings

### Info/warning/error logging (strict)
These levels must **not** include:
- raw provider errors
- absolute filesystem paths
- device identifiers
- sensitive OS details

Exception:
- application logs may mirror structured audit metadata when sanitized.

## 5. Audit Log Redaction & Provider Error Safety

- Audit logs must never contain:
  - raw provider errors
  - raw exception strings
  - absolute filesystem paths
  - unredacted mount paths
- Exception:
  - audit records may include stable drive-identifying or USB-topology metadata needed for chain-of-custody.
- Audit logs must use structured, sanitized, or redacted error information.

## 6. Backend Code Review Rules

### 6.1 API Layer
- Endpoints must use Pydantic models for all inputs/outputs.
- Endpoints must not contain business logic.
- Endpoints must return consistent error schemas (`R_*`).
- Endpoints must not block the event loop.

### 6.2 Services Layer
- Must implement all business logic.
- Must enforce project isolation before any write.
- Must handle retries, partial failures, and cleanup.
- Must never call OS functions directly—only via infrastructure.
- When exposing System-page runtime warning repairs or similar operator remediation actions, keep the router and frontend generic. New repairable warning types must plug in through a service-layer registry/definition model and trusted infrastructure adapters rather than new warning-specific branches scattered across the router or UI.
- Read-only refresh flows must stay read-only. Host mutations for warning remediation must remain explicit, auditable `POST` actions with confirmation, and any new repair action should be addable by registering warning metadata, activation logic, and execution logic in one service-owned extension point.

### 6.3 Infrastructure Layer
- Must validate all mount paths and device identities.
- Must sanitize all provider errors before returning them upward.
- Must wrap subprocess calls with timeouts and safe argument lists.
- Must handle USB disconnect‑mid‑copy safely.

## 7. Frontend (Vue) Code Review Rules

### 7.1 API Usage
- All API calls must go through a centralized client.
- All API errors must be surfaced with user‑safe messages.
- No component may hard‑code URLs.

### 7.2 Routing
- SPA routing must support direct navigation to all frontend routes.
- No collisions with backend API paths.

### 7.3 State Management
- Stores must not mutate state unpredictably.
- Derived state must be computed, not stored.

### 7.4 UI/UX Safety
- Destructive actions require confirmation.
- Buttons must disable when hardware state is unsafe.
- Frontend validation must mirror backend validation.

## 8. Database Review Rules

- All tables must use strong types, constraints, and foreign keys.
- All migrations must be reversible.
- No unbounded growth tables without retention policies.
- Indexes must exist for high‑traffic queries (jobs, drives, audit logs).
- No JSONB dumping unless justified and documented.

## 9. Reliability & Performance Rules

- All long‑running operations must be async‑safe or offloaded.
- All copy operations must handle disk‑full, disconnect, and partial writes.
- All mount operations must include retries and timeouts.
- All job state transitions must be atomic.
- No synchronous heavy operations inside request handlers.

## 10. Observability Rules

- All major operations must emit structured logs.
- Metrics must exist for job duration, copy speed, mount failures.
- Trace IDs must propagate across backend and frontend.
- Health checks must validate USB subsystem and SMB/NFS availability.
