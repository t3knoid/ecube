---
name: Narrow Backend Unit Tests
description: "Run only the narrowest relevant ECUBE backend unit tests for the current change and summarize findings."
argument-hint: "Optional file, feature, symbol, failure, or backend area to target"
agent: "agent"
---
Run only the narrowest relevant ECUBE backend unit tests for the current change or current workspace context, then summarize the findings.

Your task:
- Inspect the current context, selected files, user request, and recent changes to identify the smallest meaningful backend unit test scope first.
- Prefer the most targeted backend unit tests that can validate the current change without widening to the full backend suite unless the user explicitly asks for broader coverage.
- If the user supplies a file, feature, symbol, or failure to investigate, use that to choose the test scope.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) and the project Cursor rules under [.cursor/rules](../../.cursor/rules) as binding constraints while interpreting failures and validation gaps.
- Exclude integration and E2E coverage unless the user explicitly asks for them.
- If no focused backend unit test target is obvious, explain that clearly and choose the smallest reasonable backend unit subset available.
- Summarize what passed, what failed, and what still remains unvalidated because the run was intentionally narrow.

Output requirements:
- Start with a short outcome line stating whether the selected narrow backend unit test scope passed, failed, or was blocked.
- Then include these sections when relevant:
  - Tests run
  - Why this scope
  - Findings
  - Failures
  - Unvalidated areas
  - Recommended next steps
- Always state why the selected tests were the narrowest sensible backend unit scope.
- For failures, include the failing test names, the likely cause if it is evident, and the smallest sensible next action.
- If the test run is blocked by environment or dependency issues, say that clearly and separate it from product-code failures.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer the narrowest actionable explanation over a broad dump of raw output.
- Do not speculate beyond what the executed tests and local context support.
- Call out backend safety, RBAC, audit, isolation, or API-contract risks when the failing tests touch those areas.
