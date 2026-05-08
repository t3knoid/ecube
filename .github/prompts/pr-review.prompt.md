---
name: PR Review
description: "Review an ECUBE pull request using repository instructions and Cursor .mdc rules, including test and documentation impact."
argument-hint: "Optional focus area, risk, file, reviewer concern, or PR context"
agent: "agent"
---
# ECUBE — Unified PR Review Prompt

Review the provided pull request or change set.

Use the repository instruction sources below as the authoritative review policy. Do not duplicate or reinterpret them loosely. When sources overlap, prefer the most specific rule file for the files and behaviors under review while preserving global security, trust-boundary, auditability, and project-isolation constraints.

## Mandatory instruction sources

Read and apply all of the following before reviewing:

- `.github/copilot-instructions.md`
- `.cursor/rules/core.mdc`
- `.cursor/rules/backend.mdc`
- `.cursor/rules/frontend.mdc`
- `.cursor/rules/migrations.mdc`
- `.cursor/rules/shell-docker.mdc`

Treat these files as the single source of truth. If one of them is missing, say so explicitly in the review.

## Scope routing

Apply rules by file and behavior scope:

- `core.mdc`: always-on global rules for security, trust boundaries, logging, audit safety, architecture, tests, and documentation consistency
- `backend.mdc`: Python backend, FastAPI, services, repositories, infrastructure, models, and backend tests
- `frontend.mdc`: Vue UI, browser interactions, routing, API usage from the UI, accessibility, frontend tests, and `app/spa.py`
- `migrations.mdc`: Alembic migrations, schema history, and model-to-migration compatibility
- `shell-docker.mdc`: shell scripts, subprocess usage, Dockerfiles, entrypoints, Compose, and environment handling

When a changed file falls under multiple rule files, apply all relevant rules together.

## Review goals

Your job is to identify bugs, regressions, risks, missing tests, stale comments, and documentation gaps in the pull request.

Review for at least the following:

- correctness and behavior regressions
- security and trust-boundary violations
- RBAC and authorization mistakes
- project-isolation or auditability regressions
- unsafe logging, redaction, or error-surface behavior
- router/service boundary violations
- API contract drift and missing error responses
- frontend routing, same-origin SPA behavior, accessibility, and API-client consistency
- schema or migration workflow violations
- shell, subprocess, Docker, or Compose safety issues
- missing or insufficient automated tests
- stale or missing documentation/comments for changed behavior

## Documentation review requirement

Always evaluate documentation impact.

Report one of the following explicitly:

- `documentation is already aligned with the code changes`
- `documentation updates are required`

If documentation updates are required, name the affected documents and describe the behavior that now needs to be documented or corrected.

## Output format

Report findings in this order:

1. Cursor or repository rule violations
2. ECUBE architecture, security, testing, or documentation issues
3. General code quality issues

For each finding:

- state the severity
- explain the concrete risk or regression
- cite the specific file and line
- describe the expected behavior or rule being violated

If there are no findings, say so explicitly and mention any residual risk or test/documentation gaps.

Keep the review concise and specific. Prefer concrete findings over summaries.
