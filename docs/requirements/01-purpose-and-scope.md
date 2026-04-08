# 1. Purpose and Scope

| Field | Value |
|---|---|
| Title | Purpose and Scope |
| Purpose | Defines the scope and goals of ECUBE as a secure, auditable evidence export system. |
| Updated on | 04/08/26 |
| Audience | Stakeholders, auditors, product managers, reviewers, and QA teams. |

ECUBE is a secure, auditable, hardware aware system for exporting eDiscovery documents to encrypted USB drives. It operates on a Linux based “copy machine” connected to a multi port USB hub and exposes a controlled API for a public facing UI.

ECUBE ensures:

- Reliable, multi-threaded copying of large datasets
- Strict project isolation (no cross-project contamination)
- Full audit logging
- Hardware introspection
- Drive lifecycle management
- Support for NFS/SMB network mounts
- UI isolation from both database and hardware

ECUBE is designed for environments where multiple USB drives must always be ready for export operations.

## References

- [docs/design/01-purpose-and-scope.md](../design/01-purpose-and-scope.md)
