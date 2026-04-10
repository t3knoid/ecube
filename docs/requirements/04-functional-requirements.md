# 4. Functional Requirements

| Field | Value |
|---|---|
| Title | Functional Requirements |
| Purpose | Defines what ECUBE must do at the functional level, covering required behavior, constraints, and acceptance criteria. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, product managers, reviewers, and QA teams. |

## 4.1 Audience and Scope

### 4.1.1 Primary Audience

- Stakeholders validating functional capability coverage.
- Auditors verifying policy enforcement and traceability.
- Product managers reviewing expected behavior and acceptance criteria.
- QA and test authors deriving scenario coverage from normative requirements.

### 4.1.2 Scope

- Define required functional behavior for drive lifecycle, project isolation, job handling, copy operations, mounts, manifests, auditability, and discovery behavior.
- Define operational constraints and policy rules that implementations must satisfy.
- Define acceptance criteria that allow reviewers to determine whether the product behavior is compliant.

### 4.1.3 Explicit Exclusions

- API route definitions, HTTP verbs, and URL design.
- Internal service boundaries and module structure.
- Algorithms, OS command sequencing, or concurrency-control implementation details.
- Concrete request and response schemas.

## 4.2 Drive Lifecycle Requirements

ECUBE must:

- Detect drive insertion and removal.
- Determine and persist the current lifecycle state of each managed drive.
- Detect and retain the current filesystem classification for each managed drive.
- Support operator-initiated formatting when policy and lifecycle state allow it.
- Support drive initialization for a project-bound workflow.
- Support safe operational removal of a drive without implying export completion.
- Preserve sufficient drive history to support audit and operational review.

Managed drive states must include:

- `EMPTY`
- `AVAILABLE`
- `IN_USE`

State constraints:

- `AVAILABLE` means the drive is eligible for initialization or assignment.
- `IN_USE` means the drive is actively participating in a write-capable workflow.
- Illegal lifecycle transitions must be rejected.

### 4.2.1 Filesystem Detection Requirements

On insertion and rediscovery, ECUBE must:

- Detect the drive filesystem type when possible.
- Record the current filesystem classification as part of the drive’s visible state.
- Distinguish recognizable filesystems from unformatted or unknown media.
- Refresh the classification after formatting or rediscovery.

Acceptance criteria:

- A newly inserted or rediscovered drive exposes a current filesystem classification.
- A reformatted drive exposes the updated classification after successful completion.

### 4.2.2 Drive Formatting Requirements

Formatting behavior must satisfy all of the following:

- Formatting is only permitted from an eligible writable lifecycle state.
- Formatting is rejected when the drive is not safe to format.
- Only supported filesystem targets are accepted.
- Successful formatting updates the exposed filesystem classification.
- Successful and failed formatting attempts are audit-logged with actor, drive, and outcome context.

Acceptance criteria:

- An ineligible drive cannot be formatted.
- An unsupported filesystem target is rejected.
- Successful formatting changes the reported filesystem classification.

### 4.2.3 Prepare-Eject (Safe Removal) Requirements

Drive prepare-eject behavior is the safe-removal capability. It must:

- Flush pending writes and unmount all partitions belonging to the device.
- Transition the drive from `IN_USE` to `AVAILABLE`.
- Not imply export completion, write sealing, or custody transfer.
- Not clear `current_project_id`; the drive remains bound to its project.
- Emit an audit event recording the actor, drive, and outcome.
- Reject the operation if the drive is not in `IN_USE` state.

Acceptance criteria:

- After a successful prepare-eject, the drive is in `AVAILABLE` state and retains its `current_project_id`.
- A prepare-eject attempt on a drive not in `IN_USE` is rejected with an appropriate error.
- All prepare-eject attempts (successful and failed) are audit-logged.

## 4.3 Project Isolation Requirements

To prevent evidence contamination:

- Each writable drive workflow must be bound to a single project context.
- A drive must not accept writes for a different project than the one to which it is currently bound.
- Cross-project write attempts must be blocked before data movement begins.
- Each denial must produce audit evidence.
- The active project association of in-use drives must remain visible to operators.

Acceptance criteria:

- A drive already bound to one project cannot be used for a different project without the required lifecycle change.
- Cross-project write attempts leave no partial copied data attributable to the rejected action.

