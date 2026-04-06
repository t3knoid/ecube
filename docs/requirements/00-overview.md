# ECUBE — Requirements Specification

## Specification Structure

ECUBE requirements are organized into two layers:

- **Requirements** (this folder) — specify **WHAT** the system must do: features, behaviors, guarantees, and role model.
- **Design** (docs/design/) — specify **HOW** to implement those requirements: architecture, interfaces, patterns, platforms, and runtime assumptions.

This dual-layer organization ensures requirements remain stable and platform-independent while design documents can evolve with implementation experience.

## Document Index (Requirements Layer)

1. `01-purpose-and-scope.md` — Intent, scope boundaries, and non-functional goals
2. `02-hardware-requirements.md` — Physical host and USB hardware requirements
3. `04-functional-requirements.md` — System behaviors, state transitions, and concurrency guarantees
4. `05-data-model.md` — Persistence schema, tables, fields, and integrity constraints
5. `06-rest-api-specification.md` — API endpoint contracts, role matrix, and response semantics
6. `10-security-and-access-control.md` — Identity model, role definitions, and authorization matrix

## Reading Path

1. Start with `01` and `02` to understand scope and hardware context.
2. Read `04` for functional behaviors and workflows.
3. Consult `05` and `06` for schema and API contract details.
4. Review `10` for role model and access control requirements.

## Cross-Reference to Design

For implementation details, architecture decisions, and platform-specific patterns, see [docs/design/](../design/00-overview.md):

- Design `01–03` — Purpose, hardware assumptions, and trust boundary architecture
- Design `04–07` — Behavioral design, data modeling approach, API implementation, and introspection safety
- Design `08–10` — Language/framework choices, architectural invariants, and security implementation
- Design `11–16` — Quality, runtime environment, build/deployment, and frontend architecture

Every requirements document has a corresponding design document with the same number, providing the implementation perspective.
