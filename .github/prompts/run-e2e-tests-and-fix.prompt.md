---
name: Run E2E Tests And Fix
description: "Run relevant ECUBE Playwright E2E tests, fix the failures at the root cause, and summarize what changed or what remains blocked."
argument-hint: "Optional feature, page, workflow, spec path, selector failure, or E2E issue to investigate"
agent: "agent"
---
Run the relevant ECUBE Playwright end-to-end tests for the current task, fix issues that arise, rerun the narrowest useful validation while iterating, and finish by automatically running the full E2E suite unless the environment is clearly blocked.

Primary targets:
- [frontend/e2e](../../frontend/e2e)
- [frontend/playwright.config.js](../../frontend/playwright.config.js)
- [frontend/package.json](../../frontend/package.json)

Supporting evidence sources:
- [frontend/src](../../frontend/src)
- [tests](../../tests)
- [README.md](../../README.md)
- [copilot-instructions](../copilot-instructions.md)
- [.cursor/rules](../../.cursor/rules)

Task:
- Inspect the current context, selected files, recent changes, and user request to choose the most relevant E2E scope first.
- If the user provides a feature, page, spec path, selector, or failure, use that to narrow the first Playwright run.
- Prefer the smallest E2E slice that can falsify the current hypothesis before widening to broader E2E coverage.
- Run the relevant Playwright tests.
- If they fail, identify whether the root cause is:
  - frontend or API behavior drift
  - stale Playwright selectors, assertions, fixtures, or snapshots
  - environment or test-runner blockers
- Fix the root cause with the smallest evidence-based change.
- After each substantive edit, rerun the narrowest relevant Playwright validation before making more changes.
- Once the focused failing slice is green, automatically run the full Playwright E2E suite before concluding.
- If the issue is clearly outside E2E scope, make the necessary repo change anyway when it is local and safe, then rerun E2E validation.
- If the run is blocked by missing browsers, servers, auth setup, ports, seed data, or other environment prerequisites, stop and report the blocker clearly instead of guessing.
- Keep ECUBE trust boundaries, RBAC expectations, audit behavior, and API contracts intact while fixing failures.

Fixing rules:
- Prefer fixing product code when the test exposes a real regression.
- Prefer fixing Playwright code when the app behavior is correct and the spec is stale.
- Do not invent selectors, routes, labels, or backend behavior that are not supported by the current code.
- Avoid unrelated refactors.
- Update snapshots only when the visual change is intentional and verified.

Validation:
- Use the repo's Playwright workflow from [frontend/package.json](../../frontend/package.json) and [frontend/playwright.config.js](../../frontend/playwright.config.js).
- Prefer focused spec or test-name runs first while diagnosing and fixing failures.
- After local fixes, automatically run the full E2E suite as the final validation step whenever the environment allows it.
- If the full E2E suite cannot run, report the blocker clearly and distinguish it from product failures.

Output requirements:
- Start with a short outcome line stating whether the selected E2E tests passed, failed, were fixed, or were blocked.
- Then include these sections when relevant:
  - Tests run
  - Why this scope
  - Changes made
  - Remaining failures or blockers
  - Unvalidated areas
  - Recommended next steps
- Always state both the focused diagnostic slice and the final full-suite result, unless the full suite was blocked.
- For each fix, explain whether it was product code, test code, config, or environment setup.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer actionable conclusions over raw Playwright output dumps.
- Do not speculate beyond what the executed tests and local code support.