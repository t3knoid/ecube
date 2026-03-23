# 9. Summary of Key Guarantees — Design

## Guaranteed by Design

- Project isolation is enforced at drive initialization and copy authorization.
- Multi-threaded copying is controlled by bounded worker pools and tracked state.
- NFS/SMB mounts are lifecycle-managed with validation and safe unmounting.
- UI remains isolated from direct hardware and database access.
- System layer acts as the sole trusted enforcement point.
- Hardware introspection endpoints provide safe, read-only diagnostics.
- Every critical operation generates immutable audit records.
- After a restart, startup reconciliation automatically corrects stale mount states, fails interrupted jobs, and re-syncs USB drive presence — no manual recovery needed.
- In multi-worker deployments, a cross-process lock ensures only one worker runs startup reconciliation, preventing duplicate audit rows and race conditions.
