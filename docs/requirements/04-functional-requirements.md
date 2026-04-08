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
- Support explicit drive finalization when export handling is complete.
- Support an explicitly audited reopen of a finalized drive when additional export work is required.
- Preserve sufficient drive history to support audit and operational review.

Managed drive states must include:

- `EMPTY`
- `AVAILABLE`
- `IN_USE`
- `FINALIZED`

State constraints:

- `AVAILABLE` means the drive is eligible for initialization or assignment.
- `IN_USE` means the drive is actively participating in a write-capable workflow.
- `FINALIZED` means the drive is logically sealed against further writes until explicitly reopened.
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

### 4.2.3 Prepare-Eject, Finalize, and Reopen Requirements

ECUBE must distinguish operational safe removal from custody finalization.

Prepare-eject requirements:

- Safe-removal preparation must flush pending writes and leave the drive in a removable, non-writing state.
- Safe-removal preparation must not imply export completion or write sealing.
- Safe-removal preparation must not clear project binding.

Finalization requirements:

- Finalization must be a distinct capability from safe-removal preparation.
- Finalization must transition the drive to `FINALIZED`.
- Finalization must only be allowed for project-bound drives.
- Finalization must be rejected while active work still depends on the drive.
- If the drive is not already safely removable, finalization must include the behavior required to make it safely removable before the finalized state is committed.
- Finalization must produce dedicated audit evidence including actor, drive, project, and finalization context.
- Finalized drives must not become eligible for new writes, reinitialization, formatting, or implicit return to active use.

Reopen requirements:

- Reopen is only allowed from `FINALIZED`.
- Reopen requires elevated privilege.
- Reopen requires an explicit operator-provided reason.
- Reopen returns the drive to an eligible non-finalized state without implicitly changing its project binding.
- Reopen produces dedicated audit evidence including actor, reason, drive, and project context.
- Reopen must never occur implicitly as a side effect of unrelated operations.

Acceptance criteria:

- Safe-removal preparation and finalization remain behaviorally distinct.
- A finalized drive cannot accept additional export work until explicitly reopened.
- Reopen without a reason or sufficient privilege is rejected.

## 4.3 Project Isolation Requirements

To prevent evidence contamination:

- Each writable drive workflow must be bound to a single project context.
- A drive must not accept writes for a different project than the one to which it is currently bound.
- Cross-project write attempts must be blocked before data movement begins.
- Each denial must produce audit evidence.
- The active project association of in-use and finalized drives must remain visible to operators.
- Finalization must not clear project binding.
- A finalized drive must remain project-bound until explicitly reopened or reset by an authorized lifecycle action.

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
- Finalized drives must be excluded from new assignment until explicitly reopened.
- Additional export to a finalized drive must require an explicit reopen first.

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
- Drive safe-removal preparation success and failure.
- Drive finalization.
- Drive reopen or unfinalize.
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

## 4.9 Discovery and Reconciliation Requirements

Discovery and refresh behavior must preserve protected drive states and policy guarantees:

- Reconnected eligible drives may return to an available state when policy permits.
- Removed drives may leave the available set when no longer present or when policy disables their port.
- In-use drives must not be demoted by discovery while project isolation remains active.
- Finalized drives must not be demoted or implicitly reopened by discovery or reconciliation.
- A finalized drive that is removed and later reinserted must remain finalized until an explicit reopen occurs.

Acceptance criteria:

- Discovery refresh does not silently defeat project isolation.
- Discovery refresh does not silently convert a finalized drive back into a writable drive.

## References

- [docs/design/04-functional-design.md](../design/04-functional-design.md)
