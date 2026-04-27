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
- if the ticket appears to conflict with repository instructions, do not implement the conflicting behavior; explain the conflict and propose a compliant alternative

Implementation workflow:
1. Read [workspace instructions](../copilot-instructions.md) first and treat them as mandatory constraints.
2. Summarize the ticket and list any assumptions.
3. Read the relevant code, tests, and docs.
4. Identify the root cause with evidence.
5. Describe instruction compliance before coding, including trust boundaries, RBAC, auditability, service-layer ownership, and safe error handling.
6. Write or update focused tests.
7. Implement the minimal root-cause fix.
8. Run the relevant verification steps.
9. Report what changed and whether the ticket now appears complete.
10. Write or update documentation if needed.

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
