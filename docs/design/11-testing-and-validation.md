# 11. Testing and Validation

| Field | Value |
|---|---|
| Title | Testing and Validation |
| Purpose | Defines the quality strategy and validation categories for ECUBE backend, API, OS integration, and hardware-aware workflows. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, QA teams, and technical reviewers. |

## 11.1 Testing Objectives

The ECUBE test strategy exists to prove four things:

- business rules are enforced consistently,
- security boundaries fail closed,
- infrastructure-dependent behaviors remain predictable, and
- recovery behavior is safe after partial failure or restart.

Because ECUBE spans database state, host OS integration, and USB hardware discovery, a single test layer is insufficient.

## 11.2 Validation Layers

### Unit Validation

Unit tests provide fast feedback on route handlers, service logic, schema validation, authorization checks, and state transitions.

Design expectations:

- external dependencies are mocked or simulated,
- SQLite in-memory is used for fast repository and route validation where appropriate,
- unit coverage should exercise failure handling as aggressively as happy paths.

### Integration Validation

Integration tests validate interactions across real infrastructure boundaries that unit tests intentionally abstract away.

This includes:

- PostgreSQL behavior and migration compatibility,
- transaction and concurrency semantics,
- repository behavior under real locking and constraint rules,
- startup and reconciliation flows that depend on database-backed coordination.

### Hardware-in-the-Loop Validation

Hardware-in-the-loop validation exists because parts of the ECUBE domain depend on physical USB topology, host discovery behavior, and privileged device access that cannot be fully trusted when mocked.

These tests validate:

- USB discovery against real hubs and devices,
- port and hub metadata behavior,
- end-to-end drive lifecycle flows under real hardware conditions.

## 11.3 Risk-Focused Coverage Areas

The most important design-level coverage areas are:

- **Drive eject safety:** partition discovery, mount parsing, nested unmount ordering, encrypted volume handling, and partial failure behavior.
- **Filesystem detection and formatting:** supported filesystem recognition, unformatted-drive detection, precondition enforcement, and audit behavior around formatting failures.
- **OS user and group management:** namespace isolation, compensation on partial failure, password validation, and local-only endpoint gating.
- **Role resolution and OIDC:** deny-by-default semantics, provider-specific group mapping, token validation, and error translation.
- **Initialization and reconciliation:** first-run setup guards, stale lock reclaim, idempotent startup correction, and recovery from interrupted work.
- **Concurrency behavior:** conflict detection and correct surfacing of lock contention or uniqueness violations.

## 11.4 Quality Principles

The test architecture should follow these principles:

- **Layer fidelity:** test each behavior at the lowest useful layer, then confirm critical cross-boundary flows with integration or HIL coverage.
- **Fail-closed verification:** authentication, authorization, and setup/database guardrails must be tested primarily through negative cases.
- **Portability:** default automated test coverage should not depend on special hardware or privileged host configuration.
- **Idempotence awareness:** reconciliation and discovery tests should confirm repeat runs do not create unintended state changes.
- **Auditability:** security-relevant and state-correcting operations should be validated not only for outcome but also for emitted audit records.

## 11.5 Acceptance Expectations

At the design level, ECUBE is considered adequately validated when:

- unit validation covers the core domain and security rules,
- integration validation confirms real database and migration behavior,
- hardware-aware features have a separate HIL path for physical verification,
- concurrency and restart recovery behavior are explicitly tested,
- critical failure modes are exercised and shown to degrade safely.

Operational readiness validation should explicitly cover health signaling, readiness gating under dependency failure, metrics and telemetry correctness, structured logging correlation, and alert-triggering behavior under realistic fault conditions.

## 11.6 Related Documents

- `docs/design/04-functional-design.md`
- `docs/design/05-data-model.md`
- `docs/design/10-security-and-access-control.md`
- `docs/testing/`

## References

- [docs/testing/01-automated-test-requirements.md](../testing/01-automated-test-requirements.md)
- [docs/testing/02-automated-test-runbook.md](../testing/02-automated-test-runbook.md)
