# 6. REST API Requirements

| Field | Value |
|---|---|
| Title | REST API Requirements |
| Purpose | Defines normative API behavior, role expectations, constraints, and acceptance criteria for the ECUBE system-layer API. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, product managers, reviewers, and QA teams. |

## 1. Audience and Scope

### 1.1 Primary Audience

- Stakeholders validating that the exposed API supports the ECUBE product scope.
- Auditors verifying access control, traceability, and policy enforcement.
- Product managers reviewing capability coverage and acceptance criteria.
- Test and QA authors deriving validation scenarios from normative behavior.

### 1.2 Scope

- Define required externally visible API capabilities.
- Define authentication and authorization expectations.
- Define required behavioral constraints for privileged and non-privileged operations.
- Define minimum error-handling and auditability expectations.
- Define acceptance criteria for major API capability areas.

### 1.3 Explicit Exclusions

- URL paths and route naming.
- HTTP verb selection.
- Request and response schema shape.
- Serialization format details beyond externally visible behavior.
- Internal algorithms, locking strategies, retry loops, and implementation flow.

---

## 2. Authentication and Access Requirements

### 2.1 Identity Modes

ECUBE shall support the following authentication modes:

- Local host-backed authentication.
- LDAP-backed authentication.
- OIDC-backed authentication.

### 2.2 Authenticated Access Model

- The API shall use bearer-token authentication for protected capabilities.
- Authentication tokens shall carry enough identity and authorization information to support role evaluation and audit attribution.
- Token lifetime shall be configurable.
- Role enforcement shall occur on every protected operation.

### 2.3 Public and Conditionally Protected Capabilities

- Health visibility and version visibility shall be available without prior authentication.
- First-run bootstrap capabilities shall be available before the system is initialized and shall become restricted afterward according to role policy.
- Database provisioning capabilities shall support the setup phase without weakening post-initialization administrative controls.
- Deployment-controlled observability capabilities may be exposed publicly or restricted by deployment policy.

### 2.4 Authorization Outcomes

- Missing, invalid, or expired credentials shall be rejected as unauthenticated access.
- Authenticated callers without sufficient privilege shall be rejected as unauthorized for the requested capability.
- Invalid input values shall be rejected as validation failures.
- Security-relevant denials and failures shall be recorded in the audit log.

### 2.5 Acceptance Criteria

- A protected capability cannot be exercised without valid authentication.
- The same caller receives different outcomes when role membership changes from authorized to unauthorized.
- Pre-initialization bootstrap access narrows after initialization completes.
- Authentication failures are attributable in audit records without exposing secrets.

---

## 3. Role and Capability Requirements

### 3.1 Role Definitions

- `admin`: unrestricted administrative control over ECUBE configuration and privileged operations.
- `manager`: operational control over mounts, drives, and oversight functions.
- `processor`: job creation, execution, and operational monitoring.
- `auditor`: read-only access to audit and integrity-related capabilities.

### 3.2 Capability Allocation

The authorization model shall satisfy the following capability allocation:

| Capability Area | Admin | Manager | Processor | Auditor |
| ---------------- | :---: | :-----: | :-------: | :-----: |
| Role administration | ✔ | ✖ | ✖ | ✖ |
| OS user/group administration | ✔ | ✖ | ✖ | ✖ |
| Mount administration | ✔ | ✔ | ✖ | ✖ |
| Drive lifecycle administration | ✔ | ✔ | ✖ | ✖ |
| Job creation and execution | ✔ | ✔ | ✔ | ✖ |
| Job and drive visibility | ✔ | ✔ | ✔ | ✔ |
| Audit visibility | ✔ | ✔ | ✖ | ✔ |
| Integrity operations | ✔ | ✖ | ✖ | ✔ |
| Diagnostic introspection | ✔ | ✔ | ✔ | role-limited |
| Runtime configuration | ✔ | ✖ | ✖ | ✖ |

### 3.3 Acceptance Criteria

- Each privileged capability area is restricted to the intended role set.
- Auditor access remains read-only and excludes drive, mount, and job mutation capabilities.
- Role administration and runtime configuration remain admin-only.
- Deep diagnostic access is more restrictive than general operational visibility where security sensitivity requires it.

---

## 4. Behavioral Requirements by Capability Area

### 4.1 Health, Readiness, and Version Visibility

- The platform shall expose machine-consumable service health, readiness, and version information.
- Readiness reporting shall reflect critical dependency availability.
- Health visibility shall be sufficient for orchestration, deployment checks, and operational support.

Acceptance criteria:

- Operators can distinguish process liveness from dependency readiness.
- Version information can be retrieved without privileged access.

### 4.2 Bootstrap and Database Provisioning

- The platform shall provide a first-run bootstrap capability for initial system setup.
- Bootstrap shall be single-completion and protected against concurrent completion by multiple workers or requests.
- The platform shall provide a database connection test capability and a database provisioning capability for setup workflows.
- Post-initialization, database administration capabilities shall require administrative privilege.

Acceptance criteria:

- A second successful bootstrap is not possible after initialization completes.
- Database provisioning status is externally observable to setup consumers.
- Administrative database changes are rejected for non-admin callers after initialization.

### 4.3 Mount Management

