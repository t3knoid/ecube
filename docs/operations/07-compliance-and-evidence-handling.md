# ECUBE Compliance and Evidence Handling

| Field | Value |
|---|---|
| Title | Compliance and Evidence Handling |
| Purpose | Specifies compliance requirements, chain-of-custody procedures, and evidence integrity guarantees for legal admissibility and audit defensibility. |
| Updated on | 04/08/26 |
| Audience | Legal teams, compliance officers, evidence managers, IT security, operations. |

## Overview

ECUBE is designed for secure handling and export of eDiscovery evidence. This document specifies compliance requirements, regulatory mappings, chain-of-custody procedures, and evidence integrity guarantees necessary for legal admissibility and audit defensibility.

**Critical Note:** ECUBE must be deployed and operated in compliance with all applicable regulations in your jurisdiction. This document provides baseline requirements; consult with legal counsel and compliance specialists before production deployment.

---

## Table of Contents

1. [Regulatory Framework](#regulatory-framework)
2. [Compliance Mappings](#compliance-mappings)
3. [Chain-of-Custody](#chain-of-custody)
4. [Evidence Integrity & Preservation](#evidence-integrity--preservation)
5. [Data Handling & Retention](#data-handling--retention)
6. [Audit & Accountability](#audit--accountability)
7. [Incident Response & Breach Notification](#incident-response--breach-notification)
8. [Compliance Checklist](#compliance-checklist)

---

## Regulatory Framework

ECUBE must comply with the following regulatory and legal standards, depending on your jurisdiction and use case:

### United States

#### Federal Rules of Civil Procedure (FRCP)

**Applicable:** All federal court litigation in the U.S.

**Key Requirements:**
- **Preservation Obligation (Rule 26(g)):** Parties must take reasonable steps to preserve evidence relevant to foreseeable litigation.
- **Proportionality (Rule 26(b)(1)):** eDiscovery requests must be proportional to the needs of the case (cost, burden, importance).
- **Safe Harbor (Rule 37(e)):** If a party fails to preserve electronically stored information (ESI), courts may impose sanctions unless the loss is not due to the party's failure to take reasonable precautions, AND the information cannot be restored or replaced through additional discovery.
- **Metadata Handling:** Metadata must be preserved and produced unless parties stipulate otherwise.

**ECUBE Compliance:**
- Audit logs track all copy operations and evidence handling (Rule 26(b)(5) privilege log support).
- Manifest files include forensic metadata: file hashes, timestamps, copy source, destination, operator.
- Checksums (MD5/SHA-256) enable integrity verification for admissibility challenges.
- Retention settings prevent inadverted loss (see [Data Handling & Retention](#data-handling--retention)).

#### HIPAA (Health Insurance Portability and Accountability Act)

**Applicable:** If handling Protected Health Information (PHI) or health record discovery.

**Key Requirements:**
- **Confidentiality:** PHI must be encrypted in transit and at rest.
- **Access Controls:** Only authorized personnel with business need can access PHI.
- **Audit Controls:** All access to PHI must be logged and auditable.
- **Integrity Controls:** PHI cannot be altered in transit; checksums enable detection of tampering.
- **Breach Notification:** Breaches involving PHI require notification to affected individuals (see [Incident Response & Breach Notification](#incident-response--breach-notification)).

**ECUBE Compliance:**
- TLS encryption for API communication (`https://` only; HTTP disabled).
- LUKS or hardware-encrypted USB drives for data at rest (see [docs/design/12-runtime-environment-and-usb-visibility.md](../design/12-runtime-environment-and-usb-visibility.md)).
- Role-based access control (RBAC) restricts PHI access to authorized personnel; audit logs track all PHI handling.
- File checksums enable detection of unauthorized modifications.
- Audit logs are append-only and tamper-evident (database constraints prevent deletion/modification).

#### GLBA (Gramm-Leach-Bliley Act)

**Applicable:** If handling financial institution records or customer financial information.

**Key Requirements:**
- **Data Security:** Financial information must be protected from unauthorized access.
- **Audit Trails:** All access to financial data must be logged.
- **Retention Limits:** Data should not be retained longer than necessary.

**ECUBE Compliance:**
- Encryption in transit and at rest (TLS, LUKS).
- Audit logging of all copy operations and data access.
- Data retention settings enforce compliance with retention schedules (see [Data Handling & Retention](#data-handling--retention)).

### European Union & GDPR

#### GDPR (General Data Protection Regulation)

**Applicable:** If handling personal data of EU residents (scope applies globally wherever EU data is processed).

**Key Requirements:**
- **Lawful Basis:** Processing of personal data must have a lawful basis (legal obligation, court order, etc.).
- **Consent:** For some processing, explicit consent is required.
- **Data Subject Rights:** Individuals have rights to access, correction, erasure ("right to be forgotten"), and data portability.
- **Data Protection by Design:** Privacy controls must be built-in from the start.
- **Breach Notification:** Data protection authorities must be notified of breaches within 72 hours; affected individuals notified without undue delay.
- **Data Protection Impact Assessment (DPIA):** Required before high-risk processing.

**ECUBE Compliance:**
- **Lawful Basis:** ECUBE assumes use under a lawful basis (e.g., court order, legal obligation). Verify lawful basis before processing.
- **Access Controls:** RBAC and authentication ensure only authorized personnel access personal data.
- **Audit Trails:** Comprehensive audit logging enables data subject rights requests (retrieve all data processed for individual X).
- **Retention:** Data retention policies (see [Data Handling & Retention](#data-handling--retention)) support the right to data minimization.
- **Deletion:** Audit logs themselves are append-only and not deletable; however, source evidence can be securely wiped. Verify "right to be forgotten" applicability in your jurisdiction (tension with evidence preservation obligations).
- **Encryption:** TLS in transit, encrypted USB drives at rest, encrypted database for additional protection.
- **DPIA Requirement:** Organizations must document a Data Protection Impact Assessment before using ECUBE for large-scale personal data export; [Compliance Checklist](#compliance-checklist) includes this requirement.

### Other Jurisdictions

#### Canada: PIPEDA (Personal Information Protection and Electronic Documents Act)

**Applicable:** If handling Canadian personal information or subject to Canadian law.

**Key Requirements:** Similar to GDPR—lawful basis, access controls, breach notification, data subject rights.

**ECUBE Compliance:** Same as GDPR mappin above.

#### Australia: Privacy Act

**Applicable:** If handling Australian personal data.

**Key Requirements:** Secure storage, access controls, breach notification, data retention limits.

**ECUBE Compliance:** Same as GDPR mapping above.

#### UK: PECR (Privacy and Electronic Communications Regulations)

**Applicable:** If exporting email or communications metadata.

**Key Requirements:** Metadata of communications (To/From/Date/Subject) may be sensitive; additional retention/access controls may be required.

**ECUBE Compliance:** Audit logs track metadata access; retention policies can restrict export duration.

---

## Compliance Mappings

This section maps ECUBE features to specific regulatory controls.

### Evidence Preservation & Integrity

| Requirement | Control | ECUBE Feature |
|-------------|---------|---------------|
| **Prevent accidental loss of evidence** | System prevents deletion of evidence copies | Read-only USB drives (after copy); no delete operation on evidence files |
| **Maintain evidence integrity** | Detect unauthorized modifications | File checksums (MD5/SHA-256) in manifest; comparison tools enable hash verification |
| **Prove custody chain** | Audit trail of all handlers and timestamps | `audit_logs` table: who copied, when, from where, to which drive |
| **Verify copy accuracy** | Re-verify copy matches source | Manifest verification endpoint; automated comparison of source/destination hashes |
| **Prevent tampering** | Encrypt evidence in transit and at rest | TLS for API; LUKS/hardware-encrypted USB drives; encrypted database storage |

### Access Control & Authorization

| Requirement | Control | ECUBE Feature |
|-------------|---------|---------------|
| **Limit access to authorized personnel** | Role-based access control | Four roles: admin, manager, processor, auditor |
| **Audit who accessed what** | Access logging | `audit_logs`: all API calls, role grants, access denials |
| **Separate duties** | Distinct roles prevent conflicts of interest | Manager initializes drive; Processor creates job; Auditor reviews logs |
| **Identification & authentication** | Users must prove identity | Token-based auth (JWT) via PAM/LDAP/OIDC |
| **Session management** | Secure session handling | Token expiration (default 60 min); encrypted session storage |

### Data Retention & Security

| Requirement | Control | ECUBE Feature |
|-------------|---------|---------------|
| **Retain evidence per legal hold** | Retention policies prevent deletion | Manual retention override; audit logs track retention policy changes |
| **Encrypt sensitive data** | Encryption at rest and in transit | TLS for API; LUKS or hardware encryption for USB drives; encrypted database |
| **Secure disposal** | Clear data when no longer needed | Manual USB erase on separate admin tool (not in ECUBE core API) |
| **Minimize data collection** | Only collect what's necessary | ECUBE only stores evidence copy + metadata; no personal data beyond authentication |
| **Limit retention duration** | Automatic cleanup after retention expires | (To be implemented: automatic audit log archival after N days per retention policy) |

---

## Chain-of-Custody

Chain-of-custody (CoC) is a legal requirement for evidence admissibility. It documents continuous responsibility for evidence from collection to presentation in court. ECUBE supports CoC through comprehensive audit logging and manifest generation.

### Chain-of-Custody Record

The `audit_logs` table serves as the authoritative chain-of-custody record. For each evidence export, the following must be documented:

**A. Source & Seizure (Responsibility: Litigation Team)**
- Original evidence location (server, custodian, drive, etc.)
- Date/time of seizure
- Seizing officer/custodian
- Initial integrity check (hash of source)

**B. Transfer to ECUBE (Responsibility: IT/eDiscovery Team)**
- Date/time evidence uploaded or mounted in ECUBE
- Source path (NFS share, SMB share, or local directory)
- Project ID (case/matter identifier)
- Operator username (`audit_logs.actor`)
- Initial system verification (ECUBE readiness check)

**C. Processing (Responsibility: eDiscovery Processor)**
- Job creation: `audit_logs` entry with source, thread count, destination
- Copy operation: Start/stop timestamps, files copied, bytes transferred
- Re-verification: Checksum verification timestamp, hash comparison results
- Manifest generation: Manifest creation entry with hash values
- Errors/retries: All retry attempts and error details logged

**D. Export & Physical Custody (Responsibility: Manager/Auditor)**
- Drive initialization: project binding, filesystem type, capacity
- Drive assignment to job: timestamp, operator name
- Drive eject: unmount operation, timestamp
- USB drive handoff: Physical receipt/signature by receiving party (outside ECUBE; manual process)

**E. Final Verification (Responsibility: Receiving Party)**
- Drive contents verified against manifest hashes
- Custody receipt signed by receiving party
- Drive stored in secure facility with access controls

### Manual Chain-of-Custody Form

Organizations using ECUBE must maintain a printed or digital CoC form for each evidence export:

```
CHAIN-OF-CUSTODY RECORD

Case/Matter: [Case Name & Number]
Evidence ID: [Unique Identifier]
Description: [Brief Description of Evidence]

=== SOURCE & SEIZURE ===
Original Location: [Server/Custodian/Drive]
Seized On: [Date/Time]
Seized By: [Officer Name/Badge]
Initial Hash: [MD5/SHA-256 of source]

=== PROCESSING IN ECUBE ===
Uploaded/Mounted: [Date/Time]
Source Path: [NFS/SMB/Local Path]
Project ID: [ECUBE Project ID]
Operator: [ECUBE User]
Job ID: [ECUBE Job ID]

=== COPY DETAILS (from ECUBE audit logs) ===
Job Created: [Date/Time]
Copy Started: [Date/Time]
Copy Completed: [Date/Time]
Files Copied: [Count]
Bytes Copied: [Total]
Copy Errors: [Count/Details]
Manifest Hash: [SHA-256 of manifest.txt]

=== VERIFICATION ===
Re-Verified On: [Date/Time]
Verification Result: [PASSED/FAILED]
Verifier: [ECUBE Auditor Name]

=== HANDOFF ===
Handed Over To: [Receiving Party Name/Title]
Date/Time: [Date/Time]
Receiving Party Signature: _____________________
ECUBE Operator Signature: _____________________

=== STORAGE ===
Stored At: [Facility/Location]
Access Controls: [Who has access]
Retrieval Count: [How many times accessed post-handoff]

Signatures on file: [Yes/No]
Verified by Legal Counsel: [Yes/No]
```

### Digital Chain-of-Custody Export

ECUBE must provide an automated export of chain-of-custody records:

**Endpoint:** `GET /audit/chain-of-custody?job_id={job_id}`

**Response:**

```json
{
  "job_id": "j-12345",
  "project_id": "p-67890",
  "case_name": "Smith v. Acme Corp",
  "case_number": "2026-CV-001234",
  "evidence_description": "Email server backup for custodian 'jane@acme.com', Jan 2025",
  "source_path": "/mnt/evidence/jane-2025",
  "chain_of_custody_events": [
    {
      "event_type": "JOB_CREATED",
      "timestamp": "2026-04-05T10:00:00Z",
      "actor": "alice@example.com",
      "action": "Job created",
      "details": {
        "job_id": "j-12345",
        "source_path": "/mnt/evidence/jane-2025",
        "project_id": "p-67890",
        "thread_count": 8
      }
    },
    {
      "event_type": "JOB_STARTED",
      "timestamp": "2026-04-05T10:05:00Z",
      "actor": "bob@example.com",
      "action": "Copy operation started",
      "details": {
        "drive_id": "d-98765",
        "estimated_duration_seconds": 3600
      }
    },
    {
      "event_type": "JOB_COMPLETED",
      "timestamp": "2026-04-05T11:05:00Z",
      "actor": "bob@example.com",
      "action": "Copy operation completed",
      "details": {
        "drive_id": "d-98765",
        "files_copied": 50000,
        "bytes_copied": 1099511627776,
        "duration_seconds": 3600,
        "errors": 0
      }
    },
    {
      "event_type": "JOB_VERIFIED",
      "timestamp": "2026-04-05T11:10:00Z",
      "actor": "charlie@example.com",
      "action": "Manifest verification passed",
      "details": {
        "manifest_hash": "abc123def456...",
        "source_hashes_matched": 50000,
        "destination_hashes_matched": 50000
      }
    },
    {
      "event_type": "DRIVE_EJECT_PREPARED",
      "timestamp": "2026-04-05T11:15:00Z",
      "actor": "alice@example.com",
      "action": "Drive prepared for eject",
      "details": {
        "drive_id": "d-98765",
        "device_path": "/dev/sdb1"
      }
    }
  ],
  "manifest_summary": {
    "total_files": 50000,
    "total_bytes": 1099511627776,
    "manifest_format": "csv",
    "manifest_hash": "abc123def456...",
    "export_metadata": {
      "exported_at": "2026-04-05T11:05:00Z",
      "exported_by": "bob@example.com",
      "source_hash_algorithm": "SHA-256",
      "destination_hash_algorithm": "SHA-256"
    }
  }
}
```

---

## Evidence Integrity & Preservation

### Forensic Hashing

ECUBE computes and validates file hashes to prove evidence integrity. Hash collisions are cryptographically infeasible; matching hashes prove a file has not been altered.

**Supported Algorithms:**
- **MD5** — Legacy, no longer recommended due to collision vulnerabilities; use for backwards compatibility only.
- **SHA-256** — Cryptographically strong; recommended for all new implementations.

**Hash Computation:**
- Hashes are computed during copy: each file is read, hash is calculated sequentially, result is stored in manifest.
- Hashes are re-verified: After copy completes, ECUBE re-reads destination files and verifies hashes match manifest.
- Hashes are exportable: The `GET /files/{file_id}/hashes` endpoint allows auditors to independently verify hashes post-dispatch.

**Manifest Format:**

```
file_path,size_bytes,hash_algorithm,hash_value,copied_at,verified_at,status
/evidence/jane@acme.com/mailbox.pst,2147483648,SHA-256,e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855,2026-04-05T10:05:15Z,2026-04-05T10:06:45Z,verified
/evidence/jane@acme.com/calendar.pst,536870912,SHA-256,5feceb66ffc86f38d952786c6d696c79c2dbc238c4cafb11f2271d7a13d4a56,2026-04-05T10:05:20Z,2026-04-05T10:06:50Z,verified
...
```

### Write Protection & Immutability

After ECUBE completes a copy job, the destination USB drive should be write-protected to prevent accidental modification:

**Procedure (Manual):**

1. After receiving the USB drive, mount it read-only: `mount -o ro /dev/sdb1 /mnt/evidence`
2. Physically enable write-protection switch on the USB device (if available).
3. Store in secure facility with access controls.

**ECUBE Support:**
- ECUBE provides a drive safe-removal endpoint (`POST /drives/{drive_id}/prepare-eject`) for safe removal (flush + unmount + transition back to `AVAILABLE`).
- Prepare-eject does **not** enforce write-protection or seal custody state, and it does **not** clear `current_project_id`; project binding is preserved. Operational write-protection controls remain a physical and procedural responsibility.

### Evidence Segregation

**Project Isolation:** ECUBE enforces strict project isolation (see [docs/requirements/04-functional-requirements.md](../requirements/04-functional-requirements.md#project-isolation) and [docs/design/04-functional-design.md](../design/04-functional-design.md#project-isolation)). A single USB drive cannot contain evidence from multiple cases/projects.

**Implications:**
- Each USB drive is bound to one project_id at initialization.
- No files from different projects can be copied to the same drive.
- Visual confirmation in UI: manager views which project each drive is assigned to.

---

## Data Handling & Retention

### Retention Policies

ECUBE does not implement automatic retention/deletion policies; retention is the responsibility of the organization operating ECUBE. However, ECUBE tracks retention metadata to support policy compliance:

**Retention Metadata (Stored per Job):**

```python
class ExportJob(Base):
    ...
    # Retention fields
    legal_hold_expires_at: Optional[datetime]  # Date when legal hold expires
    destruction_authorized_at: Optional[datetime]  # Date destruction was approved
    retention_reason: str  # "litigation", "regulatory", "operational", etc.
    ...
```

**Recommended Retention Schedule:**

| Category | Retention Duration | Justification |
|----------|-------------------|---------------|
| **Active Litigation** | Duration of case + 1 year | Until litigation concludes + post-judgment retention |
| **Regulatory Hold** | Per regulation or longer | HIPAA: 6 years; GDPR: no longer than necessary |
| **Operational/Backup** | 90 days | Temporary evidence copies; delete after verification |
| **Audit Logs** | 3 years | Legal defensibility + statute of limitations |
| **Manifests** | Same as evidence | Proof of integrity; retain with evidence |

**Organizations must:**
1. Document retention policies in writing before production deployment.
2. Implement a manual process to track legal holds and destruction authorizations (outside ECUBE).
3. Configure ECUBE job creation to include `retention_reason` and `legal_hold_expires_at`.
4. Audit retention compliance annually (verify no evidence is past retention date without authorization).

### Data Security Classification

ECUBE does not enforce data classification, but organizations should classify evidence and apply appropriate controls:

| Classification | Confidentiality | Encryption | Access Restrictions |
|----------------|-----------------|------------|---------------------|
| **Public** | No | Optional | Read by auditors |
| **Internal** | Medium | TLS | Limited to employees |
| **Confidential** | High | TLS + encrypted USB | Manager + authorized processor only |
| **Secret/Sealed** | Very High | TLS + encrypted USB + encrypted database | Admin + designated auditor only |

**Organizations must:**
1. Define classification criteria for evidence.
2. Tag evidence in ECUBE (project metadata) with classification level.
3. Enforce role-based access based on classification.
4. Log all access to highly classified evidence.

### Encryption & Key Management

**Encryption in Transit:**
- All API communication must use HTTPS (TLS 1.2+).
- Server certificate must be signed by a trusted Certificate Authority.
- Verify certificate validity before connecting (TOFU or certificate pinning for high-security deployments).

**Encryption at Rest:**
- USB drives must use LUKS (Linux Unified Key Setup) or hardware-based encryption (e.g., IronKey, Kanguru).
- Database must be encrypted (transparent encryption at storage layer or encrypted column encryption).
- Encryption keys must be securely stored and rotated (see [production-support-procedures.md](production-support-procedures.md#secrets--key-rotation)).

**Key Management:**
- ECUBE does not manage USB drive encryption keys; responsibility lies with the organization.
- Best practice: Use enterprise management tools for LUKS key escrow (e.g., Clevis + Tang for network-recovered key encryption).
- Database encryption keys must be stored in a Key Management Service (KMS) such as AWS KMS, Google Cloud KMS, or hashicorp/vault.

---

## Audit & Accountability

### Audit Log Requirements

The `audit_logs` table is the primary accountability mechanism. It must be:

1. **Append-only:** No back-dating, deletion, or modification of audit entries.
2. **Timestamped:** All entries include an immutable UTC timestamp.
3. **Attributed:** Every action must credit a named user (actor).
4. **Comprehensive:** All material actions (authentication, job creation, eject, access denials) are logged.
5. **Tamper-evident:** Database constraints and cryptographic signing (if implemented) prevent unauthorized modification.

**Minimum Audit Log Fields:**

```python
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: int = Column(Integer, primary_key=True)
    timestamp: datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    actor: str = Column(String(255), nullable=False)  # Username
    action: str = Column(String(100), nullable=False)  # Event type
    resource_type: str = Column(String(50), nullable=False)  # "drive", "job", "user", "mount"
    resource_id: Optional[str] = Column(String(100))  # ID of resource accessed
    outcome: str = Column(String(50), nullable=False)  # "success", "failure", "denied"
    details: dict = Column(JSON, nullable=True)  # Additional context (JSON)
    client_ip: Optional[str] = Column(String(45))  # IPv4 or IPv6
    user_agent: Optional[str] = Column(String(500))  # Browser/client info
```

**Required Audit Events:**

| Event | Trigger | Details |
|-------|---------|---------|
| `AUTH_LOGIN_SUCCESS` | Successful login | username, client_ip, timestamp |
| `AUTH_LOGIN_FAILURE` | Failed login attempt | username, reason (invalid password, expired), client_ip |
| `AUTH_LOGOUT` | Logout | username, session_duration_seconds |
| `ROLE_ASSIGNMENT` | User assigned a role | user, role, assigned_by |
| `ROLE_REVOCATION` | User role removed | user, role, revoked_by |
| `JOB_CREATED` | Export job created | job_id, project_id, creator, source_path |
| `JOB_STARTED` | Copy job started | job_id, operator, drive_id, thread_count |
| `JOB_COMPLETED` | Job finished successfully | job_id, files_copied, bytes_copied, duration |
| `JOB_FAILED` | Job ended with failure | job_id, operator, error_message |
| `JOB_VERIFIED` | Manifest verification completed | job_id, verifier, result (passed/failed) |
| `DRIVE_INITIALIZED` | Drive bound to project | drive_id, project_id, initializer |
| `DRIVE_FORMATTED` | Drive reformatted | drive_id, filesystem_type, operator |
| `DRIVE_EJECT_PREPARED` | Drive prepared for removal | drive_id, device_path, operator |
| `MOUNT_ADDED` | Network mount created | mount_id, path, type (NFS/SMB), operator |
| `MOUNT_REMOVED` | Mount deleted | mount_id, operator |
| `ACCESS_DENIED` | Authorization check failed | resource, actor, required_role, reason |
| `CONFIG_CHANGED` | Configuration updated | setting, old_value, new_value, changed_by |

### Log Integrity

To prevent tampering with audit logs:

1. **Database Constraints:** Audit table has:
   ```sql
   ALTER TABLE audit_logs ADD CONSTRAINT audit_immutable
     CHECK (created_at IS NOT NULL);  -- Created at is immutable
   ```

2. **Archival & Offsite Storage:** Regular exports of audit logs to immutable storage (write-once S3, WORM volumes, printed records).

3. **Cryptographic Signing (Optional):** Sign audit log exports with private key; verify signatures periodically to detect tampering.

4. **Read-Only Access:** Only auditors can read logs; no other role can modify or delete audit entries.

---

## Incident Response & Breach Notification

### Security Incident Classification

| Severity | Example | Response Time | Notification |
|----------|---------|----------------|--------------|
| **Critical** | Unauthorized access to evidence, data breach, system compromise | < 1 hour | Immediate: Legal, CISO, Law Enforcement (if required) |
| **High** | Failed integrity check, unexplained audit log gap, authentication system failure | < 4 hours | Within 24 hours: Legal, stakeholders |
| **Medium** | Unusual access patterns, failed copy verification, network mount failure | < 1 day | Within 5 days: Stakeholders |
| **Low** | Minor validation error, non-critical configuration drift | < 5 days | Weekly status |

### Breach Notification Requirements

**GDPR (Article 33):** Data protection authority must be notified within **72 hours** of discovering a breach involving personal data. Affected individuals must be notified without undue delay unless risk is low.

**HIPAA (Breach Notification Rule):** Affected individuals must be notified of breaches involving unsecured PHI without unreasonable delay and no later than 60 days from discovery.

**State Laws (e.g., California Consumer Privacy Act):** Notification may be required without unreasonable delay.

**ECUBE Incident Response Procedure:**

1. **Detect:** Unauthorized access alarm, integrity check failure, or suspicious audit log entry triggers detection.
2. **Containment (30 min):**
   - Isolate affected system from network if necessary.
   - Preserve evidence (all logs, memory dumps, affected database records).
   - Lock down access (revoke tokens, disable accounts if compromised).
3. **Investigation (4–24 hours):**
   - Determine scope: What data was accessed/exfiltrated? Which users/dates?
   - Determine cause: Weak password, unpatched vulnerability, insider threat?
   - Assess impact: Personal data of N individuals exposed?
4. **Notification (24–72 hours):**
   - Legal review: Determine if breach is reportable under regulations.
   - Prepare notification: Determine recipients (DPA, affected individuals, media, etc.).
   - Send notifications per regulatory timelines.
5. **Remediation (1–4 weeks):**
   - Patch vulnerability or harden controls.
   - Notify affected parties of remediation steps.
   - Conduct post-incident review (blameless post-mortem).
6. **Documentation:**
   - Archive incident report (investigation findings, timeline, actions).
   - Update security controls based on lessons learned.

**Organizations must maintain:**
- Incident response playbook (before production)
- Contact list (Legal, CISO, DPA, law enforcement)
- Notification templates (GDPR, HIPAA, state-specific)
- Communication procedures (encrypted channels, secure email)

---

## Compliance Checklist

Before deploying ECUBE to production, complete the following compliance tasks:

### Legal & Governance

- [ ] Your organization's Legal team has reviewed ECUBE for compliance with applicable regulations.
- [ ] Regulatory requirements (FRCP, GDPR, HIPAA, etc.) applicable to your use case are documented.
- [ ] Data Protection Impact Assessment (DPIA) has been completed (GDPR requirement for high-risk processing).
- [ ] Chain-of-custody procedures are documented and reviewed by Legal.
- [ ] eDiscovery litigation hold procedures incorporate ECUBE into workflow.
- [ ] Retention and destruction policies are written and approved by Legal.

### Security & Encryption

- [ ] TLS certificates are signed by a trusted CA and valid for at least 1 year.
- [ ] Database encryption is enabled (transparent encryption or encrypted columns).
- [ ] USB drives use LUKS or hardware-based encryption.
- [ ] Encryption keys are stored in a secure Key Management Service (not on disk).
- [ ] Encryption key rotation schedule is documented and tested (see [production-support-procedures.md](production-support-procedures.md#secrets--key-rotation)).
- [ ] All API communication is HTTPS only; HTTP is disabled or redirects to HTTPS.

### Access Control & Authentication

- [ ] Initial users are created with strong passwords and MFA (if supported).
- [ ] LDAP or OIDC integration (if used) is tested end-to-end.
- [ ] Role-based access control (RBAC) is tested: Admin can do X, Manager can do Y, etc.
- [ ] Service account privileges are minimized (least privilege principle).
- [ ] Audit logs show all authentication events and access denials.

### Audit Logging & Monitoring

- [ ] Audit logs are JSON-formatted and sent to centralized logging system.
- [ ] Audit log aggregation (ELK, Datadog, Splunk, etc.) is configured and tested.
- [ ] Audit log exports can be manually triggered for legal holds or discovery.
- [ ] Alerts are configured for suspicious activity (repeated login failures, unusual data access, etc.).
- [ ] On-call escalation procedures are documented and tested.
- [ ] Log retention meets regulatory requirements (typically 3 years minimum).
- [ ] Audit logs cannot be deleted or modified by non-audit users.

### Data Handling & Retention

- [ ] Retention policies are documented (litigation: N years, regulatory: M years, operational: P days).
- [ ] Retention metadata is recorded in ECUBE (legal_hold_expires_at, retention_reason).
- [ ] A manual process (spreadsheet, ticketing system) tracks legal holds and destruction authorizations.
- [ ] No evidence is deleted without documented authorization and legal approval.
- [ ] Data destruction procedures are documented (secure erase, certification of destruction).

### Incident Response & Breach Notification

- [ ] Incident response playbook is created and shared with team.
- [ ] Contact list (Legal, CISO, DPA, law enforcement) is documented.
- [ ] Breach notification templates are prepared (GDPR, HIPAA, state-specific).
- [ ] Incident response team has conducted a tabletop exercise (simulated breach).
- [ ] Post-incident review procedure is documented.

### Testing & Validation

- [ ] End-to-end evidence export test has been completed (20+ GB dataset).
- [ ] Manifest verification test: Hashes match source and destination.
- [ ] Chain-of-custody form has been filled out for test export.
- [ ] Restore test: Evidence from exported USB drive is mounted and verified (recovery scenario).
- [ ] Disaster recovery test: Backup is restored and ECUBE recovers correctly.
- [ ] Access control test: Auditor cannot modify drives; processor cannot initialize drives.
- [ ] Audit log export test: CoC events are exported in required format.
- [ ] Error scenario tests: Disk full, network timeout, permission denied; recovery is graceful.

### Documentation & Training

- [ ] Operations runbook is updated with ECUBE-specific procedures.
- [ ] Troubleshooting guide for common issues is documented (see [production-support-procedures.md](production-support-procedures.md)).
- [ ] Support team is trained on ECUBE procedures and incident response.
- [ ] Legal team understands chain-of-custody procedures and audit log review.
- [ ] Compliance & audit team can navigate and export audit logs.
- [ ] All procedures are documented in a wiki or shared drive, with version control.

---

## Related Documents

- [docs/requirements/04-functional-requirements.md](../requirements/04-functional-requirements.md) — Project isolation, audit logging requirements
- [docs/design/04-functional-design.md](../design/04-functional-design.md) — Audit implementation, race condition handling
- [docs/design/10-security-and-access-control.md](../design/10-security-and-access-control.md) — Identity, RBAC, authentication implementation
- [01-operational-readiness.md](01-operational-readiness.md) — Health checks, monitoring, alerting
- [production-support-procedures.md](production-support-procedures.md) — Backup/recovery, upgrade, patching, troubleshooting

## References

- [docs/requirements/07-compliance-and-evidence-handling.md](../requirements/07-compliance-and-evidence-handling.md)
