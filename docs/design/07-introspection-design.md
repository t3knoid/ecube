# 7. Introspection Design

| Field | Value |
|---|---|
| Title | Introspection Design |
| Purpose | Defines the design intent for ECUBE introspection capabilities, focusing on diagnostic scope, safety boundaries, and read-only behavior. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, maintainers, and technical reviewers. |

## Endpoint Design

- `GET /introspection/usb/topology`: derive hub/port/device graph from persisted mapping + live probe.
- `GET /introspection/block-devices`: include capacity, fs type, mount state, encryption indicators.
- `GET /introspection/mounts`: report active mount table and ECUBE-managed entries.
- `GET /introspection/system-health`: aggregate CPU/memory/disk and queue depth.
- `GET /introspection/jobs/{job_id}/debug`: expose worker states, retries, and pending queue details.
- `GET /admin/logs/view`: view recent application log lines with filtering, pagination, and automatic sensitive-value redaction.

## Design Guardrails

- Read-only responses only.
- Restrict to authorized administrative roles.
- Redact sensitive path or credential-like fields from output payloads.
- Sensitive values in application logs must be automatically redacted before serialization (passwords, tokens, API keys, authorization headers).
- Large files must be handled efficiently via pagination and tail-reading (no full-file memory load).

## Audit and Accountability

Log viewing operations must emit audit events:

- `LOG_LINES_VIEWED` — Successful log access (includes source, offset, limit, lines returned)
- `LOG_LINES_VIEW_DENIED` — Access denied (includes source, actor, denial reason)

These events enable administrators to track who accessed application diagnostics and maintain compliance with audit and chain-of-custody requirements.

## References

- [docs/design/06-rest-api-design.md](06-rest-api-design.md)
- [docs/design/04-functional-design.md](04-functional-design.md)
