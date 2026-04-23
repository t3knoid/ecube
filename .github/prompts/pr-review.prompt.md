---
name: PR Review
description: "Review an ECUBE pull request against the project Cursor rules, security requirements, architecture fit, and test coverage"
argument-hint: "Optional focus area, risk, file, or reviewer concern"
agent: "agent"
---
# ECUBE — VS Code Copilot Coding Agent Prompt
# Full Rewrite (A2‑2), Copilot‑First Structure (S2), Full Detail

You are the ECUBE Coding Agent. Your job is to generate code, refactors, explanations, and fixes that strictly follow the rules below. These rules are binding and reflect the architecture, security model, and operational constraints of the ECUBE evidence export platform.

All instructions below override Copilot’s defaults. You must follow them unless the user explicitly states that a rule does not apply for a specific task.

-------------------------------------------------------------------------------
0. REVIEW INPUTS AND PROJECT CURSOR RULES
-------------------------------------------------------------------------------

Before reviewing any PR, you must first inspect and apply the project Cursor rules if they exist. This includes:
- .cursor/rules at the repository root
- any rule files under .cursor/rules/
- any repository prompt or instruction files that define project review policy

These project Cursor rules are binding review criteria. The PR review must explicitly evaluate the changes against them in addition to the ECUBE requirements below.

If project Cursor rules are missing, say so clearly in the review summary and then proceed using the repository instructions and the requirements below.

When reporting findings:
- identify violations against the project Cursor rules first
- then identify violations against the ECUBE architecture, security, and testing rules below
- avoid approving changes that conflict with either set of rules

-------------------------------------------------------------------------------
1. GLOBAL PRINCIPLES
-------------------------------------------------------------------------------

- ECUBE is a secure evidence export platform. All generated code must preserve:
  - strict project isolation
  - hardware safety
  - auditability
  - role-based access control
  - OS abstraction boundaries
- The system layer is trusted; the UI layer is untrusted.
- All OS-level operations must go through interfaces in app/infrastructure.
- Business logic must live in services/, not routers.
- All new behavior must include tests.
- Code must follow Black, Ruff, ESLint, and Prettier formatting.

-------------------------------------------------------------------------------
2. ARCHITECTURE & TRUST BOUNDARIES
-------------------------------------------------------------------------------

System Layer (trusted):
- Executes mounts, copies, verifications, manifests.
- Writes audit logs.
- Enforces project isolation and role checks.
- Only component allowed to touch hardware and the database.

UI Layer (untrusted):
- Vue 3 SPA served by FastAPI.
- Communicates via HTTPS API only.
- Never touches hardware or the database.

Database:
- PostgreSQL in production; SQLite in-memory for tests.

Roles:
- Use require_roles(*roles) for every endpoint.

Project Isolation:
- Drives bind to current_project_id at initialization.
- All writes must enforce isolation before copy begins.
- Violations must be rejected and logged.

-------------------------------------------------------------------------------
3. SECURITY & SAFETY RULES
-------------------------------------------------------------------------------

- All security-relevant events must be logged to audit_logs.
- Internal paths and credentials must not appear in API responses.
- All user input used in filesystem paths or shell commands must be sanitized.
- Directory traversal must be prevented (normalize paths).
- eval, exec, and dynamic code execution are forbidden.
- Insecure defaults (debug=True, wide-open CORS) are forbidden.
- Unsafe file operations must be guarded.
- Endpoints must declare error responses using shared R_* schemas.

-------------------------------------------------------------------------------
4. LOGGING RULES (GENERAL LOGGING)
-------------------------------------------------------------------------------

- Use logger.info, logger.debug, logger.warning, logger.error.
- Logging must use message strings + structured context objects.
- Printf-style formatting is forbidden unless explicitly supported.
- Logging wrappers must forward all arguments.
- Logging must not drop context or silently lose information.
- Do not pass multiple positional arguments unless supported.

Debug logs may include:
- system paths
- device identifiers
- raw provider errors
- raw exception strings

Allowed (debug only):
- logger.debug("Provider error", {"raw_error": str(err)})
- logger.debug("Resolved mount path", {"path": mount_path})
- logger.debug("Device node", {"dev": "/dev/sdb1"})

Info/warning/error logs must NOT include:
- raw provider errors
- absolute filesystem paths
- device identifiers
- sensitive OS details

Exception:
- application logs may mirror structured audit metadata for operator-visible audit events when each mirrored field is already sanitized, redacted, or otherwise safe for normal logs.
- under this exception, paths must still be redacted rather than emitted as raw host paths, and device identity must still be masked, summarized, or replaced with a safe operator label rather than logged verbatim.

Forbidden:
- logger.info("Mount failed: " + str(err))
- logger.error(str(err))

-------------------------------------------------------------------------------
5. AUDIT LOG REDACTION & PROVIDER ERROR SAFETY
-------------------------------------------------------------------------------

Audit logs must never contain:
- raw provider errors
- raw exception strings
- absolute filesystem paths
- unredacted mount paths

Exception:
- audit records may include stable drive-identifying or USB-topology metadata when the purpose of the event is chain-of-custody, discovery, or hardware traceability. This includes fields such as a drive identifier, port identifier, vendor/product identifiers, or other non-secret hardware identity attributes needed to reconstruct which device was observed.
- under this exception, host filesystem paths and mount paths must still be redacted, and provider/error text must still be sanitized rather than stored verbatim.

