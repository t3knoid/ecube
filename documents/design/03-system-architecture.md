# 3. System Architecture — Design

## Component View

- **UI Layer (untrusted):** Displays status, submits requests, never talks directly to DB/hardware.
- **System Layer (trusted):** Enforces policy, executes mounts/copies, writes audit logs.
- **PostgreSQL 14+ (private):** Stores source-of-truth state for jobs, drives, assignments, and logs.

## Interaction Pattern

1. UI calls authenticated API endpoint.
2. System layer validates authorization and project isolation.
3. System layer performs operation and persists transaction.
4. Response includes normalized state for UI rendering.

## Security Design

- DB reachable only from system-layer network segment.
- Hardware access scoped to system-layer process user/group.
- API endpoints validate project ownership and allowed transitions.
