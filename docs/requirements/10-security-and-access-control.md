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

## References

- [docs/design/10-security-and-access-control.md](../design/10-security-and-access-control.md)
