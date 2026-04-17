# ECUBE User Manual

| Field | Value |
|---|---|
| Title | ECUBE User Manual |
| Purpose | Guides end users, processors, managers, and auditors through day-to-day ECUBE workflows and operational tasks. |
| Updated on | 04/17/26 |
| Audience | Processors, managers, auditors, administrators, end users. |

## Table of Contents

1. [Purpose](#purpose)
2. [Scope](#scope)
3. [Installation Options](#1-installation-options)
4. [Before You Begin](#2-before-you-begin)
5. [Roles and Access](#3-roles-and-access)
6. [First Access](#4-first-access)
7. [Interface Overview](#5-interface-overview)
8. [Dashboard](#6-dashboard)
9. [Drives](#7-drives)
   - [Drive States](#71-drive-states)
   - [Formatting a Drive](#74-formatting-a-drive)
   - [Initializing a Drive](#75-initializing-a-drive)
   - [Prepare Eject](#76-prepare-eject)
10. [Mounts](#8-mounts)
11. [Jobs](#9-jobs)
12. [Job Detail, Verification, and File Review](#10-job-detail-verification-and-file-review)
13. [Audit Logs](#11-audit-logs)
   - [Chain of Custody Workflow](#111-chain-of-custody-workflow)
14. [Users](#12-users)
15. [System](#13-system)
   - [Application Logs Tab](#131-application-logs-tab)
16. [Common Tasks](#14-common-tasks)
17. [Troubleshooting](#15-troubleshooting)

---

## Purpose

This manual explains how to use the ECUBE web interface for day-to-day work. It focuses on tasks performed in the browser after the platform has already been deployed and made available by an administrator.

Primary workflows covered in this guide:

- Accessing the ECUBE web interface
- Understanding role-based navigation
- Viewing system status and drive state
- Creating and monitoring export jobs
- Reviewing job results, hashes, and file comparisons
- Managing mount definitions
- Viewing and exporting audit logs
- Accessing user and system pages when your role permits it
- Managing selected runtime configuration settings (admin-only)

## Scope

This guide is intended for users who interact with ECUBE through the web UI. It does not cover operating-system setup, service management, certificate provisioning, Docker administration, or backend troubleshooting.

For those topics, use the companion guides:

- [01-installation.md](01-installation.md) for packaged installation options
- [02-manual-installation.md](02-manual-installation.md) for native/manual deployment
- [03-docker-deployment.md](03-docker-deployment.md) for Docker Compose deployment
- [09-administration-automation-guide.md](09-administration-automation-guide.md) for administrative and API-driven tasks
- [11-api-quick-reference.md](11-api-quick-reference.md) for direct API usage

---

## 1. Installation Options

Most end users do not install ECUBE themselves, but it is still useful to understand how your environment may be delivered because the access URL, login expectations, and available integrations can vary slightly by deployment.

ECUBE is commonly provided in one of three ways:

### 1.1 Packaged Installation

An administrator installs ECUBE directly on a Linux host using the provided installer. This is the standard native or VM deployment for production-style environments.

What users should expect:

- A stable ECUBE URL provided by IT or the platform owner
- HTTPS access through the normal browser interface
- The backend API usually hidden behind the same web origin as the UI

### 1.2 Manual Installation

An administrator deploys ECUBE manually as a systemd-managed service. This is used when the installer cannot be used or when tighter enterprise controls are required. An optional external reverse proxy can be placed in front of ECUBE for additional TLS termination or load balancing.

What users should expect:

- The same browser experience as packaged installation
- Possible organization-specific hostnames, certificates, and login flow
- Split-host environments where frontend and backend are managed separately by IT

### 1.3 Docker Deployment

An administrator deploys ECUBE with Docker Compose. This is commonly used for testing, evaluation, and controlled containerized environments.

What users should expect:

- A browser URL such as `https://hostname:8443`
- The API typically reachable through the UI at `/api`
- The same UI workflows as other deployment methods

### 1.4 What Changes for the User

Regardless of installation method, the user-facing workflow is intended to remain the same:

- Open the ECUBE URL in a supported browser
- Authenticate with the account provided to you
- Use the navigation items allowed by your role
- Perform drive, mount, job, and audit tasks through the UI

The main differences between installations are usually:

- Hostname and port
- Certificate trust behavior
- Whether SSO, LDAP, or local login is used
- Whether the system has already been initialized by an administrator

---

## 2. Before You Begin

Before using ECUBE, make sure you have:

- A supported browser
- The correct ECUBE URL
- A valid user account and password or SSO-backed identity
- Permission for the tasks you need to perform

Supported browser targets for the current frontend:

- Google Chrome
- Microsoft Edge
- Safari

Use one of the latest two major browser versions maintained by your organization. Firefox is not currently a supported target for the frontend.

If you do not know your role, ask your ECUBE administrator. ECUBE uses role-based access control, so some pages and buttons are visible only to certain users.

---

## 3. Roles and Access

The UI adapts to the roles assigned to your account.

| Role | Typical Access |
| ---- | -------------- |
| `admin` | Full access to all UI areas, including user administration |
| `manager` | Drive, mount, and job oversight |
| `processor` | Create and manage export jobs, view system state |
| `auditor` | Read-only access to audit, job verification, and evidence review areas |

Common role effects in the UI:

- The `Audit` page is visible only to roles allowed to inspect audit records.
- The `Users` page is visible only to roles allowed to manage users.
- The `Configuration` page is visible only to `admin` users.
- Action buttons such as formatting or initializing drives may be disabled if your role does not permit them.

![Role-based navigation visibility (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/dashboard-default-chromium-linux.png)

---

## 4. First Access

### 4.1 First-Run Setup Screen

> **Access Summary**
> **Page visibility:** Unauthenticated users are redirected here only when the ECUBE system has not yet been initialized.
> **Intended operator:** Administrator or installer owner responsible for first-run setup.

If the system has not yet been initialized, ECUBE opens the setup wizard instead of the login page. This is typically completed by an administrator.

The setup wizard walks through:

1. Testing database connectivity
2. Provisioning the application database
3. Creating the first administrative account
4. Completing setup and returning to login

Important first-run behavior:

- If the admin username entered in setup does not yet exist on the host, ECUBE creates that OS user, adds it to `ecube-admins`, and grants the ECUBE `admin` role.
- If the admin username already exists on the host, ECUBE treats that as a reconciliation path instead of an error. The wizard adds the existing OS user to `ecube-admins`, syncs the ECUBE `admin` role, resets the password entered in the wizard, and then completes setup successfully.
- In the existing-user path, the setup screen shows an informational success message indicating that the existing OS admin user was reconciled.
- After either path completes, return to the login page and sign in with the username and password entered during setup.

If you are not responsible for installation, stop here and contact the administrator who owns the deployment.

![Setup wizard (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/setup-default-chromium-linux.png)

### 4.2 Login

> **Access Summary**
> **Page visibility:** Available to unauthenticated users after setup is complete.
> **Restricted actions:** None.

After setup is complete, open the ECUBE URL and sign in with your assigned username and password.

The login page includes:

- Username field
- Password field
- Login button
- Session-expired banner when you were redirected after token expiry
- Error banner for invalid credentials or connectivity failures

If login fails:

- Re-enter username and password carefully
- Confirm you are using the correct ECUBE URL
- Check whether your browser can reach the site over HTTPS
- Contact an administrator if your account may be locked, missing, or incorrectly assigned

![Login page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/login-default-chromium-linux.png)

---

## 5. Interface Overview

> **Access Summary**
> **Page visibility:** Available to authenticated users.
> **Restricted actions:** Navigation items shown in the shell depend on the roles assigned to your account.

After login, ECUBE displays a standard application shell:

- Header at the top
- Sidebar navigation on the left
- Main content area in the center
- Footer at the bottom

Common navigation items include:

- `Dashboard`
- `Drives`
- `Mounts`
- `Jobs`
- `Audit` (role-restricted)
- `System`
- `Users` (admin-only or otherwise restricted)
- `Configuration` (admin-only)

If you do not see a page described in this manual, your role may not include access to it.

![Application shell overview (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/dashboard-default-chromium-linux.png)

### 5.1 Theme Selection (Light/Dark/Custom)

> **Access Summary**
> **Page visibility:** Available to authenticated users.
> **Restricted actions:** None. Theme selection is user-level and does not require an elevated role.

To change your theme in the current session:

1. Open the theme selector in the top-right header area.
2. Choose the desired theme (for example `Light` or `Dark`).
3. Confirm visual changes are applied immediately.

How theme preference is stored:

- Theme choice is saved in browser local storage for that browser profile.
- Different browsers or machines may show different themes for the same user account.

Important default-theme note:

- The web UI currently does not provide an administrator control to set a system-wide default theme for all users.
- Platform administrators can still influence the deployment default by controlling which CSS is served as `default.css` in the mounted themes directory.

For deployment-side theme and branding management, see [14-theme-and-branding-guide.md](14-theme-and-branding-guide.md) and [04-configuration-reference.md](04-configuration-reference.md) (`ECUBE_THEMES_DIR`).

---

## 6. Dashboard

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `processor`, `auditor`
> **Restricted actions:** None described on this screen; use linked pages for operational actions.

The dashboard provides a quick operational summary.

Typical information shown:

- Overall system health
- Database status
- Number of active jobs
- Drive state summary (`DISCONNECTED`, `AVAILABLE`, `IN_USE`)
- Table of active jobs

Use the dashboard when you need a quick answer to questions such as:

- Is the system healthy?
- Are any jobs currently running or verifying?
- How many drives are ready for use?

The dashboard is intended for situational awareness, not full task execution. Use the dedicated pages for detailed operations.

![Dashboard overview (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/dashboard-default-chromium-linux.png)

---

## 7. Drives

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `processor`, `auditor`
> **Restricted actions:** Drive detail actions such as format, initialize, and prepare eject are currently enabled only for `admin` and `manager`.

The `Drives` page shows detected USB drives and their current state.

Typical drive fields include:

- Device identifier
- Filesystem type
- Capacity
- Assigned project
- Current state

Available actions depend on your role and the selected drive.

### 7.1 Drive States

Every drive moves through a defined set of states. Actions available in the UI depend on the current state.

| State | Meaning | Actions available |
|-----------|-------------------------------------------------------------------------|-----------------------------------|
| `DISCONNECTED` | Drive is known to the system but not currently accessible — either not physically present, or present on a disabled port. | Enable port |
| `AVAILABLE` | Drive is present on an enabled port and ready to be formatted or assigned to a project. | Format, Initialize |
| `IN_USE` | Drive is assigned to a project. Jobs can target this drive. | Prepare Eject |
| `ARCHIVED` | Drive has been permanently handed off via the Chain of Custody workflow. | None — drive is read-only. |

State transitions follow this order:

```
DISCONNECTED → AVAILABLE → IN_USE → AVAILABLE → ARCHIVED
                       ↑____________|
                     (re-insert same project)
```

A drive assigned to one project cannot be re-assigned to a different project without first being formatted. Formatting wipes the drive and clears the project binding.

### 7.2 Viewing Drives

Use the page controls to:

- Refresh the current drive list
- Trigger a rescan of connected drives
- Search by device or project information
- Filter by drive state
- Sort results

### 7.3 Drive Detail Page

Selecting a drive opens a detail view showing:

- Drive identifiers and filesystem details
- Current project assignment
- Current status badge
- Available actions such as format, initialize, and prepare eject

### 7.4 Formatting a Drive

If your role allows it, you can format a drive from the detail page.

Current UI options include:

- `ext4`
- `exfat`

Formatting removes all existing data and clears the project binding. After formatting, the drive can be initialized for any project that has an eligible mounted share.

Confirm the target drive carefully before proceeding.

### 7.5 Initializing a Drive

Initialization assigns a drive to a project identifier and transitions it to `IN_USE`. Once initialized, project isolation rules apply to all writes performed through ECUBE.

Initialization now requires at least one network share that is both assigned to the same project and currently in the `MOUNTED` state. If no eligible mounted share exists, the UI disables submission and the API rejects the request.

When you open the Initialize dialog:

- The **Project** field is shown as a dropdown populated from distinct project IDs on mounted shares only.
- If the drive has a previous project assignment and that project still has an eligible mounted share, that project is pre-selected.
- If no eligible mounted project exists, the dialog shows a helper message telling you to add and mount a share first.

Before initializing a drive:

- Confirm the correct source share for the case or matter has already been added and mounted.
- Select the correct project from the dropdown list.
- Confirm the drive is the intended destination media.
- If you need to assign the drive to a *different* project, format it first to clear the existing binding.

### 7.6 Prepare Eject

Use `Prepare Eject` before physically removing a drive. This flushes pending writes, unmounts the filesystem, and transitions the drive to `AVAILABLE`.

After a successful prepare-eject:

- The drive state returns to `AVAILABLE`.
- The project binding is preserved so the drive can be re-initialized for the same project without reformatting.
- The drive **cannot** be initialized for a *different* project until it has been formatted.
- The drive can be physically removed once the operation completes.

> To permanently retire a drive after removal, use the Chain of Custody handoff workflow on the `Audit` page. Confirming a handoff transitions the drive to `ARCHIVED`.

![Drives page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/drives-default-chromium-linux.png)

---

## 8. Mounts

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `processor`, `auditor`
> **Restricted actions:** The mounts page is currently available to all authenticated users in the frontend.

The `Mounts` page manages source locations used for export jobs.

You can typically:

- Refresh the mount list
- Validate all mounts
- Validate an individual mount
- Add a new mount definition
- Remove an existing mount definition

### 8.1 Adding a Mount

The add-mount dialog supports common fields such as:

- Type (`SMB` or `NFS`)
- Project ID
- Remote path
- Username
- Password
- Credentials file

Project assignment is required when creating a mount. Drives can only be initialized for projects that have at least one assigned share in the `MOUNTED` state.

ECUBE now creates the local mount point automatically based on the remote path and mount type (for example, NFS mounts are created under `/nfs/*` and SMB mounts under `/smb/*`).

The exact credential fields required depend on the mount type and your environment.

### 8.2 Testing Mount Connectivity

Use `Test` or `Test All` to verify that configured source mounts are reachable and valid before creating jobs that depend on them.

### 8.3 Removing a Mount

Remove a mount only if it is no longer needed. If existing workflows depend on it, removing the definition can interrupt job creation or repeatability.

![Mounts page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/mounts-default-chromium-linux.png)

---

## 8.4 Directory Browser

The directory browser allows users to explore the contents of active mount points (USB drives and network shares) before creating an export job.

**Accessing the browser:**

- **From Drive Detail:** Click the mount path link on any mounted drive to open the directory browser rooted at that drive's mount point.
- **From Mounts:** Click the mount point path on any active network mount.

**Navigating:**

- Click a folder name to descend into it. The breadcrumb trail at the top shows the current path.
- Click any breadcrumb segment to navigate back up.
- Symlinks appear with a link icon and are not navigable.
- Results are paginated; use the page controls at the bottom to navigate large directories.

**Roles:** All authenticated roles (`admin`, `manager`, `processor`, `auditor`) can browse directories.

> **Note:** Only active, registered mount points can be browsed. Arbitrary filesystem paths are not accessible through this feature.

---

## 9. Jobs

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `processor`, `auditor`
> **Restricted actions:** Creating jobs in the current UI is enabled for `admin`, `manager`, and `processor`.

The `Jobs` page is the main workspace for creating and tracking export operations.

The page includes:

- A jobs table
- Search and status filters
- Refresh action
- `Create Job` wizard

### 9.1 Viewing Jobs

Use the jobs table to review:

- Job ID
- Project ID
- Evidence number
- Current status
- Progress percentage

Common statuses include:

- `PENDING`
- `RUNNING`
- `VERIFYING`
- `COMPLETED`
- `FAILED`

### 9.2 Creating a Job

The job wizard is a four-step flow:

1. Select a target drive
2. Select a source mount
3. Enter project, evidence number, and source path
4. Choose thread count and create the job

Before creating a job, confirm:

- The correct destination drive is selected
- The correct source mount is selected
- The project ID matches the evidence being exported
- The source path is correct relative to the selected mount

### 9.3 Opening a Job

Open a job to view details and perform follow-up actions.

![Jobs list and create wizard (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/jobs-list-default-chromium-linux.png)

---

## 10. Job Detail, Verification, and File Review

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `processor`, `auditor`
> **Restricted actions:** `Start`, `Verify`, and `Manifest` actions are enabled for `admin`, `manager`, and `processor`. Hash inspection and debug-oriented file views are enabled for `admin` and `auditor`.

The job detail page provides deeper inspection and follow-up controls.

Typical functions include:

- Start a pending job
- Trigger verification
- Generate a manifest
- Review copied files
- Inspect hashes for individual files
- Compare two files

### 10.1 Starting, Verifying, and Generating a Manifest

Action buttons are shown near the top of the job detail screen.

Use them when appropriate:

- `Start` to begin the job
- `Verify` to run verification checks
- `Manifest` to generate the manifest output

### 10.2 File List

The file table usually shows:

- Relative path
- Status
- Size
- Checksum information

### 10.3 Hash Viewer

Users with sufficient permissions can inspect file hashes, including values such as:

- MD5
- SHA-256

### 10.4 Compare Two Files

The compare panel lets you select two files and evaluate whether they match.

Comparison output can include:

- Overall match
- Hash match
- Size match
- Path match

This is useful when reviewing evidence consistency or confirming repeatability after copy or verification steps.

![Job detail page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/job-detail-default-chromium-linux.png)

---

## 11. Audit Logs

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `auditor`
> **Restricted actions:** CSV export is available from the page for authorized users.

The `Audit` page is available only to authorized roles.

Use it to:

- Refresh recent audit activity
- Filter by user
- Filter by action
- Filter by date/time range
- Expand structured details for individual records
- Export the result set as CSV

The audit page is useful for review, compliance, and incident follow-up.

When exporting CSV:

- Review filters before export so the file contains the intended data set
- Treat exported audit data as sensitive operational evidence

![Audit page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/audit-default-chromium-linux.png)

### 11.1 Chain of Custody Workflow

Use the Chain of Custody panel on the `Audit` page to generate custody reports, prefill handoff fields, and record final transfer details when physical media leaves active operations.

Typical workflow:

1. Open `Audit`.
2. In the **Chain of Custody** section, filter by drive ID, drive serial, and/or project ID.
3. Click `Load CoC` to load custody report data.
4. Review the report card for the selected drive (drive ID, serial, project, manifest summary, and custody events).
5. Click `Prefill Handoff` to populate the handoff form from the selected report.
6. Enter required handoff details (`Possessor` and `Delivery Time`) and any optional receipt fields.
7. Click `Confirm Handoff`.
8. Review the **Permanent Archive Warning** modal.
9. Choose one of the following:
   - `Cancel`: closes the warning modal and does not record a handoff.
   - `Yes, archive drive`: records the handoff and archives the drive.

![Audit page with Chain of Custody panel (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/audit-default-chromium-linux.png)

![Drives page (related media lifecycle context, E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/drives-default-chromium-linux.png)

What happens when handoff is confirmed:

- The custody handoff event is written to the immutable audit trail.
- The selected drive is automatically transitioned to the `ARCHIVED` state.
- The drive is removed from active circulation workflows.
- The drive no longer appears in Chain of Custody search results intended for active media.
- Operational actions for that drive are blocked as part of archival enforcement.

Operational guidance:

- Treat `Yes, archive drive` as a finalization action.
- Verify drive ID, project, possessor, and delivery timestamp before confirming.
- Use `Cancel` if any custody detail needs correction before archival.

---

## 12. Users

> **Access Summary**
> **Page visibility:** `admin`
> **Restricted actions:** All user-management actions on this page are administrator-only.

The `Users` page is role-restricted and is generally intended for administrators.

Functions available from this page can include:

- Refreshing the current user list
- Creating an operating-system user for ECUBE access
- Assigning or removing ECUBE roles
- Resetting a user's password

### 12.1 Reset a User Password

**Allowed roles:** `admin`

1. Open `Users`.
2. Locate the target account in the users table.
3. Open the password reset action for that user.
4. Enter a temporary or policy-compliant new password.
5. Confirm the reset action.
6. Verify the UI shows a success confirmation.
7. Communicate the temporary password through your approved secure channel.
8. Require the user to change it at first sign-in if required by your policy.

Notes:

- Reset only ECUBE-managed accounts from this workflow.
- Use strong passwords that meet your organization security requirements.
- Record administrative password-reset actions according to your SOP.

If your role does not include access to this page, the navigation item will not appear.

![Users page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/users-default-chromium-linux.png)

### 12.2 Configuration Page (Administrator)

**Allowed roles:** `admin`

Use the `Configuration` page to update selected runtime settings from the UI without logging into the host terminal.

What this page is for:

- Adjusting logging behavior (level, format, and file logging options)
- Adjusting selected database pool settings exposed by the UI
- Applying safe configuration changes through role-restricted workflows

Basic workflow:

1. Open `Configuration` from the admin navigation area.
2. Review current values in each section.
3. Edit one or more fields.
4. Click `Save`.
5. Review post-save status: some changes apply immediately, and some changes are marked as pending restart.

Restart-required workflow:

1. If the page indicates that restart is required, review the listed changed settings.
2. Click `Restart Service` only when you are ready.
3. Read the confirmation dialog.
4. Confirm restart to submit the service restart request.
5. If you select cancel, no restart is triggered and the service keeps running.

Important operational notes:

- Restart actions are never automatic from this page and always require explicit confirmation.
- Restarting the application service can interrupt active operations. Prefer using a maintenance window or an idle period.
- If restart submission fails, use the displayed error and contact platform support or perform restart through approved host-level procedures.
- For field-by-field meaning and defaults, see [04-configuration-reference.md](04-configuration-reference.md).

If your role does not include access to this page, the navigation item will not appear.

![Configuration page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/configuration-default-chromium-linux.png)

---

## 13. System

> **Access Summary**
> **Page visibility:** `admin`, `manager`, `processor`, `auditor`
> **Restricted actions:** Most diagnostics on this page are relevant to administrators and support personnel. Log viewing is admin-only.

The `System` page provides operational and diagnostic information. Depending on deployment and permissions, this may include system health, USB information, block-device data, mount diagnostics, application logs, and job-debug details.

This page is useful when:

- Confirming the backend is healthy
- Checking whether hardware is visible to ECUBE
- Reviewing mount or log details during issue investigation
- Investigating system errors or performance issues via application logs (admin-only)

End users who only perform evidence exports may rarely need this page. Administrators and support personnel are more likely to use it during troubleshooting.

![System page (E2E snapshot, default theme, Chromium/Linux)](../../frontend/e2e/theme.spec.js-snapshots/system-default-chromium-linux.png)

### 13.1 Application Logs Tab

**Access:** `admin` role only

The **Logs** tab allows administrators to view recent application log lines in real time without requiring SSH or command-line access to the ECUBE host. This is useful for diagnosing system issues, checking for errors, and monitoring application behavior.

#### Viewing Logs

1. Open the `System` page.
2. Click the **Logs** tab (visible to admins only).
3. The tab displays recent log lines from the application log file.
4. Log entries are displayed in reverse chronological order (newest first).
5. File metadata shows:
   - **Source:** Log source display path (basename only, for example `app.log`)
   - **Fetched at:** Viewer-local date/time (converted by the browser from the UTC timestamp returned by the API)
   - **File modified:** Last modification time of the log file

#### Searching Logs

1. Enter a search term in the **Search** field.
2. Only log lines containing your search term will be displayed.
3. The search is case-insensitive.
4. Click **Refresh** to rerun the search with fresh log data.

#### Pagination

1. The current Logs tab UI does not expose **Limit** or **Offset** controls.
2. Log results are fetched using the UI's built-in defaults and refreshed with the **Refresh** action.
3. A total-count indicator (for example, "X of Y lines") is not currently shown in the UI.

#### Automatic Redaction

All sensitive values are automatically redacted from displayed log lines:

- **Passwords and tokens:** Any field containing password, secret, api_key, or token values are masked (e.g., `password=[REDACTED]`)
- **Authorization headers:** Bearer tokens in Authorization headers are sanitized
- **Credential-like values:** Other sensitive patterns (e.g., sensitive JSON fields) are masked

This redaction occurs automatically; you cannot bypass it via search or filter options.

#### Refreshing Log Data

1. Click the **Refresh** button to retrieve the latest log entries.
2. The displayed lines update immediately with the most recent data from the log file.
3. If the log file has been rotated or is unavailable, an appropriate error message appears.

#### Troubleshooting Log Viewing

If the Logs tab shows an error or is unavailable:

- Verify you have the `admin` role (non-admin users will not see this tab).
- Check that the application log file exists on the ECUBE host.
- Verify the ECUBE service account has read permissions on the log file.
- Consult [15. Troubleshooting](#15-troubleshooting) for service-level issues.

Governance note: denied log access attempts by non-admin users are recorded in the audit trail for accountability and compliance visibility.

---

## 14. Common Tasks

### 14.1 Insert a New Drive and Associate It with a Project

**Allowed roles:** `admin`, `manager`

1. Insert the new USB drive into the ECUBE host.
2. Open `Mounts` and confirm the correct source share for the project has been added, assigned to the project ID, and is currently `MOUNTED`.
3. Open `Drives`.
4. Refresh or rescan the drive list until the new device appears.
5. Open the drive detail page.
6. If the drive is not yet formatted (state is `DISCONNECTED` or filesystem shows `unformatted`), format it using the intended filesystem.
7. Click `Initialize`, choose the project from the dropdown list, and submit.
8. Confirm the drive now shows `IN_USE` and the expected project association.

Notes:

- `processor` and `auditor` users can view drives but cannot perform format or initialize actions in the current UI.
- Only projects backed by an actively mounted share appear in the Initialize dropdown.
- Confirm the project carefully before initialization because project isolation is enforced after association.

### 14.1a Re-insert a Drive to Add More Data to the Same Project

**Allowed roles:** `admin`, `manager`

If a drive was previously ejected and needs to receive more data for the same project:

1. Re-insert the drive into the ECUBE host.
2. Confirm the project's source share is still configured and currently `MOUNTED`.
3. Open `Drives` and locate the drive (state will be `AVAILABLE`).
4. Open the drive detail page.
5. Click `Initialize`. The previous project is selected automatically only if that project still has an eligible mounted share.
6. Confirm and submit.
7. The drive transitions back to `IN_USE` for the same project.

No format is required when re-using the same project, but the mounted-share prerequisite still applies.

### 14.1b Re-assign a Drive to a Different Project

**Allowed roles:** `admin`, `manager`

If a drive must be reassigned to a different project, a format is required to wipe existing data and clear the project binding:

1. Open `Mounts` and make sure the destination project's source share has already been added, assigned the correct project ID, and mounted successfully.
2. Open `Drives` and locate the drive (state must be `AVAILABLE`).
3. Open the drive detail page.
4. Click `Format` and select the target filesystem. Confirm the format.
5. After formatting completes, click `Initialize`.
6. Choose the new project from the dropdown and confirm.
7. The drive transitions to `IN_USE` for the new project.

> **Warning:** Formatting permanently deletes all data on the drive. Verify that copies and chain-of-custody records for prior project data are complete before proceeding.

### 14.2 Prepare a Drive for Removal and Shipment

**Allowed roles:** `admin`, `manager`

1. Confirm the export job is complete and any required verification or manifest generation has finished.
2. Open `Drives` and select the target drive.
3. Review the drive details to confirm you have the correct media.
4. Click `Prepare Eject`.
5. Wait for the UI to indicate success.
6. Physically remove the drive only after the operation completes.

Notes:

- Use this workflow before final packaging or shipment.
- Do not remove the drive while a copy or verification step is still active.
- After ejection the drive returns to `AVAILABLE` with its project binding intact. It can be re-initialized for the same project without reformatting.
- To permanently retire the drive, complete the Chain of Custody handoff on the `Audit` page after removal.

### 14.3 Export Evidence to a Drive

**Allowed roles:** `admin`, `manager`, `processor`

1. Confirm the correct drive is present and in the expected state.
2. Confirm the source mount is available.
3. Open `Jobs`.
4. Create a new job.
5. Select the drive and mount.
6. Enter project ID, evidence number, and source path.
7. Create the job and open its detail page.
8. Start the job if required.
9. Monitor progress until completion.
10. Run verification and generate a manifest if required by your workflow.

### 14.4 Review Copy Results

**Allowed roles:** `admin`, `manager`, `processor`, `auditor`

1. Open the job detail page.
2. Review the file list and status values.
3. Inspect hashes for specific files if your role allows it.
4. Compare files when you need side-by-side validation.
5. Export or retain the manifest as required by policy.

Notes:

- Hash inspection is currently available to `admin` and `auditor` in the UI.
- Operational actions such as `Start`, `Verify`, and `Manifest` are available to `admin`, `manager`, and `processor`.

### 14.5 Review Audit Activity

**Allowed roles:** `admin`, `manager`, `auditor`

1. Open `Audit`.
2. Apply user, action, and date filters.
3. Expand details for relevant records.
4. Export CSV if you need to retain or share the filtered results.

### 14.6 Add a New User

**Allowed roles:** `admin`

1. Open `Users`.
2. Click `Create User`.
3. Enter the username.
4. Select the appropriate ECUBE roles.
5. Click `Create`.
6. If the username already exists on the host (or directory-backed identity source), review the confirmation prompt and choose whether to add that existing account to ECUBE.
7. If this is a brand-new user, complete the password dialog by entering and confirming the password, then submit.
8. Refresh the page and confirm the user appears with the intended role assignments.

Notes:

- Choose the smallest role set needed for the user's responsibilities.
- If your organization uses a separate account-provisioning process, follow that policy before creating ECUBE access.
- Existing users that are linked into ECUBE are not prompted for a new password in this flow.
- For directory-backed users that cannot be fully enumerated by host account listing, ECUBE may show placeholder host fields while still exposing role management controls.

### 14.7 Remove a User's ECUBE Access

**Allowed roles:** `admin`

1. Open `Users`.
2. Locate the target user.
3. Clear all assigned ECUBE role checkboxes for that user.
4. Save the role changes.
5. Confirm the user no longer has ECUBE roles assigned.

Notes:

- In the current web UI, removing all roles is the visible workflow for removing ECUBE access.
- Full operating-system user deletion is not currently exposed in the web UI and should be handled through administrative procedures outside this manual.

### 14.8 View Application Logs for Troubleshooting

**Allowed roles:** `admin`

1. Open the `System` page.
2. Click the **Logs** tab (available to admins only).
3. The tab displays the most recent log lines from the application log file.
4. Optionally, enter a search term to filter the displayed lines.
5. Click **Refresh** to load the latest log data.
6. Review the redacted log entries for errors, warnings, or relevant diagnostic messages.
7. If you need to investigate further, take note of timestamps or error messages to share with support, or download the full log file using the file list below the viewer.

Notes:

- Sensitive values (passwords, tokens, API keys) are automatically redacted from displayed logs for security.
- The log viewer shows recent entries only; if you need earlier entries or the full log file, use the file download option in the Logs tab.
- This feature is admin-only to prevent information leakage from diagnostic data.

---

## 15. Troubleshooting

### 15.1 I Cannot Log In

Possible causes:

- Incorrect username or password
- Wrong ECUBE URL
- Browser cannot reach the site
- Your account has not been created or assigned the right role

### 15.2 A Page or Menu Item Is Missing

Possible causes:

- Your role does not include access to that feature
- The system is not fully initialized
- The deployment is using an older or partially upgraded frontend/backend combination

### 15.3 A Button Is Visible but Disabled

Possible causes:

- Your role is read-only for that operation
- The selected object is not in a state that permits the action
- Required data has not been entered yet

### 15.4 The UI Shows a Network Error

Possible causes:

- Backend service unavailable
- Reverse proxy or TLS issue
- Browser blocked cross-origin requests in a nonstandard deployment
- Expired session or lost authentication state

If the problem persists, collect:

- The exact page where the error occurred
- The action you attempted
- The visible error text
- The approximate date and time

Then provide that information to your ECUBE administrator.

### 15.5 USB Drive Is Not Recognized

**Who can do what:**

- End users (`admin`, `manager`, `processor`, `auditor`) can perform UI-level checks.
- Administrators (`admin`) can perform host-level diagnostics and recovery.

If a newly inserted USB drive does not appear in ECUBE, use this sequence.

User-level checks:

1. Re-seat the drive and wait 10-20 seconds.
2. Open `Drives`, then click `Refresh` and `Rescan`.
3. Confirm the drive is connected to the expected copy station and not another host.
4. If available in your role, open `System` and review USB/device information for recent detection changes.
5. If the drive still does not appear, notify an administrator and include:
	Approximate insert time, drive label/vendor/capacity (if known), and USB port or hub location used.

Administrator checks:

1. Verify physical connectivity first:
	Test a known-good port on the same hub and confirm hub power and cable integrity.
2. Verify host-level USB detection:
	`lsusb` and `lsblk`.
3. Check ECUBE service health and recent logs:
	`systemctl status ecube` and `journalctl -u ecube -n 200`.
4. In Docker deployments, verify container USB passthrough configuration matches the deployment design.
5. If the device appears at OS level but not in ECUBE, capture logs and escalate with timestamps and device identifiers.

Common causes:

- Faulty cable, port, or unpowered USB hub
- Unsupported or failing media
- Host permission/device passthrough issues (especially in containerized setups)
- ECUBE service not running or unable to complete hardware discovery

---

## References

- [docs/operations/00-operational-guide.md](00-operational-guide.md)
