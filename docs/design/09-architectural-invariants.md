# 9. Architectural Invariants — Design

| Field | Value |
|---|---|
| Title | Architectural Invariants |
| Purpose | Consolidates the cross-cutting design guarantees that emerge from the architecture, functional rules, security model, and deployment assumptions. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, maintainers, and technical reviewers. |

## Guaranteed by Design

This document is a synthesis layer for the design set. It consolidates the cross-cutting guarantees that emerge from the architecture, functional rules, security model, and deployment assumptions without redefining those subjects in full.

- Project isolation is enforced at drive initialization and copy authorization.
- Multi-threaded copying is controlled by bounded worker pools and tracked state.
- NFS/SMB mounts are lifecycle-managed with validation and safe unmounting.
- UI remains isolated from direct hardware and database access.
- System layer acts as the sole trusted enforcement point.
- Hardware introspection endpoints provide safe, read-only diagnostics.
- Every critical operation generates immutable audit records.
- After a restart, startup reconciliation automatically corrects stale mount states, fails interrupted jobs, and re-syncs USB drive presence — no manual recovery needed.
- In multi-worker deployments, a cross-process lock ensures only one worker runs startup reconciliation, preventing duplicate audit rows and race conditions.

## References

- [docs/design/03-system-architecture.md](03-system-architecture.md)
- [docs/design/04-functional-design.md](04-functional-design.md)
- [docs/design/10-security-and-access-control.md](10-security-and-access-control.md)
