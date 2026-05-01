# ECUBE UI Use Cases

| Field | Value |
|---|---|
| Title | UI Use Cases |
| Purpose | Provides a catalog of ECUBE user interface use cases that define expected UI behavior for design, development, and QA validation. |
| Updated on | 04/28/26 |
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
| UC-4.1 | View all USB drives (state, filesystem, project, total capacity, and last known available space) | Any authenticated user | any |
| UC-4.2 | Filter/search drives by state (DISCONNECTED, AVAILABLE, IN_USE) | Any authenticated user | any |
| UC-4.3 | Trigger USB discovery refresh | Admin, Manager | admin, manager |
| UC-4.4 | Format a drive (select ext4 or exfat) | Admin, Manager | admin, manager |
| UC-4.5 | Initialize a mounted drive for a project from eligible mounted-share assignments | Admin, Manager | admin, manager |
| UC-4.6 | Mount a drive to the managed ECUBE mount root | Admin, Manager | admin, manager |
| UC-4.7 | Prepare a drive for safe eject | Admin, Manager | admin, manager |
| UC-4.8 | View drive detail (status, project, total capacity, last known available space, with protected device and path fields) | Any authenticated user | any |
| UC-4.9 | List USB ports with enablement state | Admin, Manager | admin, manager |
| UC-4.10 | Enable a USB port for ECUBE use | Admin, Manager | admin, manager |
| UC-4.11 | Disable a USB port | Admin, Manager | admin, manager |
| UC-4.12 | List USB hubs with hardware metadata | Admin, Manager | admin, manager |
| UC-4.13 | Set/update hub location hint | Admin, Manager | admin, manager |
| UC-4.14 | Set/update port friendly label | Admin, Manager | admin, manager |

**UI Implication:** Drive inventory dashboard with state-based color indicators and a finite-state-machine visual. Action buttons (Format, Initialize, Mount, Eject) are contextually enabled based on current drive state. When a drive is tied to a job, the Drives page now surfaces the related `Project` and `Job ID`, with `Job ID` acting as the drive-to-job navigation entry point and `Project` showing the associated project for that same resolved job context. The Drives page no longer shows a `Size` column; capacity and last known available space remain on Drive Detail instead. The drive detail screen shows the same related `Job ID` in its metadata area using the same underlying job-association source of truth. The drive detail screen also shows project binding prominently, includes total capacity plus last known available space, offers a Mount action for admin and manager users when the drive has a usable filesystem path and is not already mounted, disables the Format action while the drive is mounted, uses a `Browse` button for mounted-drive directory access instead of a raw mount-path link, and redacts sensitive device and path fields in standard operator views. The Enable Drive action is shown only for admin and manager users when a DISCONNECTED drive is still physically detected on a known port; historically known but absent drives remain non-actionable in the UI. The Initialize dialog now uses a project dropdown populated only from eligible mounted shares, shows protected mounted-destination context for the selected drive, remains blocked until the destination drive itself is mounted, disables submission when prerequisites are missing, and preserves drive state and project binding when the operator cancels. Prepare Eject can require a second explicit confirmation when active assignments include timed-out or failed files; the first attempt surfaces a confirmation-required warning dialog, and the second confirm action proceeds with eject. After Prepare Eject, the UI offers a direct path into the Chain of Custody report workflow. Port management panel (accessible to admin/manager) shows all USB ports with enable/disable toggles — disabled ports prevent drives from becoming AVAILABLE during discovery, and AVAILABLE drives on a subsequently disabled port are demoted to DISCONNECTED on the next sync. IN_USE drives are never affected by port enablement. After restart, the UI may show a previously mounted managed drive restored to its expected ECUBE mount slot without an additional operator Mount action. Hub and port listing displays enriched hardware metadata (vendor/product IDs, link speed). Admins and managers can assign human-readable labels (hub location hints, port friendly labels) for easier physical identification.

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
| UC-5.7 | Discover available SMB shares or NFS exports from the Add Mount dialog | Admin, Manager | admin, manager |

