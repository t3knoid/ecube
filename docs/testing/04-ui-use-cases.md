# ECUBE UI Use Cases

| Field | Value |
|---|---|
| Title | UI Use Cases |
| Purpose | Provides a catalog of ECUBE user interface use cases that define expected UI behavior for design, development, and QA validation. |
| Updated on | 05/12/26 |
| Audience | UI designers, developers, QA. |

## Table of Contents

- [Table of Contents](#table-of-contents)
- [Group 1: First-Time Setup \& Database Configuration](#group-1-first-time-setup--database-configuration)
- [Group 2: Authentication \& Session Management](#group-2-authentication--session-management)
- [Group 3: User \& Role Management (Admin Only)](#group-3-user--role-management-admin-only)
- [Group 4: Drive Management](#group-4-drive-management)
- [Group 5: Share Management](#group-5-share-management)
- [Group 6: Export Job Workflow](#group-6-export-job-workflow)
- [Group 7: Audit \& Compliance](#group-7-audit--compliance)
- [Group 8: System Monitoring \& Introspection](#group-8-system-monitoring--introspection)
- [Group 9: Runtime Configuration](#group-9-runtime-configuration)
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

**UI Implication:** A setup wizard flow that detects uninitialized state and guides through UC-1.2 → UC-1.3 → UC-1.6 sequentially. The final admin-account step now requires the operator to enter the password twice and blocks completion with a visible validation message until the password and confirmation values match. In demo mode, the wizard can complete setup with the configured demo admin account and should still land in the normal success state even when that account already exists on the host, because the immediate post-setup demo reconciliation no longer re-prompts or fails solely on a redundant same-password reset for that one setup-managed account.

---

## Group 2: Authentication & Session Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-2.1 | Log in with local credentials (PAM) | Any user | — |
| UC-2.2 | Log in with OIDC/SSO token | Any user | — |
| UC-2.3 | View current session info (username, roles, token expiry) | Authenticated user | any |
| UC-2.4 | Log out / end session | Authenticated user | any |
| UC-2.5 | Handle expired token (re-authenticate prompt) | Authenticated user | any |
| UC-2.6 | Recover from expired local password with forced change dialog | Local authenticated user | — |
| UC-2.7 | Submit self-service password change during expired-password recovery | Local authenticated user | — |
| UC-2.8 | View and dismiss password-expiry warning banner after login | Authenticated local user | any |

**UI Implication:** Login page supports credential-based sign-in, session-expiry handling, and expired-password recovery. Session state is enforced by router guards with redirects to `/login` (expired/auth-required) and `/setup` (uninitialized systems). If `POST /auth/token` returns `401` with `reason: password_expired`, the login page opens a non-dismissible password-change dialog that requires the current password plus matching new-password confirmation, lists the active password rules inline, and keeps backend `422` PAM policy errors in that dialog instead of routing them through the global toast handler. After a successful login inside the password warning window, the dashboard shows a dismissible banner with the remaining days until expiration; dismissal is session-scoped only. If a normal API call later returns the backend setup-required `503` contract, the shared frontend client also returns the browser to `/setup` instead of leaving the operator on a generic server-error dead end.

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
| UC-4.1 | View all USB drives from the Drives list (ID, device, project, status, and related job context when present) | Any authenticated user | any |
| UC-4.2 | Filter/search drives by state (DISABLED, AVAILABLE, IN_USE) and optionally include DISCONNECTED rows | Any authenticated user | any |
| UC-4.3 | Trigger USB discovery refresh | Admin, Manager | admin, manager |
| UC-4.4 | Format a drive (select ext4 or exfat) | Admin, Manager | admin, manager |
| UC-4.5 | Initialize a mounted drive for a project from eligible mounted-share assignments | Admin, Manager | admin, manager |
| UC-4.6 | Mount a drive to the managed ECUBE mount root | Admin, Manager | admin, manager |
| UC-4.7 | Prepare a drive for safe eject | Admin, Manager | admin, manager |
| UC-4.8 | View drive detail from the Drives list using the clickable drive ID (status, project, negotiated USB speed when available, total capacity, last known available space, with protected device and path fields) | Any authenticated user | any |
| UC-4.8a | Measure mounted-drive write throughput from Drive Detail and review the latest stored result | Admin, Manager | admin, manager |
| UC-4.9 | List USB ports with enablement state | Admin, Manager | admin, manager |
| UC-4.10 | Enable a USB port for ECUBE use | Admin, Manager | admin, manager |
| UC-4.11 | Disable a USB port | Admin, Manager | admin, manager |
| UC-4.12 | List USB hubs with hardware metadata | Admin, Manager | admin, manager |
| UC-4.13 | Set/update hub location hint | Admin, Manager | admin, manager |
| UC-4.14 | Set/update port friendly label | Admin, Manager | admin, manager |

**UI Implication:** Drive inventory dashboard with state-based color indicators and a finite-state-machine visual. Action buttons (Format, Initialize, Mount, Eject) are contextually enabled based on current drive state. The Drives page uses the `Drive ID` value itself as the direct navigation entry point into Drive Detail, and when a managed mount path is present it uses the visible `Device` identifier as the browse entry point into mounted content instead of a separate `Browse` row action. The resulting browse panel uses that same visible device identifier in its title and keeps the breadcrumb root-relative so the host mount path is not exposed in the operator UI. When a drive is tied to a job, the Drives page surfaces the related `Project` and `Job ID`, with `Job ID` acting as the drive-to-job navigation entry point and `Project` showing the associated project for that same resolved job context. The Drives page does not show a `Size` column; capacity and last known available space remain on Drive Detail instead. The drive detail screen shows the same related `Job ID` in its metadata area using the same underlying job-association source of truth. The drive detail screen also shows project binding prominently, includes negotiated USB speed when available, total capacity, last known available space, latest stored write-throughput results, and offers a Mount action plus a mounted-drive `Test Throughput` action for admin and manager users when the drive is in a valid managed mounted state. The throughput action persists the latest measured write speed and timestamp for later read-only review. The drive detail screen disables the Format action while the drive is mounted, submits accepted format requests into a background flow that shows an in-progress banner and disables conflicting drive actions until the format finishes, uses the visible device identifier for mounted-drive directory access instead of a raw mount-path link, and keeps the browse panel root-relative for the same redaction reason. The Enable Drive action is shown only for admin and manager users when a physically present `DISABLED` drive is detected on a known port; that state is distinct from absent `DISCONNECTED` hardware and promotes to `AVAILABLE` after the port is enabled and discovery reconciles the device. The Drives page defaults to hiding `DISCONNECTED` rows and exposes a `Show Disconnected drives` checkbox when operators need that broader inventory view. The Initialize dialog uses a project dropdown populated only from eligible mounted shares, shows protected mounted-destination context for the selected drive, remains blocked until the destination drive itself is mounted, disables submission when prerequisites are missing, and preserves drive state and project binding when the operator cancels. Prepare Eject remains available for `IN_USE` drives and is also available when an `AVAILABLE` drive is still mounted; it can require a second explicit confirmation when active assignments include timed-out or failed files. After Prepare Eject, the UI offers a direct path into the Chain of Custody report workflow. Port management panel (accessible to admin/manager) shows all USB ports with enable/disable toggles — disabled ports prevent drives from becoming AVAILABLE during discovery, and AVAILABLE drives on a subsequently disabled port are demoted to `DISABLED` on the next sync. `DISCONNECTED` is reserved for absent hardware, and `IN_USE` drives are never affected by port enablement. After restart, the UI may show a previously mounted managed drive restored to its expected ECUBE mount slot without an additional operator Mount action. The System USB Topology listing displays enriched hardware metadata including vendor/product IDs and negotiated link speed. Admins and managers can assign human-readable labels (hub location hints, port friendly labels) for easier physical identification.

---

## Group 5: Share Management

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-5.1 | List all network shares with status | Any authenticated user | any |
| UC-5.2 | Add a new NFS share with a project assignment | Admin, Manager | admin, manager |
| UC-5.3 | Add a new SMB share with credentials and a project assignment | Admin, Manager | admin, manager |
| UC-5.4 | Remove a network share | Admin, Manager | admin, manager |
| UC-5.5 | Test candidate mount connectivity inside the Add or Edit Share dialog | Admin, Manager | admin, manager |
| UC-5.6 | Browse a mounted network share from the Shares list or Share Detail | Admin, Manager, Processor | admin, manager, processor |
| UC-5.7 | Discover available SMB shares or NFS exports from the Add Share dialog | Admin, Manager | admin, manager |
| UC-5.8 | Measure mounted-share read throughput from Share Detail and review the latest stored result | Admin, Manager | admin, manager |

**UI Implication:** Shares list with status badges (MOUNTED/UNMOUNTED/ERROR). The Shares page uses the share ID value itself as the direct navigation entry point into Share Detail, and for mounted shares it uses the visible `Project` value as the browse entry point instead of a separate `Browse` row action for `admin`, `manager`, and `processor`. The resulting browse panel uses that same project value in the title form `Browse share <project> contents`, while the mounted-share breadcrumb starts at `/` rather than a share label and must never render a doubled leading slash. When a share matches a project with an existing job, the Shares page surfaces the related `Job ID` beside the project and uses that value as a direct navigation entry point to Job Detail; rows without a valid related job keep the cell non-actionable. `Edit` and `Remove` move to Share Detail so the list stays focused on discovery and navigation while the detail page owns share-specific management actions. Share Detail shows Type, Project, NFS Client version, Last Checked, latest stored read-throughput results, Job ID, Job Status, and share Status for all permitted viewers. The related `Job Status` field is sourced from trusted backend job data for the same related job shown in the `Job ID` field, shows `No related job` when the share has no current related job, and shows `Status unavailable` instead of guessing when authoritative related-job status cannot be determined. Share Detail exposes `Browse` for mounted shares only to `admin`, `manager`, and `processor`, keeps `Edit`/`Remove` restricted to `admin` and `manager`, and adds a mounted-share `Test Throughput` action for `admin` and `manager` that persists the latest measured read speed and timestamp for later read-only review. Raw Remote Path and Local Mount Point values stay redacted for read-only roles and are only shown in Share Detail to admin and manager users. Auditor users can still open the Shares page and Share Detail, but they receive read-only project text rather than browse actions. The add-share dialog requires a project assignment together with the protocol and remote path fields, supports optional SMB credentials, and is fully keyboard accessible with focus management and live error feedback. In add mode, `admin` and `manager` users can use `Browse` to discover SMB shares or NFS exports from the entered server seed; the dialog reuses any entered credentials, opens a secondary scrollable share-selection dialog, and selecting a result fills the `Remote path` field, including when demo mode is enabled. Connectivity testing is performed inside the Add Share and Edit Share dialogs rather than from list-level validation controls. A passing Add Share or Edit Share test can show both the standard success banner and a warning banner when validation returns operator guidance, including advisories that the effective `NFS 4.1` validation path is slow on the current server while a validation-only `NFS 3` probe completes much faster, even when the dialog is left on `Use default (4.1)`. The edit dialog on Share Detail preserves stored credential values when the operator leaves credential fields blank and provides a dedicated `Clear saved credentials` action when the operator needs to remove them explicitly. Saving edits on an active share attempts an immediate remount with the updated options, so per-share NFS client-version overrides take effect without deleting and recreating the share definition. The dialog rejects exact duplicate remote paths and cross-project parent or child overlaps with inline conflict feedback, while same-project nested paths remain allowed. If another operator submits the same or overlapping share change at nearly the same time, the UI shows a non-destructive conflict message and no duplicate entry is created. Raw remote paths and local mount points stay redacted in the standard table view, and Share Detail preserves that redaction for read-only roles while still providing browse and navigation context. After restart, ECUBE may automatically remove stale ECUBE-managed `/mnt/ecube-network/*` mount points that no longer match persisted system state before the operator returns to the Shares page.

---

## Group 6: Export Job Workflow

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-6.1 | Create an export job (project, evidence #, source, drive, threads) | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2 | Start a copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2a | Pause a running copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2b | Resume a paused copy job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2c | Edit a pending job from Job Detail, including after startup analysis completes while the job remains pending | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2d | Manually complete a safe non-active job | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2da | Archive a completed or failed job after explicit confirmation | Admin, Manager | admin, manager |
| UC-6.2e | Delete a pending job with confirmation | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2f | Clear persisted startup-analysis cache from Job Detail | Admin, Manager | admin, manager |
| UC-6.2g | Run manual startup analysis from Job Detail before starting copy | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2h | Retry failed file copies from Job Detail after a partial-success completion with only failed terminal files re-queued | Admin, Manager, Processor | admin, manager, processor |
| UC-6.2i | Block Job Detail start when startup analysis already shows the assigned drive is too small | Admin, Manager, Processor | admin, manager, processor |
| UC-6.3 | Monitor job progress, startup preparing state, and sanitized failed-job summaries | Any authenticated user | any |
| UC-6.3a | Review a completed job with partial file failures | Any authenticated user | any |
| UC-6.3b | Resume follow-up work from retained startup-analysis cache after partial completion | Admin, Manager, Processor | admin, manager, processor |
| UC-6.3c | Review Job Detail information panels and source totals as trusted job metadata becomes available | Any authenticated user | any |
| UC-6.4 | View per-file status within a job with collapsible paged file review | Any authenticated user | any |
| UC-6.5 | Verify copied data (post-copy hash verification) | Admin, Manager, Processor | admin, manager, processor |
| UC-6.6 | Download an auto-generated manifest from Job Detail | Admin, Manager, Processor | admin, manager, processor |
| UC-6.7 | View file hashes (MD5/SHA-256) for an individual file | Admin, Auditor | admin, auditor |
| UC-6.8 | Compare the source and destination versions of an exported file | Admin, Auditor | admin, auditor |

**UI Implication:** Job creation uses a grouped dialog. The operator selects a project first, which unlocks the `Job details`, `Source`, `Destination`, and `Execution` sections. The same grouped dialog shell is reused for Job Detail edits, which means Create and Edit share the same grouped layout, required-field marker pattern, footer legend, pinned header/footer scrolling behavior, and modal keyboard contract while allowing Edit to omit create-only sections such as overflow selection and `Run job immediately`. When the grouped dialog opens, focus moves into the first actionable field, `Tab` stays trapped inside the modal while it remains open, and dismissing it with `Escape` or the cancel path returns focus to the triggering control. Source shares and destination drives are filtered to the selected project and currently eligible mounted resources, and the dialog exposes helper states when no projects, shares, or drives are available. The source path is resolved on the trusted backend relative to the selected mounted share, / selects the mounted-share root, and traversal outside that share is blocked. In the shared dialog workflow, the visible `Source path` field becomes read-only after project selection and is updated through the trusted `Browse folders` action only. The `Source` section includes an inline directory browser scoped to the currently selected mounted share, shows only directories, updates the existing `Source path` field as the operator traverses folders, and exposes a `..` row for moving to the parent folder when the current folder is below the share root. When a mounted drive is selected, the target destination path is derived automatically from the drive mount point. The destination selector is labeled `Select device` and uses the same port-based `Device` value shown on the Drives page and in the Jobs list. If the selected drive or share becomes unavailable, the UI/API flow surfaces a specific conflict message. If an operator explicitly selects a primary or overflow drive that is not yet bound to the selected project, the create or edit flow rejects the save and tells the operator to initialize and bind the drive before selecting it. The dialog also provides an optional `Run job immediately` control during creation. During create, `Thread count` can stay on `Use configured default`, which omits a per-job override so the job inherits the manager-configured worker count until the operator picks a specific value. The Jobs list exposes a `Device` column, uses the visible `Job ID` value as the direct navigation entry point into Job Detail, and keeps one desktop lifecycle toggle per row with state-aware availability. That same toggle shows `Start` for startable or resumable jobs, transitions to a visible disabled `Pause` while the job is still entering copy work during `PREPARING`, stays visible as a disabled `Pause` while a pause request is still draining in-flight work during `PAUSING`, and becomes disabled or hidden for other ineligible states, while smaller screens move the existing detail action and lifecycle toggle into an overflow menu. The list excludes archived jobs by default, adds a `Show Archived Jobs` toggle, and includes an `Archived` status filter when operators need to review sunset work items. During startup analysis, Dashboard and Jobs list progress can show `Preparing...` before a numeric percentage is available, and Job Detail can show `Preparing copy...` with explanatory text while ECUBE scans the source files and calculates totals. Job Detail and Dashboard keep `Duration` as the full active lifecycle value while live `Copy rate`, `Time remaining`, and `Estimated completion` use the copy phase only after the job has entered `RUNNING`. Job Detail also supports manual `Analyze` before copy start and surfaces startup-analysis state and summary values after the scan completes. Within Job Detail, `Current Task` appears before `Job Information` and reuses the same trusted `Next Step` and follow-up guidance the Dashboard derives from job and custody state. `Job Information` is split into `Job details`, `Source Information`, and `Destination Information` panels. `Job details` appears first and shows the user-entered thread count, job-specific callback URL, and notes captured during job creation. `Source Information` shows the trusted source path together with `Discovered files`, `Estimated total bytes`, `Analysis status`, and `Last data analyzed`; the count and size fields show `N/A` until trusted job data provides source totals, then update in place without moving to another panel. `Destination Information` shows the selected destination drive, available space, files copied, and either the list of overflow drives or `None` when no overflow assignments exist. During `VERIFYING`, the shared progress surface stays visible but changes to verification-specific text rather than implying an exact verification percentage. While the job remains `PENDING`, `Edit` still exposes the pre-start edit surface for supported copy-definition fields. After the job has started, Job Detail keeps `Edit` available only as a restricted runtime-tuning dialog that allows thread-count changes and reserved overflow-drive selection changes without reopening project, source, primary destination, notes, or callback edits. If the Jobs page remains open while analysis finishes, the page can show a completion banner for the affected job. If ECUBE restarts while a manual analyze run is still marked `ANALYZING`, startup reconciliation removes that stale lockout before operators return: current cached results reappear as `READY`, otherwise the job returns to a fresh `NOT_ANALYZED` state so Analyze or Start can be used again. If startup analysis is already `READY` and the related drive's last known available-space reading is too small for the estimated source bytes, pressing `Start` keeps the job out of `RUNNING`, leaves it in `PREPARING`, and surfaces an operator-safe shortfall message that directs the operator to another drive or the follow-on overflow workflow. If a running copy later hits a `target_full` failure, Job Detail reflects one of two system-layer outcomes: ECUBE either continues automatically onto the next already-assigned drive that is still project-compatible and passes the trusted backend free-space probe, or it stops the job in `FAILED` with a sanitized destination-capacity reason so the operator can use `Continue on Another Drive` as the follow-up workflow. For failed, paused, or partially successful jobs that still have a persisted startup-analysis snapshot, Job Detail can expose a `Clear startup analysis cache` action for `admin` and `manager` only; the action opens a confirmation dialog, removes only the cached startup-analysis snapshot, and forces the next restart to perform a fresh source scan. For a partial-success `COMPLETED` job with failed or timed-out file rows, Job Detail can also expose `Retry Failed Files` for `admin`, `manager`, and `processor`; the button stays hidden for read-only users, appears only when at least one failed or timed-out file remains, re-queues only those failed terminal files, leaves successful copies unchanged, returns the job to `PREPARING` for the narrowed retry set, and then resumes `RUNNING` after preparation completes. `admin` and `manager` users can archive `COMPLETED` or `FAILED` jobs through a confirmation dialog that explains the recreation impact; once archived, the job remains viewable, `Edit` is not shown, lifecycle actions stay disabled where they still provide context, the lifecycle toggle is hidden, and the Archive action is not shown. The same partial-success state also turns the completion summary panel red so the operator can identify a failed-copy completion at a glance before opening the separate failure details. The Files panel on Job Detail starts collapsed, expands through `Show files`, preserves the current page when re-collapsed, and uses the file path as the entry point for hash inspection. When a file row includes a safe `error_message`, the row is emphasized and the `ERROR` or `FAILED` status badge becomes the entry point for a `File Error Details` dialog without a separate details column. Hash inspection and source/destination comparison share a popup dialog, and smaller screens use a shorter page-number window plus compact file-status indicators to keep the panel within the viewport. While startup analysis is actively running, Job Detail disables conflicting lifecycle actions, including `Retry Failed Files`, keeping Delete and cache-clear visible only when otherwise eligible but not actionable until the analyze run finishes. On smaller screens, Job Detail keeps the highest-priority lifecycle buttons visible and moves the remaining actions into an overflow menu without changing role-based availability. The Job Detail page adds pending-only `Delete` and eligible `Archive` controls, keeps `Verify` and `Download Manifest` disabled until the job is truly 100% complete with no failed or timed-out files remaining, and shows a visible success banner with the stable manifest location when the browser download starts. Clean completion auto-generates the backing `manifest.json` before that download action becomes useful. The compare workflow uses `Source` and `Destination` terminology to compare the original file against the copied result. Dashboard, Jobs list, and Job Detail progress displays stay synchronized and conservative while a job is active so operators do not see 100% before file completion catches up. Paused, completed, failed, and archived jobs expose a summary with start time, copy threads, files copied, files failed, files timed out, total copied, elapsed time, copy rate, and failure context as applicable. A `COMPLETED` job can still carry failed or timed-out file counters after a partial-success run, and the detail view keeps those safe per-file failure summaries visible without exposing raw provider errors or host paths. Failed jobs prefer a persisted sanitized job-level reason when available, including stable timeout text, destination-capacity exhaustion guidance for `target_full`, or `Unexpected copy failure` plus safe relative `source:` and `destination:` hints. Those timing metrics remain cumulative across pause and resume cycles, and restart flows may reuse a still-current startup-analysis snapshot and avoid repeating the full initial analysis. End-to-end workflow guided experience: Source Share → Optional Source Folder Browser → Drive Mount → Job → Optional Analyze or full pending-only Edit while the job has not started → Start or retry enters `PREPARING` while ECUBE validates or reuses startup-analysis results → Restricted runtime edit remains available after start only for thread count and reserved overflow-drive changes → Copy → Pause/Resume as needed through the lifecycle toggle → Review partial-success results if needed → Retry Failed Files when needed or Continue on Another Drive after a destination-capacity failure → Verify after a clean retry completion → Download Manifest → Optional Archive for terminal jobs that should be recreated later → Eject.

---

## Group 7: Audit & Compliance

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-7.1 | Browse audit logs (paginated, most recent first) | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.2 | Filter audit logs by distinct user values | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.3 | Filter audit logs by distinct action values | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.4 | Filter audit logs by distinct job ID values | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.5 | Filter audit logs by date range across the full audit history | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.5a | Search audit logs by free-text substring across visible fields | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.6 | View audit entry details (structured JSON metadata) | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.7 | Export/download audit logs | Admin, Manager, Auditor | admin, manager, auditor |
| UC-7.8 | Retrieve chain-of-custody report by drive ID | Admin, Manager, Processor, Auditor | admin, manager, processor, auditor |
| UC-7.9 | Retrieve chain-of-custody report by drive serial number | Admin, Manager, Processor, Auditor | admin, manager, processor, auditor |
| UC-7.10 | Retrieve chain-of-custody report by project ID | Admin, Manager, Processor, Auditor | admin, manager, processor, auditor |
| UC-7.11 | View chain-of-custody events (lifecycle timeline) | Admin, Manager, Processor, Auditor | admin, manager, processor, auditor |
| UC-7.11a | View a chain-of-custody report when no drive serial is available | Admin, Manager, Processor, Auditor | admin, manager, processor, auditor |
| UC-7.12 | View manifest summary in chain-of-custody report | Admin, Manager, Processor, Auditor | admin, manager, processor, auditor |
| UC-7.13 | Confirm custody handoff with possessor and delivery details | Admin, Manager | admin, manager |
| UC-7.14 | Acknowledge permanent archive warning before handoff | Admin, Manager | admin, manager |
| UC-7.15 | Print or export the formatted chain-of-custody report for compliance records | Admin, Manager, Auditor | admin, manager, auditor |

**UI Implication:** Audit and chain-of-custody now live on separate surfaces:

The chain-of-custody report surfaces the hardware drive serial when trusted identity data includes one and leaves the serial field blank when the drive identity has no serial component.

1. **Audit Logs** (UC-7.1–7.7): Traditional log viewer with server-backed pagination and filter controls populated from backend distinct values. The page supports user, action, job, date-range, and free-text search filters, shows the newest matching rows first, and expands individual rows to reveal the JSON `details` payload. Pagination uses numbered shortcut windows instead of simple previous/next-only controls: wider screens expose the current 10-page window while smaller screens reduce the shortcut window to 5 pages. A results summary above the table reports the current page count versus the total matching rows, an unfiltered empty audit store renders the default `No audit log entries are currently available.` message, and filtered no-match searches render a distinct empty state so operators can tell the difference between an empty audit store and an over-constrained query. `Export Audit CSV` exports the full filtered result set rather than only the currently visible page.

	Startup reconciliation may add `MOUNT_RECONCILED` and `DRIVE_MOUNT_RECONCILED` entries when ECUBE restores expected managed mounts or removes orphan managed mount points during service startup.

2. **Chain of Custody** (UC-7.8–7.15): Job Detail exposes a dedicated `Chain of Custody` action that becomes available only after the current job reaches `COMPLETED` and remains available on archived job detail pages for stored-report review. The action opens a compliance-focused CoC dialog for the current job. The dialog loads the last stored snapshot, shows a `Generated At` timestamp sourced from that stored snapshot metadata, lets `admin` and `manager` users explicitly refresh and persist a new snapshot, and exposes `Print CoC`, `Export CoC CSV`, and `Export JSON` against the stored snapshot currently loaded in the dialog for all read-enabled roles (`admin`, `manager`, `processor`, `auditor`). The same dialog contains the handoff confirmation form, prefill controls, and warning modal for `admin` and `manager` users only. After handoff, the custody transfer is recorded while the drive remains governed by the normal operational lifecycle, and archived jobs continue to expose their last stored CoC snapshot for read-only review.

---

## Group 8: System Monitoring & Introspection

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-8.1 | View host and ECUBE process health (DB connectivity, active jobs, resource usage, active copy-thread correlation) | Any authenticated user | any |
| UC-8.2 | View API / application version | Any (unauthenticated) | — |
| UC-8.3 | View USB hub/port topology | Admin, Manager, Processor | admin, manager, processor |
| UC-8.4 | View block device metadata | Admin, Manager, Processor | admin, manager, processor |
| UC-8.5 | View mounted filesystems | Admin, Manager, Processor | admin, manager, processor |
| UC-8.7 | Select the active or rotated application log source from the Logs tab | Admin, Manager | admin, manager |
| UC-8.8 | Download the currently selected log source from the Logs toolbar | Admin | admin |
| UC-8.9 | Scroll within the log viewer to page to older or newer content for the selected source | Admin, Manager | admin, manager |

**UI Implication:** Dashboard/status page showing health indicators, hidden empty USB rows, and system resource metrics. The Dashboard active-jobs table makes the `Job ID` column actionable so operators can jump directly into Job Detail for a running, preparing, or pending job; rows without a valid job ID remain plain text. The dashboard refreshes system health, drive state, share workflow counts, the `Needs Attention` section, and active jobs together on a recurring background interval, while the visible `Refresh` control triggers the same full snapshot on demand. The `Drive Summary` and `Shares Summary` entries also act as drill-down controls that route into the matching Drives or Shares page with the corresponding state or workflow bucket filter preselected. Operational users also see a `Shares Summary` card alongside `Drive Summary`, with authoritative counts for `Unassigned`, `Assigned`, `Active`, `Blocked`, `Custody Pending`, `Completed`, and `Unavailable` derived from each share's current related-job lifecycle state and custody progress. The separate `Needs Attention` section highlights blocked jobs, waiting-to-start assignments, and completed or archived jobs still waiting on custody closeout, and each row uses the owning `Job ID` as the direct link into Job Detail. The `Needs Attention` and active-jobs tables also show a read-only `Next Step` column derived from trusted lifecycle, startup-analysis, failed-file, and custody signals so processors and managers can triage without executing workflow actions directly from the dashboard. On wider screens, those same dashboard rows surface trusted source path, destination drive, and compact follow-up context such as failed-file counters or live-copy rate, time remaining, and estimated completion when the backend already provides those values, while missing drive context falls back to `N/A`. On smaller screens, the summary cards stack vertically, the dashboard hides the `Project` column in `Needs Attention` and `Active Jobs` to avoid horizontal overflow, compact status icons replace full badges, and the Active Jobs progress cell reduces to the percentage label while preserving `Next Step` guidance. The source-share label follows the existing mount-path role boundary so raw mount paths remain visible only to `admin` and `manager`, while `processor` sees a redacted value. In the share summary, `Assigned` is limited to shares whose related job exists but has not started yet, `Active` includes preparing, running, pausing, and verifying work, `Blocked` captures paused or failed work, `Custody Pending` holds completed or archived rows until custody is fully recorded, and `Unavailable` explicitly captures shares whose trusted related-job or custody state could not be derived so the dashboard does not silently undercount them. Mixed backend failures degrade only the affected shares and preserve the correct classifications for unrelated rows. Auditor users see a reduced dashboard summary limited to system health and database status; the drive-summary, shares-summary, needs-attention, and active-job panels stay hidden. In the System Health tab, operators see separate host metrics and ECUBE process diagnostics, a visible `Runtime Warnings` panel whenever the backend reports degraded but non-fatal host conditions, and an Active Copy Threads table or a clear empty state when no copy workers are active. `GET /introspection/system-health` exposes warning repair-action metadata only to `admin` callers, so `manager`, `processor`, and `auditor` users can still review warning details but do not receive action metadata from the backend or warning repair controls in the UI. When the backend exposes an explicit repair action for a warning, `admin` users can trigger it from the warning card through a confirmation dialog, and the page refreshes health after the action completes. When the backend cannot offer a repair adapter for the current warning, the warning still renders and no action button appears. If a repair action completes without clearing the warning, the System Health tab keeps the warning visible and surfaces the returned conflict message. On wider screens, the USB Topology and Mounts tabs show fuller diagnostic tables for `admin`, `manager`, and `processor`; on smaller screens, those same roles keep the most important columns visible and move the remaining USB or mount metadata into per-row overflow menus. Auditor users see only the `Health` tab. The Logs tab provides a source selector for the active log and eligible rollover files to `admin` and `manager`, auto-loads the selected source, supports bounded scroll-driven paging within the viewer, shows an explicit empty state when no eligible backend log files are present, and limits raw download to `admin` from the toolbar for remote troubleshooting without SSH access.

---

## Group 9: Runtime Configuration

| UC# | Use Case | Primary Actor | Roles |
|-----|----------|---------------|-------|
| UC-9.1 | View manager-accessible runtime configuration settings | Admin, Manager | admin, manager |
| UC-9.2 | Update manager-accessible operational settings (`log_level`, `copy_job_timeout`, `copy_chunk_size_bytes`, `copy_progress_flush_bytes`, `copy_default_thread_count`, `copy_file_fsync_enabled`, `job_detail_files_page_size`, `mkfs_exfat_cluster_size`, `drive_format_timeout_seconds`, `drive_mount_timeout_seconds`, `usb_discovery_interval`, `network_mount_timeout_seconds`, `mount_share_discovery_timeout_seconds`) | Admin, Manager | admin, manager |
| UC-9.3 | View and update admin-only logging and database runtime settings | Admin | admin |
| UC-9.4 | Enable/disable file logging and set log file path | Admin | admin |
| UC-9.5 | View and update PAM password-policy settings | Admin | admin |
| UC-9.6 | Review restart-required changes after save | Admin | admin |
| UC-9.7 | Request ECUBE service restart from UI confirmation dialog | Admin | admin |

**UI Implication:** The `Configuration` page is available to `admin` and `manager` users for operational settings including log verbosity, drive formatting and mounting defaults, Background Operations such as `Auto USB Discovery Interval (seconds)`, network mount timeouts, Job Detail files-per-page, and copy-engine tuning controls for `Copy Chunk Size`, `Progress Flush Threshold`, `Default Copy Worker Count`, and `Force per-file disk sync`. That same page also provides workload profile shortcuts for `Small-file heavy`, `Mixed workload`, `Large-file heavy`, and `Greedy throughput` so operators can apply a known tuning bundle before making individual adjustments. The admin-only `Admin` page retains logging infrastructure, database runtime, password-policy, webhook, and restart-required controls. Save applies supported operational changes immediately where possible and lists deferred admin-only settings that require service restart. When demo mode is enabled and `DEMO_SHARED_PASSWORD` is unset, the login screen's shared password is implicitly derived from the current Password Policy settings, so policy edits change the generated public password and require a later startup reconciliation to realign existing demo OS accounts.

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
