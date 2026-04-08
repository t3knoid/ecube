# 17. Turnkey Appliance Requirements

| Field | Value |
|---|---|
| Title | Turnkey Appliance Requirements |
| Purpose | Defines what ECUBE turnkey appliance tiers must provide in capability, constraint, performance, and lifecycle terms for product, compliance, and operational readiness. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, product managers, reviewers, and QA teams. |

## 17.1 Audience and Scope

### 17.1.1 Primary Audience

- Stakeholders validating that turnkey appliance tiers support required product outcomes.
- Auditors validating isolation, integrity, traceability, and operational control expectations.
- Product managers validating tier differentiation and readiness criteria.
- QA and review teams deriving acceptance and regression scenarios.

### 17.1.2 Scope

- Define required turnkey appliance tiers and the outcomes each tier must support.
- Define hardware capability and isolation requirements for removable-media export workflows.
- Define constraints for reliability, safety, operability, and maintainability.
- Define performance and stability expectations under representative workloads.
- Define lifecycle expectations from manufacturing qualification through in-service operation and replacement.

### 17.1.3 Explicit Exclusions

- Specific component models, vendor SKUs, and board part numbers.
- Detailed PCIe lane maps, wiring diagrams, thermal schematics, and fabrication instructions.
- Manufacturing process instructions and assembly work-order details.
- Business-pricing rationale, user stories, or go-to-market justification.

## 17.2 Tier Capability Requirements

The system shall provide at least three turnkey appliance tiers with increasing export-capacity and concurrency envelopes.

Tier requirements:

- A baseline tier shall support four concurrently addressable export ports.
- A mid tier shall support eight concurrently addressable export ports.
- A high tier shall support twelve concurrently addressable export ports.
- Each tier shall preserve deterministic physical-to-logical port identity.
- Tier scaling shall not weaken project isolation controls or auditability expectations.

Acceptance criteria:

- Tier labeling and capacity claims are testable and verifiable in qualification runs.
- Port identity remains stable and unambiguous across insertion, removal, and restart events.

## 17.3 Isolation and Safety Requirements

Turnkey appliances shall maintain safe failure domains and isolation behavior across removable-media operations.

The appliance shall:

- Prevent cross-port ambiguity that could cause media assignment to an incorrect logical port.
- Preserve project isolation under concurrent copy and verify workflows.
- Ensure controller/path contention or failure in one domain does not silently remap active media in another domain.
- Surface degraded states in a way that permits safe operator action and audit review.

Constraints:

- Isolation behavior shall be defined in measurable terms and validated in QA.
- Degraded hardware states shall fail safe rather than proceed with ambiguous media identity.

Acceptance criteria:

- Fault-injection and contention tests demonstrate containment and deterministic recovery behavior.
- No verified test case permits silent cross-project contamination through hardware-state ambiguity.

## 17.4 Performance and Stability Requirements

Turnkey appliances shall sustain representative ECUBE workloads without recurring hardware-induced job failure.

Performance requirements:

- Support sustained copy and verification throughput for the advertised tier capacity.
- Maintain acceptable operator responsiveness during concurrent active jobs.
- Avoid persistent thermal or resource-driven throttling that invalidates operational expectations.
- Recover from transient pressure without compromising data-integrity outcomes.

Acceptance criteria:

- Load and soak testing demonstrates stable behavior at tier-appropriate concurrency.
- Repeated workload cycles do not produce an unresolved pattern of hardware-induced job failure.

## 17.5 Reliability and Operability Constraints

Turnkey appliances shall be buildable, serviceable, and operable as controlled production units.

The appliance shall:

- Use hardware classes suitable for appliance-grade continuous operation.
- Support observability sufficient for diagnosing thermal, I/O, and media-state degradation.
- Support controlled startup and restart behavior that preserves authoritative media-state understanding.
- Support replacement of failed field components without invalidating historical evidence records.

Constraints:

- Operational maintenance shall not require undocumented, ad-hoc procedures.
- Hardware changes shall require controlled revalidation prior to production reuse.

Acceptance criteria:

- Qualification and requalification evidence is available for each supported tier profile.
- Service and replacement operations preserve chain-of-custody and audit continuity.

## 17.6 Manufacturing and QA Requirements

Turnkey appliances shall have verifiable build and validation gates.

Manufacturing requirements:

- Each produced unit shall map to a declared tier profile.
- Build records shall retain tier identity and qualification evidence.
- Physical labeling shall support deterministic mapping between external ports and logical identities.

QA requirements:

- Validation shall include sustained load, hot-plug behavior, recovery, and stability checks.
- Validation shall include tests for isolation under contention and fault scenarios.
- Validation evidence shall be reproducible and reviewable by compliance and audit stakeholders.

Acceptance criteria:

- Release readiness requires passing manufacturing and QA gates for the applicable tier profile.
- Validation artifacts are sufficient for audit and operational handoff.

## 17.7 Lifecycle Requirements

Turnkey appliance support shall include introduction, change, and retirement controls.

Lifecycle requirements:

- New tier profiles shall be introducible through controlled qualification.
- Tier revisions shall preserve backward operational compatibility expectations where declared.
- Component substitutions within a tier shall require documented equivalence validation.
- End-of-life transitions shall preserve supportability and evidence-system integrity expectations.

Acceptance criteria:

- Tier lifecycle changes are governed by documented qualification and approval records.
- Lifecycle transitions do not break compliance-critical workflows.

## 17.8 References

- [docs/design/17-turnkey-appliance-design.md](../design/17-turnkey-appliance-design.md)
- [docs/requirements/02-hardware-requirements.md](02-hardware-requirements.md)
- [docs/design/02-hardware-design.md](../design/02-hardware-design.md)