## 4.4 Job Management Requirements

ECUBE must support job workflows that include:

- Source selection from supported storage sources.
- Evidence and project attribution.
- Drive assignment.
- Copy progress tracking.
- Per-file outcome visibility.
- Verification behavior.
- Manifest generation.

Assignment constraints:

- Only drives in an eligible writable state may be assigned to new work.

Acceptance criteria:

- Authorized users can create, start, monitor, and complete job workflows.
- Invalid job or drive state combinations are rejected.
- Job history preserves attribution and progress visibility needed for operations and audit.

## 4.5 Copy Engine Requirements

ECUBE must support copy behavior with all of the following characteristics:

- Parallelized copying with operator-configurable concurrency limits.
- Resume-oriented behavior when recoverable file-level failures occur.
- Per-file status tracking.
- Integrity verification of copied data.
- Reliable progress reporting throughout execution.

Constraints:

- Copy status updates must remain consistent under concurrent work.
- File failures must not erase successful-file history.
- Verification outcomes must remain attributable to the corresponding job and drive context.

Acceptance criteria:

- A partially failing copy job exposes both successful and failed file outcomes.
- Progress visibility remains available while work is ongoing.
- Verification results can be reviewed after copy completion.

## 4.6 Network Mount Requirements

ECUBE must support managed source access for at least:

- NFS
- SMB/CIFS

Mount-related behavior must include:

- Registration of usable mount sources.
- Removal of mount sources.
- Visibility into configured mount sources.
- Validation of mount accessibility before operational use.

Acceptance criteria:

- Operators can determine whether a configured mount is usable before starting a job.
- Invalid or unavailable mounts are surfaced explicitly rather than silently ignored.

## 4.7 Manifest Requirements

ECUBE must generate a manifest suitable for export review and audit.

Manifest content must include at least:

- Evidence identifier or equivalent case reference.
- Project-related metadata.
- Source context.
- File-level integrity information.
- Aggregate size or volume summary.
- Generation timestamp.

Acceptance criteria:

- A completed export can be accompanied by a manifest containing the required audit-relevant content.
- Manifest regeneration, when permitted, produces auditable output.

## 4.8 Audit Logging Requirements

The system must emit audit records for security-relevant and operationally significant events, including at minimum:

- Drive initialization.
- Drive prepare-eject (safe-removal) success and failure.
- Job creation and job state changes.
- Copy execution outcomes.
- Manifest generation.
- Mount administration and validation outcomes.
- Project isolation violations.

Constraints:

- Audit evidence must include enough context to identify actor, target, action, and outcome.
- Audit logging must cover both successful privileged actions and policy denials.

Acceptance criteria:

- Reviewers can trace major operational and policy events through the audit record.
- A denied cross-project action produces explicit audit evidence.

### 4.8.1 Chain-of-Custody Report Requirements

- The system must provide chain-of-custody report retrieval by `drive_id` and by `project_id`.
- Drive-based query must be the default mode.
- Access to chain-of-custody reports must be restricted to the same roles that can read audit reports.
- Authorized users must be able to print or save chain-of-custody reports from the UI.
- `delivery_time` must represent physical custody handoff time, not technical drive prepare-eject time.
- Drive prepare-eject and custody delivery must be modeled as separate events.
- The UI must prompt an authorized user to confirm handoff details (`possessor`, `delivery_time`) before CoC is considered complete.

Acceptance criteria:

- A valid drive-based request returns a chain-of-custody report.
- A valid project-based request returns a chain-of-custody report.
- CoC report access is denied for roles that cannot read audit reports.
- Printed/saved CoC output includes custody actors and timestamps.
- A prepare-eject event without handoff confirmation does not populate `delivery_time`.

## 4.9 Discovery and Reconciliation Requirements

Discovery and refresh behavior must preserve protected drive states and policy guarantees:

- Reconnected eligible drives may return to an available state when policy permits.
- Removed drives may leave the available set when no longer present or when policy disables their port.
- In-use drives must not be demoted by discovery while project isolation remains active.

Acceptance criteria:

- Discovery refresh does not silently defeat project isolation.

## References

- [docs/design/04-functional-design.md](../design/04-functional-design.md)
