---
name: Sync Postman Collection
description: "Sync the ECUBE Postman collection with the current FastAPI API, auth flow, and smoke-test coverage"
argument-hint: "Optional focus area, endpoint group, ticket, or PR context"
agent: "agent"
---

Review the current ECUBE API and synchronize the Postman collection with the real application behavior.

Primary target:
- [postman/ecube-postman-collection.json](../../postman/ecube-postman-collection.json)

Supporting evidence sources:
- [app/routers](../../app/routers)
- [app/schemas](../../app/schemas)
- [app/services](../../app/services)
- [tests](../../tests)
- [scripts/run_newman_smoke.sh](../../scripts/run_newman_smoke.sh)
- [docs/testing/07-newman-local.md](../../docs/testing/07-newman-local.md)

Task:
- Inspect the current API routes, request bodies, auth behavior, role gating, and stable response expectations.
- Compare them against the existing Postman folders, requests, variables, saved tests, and example payloads.
- Update the collection so it matches the real API without inventing undocumented endpoints or speculative fields.

Focus areas:
- route and method accuracy
- folder organization and naming
- auth and token handling
- request body shape and required fields
- path/query parameters
- stable response assertions and status codes
- variables such as base URL, token, job IDs, drive IDs, mount IDs, and filenames
- Newman smoke coverage and any curated smoke folders still expected by the repo

Rules:
- Be evidence-based and use the current code and tests as the source of truth.
- Preserve ECUBE security boundaries, role expectations, and redaction behavior.
- Prefer minimal targeted edits over broad rewrites.
- Keep the collection valid JSON and maintain readable formatting.
- If you find related drift in the Newman smoke script or Newman docs, update them only when required by the same verified API change.
- Do not change unrelated examples or naming just for style.

Validation:
- After edits, verify the collection is still valid JSON.
- Where practical, run the relevant Newman smoke subset or other focused checks.
- Report any endpoints that still need manual follow-up because the API behavior is ambiguous or environment-dependent.

Return results in exactly this structure:

#### Postman Collection Updates
- List each request or folder updated and why.

#### Validation Performed
- Include any JSON validation, smoke checks, or route comparisons.

#### Remaining Gaps or Follow-Ups
- Note only evidence-based follow-ups.

#### Confidence (High / Medium / Low)
- Give a short reason for the confidence level.
