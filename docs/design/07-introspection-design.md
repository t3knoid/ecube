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

## Design Guardrails

- Read-only responses only.
- Restrict to authorized administrative roles.
- Redact sensitive path or credential-like fields from output payloads.

## References

- [docs/design/06-rest-api-design.md](06-rest-api-design.md)
