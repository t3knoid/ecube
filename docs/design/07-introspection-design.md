# 7. Introspection Design — Design

## Design Goal

This document defines the design intent for ECUBE introspection capabilities as a companion to the REST API specification. It focuses on diagnostic scope, safety boundaries, and read-only behavior rather than the full endpoint contract.

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
