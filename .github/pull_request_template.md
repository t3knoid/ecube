# ECUBE Pull Request

## Summary
Provide a clear, concise summary of the change.  
Explain *why* this change is needed and what problem it solves.

---

## Type of Change
Select all that apply:

- [ ] Feature
- [ ] Bug Fix
- [ ] Refactor
- [ ] Documentation
- [ ] Performance Improvement
- [ ] Security Fix
- [ ] Database Migration (Alembic)
- [ ] Frontend (Vue.js)
- [ ] Backend (Python)
- [ ] System Layer / Hardware
- [ ] Installer / Packaging
- [ ] CI / Testing
- [ ] Other

---

# 🔍 Reviewer Checklist

# 1. Backend (Python)
- [ ] Code follows ECUBE architecture and separation of concerns
- [ ] API request/response schemas validated (Pydantic)
- [ ] HTTP status codes correct and consistent
- [ ] Error handling structured (no bare `except`)
- [ ] No secrets or sensitive data in logs
- [ ] ORM usage efficient (no N+1 queries)
- [ ] Background tasks do not block event loop
- [ ] ThreadPoolExecutor usage remains bounded
- [ ] Unit and integration tests updated or added
- [ ] Type hints added where appropriate

---

# 2. Frontend (Vue.js)
- [ ] Components are small, focused, and follow Single‑File Component (SFC) conventions
- [ ] Props, emits, and component contracts are typed (TypeScript) and validated
- [ ] State management uses Pinia or composables consistently (no ad‑hoc global state)
- [ ] API calls use a centralized service layer (no inline fetch/axios in components)
- [ ] Loading, error, and empty states handled cleanly
- [ ] Template structure is readable and not deeply nested
- [ ] No unnecessary watchers or expensive computed properties
- [ ] Refs/reactivity used correctly (no misuse of shallow/deep refs)
- [ ] Styles follow project conventions; no excessive inline CSS
- [ ] No sensitive data exposed in UI
- [ ] E2E tests updated if UI behavior changed
- [ ] Interactive elements use proper semantics:
      - No clickable <tr>, <div>, or <span> without tabindex + keyboard handlers
      - Prefer <button> or <a> for interactive actions
      - Keyboard navigation works for directory rows, tree items, and file browser entries
      - Focus states are visible and not removed

---

# 3. Full‑Stack Integration
- [ ] Frontend and backend API contracts match (fields, types, error formats)
- [ ] Pagination, filtering, and sorting consistent
- [ ] Authentication and authorization flows correct
- [ ] Errors surfaced to users consistently
- [ ] No silent failures or unhandled promise rejections
- [ ] OpenAPI updated for new or changed endpoints

---

# 4. Alembic Migrations (if applicable)
- [ ] Migration purpose clear and revision message descriptive
- [ ] `upgrade()` and `downgrade()` implemented correctly
- [ ] Schema changes match SQLAlchemy models (no drift)
- [ ] No destructive operations without safeguards
- [ ] Data migrations idempotent and efficient
- [ ] No environment‑specific logic in migrations
- [ ] Autogenerate output reviewed for noise/unintended changes
- [ ] Migration order correct (no accidental branching)
- [ ] Chain‑of‑custody and auditability preserved

---

# 5. Audit Logging & Chain‑of‑Custody
- [ ] All evidence‑affecting actions logged
- [ ] Required audit fields present (timestamp, actor, drive_id, job_id, etc.)
- [ ] No sensitive data logged (file contents, tokens, passwords)
- [ ] Log messages follow ECUBE audit schema
- [ ] Rollback scenarios produce correct audit entries
- [ ] Chain‑of‑custody invariants preserved

---

# 6. Drive Lifecycle & System Layer Boundaries
- [ ] Drive state transitions follow defined state machine
- [ ] No UI or API path allows eject/prepare during active copy jobs
- [ ] Mount/unmount logic safe and race‑condition‑free
- [ ] System‑layer API boundaries respected (UI never touches hardware directly)
- [ ] Drive metadata handled consistently (serial, vendor, model, capacity)
- [ ] No assumptions about device enumeration order

---

# 7. Background Tasks (Copy, Verify, Manifest)
- [ ] Background tasks do not block event loop
- [ ] ThreadPoolExecutor usage remains bounded
- [ ] Copy/verify/manifest workflows follow documented sequence
- [ ] Errors in background tasks logged and surfaced correctly
- [ ] No race conditions between job state and drive state
- [ ] Job cancellation or rollback paths behave correctly

---

# 8. Directory Browser & Mount Point Safety
- [ ] Directory traversal protections in place
- [ ] No exposure

# 9. Accessibility (A11y)

- [ ] All interactive elements are keyboard-focusable
- [ ] Clickable rows or divs replaced with <button>/<a> or made accessible with tabindex + key handlers
- [ ] Focus order is logical and preserved
- [ ] No keyboard traps
- [ ] ARIA roles used correctly when needed
- [ ] Directory browser and tree view fully operable with keyboard only

# 10. Code Quality & Maintainability
- [ ] No unused imports or unused variables
- [ ] No duplicated logic or copy‑paste blocks
- [ ] No dead code or commented‑out code left behind
- [ ] No leftover debug statements (console.log, print, pdb, debugger)
- [ ] Functions and components are small, focused, and readable
- [ ] Shared logic extracted into utilities/composables/services where appropriate
- [ ] Naming conventions are consistent across backend and frontend
- [ ] Imports are clean, sorted, and minimal
- [ ] No unused dependencies in requirements.txt or package.json
- [ ] Linting and formatting rules are followed (Black, Ruff, ESLint, Prettier)

## Security & System Safety
- [ ] No insecure use of user input (paths, shell commands, API calls)
- [ ] No directory traversal risks; paths are validated and normalized
- [ ] No unsafe subprocess or shell=True usage
- [ ] No sensitive data logged (tokens, passwords, internal paths)
- [ ] All endpoints enforce authentication and authorization
- [ ] No bypass of system-layer boundaries (UI never touches hardware directly)
- [ ] No insecure defaults (debug=True, permissive CORS, weak permissions)
- [ ] No dynamic code execution (eval, exec, Function)

## System Performance & Stability
- [ ] No long-running synchronous work inside FastAPI endpoints
- [ ] No CPU/IO-heavy work on the event loop
- [ ] No unbounded loops, recursion, or polling
- [ ] No unbounded ThreadPoolExecutor usage
- [ ] No N+1 queries or inefficient ORM patterns
- [ ] No repeated expensive operations that should be cached
- [ ] No unnecessary Vue reactivity triggers or excessive watchers
- [ ] Directory browsing is efficient and safe for deep/wide trees
- [ ] No memory leaks or unbounded in-memory growth
- [ ] Background tasks cleaned up properly (temp files, state, logs)

## ECUBE-Specific Safety
- [ ] Copy/verify/manifest tasks cannot degrade system performance
- [ ] Drive lifecycle transitions remain safe and atomic
- [ ] System-layer APIs cannot be called in unsafe states
- [ ] Chain-of-custody integrity preserved in all code paths

