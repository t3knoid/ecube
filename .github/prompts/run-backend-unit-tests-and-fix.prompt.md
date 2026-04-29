---
name: Backend Unit Tests And Fix
description: "Run the default ECUBE backend unit test command, optionally accept extra pytest args or a single test file, fix failures found in product code when feasible, and summarize what changed."
argument-hint: "Optional pytest args, single test file, failing test, or backend subsystem to prioritize while fixing"
agent: "agent"
---
Run the ECUBE backend unit tests from the repository root using this default command and fix issues found when feasible:

`python -m pytest tests/ --ignore=tests/integration --ignore=tests/hardware -v`

Your task:
- Start from the current workspace changes and current user request.
- Use the exact backend unit test command above as the default validation target when the user does not supply a narrower test file or extra pytest arguments.
- If the user supplies a single backend test file, run that file instead of the full default command.
- If the user supplies extra pytest arguments, append them to the default command unless the user also supplied a single test file, in which case apply the extra arguments to that single-file run.
- Keep the default ignores for `tests/integration` and `tests/hardware` unless the user explicitly asks to change them.
- Always treat integration and hardware tests as out of scope for this prompt unless the user explicitly changes that scope.
- Use the repository guidance in [copilot-instructions](../copilot-instructions.md) as binding constraints while interpreting failures and making fixes.
- If the user provides a focus area, failing test, file, or subsystem, use that to prioritize diagnosis and repair.
- If the test command fails because of product-code issues, fix the smallest relevant slice first, rerun the narrowest sensible validation for the touched area, then rerun the full backend unit command above.
- If the test command fails because of environment, dependency, permission, or external-service blockers, do not guess at product fixes. State the blocker clearly and separate it from code failures.
- Do not modify integration tests, hardware tests, or unrelated code just to make this command pass.
- Prefer root-cause fixes over superficial test-only adjustments.

Output requirements:
- Start with a short outcome line stating whether the backend unit command passed, failed, or was blocked.
- Then include these sections when relevant:
  - Tests run
  - Failures found
  - Fixes made
  - Remaining blockers
  - Validation reruns
  - Recommended next steps
- Always state whether the final status reflects the full default backend unit command, a single-file run, or the default command plus extra pytest arguments.
- For each fix, identify the affected file or behavior and the reason it was changed.
- If you stop with unresolved failures, list the failing tests and the next smallest action needed.

Style requirements:
- Keep the summary concise and evidence-based.
- Prefer concrete failing test names, commands, and changed behavior over raw log dumps.
- Call out safety, RBAC, auditability, project-isolation, or API-contract risks when the failing tests touch those areas.