- The platform shall support mount registration, mount removal, mount listing, and mount validation.
- Mount capabilities shall enforce role restrictions and provide observable failure outcomes when storage is unavailable or invalid.
- Mount-related state exposed through the API shall remain consistent with reconciliation behavior after restart.

Acceptance criteria:

- Authorized operators can create, validate, inspect, and remove mount definitions.
- Unauthorized callers cannot mutate mount state.
- Invalid or unreachable mount targets are surfaced as explicit failures rather than silent success.

### 4.4 Drive Lifecycle Management

- The platform shall expose drive inventory and project-binding status.
- Drive initialization shall enforce project isolation before any write-oriented workflow proceeds.
- Drive formatting shall be restricted to valid lifecycle states and supported filesystem choices.
- Safe-eject preparation shall flush and unmount relevant storage state before the drive is treated as removable.
- If finalized drive semantics are implemented, finalized state shall preserve chain-of-custody expectations and prevent reuse until explicitly reopened according to policy.
- Drive refresh and discovery capabilities shall preserve authoritative state where policy requires it and reconcile stale physical-state assumptions.

Acceptance criteria:

- A drive cannot be rebound across projects without the intended lifecycle transition.
- An operator cannot prepare a drive for eject from an invalid lifecycle state.
- Discovery refresh does not silently defeat project isolation or finalized-state guarantees.

### 4.5 Job Lifecycle Management

- The platform shall support job creation, job start, job verification, manifest regeneration, and job progress and status visibility.
- Job behavior shall preserve attribution for who created and who started work.
- Failed jobs may be restarted only when lifecycle policy permits it.
- Job detail visibility shall support operational monitoring without requiring privileged debug-only access.
- Callback or notification behavior, when configured, shall comply with the security and retry constraints defined elsewhere in the requirements set.

Acceptance criteria:

- Authorized users can observe job progress and terminal outcomes.
- Invalid job state transitions are rejected.
- Job detail views remain available to the intended read-only audiences.

### 4.6 Audit and Integrity Operations

- The platform shall provide audit-log visibility with filtering support.
- The platform shall provide integrity-related capabilities for hashing and comparison.
- Chain-of-custody relevant information shall be retrievable in a form suitable for audit and review.
- Security-relevant and privileged API actions shall emit structured audit records.

Acceptance criteria:

- Auditors can access audit history without mutation privileges.
- Integrity operations are limited to authorized roles.
- Privileged mutations produce corresponding audit evidence.

### 4.7 Introspection and Diagnostic Visibility

- The platform shall provide read-only diagnostic visibility into drives, USB topology, mounts, block devices, job state, and system health.
- Diagnostic capabilities shall be role-limited according to sensitivity.
- Public version visibility shall remain separated from authenticated diagnostic detail.

Acceptance criteria:

- Operational users can inspect system state without receiving mutation capability.
- More sensitive debug detail is withheld from roles that do not require it.

### 4.8 User, Group, and Role Administration

- The platform shall support administration of ECUBE role assignments.
- When local account management is enabled, the platform shall support creation, modification, and deletion of ECUBE-managed OS users and groups.
- Administrative user-management capabilities shall prevent accidental mutation of unrelated host accounts.
- Input constraints for usernames and group names shall follow a documented safe pattern.

Acceptance criteria:

- Role assignments can be created, replaced, listed, and removed by admins only.
- Local user and group operations are unavailable when the active identity mode does not support them.
- Unsafe or reserved account targets are rejected.

### 4.9 Runtime Configuration, Logs, and Telemetry

- The platform shall expose administrative runtime configuration visibility and update capabilities.
- Configuration changes that require process restart shall surface that requirement clearly through the API behavior.
- Log discovery and retrieval capabilities shall support operational support and audit review.
- Telemetry ingestion shall remain separate from privileged administration and shall accept only the intended event class.

Acceptance criteria:

- Non-admin users cannot modify runtime configuration.
- Log visibility follows the intended authenticated access policy.
- Telemetry ingestion does not grant elevated control over the system.

---

## 5. Constraints and Quality Requirements

### 5.1 Error Handling

- API failures shall use a consistent machine-readable error structure.
- Capability areas shall declare and implement the relevant failure classes for validation, authorization, conflict, not-found, infrastructure, and timeout scenarios.
- Error responses shall provide traceability without leaking secrets or unsafe host detail.

### 5.2 Auditability

- Authentication outcomes, authorization denials, privileged mutations, and policy violations shall be audit-logged.
- Audit records shall include sufficient actor and operation context for later review.

### 5.3 Security and Isolation

- Project isolation shall be enforced consistently across drive and job-related operations.
- Administrative capabilities that affect host resources shall honor deployment-mode restrictions.
- Publicly exposed capabilities shall be limited to those explicitly intended for unauthenticated or deployment-controlled use.

### 5.4 Documentation Consistency

- The implemented API surface, published API design documentation, and published API requirements shall remain consistent in capability coverage, authorization expectations, and observable behavior.

### 5.5 Acceptance Criteria

- Reviewers can determine whether an implementation is compliant without relying on route-level design details.
- Auditors can map each privileged capability area to observable control and audit evidence.
- Product review can confirm feature coverage from this document without consulting schemas or endpoint listings.

## References

- [docs/design/06-rest-api-design.md](../design/06-rest-api-design.md)

