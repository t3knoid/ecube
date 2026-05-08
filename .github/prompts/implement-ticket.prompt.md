---
name: Implement Ticket
description: "Implement an ECUBE ticket with a root-cause fix, focused tests, verification, and documentation review."
argument-hint: "Paste the ticket, acceptance criteria, issue text, or subsystem"
agent: "agent"
---
# ECUBE — Unified Ticket Implementation Prompt

Implement the provided ticket in the ECUBE repository.

Use the user argument as the source of truth for the requested behavior, acceptance criteria, or problem scope.

## Mandatory instruction sources

Read and apply all of the following before any analysis, planning, code edits, or test changes:

- `.github/copilot-instructions.md`
- `.cursor/rules/core.mdc`
- `.cursor/rules/backend.mdc`
- `.cursor/rules/frontend.mdc`
- `.cursor/rules/migrations.mdc`
- `.cursor/rules/shell-docker.mdc`
- `.github/prompts/pr-review.prompt.md`
- `.github/prompts/resolve-github-ticket.prompt.md`

Treat the repository instructions and `.mdc` files as the single source of truth. Do not restate or loosen them. If one of them is missing, say so explicitly.

## Scope routing

Apply rules by file and behavior scope:

- `core.mdc`: always-on global rules for security, trust boundaries, logging, audit safety, architecture, tests, and documentation consistency
- `backend.mdc`: Python backend, FastAPI, services, repositories, infrastructure, models, and backend tests
- `frontend.mdc`: Vue UI, browser interactions, routing, API usage from the UI, accessibility, frontend tests, and `app/spa.py`
- `migrations.mdc`: Alembic migrations, schema history, and model-to-migration compatibility
- `shell-docker.mdc`: shell scripts, subprocess usage, Dockerfiles, entrypoints, Compose, and environment handling

When a changed file falls under multiple rule files, apply all relevant rules together.

## Implementation goals

Your job is to:

- restate the ticket clearly before coding
- investigate the current implementation and identify the root cause or missing behavior
- implement the smallest complete change that satisfies the request
- keep the solution aligned with ECUBE architecture and safety rules
- add or update automated tests for the changed behavior
- verify the change with the relevant checks before declaring success
- evaluate whether documentation or nearby comments need updates

If the ticket appears to conflict with repository instructions, do not implement the conflicting behavior. Explain the conflict and propose a compliant alternative.

## Required workflow

1. Summarize the ticket and list any assumptions.
2. Identify which instruction sources apply to the touched files.
3. Read the relevant code, tests, and docs.
4. If schema changes are required, resolve the current release migration from `project.version` and reuse it instead of creating a new Alembic revision file.
5. Identify the root cause with evidence.
6. Describe instruction compliance before coding, including trust boundaries, RBAC, auditability, service ownership, safe error handling, and migration-workflow compliance when applicable.
7. Add or update focused tests.
8. Implement the minimal root-cause fix.
9. Run the relevant verification steps.
10. Report what changed and whether the ticket now appears complete.
11. State whether documentation is already aligned or which documents/comments need updates.

If the request is unclear or under-specified, ask a small number of focused questions instead of guessing.

## Output format

## Ticket understanding
Short summary of the requested behavior.

## Instruction compliance
Explain how the planned change respects the repository instructions, including trust boundaries, RBAC, auditability, service ownership, safe error handling, and migration workflow where applicable.

## Root cause
What was broken, missing, or risky.

## Implementation
Bullet list of the changes made.

## Tests and verification
List the tests or checks run and the outcomes. Do not claim success without fresh verification evidence.

## Notes
Any remaining risks, follow-ups, assumptions, instruction conflicts, or documentation updates still needed.
