# 1. Purpose and Scope — Design

| Field | Value |
|---|---|
| Title | Purpose and Scope |
| Purpose | Describes the architectural scope and design intent behind ECUBE as a controlled, trusted export system. |
| Updated on | 04/08/26 |
| Audience | Engineers, implementers, maintainers, and technical reviewers. |

## Design Intent

ECUBE is designed as a controlled export system where all privileged operations are centralized in a trusted system layer. The UI remains stateless relative to hardware and database internals.

## Architectural Scope

- A Linux-hosted service orchestrates mounts, USB state, and export jobs.
- A REST API provides controlled actions for UI and integrations.
- Evidence export flows are modeled as auditable, stateful jobs.

## Non-Functional Design Goals

- High reliability for long-running copy tasks
- Strict isolation between project data domains
- End-to-end traceability of operator and system actions
- Safe handling of removable encrypted media

## References

- [docs/requirements/01-purpose-and-scope.md](../requirements/01-purpose-and-scope.md)
