---
name: Code Review Current Branch
description: "Perform a code review of changes in the current branch using ECUBE repository instructions and Cursor .mdc rules, including required documentation updates."
argument-hint: "Optional focus area, risk, file, or reviewer concern"
agent: "agent"
---
# ECUBE — Unified Code Review Prompt

Review all changes in the current branch.

This prompt also includes the documentation-audit requirements from `.github/prompts/documentation-sync.prompt.md`. Treat required documentation updates as first-class review findings when code changes are not fully documented.

Use the repository instruction sources below as the authoritative review policy. Do not restate or reinterpret them loosely. When two sources overlap, prefer the more specific scoped rule for the files being reviewed, while preserving global security, trust-boundary, auditability, and project-isolation constraints.

## Mandatory instruction sources

Read and apply all of the following before reviewing:

- `.github/copilot-instructions.md`
- `.cursor/rules/core.mdc`
- `.cursor/rules/backend.mdc`
- `.cursor/rules/frontend.mdc`
- `.cursor/rules/installer.mdc`
- `.cursor/rules/migrations.mdc`
- `.cursor/rules/shell-docker.mdc`

Treat these files as the single source of truth. If one of them is missing, say so explicitly in the review.

## Scope routing

Apply rules by file and behavior scope:

- `core.mdc`: always-on global rules for security, trust boundaries, logging, audit safety, architecture, tests, and documentation consistency
- `backend.mdc`: Python backend, FastAPI, services, repositories, infrastructure, models, and backend tests
- `frontend.mdc`: Vue UI, browser interactions, routing, API usage from the UI, accessibility, frontend tests, and `app/spa.py`
- `installer.mdc`: native installer scripts, `.env` mutation, Python resolution, privilege dropping, demo bootstrap, and installer-focused tests
- `migrations.mdc`: Alembic migrations, schema history, and model-to-migration compatibility
- `shell-docker.mdc`: shell scripts, subprocess usage, Dockerfiles, entrypoints, Compose, and environment handling

When a changed file falls under multiple rule files, apply all relevant rules together.

## Review goals

Your job is to identify bugs, regressions, risks, missing tests, stale comments, and documentation gaps in the current branch.

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

Always evaluate documentation impact using concrete evidence from the branch diff, changed behavior, or affected files.

Primary task:

- inspect the current code changes, affected files, and any related UI or API behavior
- determine which documentation must be updated so the docs stay accurate for operators, developers, reviewers, and QA

Documentation focus areas:

- user-facing behavior
- developer-facing behavior
- architectural behavior
- validation rules and error messages
- role-based permissions visible in the UI
- drive, job, mount, browse, audit, evidence export, and directory-browser workflows
- new or changed buttons, dialogs, menus, navigation paths, loading states, empty states, and error states
- setup, configuration, deployment, or operational guidance

Check nearby documentation and comments when relevant, including:

- `README.md`
- relevant files under the `docs` tree
- API reference sections
- architecture diagrams or design docs
- setup and deployment instructions
- ECUBE-specific operator and workflow documentation
- prompt files, review prompts, and in-repo operator/developer guidance
- updated screenshots or UI mockups

For each required documentation update:

1. Show the exact diff lines, changed behavior, or concrete evidence that triggered the documentation need.
2. Name the document that must be updated and explain why.
3. Propose the minimal documentation change in 1 to 3 sentences.
4. If the change introduces a new UI state or workflow, propose a QA test case.

Documentation review constraints:

- be evidence-based; do not suggest speculative documentation work
- keep recommendations modular, concise, contributor-friendly, and onboarding-first
- prefer small targeted edits over broad rewrites
- keep formatting print-ready and easy to scan
- if no update is needed for an area, say so briefly

Report one of the following explicitly:

- `documentation is already aligned with the code changes`
- `documentation updates are required`

If documentation updates are required, name the affected documents, describe the behavior that now needs to be documented or corrected, and include the evidence that triggered the documentation finding.

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

When documentation findings exist, include them under architecture, security, testing, or documentation issues using the same severity and evidence standard as code findings.

If there are no findings, say so explicitly and mention any residual risk or test/documentation gaps.

After the findings section, always include these documentation-review sections exactly:

#### Required Documentation Updates
- Group by document or feature area.

#### Suggested Additions to QA Testing Guide
- Include manual verification scenarios when relevant.

#### Suggested Additions to UI Use Cases
- Include any new operator workflows, states, or role-dependent behavior.

#### Confidence (High / Medium / Low)
- Give a short reason for the confidence level.

Keep the review concise and specific. Prefer concrete findings over summaries.
