---
name: Repository Review
description: "Review the entire ECUBE repository using the unified code-review policy and whole-workspace context, not just current-branch changes."
argument-hint: "Optional focus area, subsystem, directory, risk, or review emphasis"
agent: "agent"
---
# ECUBE — Full Repository Review Prompt

Review the entire ECUBE repository, not just the current branch changes.

Use the repository instruction sources below and the unified review prompt as the authoritative review policy. Do not restate or reinterpret them loosely. When sources overlap, prefer the more specific scoped rule for the files being reviewed while preserving global security, trust-boundary, auditability, and project-isolation constraints.

## Mandatory instruction sources

Read and apply all of the following before reviewing:

- `.github/prompts/code-review.prompt.md`
- `.github/copilot-instructions.md`
- `.cursor/rules/core.mdc`
- `.cursor/rules/backend.mdc`
- `.cursor/rules/frontend.mdc`
- `.cursor/rules/migrations.mdc`
- `.cursor/rules/shell-docker.mdc`

Treat these files as the single source of truth. If one of them is missing, say so explicitly in the review.

## Workspace scope

Load the entire workspace into the review context.

- Treat the whole repository as in scope, including backend, frontend, tests, scripts, docs, prompt files, configuration, and deployment assets.
- Do not silently narrow the review to changed files, the active editor selection, or the current branch diff.
- If the workspace is too large to load into one context window, inspect it systematically in batches until the full repository has been covered.
- If any files or directories are intentionally skipped, list them explicitly and explain why.

## Scope routing

Apply rules by file and behavior scope:

- `core.mdc`: always-on global rules for security, trust boundaries, logging, audit safety, architecture, tests, and documentation consistency
- `backend.mdc`: Python backend, FastAPI, services, repositories, infrastructure, models, and backend tests
- `frontend.mdc`: Vue UI, browser interactions, routing, API usage from the UI, accessibility, frontend tests, and `app/spa.py`
- `migrations.mdc`: Alembic migrations, schema history, and model-to-migration compatibility
- `shell-docker.mdc`: shell scripts, subprocess usage, Dockerfiles, entrypoints, Compose, and environment handling

When a file falls under multiple rule files, apply all relevant rules together.

## Review goals

Your job is to identify repository-wide bugs, regressions, risks, missing tests, stale comments, outdated prompts, inconsistent documentation, and structural policy drift.

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
- stale or conflicting prompt, instruction, comment, or documentation content

## Documentation and prompt review requirement

Always evaluate documentation and prompt impact.

Report one of the following explicitly:

- `documentation and prompts are already aligned with the codebase`
- `documentation or prompt updates are required`

If updates are required, name the affected documents or prompt files and describe what is stale, duplicated, inconsistent, or missing.

Check nearby documentation and review guidance when relevant, including:

- `README.md`
- `docs/operations/`
- `docs/testing/`
- `docs/design/`
- `docs/development/`
- `.github/prompts/`
- `.github/copilot-instructions.md`
- `.cursor/rules/`

## Output format

Use a findings-only output. Do not include an executive summary, overview paragraph, or narrative recap before the findings.

Report findings in this order:

1. Cursor or repository rule violations
2. ECUBE architecture, security, testing, documentation, or prompt issues
3. General code quality or consistency issues

Before the findings, include a `Coverage` section that lists which top-level repository areas were reviewed and whether each was fully reviewed, sampled, or skipped.

At minimum, account for these areas when they exist in the workspace:

- `app/`
- `frontend/`
- `tests/`
- `alembic/`
- `scripts/`
- `docs/`
- `.github/`
- `deploy/`
- root-level project files such as `pyproject.toml`, `README.md`, Compose files, and other top-level configuration

For each coverage entry:

- state `fully reviewed`, `sampled`, or `skipped`
- briefly note the review basis or reason for any sampling or skip

After the findings, include a final `Documentation and prompt alignment` line that states exactly one of:

- `documentation and prompts are already aligned with the codebase`
- `documentation or prompt updates are required`

For each finding:

- state the severity
- explain the concrete risk, inconsistency, or regression
- cite the specific file and line when applicable
- describe the expected behavior or rule being violated

If there are no findings, say `No findings.` and still include the `Coverage` section and the final `Documentation and prompt alignment` line.

Keep the review concise and specific. Prefer concrete findings over summaries.