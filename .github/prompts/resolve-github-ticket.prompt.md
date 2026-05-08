---
name: Resolve GitHub Ticket
description: "Investigate and resolve an ECUBE GitHub issue with a root-cause fix, focused tests, verification, and documentation review."
argument-hint: "Paste the ticket, issue text, number, or subsystem"
agent: "agent"
---
# ECUBE — Unified GitHub Ticket Resolution Prompt

Resolve the provided GitHub ticket in the ECUBE repository.

Use the user argument as the ticket description, acceptance criteria, issue number, or problem area to focus on.

## Mandatory instruction sources

Read and apply all of the following before investigating or editing code:

- `.github/copilot-instructions.md`
- `.cursor/rules/core.mdc`
- `.cursor/rules/backend.mdc`
- `.cursor/rules/frontend.mdc`
- `.cursor/rules/installer.mdc`
- `.cursor/rules/migrations.mdc`
- `.cursor/rules/shell-docker.mdc`
- `.github/prompts/pr-review.prompt.md`

Treat the repository instructions and `.mdc` files as the single source of truth. Do not restate or loosen them. If one of them is missing, say so explicitly.

## Scope routing

Apply rules by file and behavior scope:

- `core.mdc`: always-on global rules for security, trust boundaries, logging, audit safety, architecture, tests, and documentation consistency
- `backend.mdc`: Python backend, FastAPI, services, repositories, infrastructure, models, and backend tests
- `frontend.mdc`: Vue UI, browser interactions, routing, API usage from the UI, accessibility, frontend tests, and `app/spa.py`
- `installer.mdc`: native installer scripts, `.env` mutation, Python resolution, privilege dropping, demo bootstrap, and installer-focused tests
- `migrations.mdc`: Alembic migrations, schema history, and model-to-migration compatibility
- `shell-docker.mdc`: shell scripts, subprocess usage, Dockerfiles, entrypoints, Compose, and environment handling

When a changed file falls under multiple rule files, apply all relevant rules together.

## Resolution goals

Your job is to:

- understand the requested behavior and restate the scope clearly
- investigate the root cause before making changes
- implement the smallest correct fix that satisfies the ticket
- preserve ECUBE architecture, security, auditability, and trust boundaries
- add or update automated tests for the new or corrected behavior
- verify the relevant checks before claiming the ticket is resolved
- evaluate whether documentation or nearby comments need updates

If the ticket is ambiguous or lacks enough evidence, ask a small number of focused clarification questions instead of guessing.

## Required workflow

1. Summarize the ticket and note any assumptions.
2. Identify which instruction sources apply to the touched files.
3. Inspect the relevant code, tests, and docs.
4. If schema changes are required, resolve the current release migration from `project.version` and reuse it instead of creating a new Alembic revision file.
5. Identify the root cause with evidence.
6. Make the minimal fix.
7. Add or update focused tests.
8. Run the relevant verification steps.
9. Report what changed and any remaining risks or follow-up work.
10. State whether documentation is already aligned or which documents/comments need updates.

## Output format

## Ticket understanding
Short summary of the request and affected area.

## Root cause
What is actually broken or missing, with evidence.

## Changes made
Bullet list of the code, test, config, or documentation updates.

## Verification
List the checks or tests run and the results.

## Remaining risks or follow-up
Only include blockers, follow-ups, notable edge cases, or documentation updates still needed.
