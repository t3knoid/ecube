---
name: Compare Validation Gaps
description: "Compare backend unit, integration, and E2E validation gaps for the current ECUBE change and recommend the next best test scope."
argument-hint: "Optional file, feature, workflow, ticket, or failure context to anchor the comparison"
agent: "agent"
---
Compare the backend unit, integration, and E2E validation gaps for the current ECUBE change, then recommend the next best validation step.

Your task:
- Inspect the current workspace context, recent changes, selected files, and user request to identify what behavior is changing.
- Evaluate which parts of that change are already covered, weakly covered, or still unvalidated by backend unit tests, integration tests, and E2E tests.
- Use existing test files, current branch context, recent failures, and nearby implementation details as evidence.
- Run the narrowest additional validation checks needed only when that materially improves the comparison and can be done cheaply.
- Do not turn this into a full broad test run unless the evidence is too weak to compare the three layers honestly.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) and the project Cursor rules under [.cursor/rules](../../.cursor/rules) as binding constraints while judging risk and validation needs.
- Treat backend unit tests as code-path validation, integration tests as cross-service or database-backed workflow validation, and E2E tests as user-visible workflow validation.
- Call out when a gap is due to missing tests, insufficient test scope, environment blockers, or uncertainty about changed behavior.

Output requirements:
- Start with a short outcome line stating which validation layer is currently strongest, which is weakest, and the most important remaining gap.
- Then include these sections:
  - Change surface
  - Backend unit gaps
  - Integration gaps
  - E2E gaps
  - Best next validation step
  - Deferred or blocked validation
- For each validation layer, distinguish between what is already covered, what is partially covered, and what is not covered.
- Be explicit about whether each conclusion is based on executed tests, existing test coverage only, code inspection, or environment constraints.
- Recommend one primary next step, not a broad laundry list, unless multiple independent high-risk gaps exist.
- If the current change does not justify one of the three layers, say so explicitly instead of forcing coverage.

Style requirements:
- Keep the comparison concise, evidence-based, and decision-oriented.
- Prefer actionable reasoning over raw test output.
- Do not speculate beyond the executed checks, visible test coverage, and local code context.
- Call out ECUBE-specific risks such as RBAC, audit logging, project isolation, API contracts, database effects, and user-visible workflow regressions when relevant.
