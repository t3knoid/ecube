---
name: Full Integration Tests
description: "Run the full ECUBE integration test suite and summarize findings, failures, and validation gaps."
argument-hint: "Optional focus area, file, feature, or failure to highlight in the summary"
agent: "agent"
---
Run the full ECUBE integration test suite for the current workspace context, then summarize the findings.

Your task:
- Run the full ECUBE integration test suite by default.
- Treat integration tests as the primary validation target only when the user explicitly asks for integration coverage or when this prompt is invoked.
- If the user supplies a file, feature, or failure to investigate, use that to focus the summary, but still run the full integration suite unless the user explicitly asks for a narrower run.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) and the project Cursor rules under [.cursor/rules](../../.cursor/rules) as binding constraints while interpreting failures and validation gaps.
- Exclude backend unit and E2E coverage unless the user explicitly asks for them.
- If the full integration suite cannot run, explain why and run the broadest valid integration subset available.
- If integration tests are blocked by external services, databases, configuration, or environment preconditions, say that clearly and separate those blockers from product-code failures.
- Summarize what passed, what failed, and what still remains unvalidated.

Output requirements:
- Start with a short outcome line stating whether the full integration suite passed, failed, or was blocked.
- Then include these sections when relevant:
  - Tests run
  - Findings
  - Failures
  - Unvalidated areas
  - Recommended next steps
- Always state whether the run covered the full integration suite or a fallback subset.
- For failures, include the failing test names, the likely cause if it is evident, and the smallest sensible next action.
- Distinguish clearly between product failures, environment blockers, and missing test coverage.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer the most actionable explanation over a broad dump of raw output.
- Do not speculate beyond what the executed tests and local context support.
- Call out backend safety, RBAC, audit, isolation, database behavior, or API-contract risks when the failing integration tests touch those areas.
