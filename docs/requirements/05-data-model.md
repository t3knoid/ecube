# 5. Data Model Requirements

| Field | Value |
|---|---|
| Title | Data Model Requirements |
| Purpose | Defines what ECUBE data must represent, including the meaning, constraints, lifecycle expectations, and acceptance criteria for core data domains. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, product managers, reviewers, and QA teams. |

## 5.1 Audience and Scope

### 5.1.1 Primary Audience

- Stakeholders validating that ECUBE records the right operational and compliance information.
- Auditors verifying traceability, policy enforcement, and data retention expectations.
- Product managers reviewing whether the model supports the required product behavior.
- QA and review teams deriving validation criteria from the required meaning of the data.

### 5.1.2 Scope

- Define the business meaning of the core data domains.
- Define the constraints and invariants the data must satisfy.
- Define the lifecycle expectations for key records and stateful entities.
- Define acceptance criteria for whether the model adequately represents required system behavior.

### 5.1.3 Explicit Exclusions

- Table and column definitions.
- Storage engine choices.
- Field types, enum encodings, and JSON layout.
- Indexes, foreign keys, and ORM-level structure.

## 5.2 Hardware and Topology Representation Requirements

ECUBE data must represent the managed USB topology in a way that allows the system to distinguish hubs, ports, and drives across discovery cycles.

The data must:

- Represent hubs as stable physical topology anchors.
- Represent ports as operator-visible attachment points that can carry policy and labeling state.
- Represent drives as distinct managed media with stable identity across reconnects when the underlying platform can provide that identity.
- Preserve the relationship between a drive and its most recently associated physical location when that information is available.
- Preserve operator-assigned labels and location hints independently from transient device presence.

Constraints:

- Hub, port, and drive identity must remain stable enough to support reconciliation and audit review.
- Absence of a currently attached device must not erase operator-managed topology metadata.
- Policy state associated with a port must influence the operational treatment of attached drives.

Acceptance criteria:

- Operators can distinguish the physical location context of a managed drive when topology data is available.
- Reconciliation can associate rediscovered hardware with previously known managed entities.

## 5.3 Drive Representation Requirements

Drive data must represent all information necessary to manage evidence export media safely and audibly.

The data must represent:

- Stable drive identity.
- Current lifecycle state.
- Current project binding, if any.
- Current filesystem classification.
- Capacity and visibility-related properties needed for operations.
- Recent presence or observation history sufficient to support reconciliation.
- Security-relevant status information such as encryption-related visibility when that information is available.

Lifecycle requirements:

- Drive state must change in ways that preserve an auditable lifecycle.
- Project binding must persist across temporary removal and reinsertion unless an explicit reset or lifecycle transition changes it.
- Finalize behavior must transition drive lifecycle state from `IN_USE` to `AVAILABLE` without clearing project binding.

Constraints:

- A drive cannot simultaneously represent mutually incompatible lifecycle meanings.
- Filesystem classification must distinguish recognized media from unknown or unformatted media.

Acceptance criteria:

- Reviewers can determine from stored drive data whether the media is writable, in use, or absent.
- Reviewers can determine whether a drive remains bound to a project after temporary removal.

## 5.4 Mount Representation Requirements

ECUBE data must represent managed source mounts and their operational availability.

The data must:

- Distinguish supported mount protocols.
- Represent the remote source being referenced.
- Represent the system’s current view of mount usability and health.
- Preserve enough recent validation context to support operational troubleshooting.

Constraints:

- Mount data must distinguish configured intent from current operational health.
- A mount that is configured but currently unusable must remain representable as such rather than disappearing from the system view.

Acceptance criteria:

- Operators can determine which source mounts are configured and whether they are usable.
- Reconciliation and validation workflows can surface stale or failed mounts without losing configuration intent.

## 5.5 Job and File Representation Requirements

ECUBE data must represent export jobs and per-file outcomes in a way that supports operations, audit review, retry behavior, and manifest generation.

Job-level meaning must include:

- Project and evidence attribution.
- Source context.
- Assigned target context.
- Current lifecycle status.
- Aggregate progress.
- Timing and operator attribution.
- Completion and failure context.

File-level meaning must include:

- File identity relative to the export set.
- Size and integrity outcome when available.
- Current processing result.
- Failure context and retry history where applicable.

