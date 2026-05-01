---
name: Create Commit Message
description: "Create a commit message from the currently staged git changes. Use when you want a concise, implementation-grounded commit summary for ECUBE changes."
argument-hint: "Optional emphasis, such as terse, include body, reviewer-friendly, or include ticket reference"
agent: agent
---
Create a commit message for the currently staged git changes in this ECUBE workspace.

Instructions:
- Inspect only staged changes. Ignore unstaged and untracked changes unless the user explicitly asks for them.
- Base the message on the actual behavior change, not a file-by-file changelog.
- Prefer ECUBE-relevant framing such as project isolation, auditability, job behavior, drive lifecycle, mount handling, copy behavior, API behavior, or UI behavior.
- If the staged changes span both backend and frontend, write a message that reflects the shared outcome rather than listing both layers separately.
- If the user provided an argument, use it to tune the message format or emphasis.
- If there are no staged changes, say that directly and stop.

Preferred output:
1. A fenced text block containing a commit-ready subject line.
2. If the staged diff is substantial or the user asked for it, include a short commit body after a blank line inside the same code block.

Commit message rules:
- Keep the subject line concise and specific.
- Use imperative mood.
- Avoid vague subjects like "update files" or "misc fixes".
- Mention the primary behavior change or safeguard added.
- Include an issue or ticket reference only if it is clearly supported by the staged diff or the current session context.
- Do not invent scope tags, prefixes, or ticket numbers.

Keep the response concise and grounded in the staged diff.