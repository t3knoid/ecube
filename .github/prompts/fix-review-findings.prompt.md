---
name: Fix Review Findings
description: "Resolve issues identified in a recent ECUBE review with root-cause fixes, focused validation, and required documentation sync."
argument-hint: "Paste the review findings, PR comments, issue list, or review summary to address"
agent: "agent"
---
# ECUBE — Review Findings Resolution Prompt

Use this prompt to fix issues identified during a recent review of ECUBE.

Use the user argument as the source of truth for the findings to address. Treat each finding as a concrete defect, regression risk, or test/documentation gap unless the user explicitly marks it as non-actionable.

-------------------------------------------------------------------------------
## Mandatory instruction sources
-------------------------------------------------------------------------------

Read and apply all of the following before any analysis, planning, code edits, test changes, or documentation updates:

- `.github/copilot-instructions.md`
- `.cursor/rules/core.mdc`
- `.cursor/rules/backend.mdc`
- `.cursor/rules/frontend.mdc`
- `.cursor/rules/installer.mdc`
- `.cursor/rules/migrations.mdc`
- `.cursor/rules/shell-docker.mdc`
- `.github/prompts/code-review.prompt.md`
- `.github/prompts/documentation-sync.prompt.md`
- `.github/prompts/implement-ticket.prompt.md`

Treat these repository documents as the single source of truth.
Do not restate or loosen them.
If one of them is missing, say so explicitly.

-------------------------------------------------------------------------------
## Review-fix goals
-------------------------------------------------------------------------------

Your job is to:

- restate the review findings you are going to fix
- confirm which findings are reproducible, already fixed, blocked, or invalid
- identify the root cause for each actionable finding
- implement the smallest complete fix that resolves the actual defect
- preserve ECUBE trust boundaries, project isolation, hardware safety, auditability, and RBAC
- keep routers thin, business logic in services, and OS-level operations behind `app/infrastructure`
- add or update focused tests for each fixed issue when practical
- re-run the narrowest checks that prove each finding is resolved
- update documentation when the fix changes API behavior, setup, operations, architecture, or UI expectations
- update API and operator docs when the fix changes role visibility, validation rules, callback behavior, drive/job workflows, or configuration surfaces
- update `docs/testing/03-qa-testing-guide.md` when the fix changes user-facing behavior, UI states, or operational workflows
- update frontend tests and E2E coverage when the fix changes user-facing behavior or UI states
- provide a concise summary of the change suitable for use as a commit message

If a reported finding is incorrect, outdated, or no longer reproducible, say so with concrete evidence rather than silently skipping it.

-------------------------------------------------------------------------------
## Pattern Discovery and DRY Enforcement (Mandatory)
-------------------------------------------------------------------------------

Before writing code, perform targeted pattern discovery around each finding.

Inspect the nearest existing implementation for:

- routers, response models, and shared `R_*` error envelopes
- service-layer validation, orchestration, and audit behavior
- infrastructure adapters, subprocess wrappers, and OS abstraction boundaries
- SQLAlchemy, repository, and release-scoped Alembic conventions
- logging, redaction, sanitized error reporting, and audit logging patterns
- Vue UI behavior, centralized API client usage, and role-scoped view patterns
- existing backend, frontend, integration, and documentation tests that cover adjacent behavior

You must:

- reuse existing contracts and patterns where possible
- avoid duplicate fixes, one-off abstractions, or new variants without need
- justify any new pattern introduced to fix a finding

-------------------------------------------------------------------------------
## ECUBE-specific invariants
-------------------------------------------------------------------------------

Unless the reviewed change explicitly alters the specification and the docs are updated accordingly, these rules remain true:

- strict project isolation remains mandatory for all write paths
- the system layer is trusted and the UI layer is untrusted
- all OS-level operations go through `app/infrastructure`
- routers remain validation and delegation layers, not business-logic layers
- all endpoints enforce roles with `require_roles(*roles)`
- internal OS details, raw provider errors, absolute paths, and sensitive metadata do not leak outside debug logs
- audit logs remain sanitized and preserve chain-of-custody integrity
- callback, mount, drive, copy, and verification flows remain safe under retries, partial failures, and restarts
- migrations follow the release-scoped Alembic workflow and update the current release migration in place when schema changes are required
- frontend behavior continues to use the centralized API client and must mirror backend validation without replacing it
- any API implementation or API modification must update the relevant API and operator documentation
- any configuration addition, removal, rename, default change, expected-type change, or runtime config behavior change must update the relevant configuration and operations documentation

-------------------------------------------------------------------------------
## Required workflow
-------------------------------------------------------------------------------

1. Summarize the findings and list any assumptions.
2. Identify which findings are actionable, already fixed, blocked, or invalid.
3. Identify which instruction sources apply to the touched files.
4. Perform pattern discovery near each finding and list the patterns you will reuse.
5. Read the relevant code, tests, and docs.
6. Reproduce or otherwise validate each finding with evidence when feasible.
7. Identify the root cause for each finding you will fix.
8. Describe instruction compliance before coding, including trust boundaries, RBAC, service ownership, auditability, safe logging/error handling, async safety, and migration fidelity when relevant.
9. Add or update focused tests first when practical.
10. Implement the minimal root-cause fixes.
11. Audit the changed behavior for required documentation updates, including API, operations, QA, and design/security docs when relevant.
12. Run the relevant verification steps.
13. Report which findings are fixed, which remain open, and why.
14. End with a concise change summary that can be reused as a commit message. Present the commit message in imperative or past-tense style inside a code block.

If the user supplied multiple findings, address them in severity order unless there is a clear dependency that requires a different order.

If a finding cannot be fixed safely without more context, ask a small number of focused questions instead of guessing.

-------------------------------------------------------------------------------
## Documentation sync requirements
-------------------------------------------------------------------------------

Review the fixes for any required documentation updates.

Check for updates in places such as:

- `README.md`
- files under `docs/`
- API quick reference and operations guides
- design and security documentation
- setup and deployment guidance
- QA guides and UI use-case material
- prompt files if workflow expectations changed
- generated help content such as `frontend/public/help/manual.html` when operator docs change

For each required update:

1. Show the concrete evidence that triggered the documentation need.
2. Name the document that must change and explain why.
3. Make the minimal documentation edit needed to keep docs accurate.

Keep documentation edits present-tense, evidence-based, and narrowly scoped.

-------------------------------------------------------------------------------
## Output format
-------------------------------------------------------------------------------

## Findings Addressed
List the review findings you handled in this pass.

## Instruction Compliance
Explain how the fixes respect repository rules, including architecture boundaries, trust boundaries, RBAC, auditability, safe error handling, migration workflow, and documentation obligations.

## Pattern Reuse Plan
List the existing patterns, contracts, and abstractions reused for the fixes.

## Root Cause
Describe the actual cause of each actionable finding.

## Implementation
Bullet list of the fixes made.

## Tests and Verification
List the checks run and their outcomes. Do not claim a finding is fixed without fresh evidence.

#### Required Documentation Updates
- Group by document or feature area.

#### Remaining Findings or Blockers
- List any review findings not fixed in this pass and explain why.

#### Confidence (High / Medium / Low)
- Give a short reason for the confidence level.

## Notes
Include follow-ups, assumptions, invalidated findings, or residual risks.

## Commit Message Summary
Provide 1 concise sentence in imperative or past-tense style inside a fenced code block that summarizes the change set and can be used directly or adapted for a git commit message.