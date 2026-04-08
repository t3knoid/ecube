# 7. Compliance and Evidence Handling Requirements

| Field | Value |
|---|---|
| Title | Compliance and Evidence Handling Requirements |
| Purpose | Defines normative compliance, chain-of-custody, evidence integrity, retention, and incident-response requirements for ECUBE legal evidence exports. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, compliance officers, legal teams, and QA teams. |

## 7.1 Purpose

This document defines normative compliance, chain-of-custody, evidence integrity, retention, and incident-response requirements for ECUBE operations handling legal evidence exports.

## 7.2 Scope

These requirements apply to all environments that process, copy, verify, store, transfer, or audit evidence with ECUBE, including API services, copy workers, storage paths, audit pipelines, and operator procedures.

## 7.3 Regulatory and Policy Baseline

ECUBE deployments must be mapped to all applicable legal and regulatory obligations before production go-live.

- The operating organization must maintain a jurisdiction-specific control matrix that maps ECUBE controls to applicable obligations (for example FRCP, GDPR, HIPAA, GLBA, and equivalent regional privacy laws).
- A legal review must approve the control matrix, retention policy, and chain-of-custody procedure before first production evidence export.
- The organization must define lawful basis and processing purpose for each evidence project and retain this decision as auditable metadata.

## 7.4 Chain-of-Custody Requirements

ECUBE must provide an auditable chain-of-custody record for every evidence export.

- Every material custody event must be recorded with immutable UTC timestamp, actor identity, action, resource identifiers, outcome, and contextual metadata.
- Chain-of-custody records must cover at minimum: job creation, copy start, copy completion/failure, verification, manifest generation, drive assignment, and drive eject preparation.
- Chain-of-custody exports must be reproducible from system records and must not require modification of historical audit entries.
- Physical handoff events that occur outside ECUBE must be captured in an operator-controlled custody form linked to job and drive identifiers.

## 7.5 Evidence Integrity and Preservation

ECUBE must preserve evidentiary integrity from source read through destination verification.

- The system must compute and persist per-file cryptographic hashes during export.
- The system must support post-copy verification that recomputes destination hashes and compares them with recorded values.
- Hash algorithm policy must support SHA-256 as the baseline algorithm for new exports.
- Manifest artifacts must include file identity, file size, hash algorithm, hash value, copy timestamp, and verification status.
- Project isolation controls must prevent cross-project writes to a bound drive before copy begins.

## 7.6 Audit and Accountability

ECUBE must provide tamper-resistant accountability records.

- Audit storage must be append-only from the perspective of application users.
- Authorization denials, authentication outcomes, privileged changes, and evidence-handling actions must all be audit-logged.
- Audit records must be queryable by time range, actor, resource type, resource identifier, and event type.
- Audit exports for legal review must preserve field semantics and event ordering.

## 7.7 Data Handling, Encryption, and Retention

Evidence and sensitive metadata must be protected in transit and at rest and retained according to approved policy.

- API and service communication handling sensitive data must use TLS.
- Evidence destination media used for production exports must be encrypted at rest per organizational security policy.
- The organization must define retention periods by evidence category and legal context.
- Evidence destruction must require explicit authorization outside routine job operations and must leave a durable audit trail.
- Retention exceptions (for example legal hold) must be represented as structured metadata associated with the project or export job.

## 7.8 Incident Response and Breach Notification

Security and integrity incidents affecting evidence must follow time-bound response requirements.

- The organization must maintain an incident playbook that includes containment, investigation, notification decisioning, remediation, and post-incident review.
- ECUBE operations must preserve forensic records required for incident investigation.
- Breach notification timelines and recipients must follow applicable law for the affected jurisdiction and data class.

## 7.9 Acceptance Criteria

A deployment satisfies this requirements document only when all statements below are true.

- A compliance control matrix exists, is legally reviewed, and is version-controlled.
- Chain-of-custody events are complete and exportable for representative test jobs.
- Hash-based verification demonstrates source-to-destination integrity for representative datasets.
- Audit immutability and access controls are verified in pre-production testing.
- Retention and legal-hold procedures are documented and exercised.
- Incident response runbook and notification workflow are tested.

## 7.10 Traceability

Primary operational reference: [docs/operations/07-compliance-and-evidence-handling.md](../operations/07-compliance-and-evidence-handling.md).
Related requirements: [docs/requirements/04-functional-requirements.md](04-functional-requirements.md) and [docs/requirements/10-security-and-access-control.md](10-security-and-access-control.md).

## References

- [docs/design/04-functional-design.md](../design/04-functional-design.md)
- [docs/operations/07-compliance-and-evidence-handling.md](../operations/07-compliance-and-evidence-handling.md)
