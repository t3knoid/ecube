# 10. Security and Role-Based Access Control

| Field | Value |
|---|---|
| Title | Security and Role-Based Access Control |
| Purpose | Defines the ECUBE identity model, role-based access control requirements, and authentication and authorization policy constraints. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, security engineers, product managers, and QA teams. |

## Identity Model

ECUBE must:

- Authenticate users against a configurable identity provider
- Resolve roles for each authenticated user
- Support identity modes including local OS users, LDAP, and OIDC
- Enforce role-based access control on all endpoints

## Roles

ECUBE defines four roles:

### Admin

- Full access to all ECUBE operations and APIs.

### Manager

- Initialize drives and assign them to projects.
- Manage mounts and drive lifecycle.
- View jobs, drives, mounts, and logs.

### Processor

- Create jobs (within allowed projects).
- Start and monitor copy operations.
- View job and drive status.

### Auditor

- Read audit logs.
- View job and file metadata.
- Compute file hashes (for example, MD5 and SHA-256).
- Perform file comparisons.
- No write operations to jobs, drives, or mounts.

## Authorization Matrix (High Level)

| Operation / API area                        | Admin | Manager | Processor | Auditor |
|---------------------------------------------|:-----:|:-------:|:---------:|:-------:|
| Manage users / security config (future)     |  ✔    |    ✖    |     ✖     |    ✖    |
| Add/remove mounts                           |  ✔    |    ✔    |     ✖     |    ✖    |
| List mounts                                 |  ✔    |    ✔    |     ✔     |    ✔    |
| Initialize drives / assign to projects      |  ✔    |    ✔    |     ✖     |    ✖    |
| Prepare drives for eject                    |  ✔    |    ✔    |     ✖     |    ✖    |
| List drives / drive states                  |  ✔    |    ✔    |     ✔     |    ✔    |
| Create jobs                                 |  ✔    |    ✔    |     ✔     |    ✖    |
| Start copy jobs                             |  ✔    |    ✔    |     ✔     |    ✖    |
| View job status                             |  ✔    |    ✔    |     ✔     |    ✔    |
| Regenerate manifest / verify job            |  ✔    |    ✔    |     ✔     |    ✖    |
| Read audit logs                             |  ✔    |    ✔    |     ✖     |    ✔    |
| Introspection (read-only system info)       |  ✔    |    ✔    |     ✔     |    ✔    |
| File hash / file compare (audit functions)  |  ✔    |    ✖    |     ✖     |    ✔    |

## Access Control Requirements

- Role enforcement must occur at the API layer for every endpoint.
- Unauthenticated requests must return `401 Unauthorized`.
- Requests lacking required roles must return `403 Forbidden`.
- All security-relevant events must be audit-logged, including authentication attempts and access denials.

## Password Complexity and Policy Requirements

ECUBE must enforce password complexity and lifecycle policy for locally managed OS user accounts through the host's PAM framework.

### Acceptance Criteria

#### Complexity and Length

- Passwords for ECUBE-managed accounts must comply with the host's PAM policy at the point of creation and at each reset, including minimum length, character-class requirements, and dictionary checks.
- The minimum password length must be at least 12 characters, with 14 characters as the recommended default, in alignment with NIST SP 800-63B guidelines (length over complexity).
- The system must configure `pam_pwquality` with `enforce_for_root = 1` so that passwords set or reset via the ECUBE service account (which runs with root-equivalent privileges through `sudo`) are not exempt from policy enforcement.
- Following NIST SP 800-63B guidance, the minimum length requirement is the primary complexity control. Additional character class requirements may be applied by the host administrator but are not mandated by ECUBE alone.

#### Password History

- The host PAM stack must be configured to reject passwords that were used within the last 12 password changes (`pam_pwhistory remember = 12`).
- ECUBE must not bypass history enforcement. Passwords set through the ECUBE API must pass through the same `pam_pwhistory` check applied to interactive password changes.

#### Password Expiration

- The default maximum password age must be 90 days.
- ECUBE must detect when a user's password has expired or will expire within a configurable warning period.
- When a user authenticates with an expired password, the system must reject login and return an error that the UI can distinguish from a generic credentials failure.
- The UI must provide a forced password-change workflow so that a user with an expired (or soon-to-expire) password can update it without requiring administrator intervention.
- The current password must be verified before the new password is accepted in the self-service expiry workflow.
- Password expiration does not apply to SSO or LDAP-backed accounts. The expiration check is scoped to local OS user accounts only.

#### Admin-Managed Complexity Rules

- An administrator must be able to view the current `pam_pwquality` configuration from the ECUBE UI.
- An administrator must be able to modify key `pam_pwquality` parameters — at minimum `minlen`, `minclass`, `maxrepeat`, `dictcheck`, and `enforce_for_root` — through the ECUBE configuration API without requiring direct host access.
- Changes to the `pwquality.conf` file must be audit-logged with the actor identity, the previous values, and the new values.
- Writes to `pwquality.conf` must be atomic (write to a temporary file and rename) to prevent a partial-write from corrupting the policy file.
- The ECUBE service account requires write access to `/etc/security/pwquality.conf` through a narrowly scoped `sudoers` rule.

#### API Behavior for Policy Violations

- When PAM rejects a new password at creation or reset time, the API must return `422 Unprocessable Entity` (not `500 Internal Server Error`) and must include the PAM-provided rejection reason in the response body so that the client can display it to the user.
- A generic fallback message must be provided for PAM error text that cannot be safely forwarded to the client.

#### Audit Trail

- Every password-policy rejection must be recorded in `audit_logs` with the actor, the target username, and the reason category (`pam_policy_violation`, `password_expired`, `history_reuse`).
- Every successful password change must be audit-logged with the actor and target username.
- Every modification to `pwquality.conf` must be audit-logged.

### Scope Boundary

- These requirements apply exclusively to local OS accounts managed through the `/admin/os-users` API.
- LDAP and OIDC-backed accounts inherit the password and expiration policies of their upstream identity provider. ECUBE does not attempt to enforce or override those policies.
- The configuration of `pam_pwhistory` and base `pam_pwquality` parameters in `/etc/pam.d/common-password` is a host-level prerequisite and is handled by the ECUBE installer and Ansible roles, not by the application at runtime.

## References

- [docs/design/10-security-and-access-control.md](../design/10-security-and-access-control.md)
