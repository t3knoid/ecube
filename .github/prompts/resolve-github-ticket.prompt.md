---
name: Resolve GitHub Ticket
description: "Investigate and resolve an ECUBE GitHub issue with a root-cause fix and verified tests"
argument-hint: "Paste the ticket, issue text, number, or subsystem"
agent: "agent"
---
Resolve the provided GitHub ticket in the ECUBE repository.

Use the user argument as the ticket description, acceptance criteria, issue number, or problem area to focus on.

Your job is to:
- understand the requested behavior and restate the scope clearly
- investigate the root cause before making changes
- implement the smallest correct fix that satisfies the ticket
- preserve ECUBE architecture, security, auditability, and trust boundaries
- add or update automated tests for the new or corrected behavior
- verify the relevant checks before claiming the ticket is resolved

Required ECUBE guardrails:
- keep business logic in services, not routers
- use require_roles() for endpoint access where relevant
- preserve project isolation and audit logging
- keep OS and hardware operations behind interfaces in app/infrastructure
- redact internal paths, credentials, hardware identifiers, and raw provider errors
- avoid unsafe shell usage, directory traversal risks, and blocking endpoint behavior
- follow Black, Ruff, ESLint, and Prettier conventions
- follow the ECUBE release-scoped Alembic workflow: reuse the current release migration file and do not create a second unreleased revision under `alembic/versions`

Investigation workflow:
1. Summarize the ticket and note any assumptions.
2. Inspect the relevant code, tests, and docs.
3. If schema changes are required, resolve the current release migration from `project.version` and reuse it instead of creating a new Alembic revision file.
4. Identify the root cause with evidence.
5. Make the minimal fix.
6. Add or update focused tests.
7. Run the relevant verification steps.
8. Report what changed and any remaining risks or follow-up work.

If the ticket is ambiguous or lacks enough evidence, ask a small number of focused clarification questions instead of guessing.

Respond in this format:

## Ticket understanding
Short summary of the request and affected area.

## Root cause
What is actually broken or missing, with evidence.

## Changes made
Bullet list of the code, test, or config updates.

## Verification
List the checks or tests run and the results.

## Remaining risks or follow-up
Only include blockers, follow-ups, or notable edge cases.

Use repository guidance when helpful, including [workspace instructions](../copilot-instructions.md) and [the PR review prompt](./pr-review.prompt.md).