Constraints:

- Job progress must remain meaningful throughout execution and after completion.
- File-level outcomes must not be collapsed into a single aggregate status that hides partial failure.
- Restart or retry behavior must not destroy previously recorded outcome history needed for audit or operations.

Acceptance criteria:

- Reviewers can determine who created and started a job, what project it belongs to, and how it concluded.
- Reviewers can distinguish fully successful jobs from partially failing jobs.
- Operators can inspect per-file outcomes without losing job-level context.

## 5.6 Manifest Representation Requirements

ECUBE data must represent generated manifests as auditable export artifacts.

The data must:

- Preserve the relationship between a manifest and the export activity it describes.
- Preserve enough metadata to identify when the manifest was produced.
- Distinguish manifest artifacts from the exported evidence data itself.

Constraints:

- Manifest records must remain attributable to the corresponding export context.
- Regenerated manifests must remain distinguishable as separate auditable outputs when policy allows regeneration.

Acceptance criteria:

- Reviewers can determine whether a manifest exists for a given export context.
- Manifest history remains reviewable when regeneration occurs.

## 5.7 Assignment History Requirements

ECUBE data must represent the historical relationship between drives and export work over time.

The data must:

- Preserve when a drive was associated with a job or export activity.
- Preserve when that association ended, if applicable.
- Support review of reuse or repeated assignment across multiple export activities.

Constraints:

- Historical assignment records must survive after the active assignment ends.
- Assignment history must support chronology review for audit and operational reconstruction.

Acceptance criteria:

- Auditors can reconstruct which drive was used for which job and in what sequence.

## 5.8 Audit Record Requirements

ECUBE data must represent audit history as append-only operational evidence.

Audit data must represent:

- Actor identity when available.
- Action or event identity.
- Time of occurrence.
- Relevant subject context such as drive, job, project, or system action.
- Outcome and supporting detail sufficient for later review.
- Request-origin context where relevant to security or operations.

Constraints:

- Audit records must not be silently overwritten by later events.
- Audit records must capture both successful privileged actions and denied or failed security-relevant actions.
- Audit detail must be sufficient for review without requiring inference from unrelated records.

Acceptance criteria:

- Auditors can reconstruct a privileged action and its outcome from the audit trail.
- Security denials and policy violations appear as explicit auditable events.

## 5.9 Role and Authorization Representation Requirements

ECUBE data must represent explicit authorization assignments independently from authentication source data.

The data must:

- Represent explicit role assignments for known identities.
- Prevent duplicate effective assignments of the same role to the same identity.
- Support administrative override of fallback or externally derived authorization.
- Preserve a clear distinction between authentication identity and ECUBE authorization state.

Constraints:

- Authorization data must not require ECUBE to own password or identity-provider data.
- Removing an explicit role assignment must allow the system to fall back to other approved authorization sources where policy permits.

Acceptance criteria:

- Reviewers can determine whether a user has explicit ECUBE-managed roles.
- Duplicate explicit role assignments for the same identity are not possible.

## 5.10 System Guard and Lifecycle Control Requirements

ECUBE data must represent one-time and singleton coordination state needed for safe lifecycle control.

The data must:

- Represent whether first-run initialization has occurred.
- Represent which actor performed initialization and when it occurred.
- Represent exclusive control state for reconciliation or other singleton startup activities when required.

Constraints:

- Initialization state must support prevention of repeated successful first-run completion.
- Singleton coordination state must support safe recovery and review when a prior holder fails unexpectedly.

Acceptance criteria:

- Reviewers can determine whether initialization has already completed and by whom.
- Operators can determine whether reconciliation control was previously held and whether recovery is needed.

## 5.11 Cross-Domain Constraints

The overall data model must satisfy these cross-domain requirements:

- Project-related data must remain consistent across drive, job, manifest, and audit contexts.
- Lifecycle data must support restart reconciliation without losing authoritative meaning.
- Data needed for operational support and audit review must remain available even after active work has ended.
- The represented meaning of the data must remain consistent with the functional and API requirements documents.

Acceptance criteria:

- Reviewers can trace a project-bound export across drive state, job state, manifest output, and audit evidence.
- Temporary infrastructure interruptions do not erase the system’s authoritative understanding of prior work.
## References

- [docs/design/05-data-model.md](../design/05-data-model.md)