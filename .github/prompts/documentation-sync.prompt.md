---
name: Documentation Sync
description: Audit code changes and identify the exact documentation, QA, and UI use-case updates required.
argument-hint: Describe the feature, branch, PR, or diff to audit for documentation updates
agent: agent
---

Review the current workspace changes and identify every documentation update required for ECUBE.

Primary task:
- Inspect the current code changes, affected files, and any related UI or API behavior.
- Determine which documentation must be updated so the docs stay accurate for operators, developers, reviewers, and QA.

Focus areas:
- User-facing behavior
- Developer-facing behavior
- Architectural behavior
- Validation rules and error messages
- Role-based permissions visible in the UI
- Drive, job, mount, browse, audit, evidence export, and directory-browser workflows
- New or changed buttons, dialogs, menus, navigation paths, loading states, empty states, and error states
- Setup, configuration, deployment, or operational guidance

Check for required updates in places such as:
- [README.md](../../README.md)
- relevant files under the docs tree
- API reference sections
- architecture diagrams or design docs
- setup and deployment instructions
- ECUBE-specific operator and workflow documentation
- Updated screenshots or UI mockups

For each required update:
1. Show the exact diff lines, changed behavior, or concrete evidence that triggered the documentation need.
2. Name the document that must be updated and explain why.
3. Propose the minimal documentation change in 1 to 3 sentences.
4. If the change introduces a new UI state or workflow, propose a QA test case.
5. Implement the change in the relevant document.

Constraints:
- Be evidence-based. Do not suggest speculative documentation work.
- Keep recommendations modular, concise, contributor-friendly, and onboarding-first.
- Prefer small targeted edits over broad rewrites.
- Keep formatting print-ready and easy to scan.
- If no update is needed for an area, say so briefly.

Return findings in exactly this structure:

#### Required Documentation Updates
- Group by document or feature area.

#### Suggested Additions to QA Testing Guide
- Include manual verification scenarios when relevant.

#### Suggested Additions to UI Use Cases
- Include any new operator workflows, states, or role-dependent behavior.

#### Confidence (High / Medium / Low)
- Give a short reason for the confidence level.
