# ECUBE UI Use Cases

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** UI Designers, Developers, QA  
**Document Type:** Use Case Catalog  
**Source:** Derived from [06-administration-guide.md](../operations/06-administration-guide.md)

---

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Group 1: First-Time Setup \& Database Configuration](#group-1-first-time-setup--database-configuration)
- [Group 2: Authentication \& Session Management](#group-2-authentication--session-management)
- [Group 3: User \& Role Management (Admin Only)](#group-3-user--role-management-admin-only)
- [Group 4: Drive Management](#group-4-drive-management)
- [Group 5: Mount Management](#group-5-mount-management)
- [Group 6: Export Job Workflow](#group-6-export-job-workflow)
- [Group 7: Audit \& Compliance](#group-7-audit--compliance)
- [Group 8: System Monitoring \& Introspection](#group-8-system-monitoring--introspection)
- [Cross-Cutting UI Concerns](#cross-cutting-ui-concerns)
- [End-to-End Happy Path Workflow](#end-to-end-happy-path-workflow)
- [Summary](#summary)

---

## Group 1: First-Time Setup & Database Configuration

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-1.1 | Check system initialization status | Any (unauthenticated) | — |
| UC-1.2 | Test database connection | Any (before init) / Admin (after) | admin |
| UC-1.3 | Provision database (run migrations) | Any (before init) / Admin (after) | admin |
| UC-1.4 | Check database migration status | Admin | admin |
| UC-1.5 | Update database connection settings | Admin | admin |
| UC-1.6 | Initialize system (create first admin) | Any (unauthenticated, one-time) | — |

**UI Implication:** A setup wizard flow that detects uninitialized state and guides through UC-1.2 → UC-1.3 → UC-1.6 sequentially.

---

## Group 2: Authentication & Session Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-2.1 | Log in with local credentials (PAM) | Any user | — |
| UC-2.2 | Log in with OIDC/SSO token | Any user | — |
| UC-2.3 | View current session info (username, roles, token expiry) | Authenticated user | any |
| UC-2.4 | Log out / end session | Authenticated user | any |
| UC-2.5 | Handle expired token (re-authenticate prompt) | Authenticated user | any |

**UI Implication:** Login page with identity provider selector (local vs. OIDC). Session indicator in UI header showing username, role badges, and expiry countdown.

---

## Group 3: User & Role Management (Admin Only)

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-3.1 | List all users with role assignments | Admin | admin |
| UC-3.2 | View roles for a specific user | Admin | admin |
| UC-3.3 | Assign/replace roles for a user | Admin | admin |
| UC-3.4 | Remove all roles for a user | Admin | admin |
| UC-3.5 | Create an OS user account | Admin | admin |
| UC-3.6 | List OS user accounts | Admin | admin |
| UC-3.7 | Reset a user's password | Admin | admin |
| UC-3.8 | Delete an OS user account | Admin | admin |
| UC-3.9 | Set/modify a user's OS group memberships | Admin | admin |
| UC-3.10 | List groups | Admin | admin |
| UC-3.11 | Create an OS group *(API only; not exposed in current UI)* | Admin | admin |
| UC-3.12 | Delete an OS group *(API only; not exposed in current UI)* | Admin | admin |

**UI Implication:** Admin panel uses a single editable users table with role selection, per-user save actions, password reset, and user creation with role picker. Group listing/management is API-only in the current UI build.

---

## Group 4: Drive Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-4.1 | View all USB drives (state, filesystem, project, capacity) | Any authenticated user | any |
| UC-4.2 | Filter/search drives by state (EMPTY, AVAILABLE, IN_USE) | Any authenticated user | any |
| UC-4.3 | Trigger USB discovery refresh | Admin, Manager | admin, manager |
| UC-4.4 | Format a drive (select ext4 or exfat) | Admin, Manager | admin, manager |
| UC-4.5 | Initialize a drive for a project (bind project ID) | Admin, Manager | admin, manager |
| UC-4.6 | Prepare a drive for safe eject | Admin, Manager | admin, manager |
| UC-4.7 | View drive detail (serial, port, device path, mount history) | Any authenticated user | any |
| UC-4.8 | List USB ports with enablement state | Admin, Manager | admin, manager |
| UC-4.9 | Enable a USB port for ECUBE use | Admin, Manager | admin, manager |
| UC-4.10 | Disable a USB port | Admin, Manager | admin, manager |
| UC-4.11 | List USB hubs with hardware metadata | Admin, Manager | admin, manager |
| UC-4.12 | Set/update hub location hint | Admin, Manager | admin, manager |
| UC-4.13 | Set/update port friendly label | Admin, Manager | admin, manager |

**UI Implication:** Drive inventory dashboard with state-based color indicators and a finite-state-machine visual. Action buttons (Format, Initialize, Eject) contextually enabled based on current drive state. Project binding shown prominently on IN_USE drives. Port management panel (accessible to admin/manager) showing all USB ports with enable/disable toggles — disabled ports prevent drives from becoming AVAILABLE during discovery, and AVAILABLE drives on a subsequently disabled port are demoted to EMPTY on the next sync. IN_USE drives are never affected by port enablement. Hub and port listing displays enriched hardware metadata (vendor/product IDs, link speed). Admins and managers can assign human-readable labels (hub location hints, port friendly labels) for easier physical identification.

---

## Group 5: Mount Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-5.1 | List all network mounts with status | Any authenticated user | any |
| UC-5.2 | Add a new NFS mount | Admin, Manager | admin, manager |
| UC-5.3 | Add a new SMB mount (with credentials) | Admin, Manager | admin, manager |
| UC-5.4 | Remove a network mount | Admin, Manager | admin, manager |
| UC-5.5 | Validate a specific mount (test connectivity) | Admin, Manager | admin, manager |
| UC-5.6 | Validate all mounts (batch connectivity check) | Admin, Manager | admin, manager |

**UI Implication:** Mount list with status badges (MOUNTED/UNMOUNTED/ERROR). Add-mount form with protocol selector (NFS vs SMB) that conditionally shows credential fields. Validate button per mount and a "Validate All" bulk action.

---

## Group 6: Export Job Workflow

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-6.1 | Create an export job (project, evidence #, source, drive, threads) | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2 | Start a copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.3 | Monitor job progress (status, bytes copied, file count) | Any authenticated user | any |
| UC-6.4 | View per-file status within a job | Any authenticated user | any |
| UC-6.5 | Verify copied data (post-copy hash verification) | Admin, Manager, Processor | admin, manager, processor |
| UC-6.6 | Generate manifest on USB drive | Admin, Manager, Processor | admin, manager, processor |
| UC-6.7 | View file hashes (MD5/SHA-256) for an individual file | Admin, Auditor | admin, auditor |
| UC-6.8 | Compare two files by hash | Any authenticated user | any |

**UI Implication:** Job creation wizard (select mount → select drive → enter project/evidence metadata → configure threads → submit). Job monitoring dashboard with progress bars, real-time byte counters, and per-file status table. Post-copy action buttons for Verify and Generate Manifest. End-to-end workflow guided experience: Mount → Drive → Job → Copy → Verify → Manifest → Eject.

---

## Group 7: Audit & Compliance

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-7.1 | Browse audit logs (paginated, most recent first) | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.2 | Filter audit logs by user | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.3 | Filter audit logs by action type | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.4 | Filter audit logs by job ID | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.5 | Filter audit logs by date range | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.6 | View audit entry details (structured JSON metadata) | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.7 | Export/download audit logs | Admin, Manager, Auditor | admin, manager, auditor |

**UI Implication:** Audit log viewer with multi-filter sidebar (user, action type dropdown, job ID, date range picker). Paginated table with expandable detail rows showing the JSON `details` payload. Export button for compliance reporting.

---

## Group 8: System Monitoring & Introspection

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-8.1 | View system health (DB connectivity, active jobs, resource usage) | Any authenticated user | any |
| UC-8.2 | View API / application version | Any (unauthenticated) | — |
| UC-8.3 | View USB hub/port topology | Any authenticated user | any |
| UC-8.4 | View block device metadata | Any authenticated user | any |
| UC-8.5 | View mounted filesystems | Any authenticated user | any |
| UC-8.6 | View job debug info | Admin, Auditor | admin, auditor |
| UC-8.7 | List application log files | Any authenticated user | any |
| UC-8.8 | Download a specific log file | Any authenticated user | any |

**UI Implication:** Dashboard/status page showing health indicators, USB topology diagram, and system resource metrics. Log viewer for remote troubleshooting without SSH access.

---

## Cross-Cutting UI Concerns

| Concern | Description |
|---------|-------------|
| **Role-based UI gating** | Hide or disable actions the current user's role cannot perform. Never rely on UI-only enforcement — the API enforces authorization. |
| **Error handling** | Map 401 → re-login prompt, 403 → "insufficient permissions" message with role hint, 409 → state conflict explanation. |
| **Project isolation visibility** | Prominently show project binding on drives and jobs. Prevent accidental cross-project operations in the UI flow. |
| **Real-time updates** | Job progress monitoring via REST polling (baseline). Consider WebSocket upgrade path for live progress. |
| **Data redaction** | Credentials never shown in mount list or audit details. Device paths redacted where sensitive. |
| **Responsive/accessible** | Appliance may be accessed from various devices on the network. |

---

## End-to-End Happy Path Workflow

The primary operational workflow combines use cases across groups:

1. **Setup** (one-time): UC-1.1 → UC-1.2 → UC-1.3 → UC-1.6 → UC-2.1
2. **Prepare infrastructure**: UC-5.2/5.3 (add mounts) → UC-4.3 (discover drives) → UC-4.8/4.9 (enable ports) → UC-4.4 (format) → UC-4.5 (initialize for project)
3. **Execute export**: UC-6.1 (create job) → UC-6.2 (start) → UC-6.3 (monitor) → UC-6.5 (verify) → UC-6.6 (manifest)
4. **Eject & hand off**: UC-4.6 (eject drive)
5. **Audit trail**: UC-7.1–7.7 (review compliance)

---

## Summary

- **50 use cases** across **8 functional groups**
- Organized by functional domain (matching the administration guide structure), which maps naturally to UI screens/pages
- Each use case maps to one or more existing API endpoints
- The setup wizard (Group 1) is a distinct UX flow from the main application
- Audit log export (UC-7.7) may require a dedicated API endpoint — currently only query/pagination is supported

