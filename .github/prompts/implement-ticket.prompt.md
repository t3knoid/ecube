---
name: Implement Ticket
description: "Implement an ECUBE ticket with a root-cause fix, tests, and verification"
argument-hint: "Paste the ticket, acceptance criteria, issue text, or subsystem"
agent: "agent"
---
Implement the provided ticket in the ECUBE repository.

Mandatory first step: read [workspace instructions](../copilot-instructions.md) before any analysis, planning, code edits, or test changes.

Use the user argument as the source of truth for the requested behavior, acceptance criteria, or problem scope.

Your job is to:
- restate the ticket clearly before coding
- investigate the current implementation and identify the root cause or missing behavior
- implement the smallest complete change that satisfies the request
- keep the solution aligned with ECUBE architecture and safety rules
- add or update automated tests for the changed behavior
- verify the change with the relevant checks before declaring success
- modify or add any documentation if the ticket impacts existing docs or requires new ones

Required ECUBE rules:
- these repository instructions are binding, not optional
- preserve strict project isolation, auditability, and role-based access control
- keep the system layer trusted and the UI layer untrusted
- route OS-level operations through interfaces in app/infrastructure
- keep business logic in services rather than routers
- redact sensitive paths, credentials, device identifiers, and raw provider errors
- use shared error responses and correct 401 vs 403 behavior where applicable
- avoid blocking FastAPI endpoints or introducing unsafe shell/file behavior
- follow Black, Ruff, ESLint, and Prettier formatting conventions
- follow the ECUBE release-scoped Alembic workflow: update the current release migration in place and do not create a second unreleased file under `alembic/versions`
- if the ticket appears to conflict with repository instructions, do not implement the conflicting behavior; explain the conflict and propose a compliant alternative
- if the ticket requires a new visual or interaction pattern, inspect the closest existing component that already solves the same problem and match its styling patterns before introducing a new variant
- if the ticket requires a UI change, prefer reusing the same tokens, spacing, scrollbar, button, panel, and state treatments from the existing component unless the task explicitly requires a different design
- if the ticket requires a UI change, ensure to support keyboard interaction and accessibility-sensitive behavior for the changed components, and preserve API-only trust boundaries in UI flows
- if the ticket requires a new API endpoint, ensure to validate input, enforce roles, delegate to services, and declare error responses using shared R_* schemas
- if the ticket requires a UI change, ensure to support a mobile-responsive layout with the minimum screen dimension of 390px x 844px, and test the change in a mobile viewport to verify usability and visual integrity
- if the ticket requires a UI change, ensure the change does not cause normal desktop views to regress in usability or visual integrity

Implementation workflow:
1. Read [workspace instructions](../copilot-instructions.md) first and treat them as mandatory constraints.
2. Summarize the ticket and list any assumptions.
3. Read the relevant code, tests, and docs.
4. If schema changes are required, resolve the current release migration from `project.version` and reuse it instead of creating a new Alembic revision file.
5. Identify the root cause with evidence.
6. Describe instruction compliance before coding, including trust boundaries, RBAC, auditability, service-layer ownership, safe error handling, and release-migration workflow compliance when applicable.
7. Write or update focused tests.
8. Implement the minimal root-cause fix.
9. Run the relevant verification steps.
10. Report what changed and whether the ticket now appears complete.
11. Write or update documentation if needed.

If the request is unclear or under-specified, ask a small number of focused questions instead of guessing.

Respond in this format:

## Ticket understanding
Short summary of the requested behavior.

## Instruction compliance
Explain how the planned change respects the repository instructions, including trust boundaries, RBAC, auditability, service ownership, and safe error handling.

## Root cause
What was broken, missing, or risky.

## Implementation
Bullet list of the changes made.

## Tests and verification
List the tests or checks run and the outcomes. Do not claim success without fresh verification evidence.

## Notes
Any remaining risks, follow-ups, assumptions, or instruction conflicts.

Use repository guidance as mandatory context, including [workspace instructions](../copilot-instructions.md), [the PR review prompt](./pr-review.prompt.md), and [the resolve ticket prompt](./resolve-github-ticket.prompt.md).
