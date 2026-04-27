---
name: PR Summary
description: Generate a concise, reviewer-friendly pull request description from the current workspace changes.
argument-hint: Describe the branch, feature, bugfix, or PR context to summarize
agent: agent
---

Create a polished pull request summary for the current ECUBE workspace changes.

Your task:
- Review the changed files, behavior changes, and any related tests or verification evidence in the current workspace.
- Summarize the change set in a concise, reviewer-friendly format.
- Focus on what changed, why it matters, and how it was validated.


Create a fenced code block with the following sections:
- a short overview paragraph
- a bullet list of the key changes
- any important user-facing or operator-facing effects
- validation evidence such as tests, build verification, or manual checks when available

Style requirements:
- Keep it concise and scannable.
- Use onboarding-first language that helps a reviewer quickly understand the intent.
- Prefer grouped bullets over long prose.
- Avoid speculation; use only evidence from the actual diff and verification results.
- If the branch touches security, audit, RBAC, hardware, or operator workflows, call that out clearly.

When helpful, organize the output under headings such as:
- Summary
- Changes included
- Validation

If there is not enough evidence for a claim, say that verification is still needed.
