---
name: Scaffold GitHub Ticket
description: "Draft and create a well-structured ECUBE GitHub issue using gh CLI"
argument-hint: "Describe the bug, feature request, follow-up task, or subsystem to turn into a GitHub ticket"
agent: "agent"
---

Create a GitHub issue in the current ECUBE repository using `gh` CLI.

Use the user argument as the bug report, feature request, problem statement, follow-up work item, or implementation area.

Your job is to:
- understand the requested problem or improvement
- inspect the local workspace when needed for evidence
- write a concise, contributor-friendly issue title
- draft a structured issue body with clear reproduction or acceptance criteria
- create the issue with `gh issue create`
- verify the issue was created successfully and return the issue number and URL

When drafting the issue:
- be evidence-based and avoid speculation
- keep the scope narrow and implementation-ready
- preserve ECUBE terminology such as drives, mounts, jobs, project isolation, audit logs, and chain of custody when relevant
- distinguish clearly between actual behavior and expected behavior
- include acceptance criteria that are testable
- if the request is under-specified, ask a small number of focused questions instead of guessing

Preferred issue body structure for bugs:
- Summary
- Impact
- Steps to Reproduce
- Actual Behavior
- Expected Behavior
- Acceptance Criteria
- Notes (optional)

Preferred issue body structure for enhancements:
- Summary
- Problem or Need
- Proposed Behavior
- Acceptance Criteria
- Notes (optional)

Constraints:
- Use `gh` CLI rather than manually drafting only in chat
- Do not include secrets, credentials, internal paths, or unsafe host details
- Keep wording clear for reviewers, QA, and implementers
- Prefer small follow-up tickets over broad umbrella issues

Return results in exactly this structure:

## Ticket Draft
- Final title
- Short summary of the body sections used

## GitHub Issue Result
- Issue number
- Issue URL

## Notes
- Any assumptions made or clarifications still needed
