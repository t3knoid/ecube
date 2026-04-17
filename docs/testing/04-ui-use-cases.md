# ECUBE UI Use Cases

| Field | Value |
|---|---|
| Title | UI Use Cases |
| Purpose | Provides a catalog of ECUBE user interface use cases that define expected UI behavior for design, development, and QA validation. |
| Updated on | 04/11/26 |
| Audience | UI designers, developers, QA. |

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
- [Group 9: Runtime Configuration (Admin Only)](#group-9-runtime-configuration-admin-only)
- [Group 10: Help System](#group-10-help-system)
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

**UI Implication:** Login page supports credential-based sign-in and session-expiry handling. Session state is enforced by router guards with redirects to `/login` (expired/auth-required) and `/setup` (uninitialized systems).

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

### Group 3 QA Checklist: Create User Modal Behavior

Use this checklist when validating UI behavior for UC-3.5 (create user), UC-3.6 (list users), and UC-3.7 (reset password).

| Check | Steps | Expected |
|---|---|---|
| Existing user confirmation prompt appears | In `Users` click `Create User`, enter a username that already exists in OS/directory identity, choose roles, click `Create` | Create dialog closes and confirmation dialog appears with existing-user wording |
| Existing user confirm path | In confirmation dialog click `Add to ECUBE` | Confirmation dialog closes, user is linked to ECUBE roles, no password dialog is shown |
| Existing user cancel path | In confirmation dialog click `Cancel` | Dialog closes and screen returns to Users page (create dialog does not reopen) |
| New user deferred password prompt | Create a brand-new username with roles and click `Create` | Password dialog appears after create attempt |
| Password confirmation enforcement | Enter non-matching password/confirm password in password dialog | Validation message appears and submit action remains disabled |
| Password show/hide control | Toggle the show/hide password control in password dialog | Password fields toggle between masked and plain text |
| New user completion | Enter matching password values and submit | Password dialog closes and new user appears in Users list with selected roles |
| Directory-backed role visibility | Link a directory-backed user into ECUBE roles and refresh Users page | User remains visible in list even when host-enumeration fields are placeholders |

---

## Group 4: Drive Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-4.1 | View all USB drives (state, filesystem, project, capacity, mount point) | Any authenticated user | any |
| UC-4.2 | Filter/search drives by state (DISCONNECTED, AVAILABLE, IN_USE, ARCHIVED) | Any authenticated user | any |
| UC-4.3 | Trigger USB discovery refresh | Admin, Manager | admin, manager |
| UC-4.4 | Format a drive (select ext4 or exfat) | Admin, Manager | admin, manager |
| UC-4.5 | Initialize a drive for a project from eligible mounted-share assignments | Admin, Manager | admin, manager |
| UC-4.6 | Mount a drive to the managed ECUBE mount root | Admin, Manager | admin, manager |
| UC-4.7 | Prepare a drive for safe eject | Admin, Manager | admin, manager |
| UC-4.8 | View drive detail (status, project, capacity, with protected device and path fields) | Any authenticated user | any |
| UC-4.9 | List USB ports with enablement state | Admin, Manager | admin, manager |
| UC-4.10 | Enable a USB port for ECUBE use | Admin, Manager | admin, manager |
| UC-4.11 | Disable a USB port | Admin, Manager | admin, manager |
| UC-4.12 | List USB hubs with hardware metadata | Admin, Manager | admin, manager |
| UC-4.13 | Set/update hub location hint | Admin, Manager | admin, manager |
| UC-4.14 | Set/update port friendly label | Admin, Manager | admin, manager |

**UI Implication:** Drive inventory dashboard with state-based color indicators and a finite-state-machine visual. Action buttons (Format, Initialize, Mount, Eject) are contextually enabled based on current drive state. The drive detail screen shows project binding prominently, offers a Mount action for admin and manager users when the drive has a usable filesystem path and is not already mounted, and redacts sensitive device and path fields in standard operator views. The Initialize dialog now uses a project dropdown populated only from eligible mounted shares, blocks submission when no such share exists, and remains fully keyboard-operable. After Prepare Eject, the UI offers a direct path into the Chain of Custody report workflow. Port management panel (accessible to admin/manager) shows all USB ports with enable/disable toggles — disabled ports prevent drives from becoming AVAILABLE during discovery, and AVAILABLE drives on a subsequently disabled port are demoted to DISCONNECTED on the next sync. IN_USE drives are never affected by port enablement. Hub and port listing displays enriched hardware metadata (vendor/product IDs, link speed). Admins and managers can assign human-readable labels (hub location hints, port friendly labels) for easier physical identification.

---

## Group 5: Mount Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-5.1 | List all network mounts with status | Any authenticated user | any |
| UC-5.2 | Add a new NFS mount with a project assignment | Admin, Manager | admin, manager |
| UC-5.3 | Add a new SMB mount with credentials and a project assignment | Admin, Manager | admin, manager |
| UC-5.4 | Remove a network mount | Admin, Manager | admin, manager |
| UC-5.5 | Validate a specific mount (test connectivity) | Admin, Manager | admin, manager |
| UC-5.6 | Validate all mounts (batch connectivity check) | Admin, Manager | admin, manager |

**UI Implication:** Mount list with status badges (MOUNTED/UNMOUNTED/ERROR). The add-mount dialog requires a project assignment together with the protocol and remote path fields, supports optional SMB credentials, and is fully keyboard accessible with focus management and live error feedback. Raw remote paths and local mount points are redacted in the standard table view, while Browse is enabled only for active mounted shares. Validate button per mount and a "Validate All" bulk action remain available.

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
| UC-6.8 | Compare two files by hash | Admin, Auditor | admin, auditor |

**UI Implication:** Job creation wizard (select source mount → select mounted destination drive → enter project/evidence metadata → configure threads → submit). When a mounted drive is selected, the target destination path is derived automatically from the drive mount point. If the assigned drive is not mounted, the UI/API flow returns a conflict that instructs the operator to mount the drive first. Job monitoring dashboard with progress bars, real-time byte counters, and per-file status table. Post-copy action buttons for Verify and Generate Manifest. End-to-end workflow guided experience: Source Mount → Drive Mount → Job → Copy → Verify → Manifest → Eject.

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
| UC-7.8 | Retrieve chain-of-custody report by drive ID | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.9 | Retrieve chain-of-custody report by drive serial number | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.10 | Retrieve chain-of-custody report by project ID | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.11 | View chain-of-custody events (lifecycle timeline) | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.12 | View manifest summary in chain-of-custody report | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.13 | Confirm custody handoff with possessor and delivery details | Admin, Manager | admin, manager |
| UC-7.14 | Acknowledge permanent archive warning before handoff | Admin, Manager | admin, manager |
| UC-7.15 | Print or save chain-of-custody report for compliance records | Admin, Manager, Auditor | admin, manager, auditor |

**UI Implication:** The Audit section includes two sub-areas:

1. **Audit Logs** (UC-7.1–7.7): Traditional log viewer with multi-filter sidebar (user, action type dropdown, job ID, date range picker). Paginated table with expandable detail rows showing the JSON `details` payload. Export button for compliance reporting.

2. **Chain of Custody** (UC-7.8–7.15): Compliance-focused CoC report viewer with selector panel (drive ID dropdown, drive serial input, project ID dropdown), lifecycle timeline showing custody events, manifest inventory per job, handoff confirmation form with pre-filled defaults, and permanent-archive warning confirmation modal. Print and save actions generate compliance-ready output. After handoff, drives transition to `ARCHIVED` and are excluded from all CoC searches.

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
| UC-8.7 | List application log files | Admin | admin |
| UC-8.8 | Download a specific log file | Admin | admin |

**UI Implication:** Dashboard/status page showing health indicators, USB topology diagram, and system resource metrics. Log viewer for remote troubleshooting without SSH access.

---

## Group 9: Runtime Configuration (Admin Only)

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-9.1 | View current runtime configuration settings | Admin | admin |
| UC-9.2 | Update logging settings (`log_level`, `log_format`, log rotation) | Admin | admin |
| UC-9.3 | Enable/disable file logging and set log file path | Admin | admin |
| UC-9.4 | Update DB pool hot settings (`db_pool_size`, `db_pool_max_overflow`) | Admin | admin |
| UC-9.5 | Review restart-required changes after save | Admin | admin |
| UC-9.6 | Request ECUBE service restart from UI confirmation dialog | Admin | admin |

**UI Implication:** Admin-only `Configuration` page provides editable logging and DB pool fields, localized error handling, and a restart-required panel. Save applies supported changes immediately where possible and lists deferred settings that require service restart.

---

## Group 10: Help System

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-10.1 | Open Help from authenticated shell | Authenticated user | any |
| UC-10.2 | View curated in-app help content in modal | Authenticated user | any |
| UC-10.3 | Open full help document from modal | Authenticated user | any |
| UC-10.4 | Handle missing help asset with non-fatal fallback state | Authenticated user | any |

**UI Implication:** Persistent Help trigger in shell (header/footer/sidebar), modal rendering of generated static help HTML sourced from the user manual pipeline, and non-blocking fallback behavior when help asset loading fails.

---

## Cross-Cutting UI Concerns

| Concern | Description |
|---------|-------------|
| **Role-based UI gating** | Hide or disable actions the current user's role cannot perform. Never rely on UI-only enforcement — the API enforces authorization. |
| **Error handling** | Map 401 → re-login prompt, 403 → "insufficient permissions" message with role hint, 409 → state conflict explanation. |
| **Project isolation visibility** | Prominently show project binding on drives and jobs. Prevent accidental cross-project operations in the UI flow. |
| **Real-time updates** | Job progress monitoring via REST polling (baseline). Consider WebSocket upgrade path for live progress. |
| **Navigation diagnostics** | Router guards and click/route-completion hooks emit debug telemetry (`UI_NAVIGATION_*`) for troubleshooting; this is operational telemetry, not compliance audit data. |
| **Data redaction** | Credentials never shown in mount list or audit details. Device paths redacted where sensitive. |
| **Responsive/accessible** | Appliance may be accessed from various devices on the network. |

---

## End-to-End Happy Path Workflow

The primary operational workflow combines use cases across groups:

1. **Setup** (one-time): UC-1.1 → UC-1.2 → UC-1.3 → UC-1.6 → UC-2.1
2. **Prepare infrastructure**: UC-5.2/5.3 (add mounts) → UC-4.3 (discover drives) → UC-4.9/4.10 (enable ports) → UC-4.4 (format) → UC-4.5 (initialize for project) → UC-4.6 (mount drive)
3. **Execute export**: UC-6.1 (create job using the mounted destination) → UC-6.2 (start) → UC-6.3 (monitor) → UC-6.5 (verify) → UC-6.6 (manifest)
4. **Eject & chain of custody**: UC-4.7 (prepare eject) → UC-7.8/7.10 (retrieve CoC) → UC-7.13 (confirm handoff) → UC-7.14 (dismiss warning) → UC-7.15 (save report for records) → drive transitions to `ARCHIVED`
5. **Audit trail**: UC-7.1–7.7 (review operational audit) + UC-7.8–7.12 (validate handoff in compliance record)
6. **Operational tuning (admin, optional)**: UC-9.1 → UC-9.2/UC-9.4 → UC-9.5 → UC-9.6
7. **Contextual assistance (optional)**: UC-10.1 → UC-10.2/UC-10.3 during any workflow stage

---

## Summary

- **75 use cases** across **10 functional groups**
- Organized by functional domain (matching the administration automation guide structure), which maps naturally to UI screens/pages
- Each use case maps to one or more existing UI/backend integration points
- The setup wizard (Group 1) is a distinct UX flow from the main application
- Runtime configuration workflows (Group 9) are admin-only and include restart-aware UX for deferred settings
- Help workflows (Group 10) provide in-app user guidance sourced from generated user-manual content

## References

- [docs/testing/01-automated-test-requirements.md](01-automated-test-requirements.md)
- [docs/design/14-ui-wireframes.md](../design/14-ui-wireframes.md)