**UI Implication:** Mount list with status badges (MOUNTED/UNMOUNTED/ERROR). The add-mount dialog requires a project assignment together with the protocol and remote path fields, supports optional SMB credentials, and is fully keyboard accessible with focus management and live error feedback. In add mode, `admin` and `manager` users can use `Browse` to discover SMB shares or NFS exports from the entered server seed; the dialog reuses any entered credentials, opens a secondary scrollable share-selection dialog, and selecting a result fills the `Remote path` field. The browse-share control is hidden in demo mode, and when required host discovery tooling is missing the dialog surfaces actionable guidance telling the operator which host package to install. The same dialog is reused for `Edit`, preserving stored credential values when the operator leaves credential fields blank and providing a dedicated `Clear saved credentials` action when the operator needs to remove them explicitly. The dialog rejects exact duplicate remote paths and cross-project parent or child overlaps with inline conflict feedback, while same-project nested paths remain allowed. If another operator submits the same or overlapping mount change at nearly the same time, the UI shows a non-destructive conflict message and no duplicate entry is created. Raw remote paths and local mount points are redacted in the standard table view, while Browse is exposed as a button and remains enabled only for active mounted shares. If an edit returns a mount object with `ERROR` status, the dialog stays open so the operator can review the failure state instead of following a success-only close path. Validate button per mount and a `Validate All` bulk action remain available. After restart, ECUBE may automatically remove stale ECUBE-managed `/nfs/*` or `/smb/*` mount points that no longer match persisted system state before the operator returns to the Mounts page.

---

