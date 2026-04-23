---
name: Backend Unit Tests With Coverage
description: "Run ECUBE backend unit tests with coverage reporting for touched backend files and summarize findings."
argument-hint: "Optional file, feature, failure, or backend area to emphasize in coverage reporting"
agent: "agent"
---
Run ECUBE backend unit tests with coverage reporting focused on the touched backend files, then summarize the findings.

Your task:
- Inspect the current context, selected files, user request, and recent changes to identify the touched backend files first.
- Prefer backend unit tests over integration and E2E coverage unless the user explicitly asks for wider validation.
- Choose the most relevant backend unit test scope that gives meaningful coverage feedback for the touched backend files.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) and the project Cursor rules under [.cursor/rules](../../.cursor/rules) as binding constraints while interpreting failures, coverage gaps, and validation risks.
- Report coverage for the touched backend files when the test tooling and environment make that possible.
- If touched backend files cannot be determined clearly, explain that and choose the smallest reasonable backend unit scope with the best available backend coverage signal.
- If coverage reporting is blocked by environment or tooling limits, say that clearly and still summarize the executed backend unit tests.
- Summarize what passed, what failed, which touched files received coverage feedback, and what still remains unvalidated.

Output requirements:
- Start with a short outcome line stating whether the selected backend unit tests and coverage collection passed, failed, or were blocked.
- Then include these sections when relevant:
  - Tests run
  - Touched files considered
  - Coverage findings
  - Failures
  - Unvalidated areas
  - Recommended next steps
- For coverage findings, identify the touched backend files that received coverage reporting and call out notable coverage gaps.
- For failures, include the failing test names, the likely cause if it is evident, and the smallest sensible next action.
- Distinguish clearly between test failures, coverage gaps, and environment or tooling blockers.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer the most actionable explanation over a broad dump of raw output.
- Do not speculate beyond what the executed tests, coverage results, and local context support.
- Call out backend safety, RBAC, audit, isolation, or API-contract risks when failures or missing coverage affect those areas.