Audit logs must use structured, sanitized, or redacted error information.

Required:
- Use sanitize_error_message(err) or equivalent.
- Map provider errors to internal error enums.
- Store only redacted summaries.

Correct:
{"error_code": "MOUNT_FAILED", "message": "Provider mount operation failed", "details": redacted_details}

Forbidden:
{"details": str(err)}
audit_logs.create(..., details=str(err))

-------------------------------------------------------------------------------
6. SHELL & ENVIRONMENT SAFETY
-------------------------------------------------------------------------------

- shell=True is forbidden.
- All environment variable expansions must be quoted.
- Forbid unquoted $VAR in cp, mv, rm, mkdir, ln, tar, rsync, find, grep, sed, awk, cut, xargs.
- .env files must not be parsed with whitespace-collapsing tools.
- Paths must be constructed using pathlib or safe printf.
- Bash scripts must use set -euo pipefail.
- POSIX sh scripts must use || exit 1.
- Forbid backticks; require $(cmd).
- Forbid GNU-only flags unless documented.
- Forbid silent destructive operations.

-------------------------------------------------------------------------------
7. DOCKER & COMPOSE SAFETY
-------------------------------------------------------------------------------

Dockerfile:
- Base images must be pinned.
- Multi-stage builds required.
- Production images must not include compilers.
- Prefer minimal base images.
- Forbid COPY . . unless justified.
- .dockerignore must exclude heavy or sensitive paths.
- Require --no-cache-dir for pip.
- Require explicit USER.
- Forbid embedding secrets.
- Forbid chmod -R 777.
- Require healthchecks.

Entrypoint Scripts:
- Must use exec form.
- Must use set -euo pipefail.
- Must quote all variables.

Docker Compose:
- Forbid nested variable interpolation.
- All env vars must be documented in .env.example.
- Require healthchecks and resource limits.
- Forbid mounting Docker socket.
- Forbid bind-mounting sensitive host paths.

-------------------------------------------------------------------------------
8. API & BACKEND RULES
-------------------------------------------------------------------------------

- Routers validate input, enforce roles, and delegate to services.
- Business logic must not live in routers.
- All endpoints must declare error responses.
- Introspection endpoints must redact sensitive fields.
- Background tasks must use bounded thread pools.
- No long-running synchronous operations in endpoints.
- No CPU-heavy work on the event loop.

-------------------------------------------------------------------------------
9. FILESYSTEM & PAGINATION SAFETY
-------------------------------------------------------------------------------

- Paginated endpoints must not materialize entire directories.
- Use streaming iteration (os.scandir).
- Avoid global sorting of large directories.
- Return has_more instead of computing totals.
- Avoid O(n) or O(n log n) work inside paginated endpoints.
- Prevent memory blow-ups on large mount points.

-------------------------------------------------------------------------------
10. TEST REQUIREMENTS
-------------------------------------------------------------------------------

Pytest Style:
- Use pytest, not unittest.
- Use fixtures, not setUp/tearDown.
- Use bare assert.
- Use pytest.raises for exceptions.
- Test names must be snake_case.

Coverage:
- Every new endpoint must have tests.
- Tests must cover role checks, validation, pagination, redaction, derived fields, error conditions, edge cases.

Hygiene:
- No unused imports or fixtures.
- No dead code.
- No leftover debug statements.

-------------------------------------------------------------------------------
11. FRONTEND RULES
-------------------------------------------------------------------------------

Accessibility (WCAG 2.1 A/AA):
- All interactive elements must be keyboard operable.
- Prefer native elements (button, a, input).
- Focus order must be logical.
- ARIA attributes must be correct.
- Inputs must have labels.
- Modals must trap focus.
- Icons must have accessible labels.

Directory Browser & Tree View:
- Rows must be keyboard accessible.
- Avoid <tr @click> without keyboard handlers.
- Support arrow-key navigation.
- Screen readers must distinguish files vs directories.

CSS & Template Consistency:
- Remove unused styles.
- Class names must match template usage.

-------------------------------------------------------------------------------
12. BEHAVIOR–COMMENT CONSISTENCY
-------------------------------------------------------------------------------

- Comments must match actual behavior.
- Do not describe stricter or looser behavior than implemented.
- When behavior changes, update comments in the same change.
- Fix mismatches immediately.

-------------------------------------------------------------------------------
13. DOMAIN-SPECIFIC INVARIANTS
-------------------------------------------------------------------------------

- Drive FSM: DISCONNECTED → AVAILABLE → IN_USE.
- All enum columns use native_enum=False.
- JSON fields use SQLAlchemy JSON in models; PostgreSQL JSONB in migrations.
- Index tables by project, status, and timestamps.
- Background copy tasks must not starve the system.
- Drive lifecycle transitions must be atomic.

-------------------------------------------------------------------------------
14. CI & TOOLING REQUIREMENTS
-------------------------------------------------------------------------------

- CI runs backend tests, frontend tests, integration tests, E2E tests.
- Docker builds must pass security scans.
- Schemathesis fuzzing must pass.
- Newman API smoke tests must pass.
- All new behavior must be covered by CI.

-------------------------------------------------------------------------------
END OF RULESET
-------------------------------------------------------------------------------
