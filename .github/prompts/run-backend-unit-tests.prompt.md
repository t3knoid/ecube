---
name: Backend Unit Tests
description: "Run the full ECUBE backend unit test suite and summarize findings, failures, and validation gaps."
argument-hint: "Optional focus area, file, feature, or failure to highlight in the summary"
agent: "agent"
---
Run the full ECUBE backend unit test suite for the current workspace context, then summarize the findings.

Your task:
- Run the full ECUBE backend unit test suite by default.
- Treat backend unit tests as the primary validation target unless the user explicitly asks for integration, E2E, or a narrower subset.
- If the user supplies a file, feature, or failure to investigate, use that to focus the summary, but still run the full backend unit suite unless the user explicitly requests a scoped run.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) and the project Cursor rules under [.cursor/rules](../../.cursor/rules) as binding constraints while interpreting failures and validation gaps.
- Exclude integration and E2E coverage unless the user explicitly asks for them.
- If the full backend unit suite cannot run, explain why and run the broadest valid backend unit subset available.
- Summarize what passed, what failed, and what still remains unvalidated.

Output requirements:
- Start with a short outcome line stating whether the full backend unit suite passed, failed, or was blocked.
- Then include these sections when relevant:
  - Tests run
  - Findings
  - Failures
  - Unvalidated areas
  - Recommended next steps
- Always state whether the run covered the full backend unit suite or a fallback subset.
- For failures, include the failing test names, the likely cause if it is evident, and the smallest sensible next action.
- If the test run is blocked by environment or dependency issues, say that clearly and separate it from product-code failures.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer the most actionable explanation over a broad dump of raw output.
- Do not speculate beyond what the executed tests and local context support.
- Call out backend safety, RBAC, audit, isolation, or API-contract risks when the failing tests touch those areas.
