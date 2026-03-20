# 7. Low-Level Introspection API — Design

## Design Goal

Expose diagnostic information without bypassing security boundaries or mutating system state.

## Endpoint Design

- `GET /introspection/usb/topology`: derive hub/port/device graph from persisted mapping + live probe.
- `GET /introspection/block-devices`: include capacity, fs type, mount state, encryption indicators.
- `GET /introspection/mounts`: report active mount table and ECUBE-managed entries.
- `GET /introspection/system-health`: aggregate CPU/memory/disk and queue depth.
- `GET /introspection/jobs/{id}/debug`: expose worker states, retries, and pending queue details.

## Operational Guardrails

- Read-only responses only.
- Restrict to authorized administrative roles.
- Redact sensitive path or credential-like fields from output payloads.