## Group 6: Export Job Workflow

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-6.1 | Create an export job (project, evidence #, source, drive, threads) | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2 | Start a copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2a | Pause a running copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2b | Resume a paused copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2c | Edit a pending, paused, or failed job from Job Detail | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2d | Manually complete a safe non-active job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2da | Archive a completed or failed job after explicit confirmation | Admin, Manager | admin, manager |
| UC-6.2e | Delete a pending job with confirmation | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2f | Clear persisted startup-analysis cache from Job Detail | Admin, Manager | admin, manager |
| UC-6.2g | Run manual startup analysis from Job Detail before starting copy | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2h | Retry failed file copies from Job Detail after a partial-success completion with only failed terminal files re-queued | Admin, Manager, Processor | admin, manager, processor |
| UC-6.3 | Monitor job progress, startup preparing state, and sanitized failed-job summaries | Any authenticated user | any |
| UC-6.3a | Review a completed job with partial file failures | Any authenticated user | any |
| UC-6.3b | Resume follow-up work from retained startup-analysis cache after partial completion | Admin, Manager, Processor | admin, manager, processor |
| UC-6.4 | View per-file status within a job with collapsible paged file review | Any authenticated user | any |
| UC-6.5 | Verify copied data (post-copy hash verification) | Admin, Manager, Processor | admin, manager, processor |
| UC-6.6 | Generate manifest on USB drive | Admin, Manager, Processor | admin, manager, processor |
| UC-6.7 | View file hashes (MD5/SHA-256) for an individual file | Admin, Auditor | admin, auditor |
| UC-6.8 | Compare the source and destination versions of an exported file | Admin, Auditor | admin, auditor |

**UI Implication:** Job creation now uses a grouped dialog rather than a step-by-step wizard. The operator selects a project first, which unlocks the `Job details`, `Source`, `Destination`, and `Execution` sections. Source mounts and destination drives are filtered to the selected project and currently eligible mounted resources, and the dialog exposes helper states when no projects, mounts, or drives are available. The source path is resolved on the trusted backend relative to the selected mounted share, / selects the mounted-share root, and traversal outside that share is blocked. When a mounted drive is selected, the target destination path is derived automatically from the drive mount point. The destination selector is labeled `Select device` and uses the same port-based `Device` value shown on the Drives page and in the Jobs list. If the selected drive or mount becomes unavailable, the UI/API flow surfaces a specific conflict message. The dialog also provides an optional `Run job immediately` control. The Jobs list now exposes a `Device` column plus row-level `Details`, `Start`, and `Pause` controls with state-aware availability; on smaller screens it hides lower-priority columns, renders compact status indicators, and moves row actions into an overflow menu. The list excludes archived jobs by default, adds a `Show Archived Jobs` toggle, and includes an `Archived` status filter when operators need to review sunset work items. During startup analysis, Dashboard and Jobs list progress can show `Preparing...` before a numeric percentage is available, and Job Detail can show `Preparing copy...` with explanatory text while ECUBE scans the source files and calculates totals. Job Detail also supports manual `Analyze` before copy start, surfaces startup-analysis state and summary values after the scan completes, and can replace the started message with a completed message when the page stays open during the run. The top Job Detail summary now includes the selected destination, the related drive's last known available space when present, and the job-specific callback URL. If the Jobs page remains open while analysis finishes, the page can show a completion banner for the affected job. For failed, paused, or partially successful jobs that still have a persisted startup-analysis snapshot, Job Detail can expose a `Clear startup analysis cache` action for `admin` and `manager` only; the action opens a confirmation dialog, removes only the cached startup-analysis snapshot, and forces the next restart to perform a fresh source scan. For a partial-success `COMPLETED` job with failed or timed-out file rows, Job Detail can also expose `Retry Failed Files` for `admin`, `manager`, and `processor`; the button stays hidden for read-only users, appears only when at least one failed or timed-out file remains, re-queues only those failed terminal files, leaves successful copies unchanged, and returns the job to `RUNNING` for the narrowed retry set. `admin` and `manager` users can archive `COMPLETED` or `FAILED` jobs through a confirmation dialog that explains the recreation impact; once archived, the job remains viewable but lifecycle actions stay disabled and the Archive action is no longer shown. The same partial-success state now also turns the completion summary panel red so the operator can identify a failed-copy completion at a glance before opening the separate failure details. The Files panel on Job Detail now starts collapsed, expands through `Show files`, preserves the current page when re-collapsed, and opens hash inspection from the file path itself instead of a separate button. When a file row includes a safe `error_message`, the row is emphasized and the `ERROR` or `FAILED` status badge becomes the entry point for a `File Error Details` dialog instead of showing a separate details column. Hash inspection and source/destination comparison now share a popup dialog, and smaller screens use a shorter page-number window plus compact file-status indicators to keep the panel within the viewport. While startup analysis is actively running, Job Detail disables conflicting lifecycle actions, including `Retry Failed Files`, keeping Delete and cache-clear visible only when otherwise eligible but not actionable until the analyze run finishes. On smaller screens, Job Detail keeps the highest-priority lifecycle buttons visible and moves the remaining actions into an overflow menu without changing role-based availability. The Job Detail page adds `Edit`, `Complete`, pending-only `Delete`, and eligible `Archive` controls, keeps `Verify` and `Generate Manifest` disabled until the job is truly 100% complete with no failed or timed-out files remaining, and shows a visible success banner with the stable manifest location after generation. The compare workflow uses `Source` and `Destination` terminology to compare the original file against the copied result. Dashboard, Jobs list, and Job Detail progress displays stay synchronized and conservative while a job is active so operators do not see 100% before file completion catches up. Paused, completed, failed, and archived jobs expose a summary with start time, copy threads, files copied, files failed, files timed out, total copied, elapsed time, copy rate, and failure context as applicable. A `COMPLETED` job can still carry failed or timed-out file counters after a partial-success run, and the detail view keeps those safe per-file failure summaries visible without exposing raw provider errors or host paths. Failed jobs prefer a persisted sanitized job-level reason when available, including stable timeout text or `Unexpected copy failure` plus safe relative `source:` and `destination:` hints. Those timing metrics remain cumulative across pause and resume cycles, and restart flows may reuse a still-current startup-analysis snapshot instead of repeating the full initial analysis. End-to-end workflow guided experience: Source Mount → Drive Mount → Job → Optional Analyze or Edit → Copy → Pause/Resume as needed → Review partial-success results if needed → Retry Failed Files when needed → Verify after a clean retry completion → Manifest → Optional Archive for terminal jobs that should be recreated later → Eject.

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
| UC-7.15 | Print or export the formatted chain-of-custody report for compliance records | Admin, Manager, Auditor | admin, manager, auditor |

**UI Implication:** Audit and chain-of-custody now live on separate surfaces:

1. **Audit Logs** (UC-7.1–7.7): Traditional log viewer with multi-filter sidebar (user, action type dropdown, job ID, date range picker). Paginated table with expandable detail rows showing the JSON `details` payload. Dedicated `Export Audit CSV` button for compliance reporting.

	Startup reconciliation may add `MOUNT_RECONCILED` and `DRIVE_MOUNT_RECONCILED` entries when ECUBE restores expected managed mounts or removes orphan managed mount points during service startup.

2. **Chain of Custody** (UC-7.8–7.15): Job Detail exposes a dedicated `Chain of Custody` action that opens a compliance-focused CoC dialog for the current job. The dialog loads the last stored snapshot, shows a `Generated At` timestamp sourced from that stored snapshot metadata, lets `admin` and `manager` users explicitly refresh and persist a new snapshot, and exposes `Print CoC`, `Export CoC CSV`, and `Export JSON` against the stored snapshot currently loaded in the dialog. The same dialog contains the handoff confirmation form, prefill controls, and warning modal for `admin` and `manager` users only. After handoff, the custody transfer is recorded while the drive remains governed by the normal operational lifecycle, and archived jobs continue to expose their last stored CoC snapshot for read-only review.

---

## Group 8: System Monitoring & Introspection

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-8.1 | View host and ECUBE process health (DB connectivity, active jobs, resource usage, active copy-thread correlation) | Any authenticated user | any |
| UC-8.2 | View API / application version | Any (unauthenticated) | — |
| UC-8.3 | View USB hub/port topology | Any authenticated user | any |
| UC-8.4 | View block device metadata | Any authenticated user | any |
| UC-8.5 | View mounted filesystems | Any authenticated user | any |
| UC-8.7 | Select the active or rotated application log source from the Logs tab | Admin | admin |
| UC-8.8 | Download the currently selected log source from the Logs toolbar | Admin | admin |
| UC-8.9 | Scroll within the log viewer to page to older or newer content for the selected source | Admin | admin |

**UI Implication:** Dashboard/status page showing health indicators, hidden empty USB rows, and system resource metrics. The Dashboard active-jobs table now makes the `Job ID` column actionable so operators can jump directly into Job Detail for a running or pending job; rows without a valid job ID stay non-actionable rather than rendering a broken control. In the System Health tab, operators now see separate host metrics and ECUBE process diagnostics, followed by an Active Copy Threads table or a clear empty state when no copy workers are active. On wider screens, the USB Topology and Mounts tabs show fuller diagnostic tables; on smaller screens, they keep the most important columns visible and move the remaining USB or mount metadata into per-row overflow menus. The admin-only Logs tab provides a source selector for the active log and eligible rollover files, auto-loads the selected source, supports bounded scroll-driven paging within the viewer, and downloads the currently selected source from the toolbar for remote troubleshooting without SSH access.

---

## Group 9: Runtime Configuration (Admin Only)

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-9.1 | View current runtime configuration settings | Admin | admin |
| UC-9.2 | Update logging settings (`log_level`, `log_format`, log rotation) | Admin | admin |
| UC-9.3 | Enable/disable file logging and set log file path | Admin | admin |
| UC-9.4 | Update copy and DB pool runtime settings (`copy_job_timeout`, `job_detail_files_page_size`, `db_pool_size`, `db_pool_max_overflow`) | Admin | admin |
| UC-9.5 | Review restart-required changes after save | Admin | admin |
| UC-9.6 | Request ECUBE service restart from UI confirmation dialog | Admin | admin |

**UI Implication:** Admin-only `Configuration` page provides editable logging, copy job timeout, Job Detail files-per-page, and DB pool fields, localized error handling, and a restart-required panel. Save applies supported changes immediately where possible and lists deferred settings that require service restart.

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
2. **Prepare infrastructure**: UC-5.2/5.3 (add mounts) → UC-4.3 (discover drives) → UC-4.9/4.10 (enable ports) → UC-4.4 (format) → UC-4.6 (mount drive) → UC-4.5 (initialize for project)
3. **Execute export**: UC-6.1 (create job using the mounted destination) → UC-6.2c (optional edit before run) → UC-6.2 (start) → UC-6.3 (monitor) → UC-6.2a/UC-6.2b (pause/resume if needed) → UC-6.5 (verify once fully complete) → UC-6.6 (manifest)
4. **Eject & chain of custody**: UC-4.7 (prepare eject) → UC-7.8/7.10 (retrieve CoC) → UC-7.13 (confirm handoff) → UC-7.14 (dismiss warning) → UC-7.15 (save report for records) → custody transfer is recorded for the job
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
