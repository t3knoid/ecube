---
name: Update E2E Tests
description: "Update Playwright e2e tests to match the latest UI and workflow changes on the current branch"
argument-hint: "Optional feature area, screen, ticket, or PR context"
agent: "agent"
---

Review the current branch changes and update the ECUBE end-to-end tests so they match the latest real behavior.

Primary targets:
- [frontend/e2e](../../frontend/e2e)
- [frontend/playwright.config.js](../../frontend/playwright.config.js)

Supporting evidence sources:
- [frontend/src](../../frontend/src)
- [tests](../../tests)
- [README.md](../../README.md)
- Active branch diff versus `main`

Task:
- Inspect the current branch changes and identify user-visible behavior that affects Playwright coverage.
- Update the relevant e2e specs, fixtures, routes, assertions, and snapshots to match the latest implementation.
- Prefer minimal targeted edits over broad rewrites.
- Reuse existing helpers and established test patterns in the repo.

Focus areas:
- changed UI labels, buttons, dialogs, and status text
- updated routes, navigation, and page flows
- role-based visibility and disabled states
- manifest, pause/resume, compare, configuration, and job-detail workflows when affected by the branch
- mocked API responses and route handlers used by Playwright tests
- visual snapshots only when the UI change is verified and intentional

Rules:
- Be evidence-based and use the current code as the source of truth.
- Do not invent flows, selectors, or API behavior that are not in the branch.
- Keep ECUBE security boundaries and role expectations intact.
- Avoid unrelated refactors while updating tests.
- If a branch change implies drift in test docs or helpers, update them only when directly required.

Validation:
- Run the most relevant focused Playwright tests where practical.
- If full browser validation is not feasible, run the nearest reliable check and explain the limitation.
- Report any ambiguous behavior that still needs manual confirmation.

Return results in exactly this structure:

#### E2E Test Updates
- List each spec or snapshot updated and why.

#### Validation Performed
- Include the exact focused test runs or other verification performed.

#### Remaining Gaps or Follow-Ups
- Note only evidence-based follow-ups.

#### Confidence (High / Medium / Low)
- Give a short reason for the confidence level.
