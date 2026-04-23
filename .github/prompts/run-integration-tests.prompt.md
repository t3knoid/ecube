---
name: Integration Tests
description: "Run relevant ECUBE integration tests and summarize findings, failures, and validation gaps."
argument-hint: "Optional focus area, file, feature, integration test path, or failure to investigate"
agent: "agent"
---
Run the relevant ECUBE integration tests for the current task or current workspace context, then summarize the findings.

Your task:
- Inspect the current context, selected files, user request, and recent changes to determine the most relevant integration test scope first.
- Prefer integration tests over backend unit or E2E coverage when the goal is validating cross-service, database-backed, or workflow-level behavior.
- If the user supplies a file, feature, failure, or integration test path, use that to focus the integration test selection.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) and the project Cursor rules under [.cursor/rules](../../.cursor/rules) as binding constraints while interpreting failures and validation gaps.
- Exclude E2E coverage unless the user explicitly asks for it.
- If no focused integration test target is obvious, explain that and choose the smallest reasonable integration test scope, or the full integration suite if that is the most honest validation target.
- If integration tests are blocked by external services, databases, configuration, or environment preconditions, say that clearly and separate those blockers from product-code failures.
- Summarize what passed, what failed, and what still remains unvalidated.

Output requirements:
- Start with a short outcome line stating whether the selected integration tests passed, failed, or were blocked.
- Then include these sections when relevant:
  - Tests run
  - Why this scope
  - Findings
  - Failures
  - Unvalidated areas
  - Recommended next steps
- Always state whether the run covered a focused integration subset or the broader integration suite.
- For failures, include the failing test names, the likely cause if it is evident, and the smallest sensible next action.
- Distinguish clearly between product failures, environment blockers, and missing test coverage.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer the most actionable explanation over a broad dump of raw output.
- Do not speculate beyond what the executed tests and local context support.
- Call out backend safety, RBAC, audit, isolation, database behavior, or API-contract risks when the failing integration tests touch those areas.
