# ECUBE UI Wireframes

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** UI Designers, Developers, QA  
**Document Type:** Wireframe Reference  
**Source:** Derived from [02-ui-use-cases.md](../testing/02-ui-use-cases.md)

---

## Table of Contents

- [Global Layout & Navigation](#global-layout--navigation)
- [Screen 1: Setup Wizard](#screen-1-setup-wizard)
- [Screen 2: Login](#screen-2-login)
- [Screen 3: Dashboard](#screen-3-dashboard)
- [Screen 4: Drive Management](#screen-4-drive-management)
- [Screen 5: Mount Management](#screen-5-mount-management)
- [Screen 6: Export Jobs](#screen-6-export-jobs)
- [Screen 7: Audit Logs](#screen-7-audit-logs)
- [Screen 8: User & Role Administration](#screen-8-user--role-administration)
- [Screen 9: System Monitoring](#screen-9-system-monitoring)
- [Modals & Dialogs](#modals--dialogs)
- [Error States](#error-states)
- [Use Case to Wireframe Traceability](#use-case--wireframe-traceability)

---

## Global Layout & Navigation

The authenticated application uses a persistent shell with a top header bar containing a logo area and user/logout controls, sidebar navigation, and a footer status bar.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ┌────────┐                                                                  │
│  │ [LOGO] │  ECUBE                       alice [admin] ▾  ⏱ 54m  [ Log Out ]│
│  └────────┘                                                                  │
├──────────────┬───────────────────────────────────────────────────────────────┤
│              │                                                               │
│  ◉ Dashboard │   [ Page Content Area ]                                       │
│              │                                                               │
│  ◎ Drives    │                                                               │
│              │                                                               │
│  ◎ Mounts    │                                                               │
│              │                                                               │
│  ◎ Jobs      │                                                               │
│              │                                                               │
│  ◎ Audit     │                                                               │
│              │                                                               │
│  ─────────── │                                                               │
│  ◎ Users     │   (admin only)                                                │
│  ◎ System    │                                                               │
│              │                                                               │
├──────────────┴───────────────────────────────────────────────────────────────┤
│  ECUBE v1.0.0  │  DB: Connected  │  Active Jobs: 2                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Header bar** (UC-2.3, UC-2.4, UC-2.5):

| Area | Position | Contents |
|------|----------|----------|
| **Logo placeholder** | Left | Reserved space for organization/product logo image (configurable) |
| **App name** | Left (beside logo) | "ECUBE" label |
| **User info** | Right | Logged-in username + role badge(s) + dropdown menu |
| **Token expiry** | Right | Countdown timer showing remaining session time (⏱) |
| **Log Out button** | Far right | Explicit logout action — ends session and redirects to login screen |

**Sidebar navigation** — items visible based on role:
- Dashboard, Drives, Mounts, Jobs, Audit — visible to all roles
- Users — visible to admin only (UC-3.*)
- System — visible to all (introspection is read-only)

**Footer status bar** (UC-8.1, UC-8.2):
- Application version
- Database connection indicator (green/red dot)
- Active job count

---

## Screen 1: Setup Wizard

Shown when `GET /setup/status` returns `{"initialized": false}`. Replaces the entire application shell. Three-step sequential wizard.

### Step 1 of 3 — Database Connection (UC-1.2, UC-1.3, UC-1.4, UC-1.5)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            ECUBE  First-Time Setup                           │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Step  ●━━━━━━━━━━━○━━━━━━━━━━━○                                     │    │
│  │         1. Database    2. Provision   3. Admin Account               │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─ Database Connection ───────────────────────────────────────────────┐     │
│  │                                                                     │     │
│  │  Host        [ db-host                          ]                   │     │
│  │  Port        [ 5432                             ]                   │     │
│  │  Database    [ ecube                            ]                   │     │
│  │  Username    [ ecube                            ]                   │     │
│  │  Password    [ ••••••••                         ]                   │     │
│  │                                                                     │     │
│  │  ┌──────────────────┐                                               │     │
│  │  │ Test Connection   │                                              │     │
│  │  └──────────────────┘                                               │     │
│  │                                                                     │     │
│  │  Status:  ✅ Connected — PostgreSQL 14.2                           │     │
│  │                                                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│                                                         [ Next → ]           │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Step 2 of 3 — Provision Database (UC-1.3, UC-1.4)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            ECUBE  First-Time Setup                           │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Step  ✔━━━━━━━━━━━●━━━━━━━━━━━○                                     │    │
│  │         1. Database    2. Provision   3. Admin Account               │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─ Database Provisioning ─────────────────────────────────────────────┐     │
│  │                                                                     │     │
│  │  This will create the application database user, schema, and        │     │
│  │  run all pending migrations. Safe to re-run.                        │     │
│  │                                                                     │     │
│  │  ┌───────────────────────┐                                          │     │
│  │  │  Provision Database   │                                          │     │
│  │  └───────────────────────┘                                          │     │
│  │                                                                     │     │
│  │  Result:                                                            │     │
│  │  ✅ Database created: ecube                                         │     │
│  │  ✅ User created: ecube                                             │     │
│  │  ✅ Migrations applied: 5                                           │     │
│  │                                                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│                                              [ ← Back ]   [ Next → ]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Step 3 of 3 — Create Admin Account (UC-1.6)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            ECUBE  First-Time Setup                           │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  Step  ✔━━━━━━━━━━━✔━━━━━━━━━━━●                                    │    │
│  │         1. Database    2. Provision   3. Admin Account               │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─ Create Administrator Account ──────────────────────────────────────┐     │
│  │                                                                     │     │
│  │  This creates a Linux OS account with full admin privileges.        │     │
│  │  Username must be lowercase alphanumeric, hyphens, or underscores.  │     │
│  │                                                                     │     │
│  │  Username  [ ecube-admin                        ]                   │     │
│  │  Password  [ ••••••••                           ]                   │     │
│  │  Confirm   [ ••••••••                           ]                   │     │
│  │                                                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│                                              [ ← Back ]  [ Initialize ✓ ]    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Setup Complete — Confirmation

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            ECUBE  First-Time Setup                           │
│                                                                              │
│                         ┌─────────────────────────┐                          │
│                         │       ✅  Success!      │                          │
│                         └─────────────────────────┘                          │
│                                                                              │
│          System initialized. Admin account "ecube-admin" created.            │
│                                                                              │
│          Groups created:                                                     │
│            • ecube-admins                                                    │
│            • ecube-managers                                                  │
│            • ecube-processors                                                │
│            • ecube-auditors                                                  │
│                                                                              │
│                          [ Go to Login → ]                                   │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Use Cases Covered:** UC-1.1, UC-1.2, UC-1.3, UC-1.4, UC-1.5, UC-1.6

---

## Screen 2: Login

### 2a — Local Login (UC-2.1)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│                              ┌──────────┐                                    │
│                              │  ECUBE   │                                    │
│                              └──────────┘                                    │
│                    Evidence Copying & USB Based Export                       │
│                                                                              │
│                 ┌──────────────────────────────────────┐                     │
│                 │                                      │                     │
│                 │  Username  [ _____________________ ] │                     │
│                 │  Password  [ _____________________ ] │                     │
│                 │                                      │                     │
│                 │         ┌──────────────┐             │                     │
│                 │         │    Log In    │             │                     │
│                 │         └──────────────┘             │                     │
│                 │                                      │                     │
│                 │  ─────── or ───────                  │                     │
│                 │                                      │                     │
│                 │         ┌──────────────┐             │                     │
│                 │         │  SSO Login   │             │                     │
│                 │         └──────────────┘             │                     │
│                 │                                      │                     │
│                 └──────────────────────────────────────┘                     │
│                                                                              │
│                 ⚠ Invalid username or password.                             │
│                   (shown on failed attempt)                                  │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2b — Session Expired Dialog (UC-2.5)

```
┌──────────────────────────────────────────────────┐
│         Session Expired                          │
│                                                  │
│  Your session has expired. Please log in         │
│  again to continue.                              │
│                                                  │
│              ┌──────────────┐                    │
│              │   Log In     │                    │
│              └──────────────┘                    │
└──────────────────────────────────────────────────┘
```

**Use Cases Covered:** UC-2.1, UC-2.2, UC-2.3, UC-2.4, UC-2.5

---

## Screen 3: Dashboard

The default landing page after login. Provides an at-a-glance overview of system status and quick access to primary workflows.

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  Dashboard                                                    │
│  ◉ Dashboard │                                                               │
│  ◎ Drives    │  ┌─ System Health ──────────────────────────────────────────┐  │
│  ◎ Mounts    │  │  Database   ● Connected     Active Jobs   2 running     │  │
│  ◎ Jobs      │  │  API        ● Online        Pending Jobs  1 pending     │  │
│  ◎ Audit     │  └──────────────────────────────────────────────────────────┘  │
│  ─────────── │                                                               │
│  ◎ Users     │  ┌─ Drives ───────────────┐  ┌─ Mounts ────────────────────┐  │
│  ◎ System    │  │                        │  │                             │  │
│              │  │  EMPTY       0          │  │  MOUNTED     3             │  │
│              │  │  AVAILABLE   3          │  │  UNMOUNTED   0             │  │
│              │  │  IN_USE      2          │  │  ERROR       1             │  │
│              │  │              ──         │  │              ──            │  │
│              │  │  Total       5          │  │  Total       4             │  │
│              │  │                         │  │                             │  │
│              │  │  [ View Drives → ]      │  │  [ View Mounts → ]         │  │
│              │  └─────────────────────────┘  └─────────────────────────────┘  │
│              │                                                               │
│              │  ┌─ Recent Jobs ─────────────────────────────────────────────┐ │
│              │  │  ID  │ Project     │ Evidence #    │ Status    │ Progress │ │
│              │  │ ─────┼─────────────┼───────────────┼───────────┼──────────│ │
│              │  │  3   │ PROJ-042    │ EV-2026-003   │ ● RUNNING │ ███░ 65% │ │
│              │  │  2   │ PROJ-042    │ EV-2026-002   │ ● RUNNING │ █████92% │ │
│              │  │  1   │ PROJ-001    │ EV-2026-001   │ ✔ DONE    │ █████100%│ │
│              │  │                                                           │ │
│              │  │  [ View All Jobs → ]                                      │ │
│              │  └───────────────────────────────────────────────────────────┘ │
│              │                                                               │
│              │  ┌─ Quick Actions ───────────────────────────────────────────┐ │
│              │  │  [ + New Export Job ]  [ Refresh Drives ]  [ Validate    ]│ │
│              │  │                                             Mounts       ]│ │
│              │  └───────────────────────────────────────────────────────────┘ │
├──────────────┴───────────────────────────────────────────────────────────────┤
│  ECUBE v1.0.0  │  DB: Connected  │  Active Jobs: 2                           │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Use Cases Covered:** UC-8.1, UC-8.2, UC-4.1 (summary), UC-5.1 (summary), UC-6.3 (summary)

---

## Screen 4: Drive Management

### 4a — Drive List View (UC-4.1, UC-4.2, UC-4.3)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  Drives                                    [ Refresh Drives ] │
│  ◎ Dashboard │                                                               │
│  ◉ Drives    │  Filter: [ All States ▾ ]   Search: [ __________________ 🔍] │
│  ◎ Mounts    │                                                               │
│  ◎ Jobs      │  ┌────┬─────────────────────┬────────┬───────┬───────────────┐│
│  ◎ Audit     │  │ ID │ Device Identifier    │ State  │ FS    │ Project       ││
│              │  ├────┼─────────────────────┼────────┼───────┼───────────────┤│
│              │  │ 1  │ 4C53000022022622301 │🟢IN_USE│ ext4  │ PROJ-042      ││
│              │  │ 2  │ A1B2C3D4E5F60001    │🟡AVAIL │ exfat │ —             ││
│              │  │ 3  │ 7F8E9D0A1B2C3456    │🟡AVAIL │ ext4  │ —             ││
│              │  │ 4  │ B2C3D4E5F6070002    │🟢IN_USE│ ext4  │ PROJ-001      ││
│              │  │ 5  │ C3D4E5F607080003    │⚪EMPTY │ —     │ —             ││
│              │  └────┴─────────────────────┴────────┴───────┴───────────────┘│
│              │                                                               │
│              │  Click a row to view drive details and available actions.      │
│              │                                                               │
│              │  [ Manage Ports ]  (admin/manager only — opens Screen 4c)     │
│              │                                                               │
│              │  ┌─ Lifecycle Reference ─────────────────────────────────────┐ │
│              │  │   EMPTY ──▶ AVAILABLE ──▶ IN_USE                         │ │
│              │  │     ▲      (format)    (initialize)  │                    │ │
│              │  │     │         ▲                       │ (eject)           │ │
│              │  │     │         └───────────────────────┘                   │ │
│              │  │  (removed)                                                │ │
│              │  └──────────────────────────────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**State color key:** 🟢 IN_USE (green) · 🟡 AVAILABLE (yellow) · ⚪ EMPTY (gray)

### 4b — Drive Detail Panel (UC-4.7, UC-4.4, UC-4.5, UC-4.6)

Shown when a drive row is selected (slide-out panel or detail page).

```
┌─ Drive Detail ───────────────────────────────────────────────────────────────┐
│                                                                              │
│  Drive #2 — A1B2C3D4E5F60001                              State: 🟡AVAILABLE│
│                                                                              │
│  ┌─ Properties ────────────────────────────────────────────────────────┐     │
│  │  Device Identifier:   A1B2C3D4E5F60001                              │     │
│  │  Filesystem Path:     /dev/sdh                                      │     │
│  │  Port:                4                                             │     │
│  │  Capacity:            64.0 GB (64,023,257,088 bytes)                │     │
│  │  Filesystem:          exfat                                         │     │
│  │  Encryption:          none                                          │     │
│  │  Project:             (not assigned)                                 │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌─ Actions ───────────────────────────────────────────────────────────┐     │
│  │                                                                     │     │
│  │  ┌─────────────────────────────────────┐                            │     │
│  │  │  Format Drive                        │                           │     │
│  │  │                                      │                           │     │
│  │  │  Filesystem: ( ) ext4  (●) exfat     │                           │     │
│  │  │                                      │                           │     │
│  │  │  ⚠ This will erase all data.         │                           │     │
│  │  │                                      │                           │     │
│  │  │           [ Format ]                 │                           │     │
│  │  └─────────────────────────────────────┘                            │     │
│  │                                                                     │     │
│  │  ┌─────────────────────────────────────┐                            │     │
│  │  │  Initialize for Project              │                           │     │
│  │  │                                      │                           │     │
│  │  │  Project ID: [ PROJ-042            ] │                           │     │
│  │  │                                      │                           │     │
│  │  │           [ Initialize ]             │                           │     │
│  │  └─────────────────────────────────────┘                            │     │
│  │                                                                     │     │
│  │  [ Eject Drive ] (disabled — drive not IN_USE)                      │     │
│  │                                                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│                                                            [ ← Back ]       │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Action button states by drive state:**

| Drive State | Format | Initialize | Eject |
|-------------|--------|------------|-------|
| EMPTY       | disabled | disabled | disabled |
| AVAILABLE   | enabled | enabled (if FS present) | disabled |
| IN_USE      | disabled | disabled | enabled |

**Use Cases Covered:** UC-4.1, UC-4.2, UC-4.3, UC-4.4, UC-4.5, UC-4.6, UC-4.7, UC-4.8, UC-4.9, UC-4.10

### 4c — Port Management Panel (UC-4.8, UC-4.9, UC-4.10)

Accessible from the Drive Management screen via a "Manage Ports" button. Visible to admin and manager roles only.

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  USB Port Management                         [ ← Back to     │
│  ◎ Dashboard │                                                 Drives ]     │
│  ◉ Drives    │                                                               │
│  ◎ Mounts    │  Ports default to disabled. Enable ports to allow drives to   │
│  ◎ Jobs      │  become AVAILABLE during discovery.                           │
│  ◎ Audit     │                                                               │
│              │  ┌────┬────────┬──────────────────────────┬─────────┬────────┐│
│              │  │ ID │ Hub    │ System Path              │ Label   │ Enable ││
│              │  ├────┼────────┼──────────────────────────┼─────────┼────────┤│
│              │  │ 1  │ Hub 1  │ /sys/bus/usb/devices/1-1 │ —       │ [✓]    ││
│              │  │ 2  │ Hub 1  │ /sys/bus/usb/devices/1-2 │ —       │ [ ]    ││
│              │  │ 3  │ Hub 1  │ /sys/bus/usb/devices/1-3 │ —       │ [✓]    ││
│              │  │ 4  │ Hub 2  │ /sys/bus/usb/devices/2-1 │ —       │ [ ]    ││
│              │  └────┴────────┴──────────────────────────┴─────────┴────────┘│
│              │                                                               │
│              │  ⚠ Changes take effect on the next discovery refresh.         │
│              │    Drives on disabled ports remain in EMPTY state.            │
│              │    Drives already IN_USE are not affected.                    │
│              │                                                               │
│              │  [ Refresh Drives ] — run discovery after enabling ports      │
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**Behavior:**
- Each toggle calls `PATCH /admin/ports/{id}` with `{"enabled": true/false}`
- Toggle state reflects the current `enabled` value from `GET /admin/ports`
- Success shows a brief toast notification ("Port 1 enabled" / "Port 2 disabled")
- The "Refresh Drives" button calls `POST /drives/refresh` to immediately apply enablement changes
- Hidden for processor and auditor roles (API returns 403)

---

## Screen 5: Mount Management

### 5a — Mount List View (UC-5.1, UC-5.4, UC-5.5, UC-5.6)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  Network Mounts                    [ Validate All ] [ + Add ] │
│  ◎ Dashboard │                                                               │
│  ◎ Drives    │  ┌────┬──────┬──────────────────────────┬──────────────────┐  │
│  ◉ Mounts    │  │ ID │ Type │ Remote Path              │ Local Mount      │  │
│  ◎ Jobs      │  │    │      │                          │                  │  │
│              │  ├────┼──────┼──────────────────────────┼──────────────────┤  │
│              │  │ 1  │ NFS  │ nfs.example.com:/evidence│ /mnt/evidence    │  │
│              │  │    │      │ Status: 🟢 MOUNTED       │ Checked: 14:30   │  │
│              │  │    │      │              [ Validate ] │ [ Remove ]       │  │
│              │  ├────┼──────┼──────────────────────────┼──────────────────┤  │
│              │  │ 2  │ SMB  │ //fileserver/cases       │ /mnt/cases       │  │
│              │  │    │      │ Status: 🔴 ERROR         │ Checked: 14:30   │  │
│              │  │    │      │              [ Validate ] │ [ Remove ]       │  │
│              │  ├────┼──────┼──────────────────────────┼──────────────────┤  │
│              │  │ 3  │ NFS  │ nfs2.example.com:/archive│ /mnt/archive     │  │
│              │  │    │      │ Status: 🟢 MOUNTED       │ Checked: 14:30   │  │
│              │  │    │      │              [ Validate ] │ [ Remove ]       │  │
│              │  └────┴──────┴──────────────────────────┴──────────────────┘  │
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**Status colors:** 🟢 MOUNTED · ⚪ UNMOUNTED · 🔴 ERROR

### 5b — Add Mount Dialog (UC-5.2, UC-5.3)

```
┌─ Add Network Mount ──────────────────────────────────────────┐
│                                                               │
│  Protocol:    (●) NFS    ( ) SMB                              │
│                                                               │
│  Remote Path:       [ nfs.example.com:/evidence            ]  │
│  Local Mount Point: [ /mnt/evidence                        ]  │
│                                                               │
│  ┌─ SMB Credentials (shown only when SMB selected) ────────┐ │
│  │  Username:  [ svc-ecube                               ]  │ │
│  │  Password:  [ ••••••••                                ]  │ │
│  │                                                          │ │
│  │  — or —                                                  │ │
│  │                                                          │ │
│  │  Credentials File: [ /etc/ecube/smb-creds.conf        ]  │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                               │
│                              [ Cancel ]   [ Add Mount ]       │
└───────────────────────────────────────────────────────────────┘
```

**Use Cases Covered:** UC-5.1, UC-5.2, UC-5.3, UC-5.4, UC-5.5, UC-5.6

---

## Screen 6: Export Jobs

### 6a — Job List View (UC-6.3)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  Export Jobs                                 [ + New Job ]     │
│  ◎ Dashboard │                                                               │
│  ◎ Drives    │  Filter: [ All ▾ ]  Project: [ _________ ]  Search: [ __ 🔍] │
│  ◎ Mounts    │                                                               │
│  ◉ Jobs      │  ┌────┬───────────┬──────────────┬───────────┬──────────────┐ │
│  ◎ Audit     │  │ ID │ Project   │ Evidence #   │ Status    │ Progress     │ │
│              │  ├────┼───────────┼──────────────┼───────────┼──────────────┤ │
│              │  │ 3  │ PROJ-042  │ EV-2026-003  │ ● RUNNING │ ████░░ 65%  │ │
│              │  │    │           │              │           │ 3.2/5.0 GB   │ │
│              │  ├────┼───────────┼──────────────┼───────────┼──────────────┤ │
│              │  │ 2  │ PROJ-042  │ EV-2026-002  │ ◉ VERIFY  │ ██████ 92%  │ │
│              │  │    │           │              │           │ verifying... │ │
│              │  ├────┼───────────┼──────────────┼───────────┼──────────────┤ │
│              │  │ 1  │ PROJ-001  │ EV-2026-001  │ ✔ DONE    │ ██████ 100% │ │
│              │  │    │           │              │           │ 12.4 GB      │ │
│              │  └────┴───────────┴──────────────┴───────────┴──────────────┘ │
│              │                                                               │
│              │  Click a row to view job details, files, and actions.          │
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**Status indicators:**
- ○ PENDING (gray) · ● RUNNING (blue, animated) · ◉ VERIFYING (orange)
- ✔ COMPLETED (green) · ✖ FAILED (red)

### 6b — Job Detail & Monitoring View (UC-6.3, UC-6.4, UC-6.5, UC-6.6)

```
┌─ Job #3 — PROJ-042 / EV-2026-003 ───────────────────────────────────────────┐
│                                                                              │
│  Status: ● RUNNING                                         Created by: alice │
│                                                                              │
│  ┌─ Overview ──────────────────────────────────────────────────────────┐     │
│  │  Project:      PROJ-042             Evidence #:  EV-2026-003       │     │
│  │  Source:       /mnt/evidence/case-003                               │     │
│  │  Target:       /mnt/usb/drive1                                      │     │
│  │  Drive:        #1 (4C530000220226...)    Threads: 4                 │     │
│  │  Retries:      3 max / 1s delay                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌─ Progress ──────────────────────────────────────────────────────────┐     │
│  │                                                                     │     │
│  │  ████████████████████████████░░░░░░░░░░░░░░░  65%                   │     │
│  │                                                                     │     │
│  │  Copied:   3,489,660,928 / 5,368,709,120 bytes  (3.2 / 5.0 GB)     │     │
│  │  Files:    223 / 342 files completed                                │     │
│  │                                                                     │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌─ Files ─────────────────────────────────────────────────────────────┐     │
│  │  Filter: [ All ▾ ]   Search: [ __________________________ 🔍 ]      │     │
│  │                                                                     │     │
│  │  Status │ Relative Path                    │ Size      │ Checksum   │     │
│  │  ───────┼──────────────────────────────────┼───────────┼────────────│     │
│  │  ✔ DONE │ docs/report.pdf                  │ 1.0 MB    │ a1b2c3...  │     │
│  │  ✔ DONE │ docs/evidence-log.xlsx           │ 245 KB    │ d4e5f6...  │     │
│  │  ● COPY │ images/photo-001.jpg             │ 4.2 MB    │ —          │     │
│  │  ○ PEND │ images/photo-002.jpg             │ 3.8 MB    │ —          │     │
│  │  ✖ ERR  │ corrupt/bad-file.dat             │ 12 KB     │ —          │     │
│  │         │ Error: I/O error reading source   │           │            │     │
│  │  ↻ RTRY │ large/dataset.zip                │ 1.2 GB    │ —          │     │
│  │         │ Attempt 2 of 3                    │           │            │     │
│  │                                                                     │     │
│  │  Showing 1–50 of 342           [ ◀ Prev ]  Page 1 of 7  [ Next ▶ ] │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│  ┌─ Actions ───────────────────────────────────────────────────────────┐     │
│  │  [ Start ] (disabled—running)   [ Verify ]   [ Generate Manifest ] │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
│                                                            [ ← Back ]       │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Action button states by job status:**

| Job Status | Start | Verify | Manifest |
|------------|-------|--------|----------|
| PENDING    | enabled | disabled | disabled |
| RUNNING    | disabled | disabled | disabled |
| COMPLETED  | disabled | enabled | enabled |
| VERIFYING  | disabled | disabled | disabled |
| FAILED     | disabled | enabled | enabled |

### 6c — Create Job Wizard (UC-6.1)

```
┌─ New Export Job ─────────────────────────────────────────────────────────────┐
│                                                                              │
│  Step 1:  Project & Evidence Metadata                                        │
│  ─────────────────────────────────────                                       │
│  Project ID:       [ PROJ-042                              ]                 │
│  Evidence Number:  [ EV-2026-003                           ]                 │
│                                                                              │
│  Step 2:  Source                                                             │
│  ─────────────────                                                           │
│  Source Mount:      [ /mnt/evidence  (NFS — MOUNTED)     ▾ ]                 │
│  Source Path:       [ /mnt/evidence/case-003               ]                 │
│                                                                              │
│  Step 3:  Target Drive                                                       │
│  ─────────────────────                                                       │
│  Drive:             [ #1 — 4C5300... — IN_USE — PROJ-042 ▾ ]                │
│                     Only drives IN_USE for PROJ-042 are shown                │
│                                                                              │
│  Step 4:  Copy Settings                                                      │
│  ──────────────────────                                                      │
│  Thread Count:      [ 4 ▾ ]  (1–8)                                           │
│  Max File Retries:  [ 3   ]                                                  │
│  Retry Delay (sec): [ 1   ]                                                  │
│                                                                              │
│                                          [ Cancel ]   [ Create Job ]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 6d — File Hash Viewer (UC-6.7) & File Compare (UC-6.8)

```
┌─ File Hashes — #42 ─────────────────────────────┐
│                                                   │
│  File:     docs/report.pdf                        │
│  Size:     1,048,576 bytes (1.0 MB)               │
│  MD5:      d41d8cd98f00b204e9800998ecf8427e       │
│  SHA-256:  e3b0c44298fc1c149afbf4c8996fb92...     │
│                                                   │
│           [ Compare with Another File ]           │
│                        [ Close ]                  │
└───────────────────────────────────────────────────┘
```

```
┌─ Compare Files ──────────────────────────────────────────────────────────────┐
│                                                                              │
│  File A: [ 42  ] docs/report.pdf        File B: [ 108 ] docs/report.pdf     │
│                                                                              │
│  Result:  ✅ MATCH                                                           │
│                                                                              │
│  ┌──────────┬─────────────────────────┬─────────────────────────┐            │
│  │ Check    │ File A (#42)            │ File B (#108)           │            │
│  ├──────────┼─────────────────────────┼─────────────────────────┤            │
│  │ Path     │ docs/report.pdf     ✔   │ docs/report.pdf     ✔   │            │
│  │ Size     │ 1,048,576 bytes     ✔   │ 1,048,576 bytes     ✔   │            │
│  │ SHA-256  │ a1b2c3...f0         ✔   │ a1b2c3...f0         ✔   │            │
│  └──────────┴─────────────────────────┴─────────────────────────┘            │
│                                                                              │
│                                                            [ Close ]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Use Cases Covered:** UC-6.1, UC-6.2, UC-6.3, UC-6.4, UC-6.5, UC-6.6, UC-6.7, UC-6.8

---

## Screen 7: Audit Logs

### 7a — Audit Log Viewer (UC-7.1 through UC-7.7)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  Audit Logs                                    [ Export CSV ] │
│  ◎ Dashboard │                                                               │
│  ◎ Drives    │  ┌─ Filters ────────────────────────────────────────────────┐  │
│  ◎ Mounts    │  │  User:    [ ____________ ]   Action: [ All Actions   ▾ ] │  │
│  ◉ Audit     │  │  Job ID:  [ __ ]              Since:  [ 2026-03-01   📅]│  │
│  ◎ Jobs      │  │                                Until:  [ 2026-03-19   📅]│  │
│              │  │                                         [ Apply Filters ]│  │
│              │  └──────────────────────────────────────────────────────────┘  │
│              │                                                               │
│              │  ┌─────┬────────────────────┬────────┬────────────────┬─────┐  │
│              │  │ ID  │ Timestamp          │ User   │ Action         │ Job │  │
│              │  ├─────┼────────────────────┼────────┼────────────────┼─────┤  │
│              │  │ 847 │ 2026-03-18 14:30   │ alice  │ JOB_STARTED    │ 42  │  │
│              │  │ 846 │ 2026-03-18 14:29   │ alice  │ JOB_CREATED    │ 42  │  │
│              │  │ 845 │ 2026-03-18 14:25   │ bob    │ DRIVE_INIT     │ —   │  │
│              │  │ 844 │ 2026-03-18 14:20   │ —      │ USB_DISC_SYNC  │ —   │  │
│              │  │ 843 │ 2026-03-18 13:55   │ alice  │ MOUNT_ADDED    │ —   │  │
│              │  └─────┴────────────────────┴────────┴────────────────┴─────┘  │
│              │                                                               │
│              │  ▼ Entry #847 — Expanded Detail                               │
│              │  ┌──────────────────────────────────────────────────────────┐  │
│              │  │  {                                                       │  │
│              │  │    "thread_count": 4                                     │  │
│              │  │  }                                                       │  │
│              │  └──────────────────────────────────────────────────────────┘  │
│              │                                                               │
│              │  Showing 1–100 of 847       [ ◀ Prev ]  Page 1 of 9 [ Next ▶]│
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**Action dropdown options** (UC-7.3 — partial list):
- All Actions
- AUTH_FAILURE
- AUTHORIZATION_DENIED
- DRIVE_INITIALIZED / DRIVE_FORMATTED / DRIVE_EJECT_PREPARED
- PORT_ENABLED / PORT_DISABLED
- JOB_CREATED / JOB_STARTED / JOB_VERIFY_STARTED
- FILE_COPY_SUCCESS / FILE_COPY_FAILURE
- MOUNT_ADDED / MOUNT_REMOVED / MOUNT_VALIDATED
- PROJECT_ISOLATION_VIOLATION
- SYSTEM_INITIALIZED

**Use Cases Covered:** UC-7.1, UC-7.2, UC-7.3, UC-7.4, UC-7.5, UC-7.6, UC-7.7

---

## Screen 8: User & Role Administration

Visible only to admin role.

### 8a — User List with Roles (UC-3.1, UC-3.2, UC-3.6)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  User Management                              [ + New User ] │
│  ◎ Dashboard │                                                               │
│  ◎ Drives    │  Tab: [ Users ]  [ OS Groups ]                                │
│  ◎ Mounts    │                                                               │
│  ◎ Jobs      │  ┌───────────────┬──────────────────────────┬────────────────┐│
│  ◎ Audit     │  │ Username      │ DB Roles                 │ OS Groups      ││
│  ─────────── │  ├───────────────┼──────────────────────────┼────────────────┤│
│  ◉ Users     │  │ alice         │ [admin]                  │ ecube-admins   ││
│  ◎ System    │  │               │                          │                ││
│              │  │               │  [ Edit Roles ] [ Reset  │ [ Edit Groups ]││
│              │  │               │                  Pwd   ] │ [ Delete ]     ││
│              │  ├───────────────┼──────────────────────────┼────────────────┤│
│              │  │ bob           │ [processor]              │ ecube-processors│
│              │  │               │                          │                ││
│              │  │               │  [ Edit Roles ] [ Reset  │ [ Edit Groups ]││
│              │  │               │                  Pwd   ] │ [ Delete ]     ││
│              │  ├───────────────┼──────────────────────────┼────────────────┤│
│              │  │ carol         │ [manager] [processor]    │ ecube-managers ││
│              │  │               │                          │ ecube-processors│
│              │  │               │  [ Edit Roles ] [ Reset  │ [ Edit Groups ]││
│              │  │               │                  Pwd   ] │ [ Delete ]     ││
│              │  └───────────────┴──────────────────────────┴────────────────┘│
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

### 8b — Edit Roles Dialog (UC-3.3, UC-3.4)

```
┌─ Edit Roles — bob ───────────────────────────────────┐
│                                                       │
│  Select roles for this user:                          │
│                                                       │
│  [✓] admin        [✓] processor                       │
│  [ ] manager      [ ] auditor                         │
│                                                       │
│  ⚠ Changes take effect on user's next login.          │
│                                                       │
│              [ Cancel ]   [ Save Roles ]              │
│                                                       │
│  ── or ──                                             │
│                                                       │
│  [ Remove All Roles ] — user falls back to            │
│  OS group role mapping                                │
└───────────────────────────────────────────────────────┘
```

### 8c — Create User Dialog (UC-3.5)

```
┌─ Create User ────────────────────────────────────────────────┐
│                                                               │
│  Username:  [ _____________________ ]                         │
│             Lowercase letters, digits, hyphens, underscores   │
│                                                               │
│  Password:  [ _____________________ ]                         │
│  Confirm:   [ _____________________ ]                         │
│                                                               │
│  OS Groups:                                                   │
│  [✓] ecube-processors                                         │
│  [ ] ecube-managers                                           │
│  [ ] ecube-auditors                                           │
│  [ ] ecube-admins                                             │
│                                                               │
│  DB Roles (optional — assigned immediately):                  │
│  [ ] admin   [ ] manager   [✓] processor   [ ] auditor       │
│                                                               │
│                            [ Cancel ]   [ Create User ]       │
└───────────────────────────────────────────────────────────────┘
```

### 8d — OS Groups Tab (UC-3.10, UC-3.11, UC-3.12)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  User Management                             [ + New Group ] │
│              │                                                               │
│              │  Tab: [ Users ]  [OS Groups]                                  │
│              │                                                               │
│              │  ┌─────────────────────┬───────┬──────────────┬─────────────┐ │
│              │  │ Group Name          │ GID   │ Members      │ Actions     │ │
│              │  ├─────────────────────┼───────┼──────────────┼─────────────┤ │
│              │  │ ecube-admins        │ 1001  │ alice        │ [ Delete ]  │ │
│              │  │ ecube-managers      │ 1002  │ carol        │ [ Delete ]  │ │
│              │  │ ecube-processors    │ 1003  │ bob, carol   │ [ Delete ]  │ │
│              │  │ ecube-auditors      │ 1004  │ (none)       │ [ Delete ]  │ │
│              │  └─────────────────────┴───────┴──────────────┴─────────────┘ │
│              │                                                               │
│              │  ⚠ Groups must start with "ecube-".                           │
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

**Use Cases Covered:** UC-3.1 through UC-3.12

---

## Screen 9: System Monitoring

### 9a — System Overview (UC-8.1, UC-8.2)

```
┌──────────────┬───────────────────────────────────────────────────────────────┐
│              │  System Monitoring                                            │
│  ◎ Dashboard │                                                               │
│  ◎ Drives    │  Tab: [ Health ] [ USB Topology ] [ Block Devices ] [ Logs ]  │
│  ◎ Mounts    │                                                               │
│  ◎ Jobs      │  ┌─ System Health ──────────────────────────────────────────┐  │
│  ◎ Audit     │  │  Status:     ● OK                                       │  │
│  ─────────── │  │  Database:   ● Connected                                │  │
│  ◎ Users     │  │  Active Jobs: 2                                         │  │
│  ◉ System    │  │  Version:    1.0.0                                      │  │
│              │  └──────────────────────────────────────────────────────────┘  │
│              │                                                               │
│              │  ┌─ Mounted Filesystems ─────────────────────────────────────┐ │
│              │  │  Device         │ Mount Point     │ FS Type │ Options     │ │
│              │  │  /dev/sda1      │ /               │ ext4    │ rw,relatime │ │
│              │  │  /dev/sdg1      │ /mnt/usb/drive1 │ ext4    │ rw,nosuid   │ │
│              │  │  nfs.example... │ /mnt/evidence   │ nfs4    │ rw,vers=4.1 │ │
│              │  └──────────────────────────────────────────────────────────┘  │
│              │                                                               │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

### 9b — USB Topology Tab (UC-8.3)

```
│  Tab: [ Health ] [USB Topology] [ Block Devices ] [ Logs ]                   │
│                                                                              │
│  ┌─ USB Device Tree ───────────────────────────────────────────────────────┐ │
│  │                                                                         │ │
│  │  📦 usb1 — Linux Foundation — Root Hub                                  │ │
│  │   ├── 📦 1-1 — Genesys Logic — USB Hub                                 │ │
│  │   │    ├── 💾 1-1.1 — SanDisk — Ultra (port 1)                         │ │
│  │   │    ├── 💾 1-1.2 — Kingston — DataTraveler (port 2)                  │ │
│  │   │    ├── (empty port 3)                                               │ │
│  │   │    └── 💾 1-1.4 — Samsung — Flash Drive (port 4)                    │ │
│  │   └── 📦 1-2 — Genesys Logic — USB Hub                                 │ │
│  │        ├── (empty port 1)                                               │ │
│  │        └── 💾 1-2.2 — Seagate — Portable (port 2)                      │ │
│  │                                                                         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
```

### 9c — Application Logs Tab (UC-8.7, UC-8.8)

```
│  Tab: [ Health ] [ USB Topology ] [ Block Devices ] [Logs]                   │
│                                                                              │
│  ┌─ Application Log Files ─────────────────────────────────────────────────┐ │
│  │  Total size: 14.2 MB       Directory: /var/log/ecube/                   │ │
│  │                                                                         │ │
│  │  File Name          │ Size      │ Modified            │ Action          │ │
│  │  ───────────────────┼───────────┼─────────────────────┼──────────────── │ │
│  │  ecube.log          │ 8.4 MB    │ 2026-03-19 10:22    │ [ Download ]   │ │
│  │  ecube.log.1        │ 5.0 MB    │ 2026-03-18 00:00    │ [ Download ]   │ │
│  │  ecube-error.log    │ 0.8 MB    │ 2026-03-19 09:15    │ [ Download ]   │ │
│  │                                                                         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
```

### 9d — Job Debug View (UC-8.6)

```
│  Job Debug — Admin/Auditor Only                                              │
│                                                                              │
│  Job ID: [ 1 ]   [ Load Debug Info ]                                         │
│                                                                              │
│  ┌─ Debug Details ─────────────────────────────────────────────────────────┐ │
│  │  Job ID:          1                                                     │ │
│  │  Status:          COMPLETED                                             │ │
│  │  Project:         PROJ-001                                              │ │
│  │  Source:          /mnt/evidence/case-001                                 │ │
│  │  Target:          /mnt/usb/drive4                                       │ │
│  │  Total Bytes:     13,312,196,608                                        │ │
│  │  Copied Bytes:    13,312,196,608                                        │ │
│  │  Files:           1,247                                                 │ │
│  │  Threads:         4                                                     │ │
│  │                                                                         │ │
│  │  Files with errors:                                                     │ │
│  │  ID   │ Path                    │ Status │ Error                        │ │
│  │  ─────┼─────────────────────────┼────────┼───────────────────────────── │ │
│  │  156  │ archive/corrupted.bin   │ ERROR  │ I/O error reading source     │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
```

**Use Cases Covered:** UC-8.1 through UC-8.8

---

## Modals & Dialogs

### Confirmation Dialog (destructive actions)

Used for: Format Drive (UC-4.4), Delete User (UC-3.8), Remove Mount (UC-5.4), Remove Roles (UC-3.4)

```
┌─ Confirm: Format Drive ─────────────────────────┐
│                                                   │
│  ⚠ Warning                                       │
│                                                   │
│  You are about to format drive #2                 │
│  (A1B2C3D4E5F60001) with ext4.                    │
│                                                   │
│  This will permanently erase all data             │
│  on the drive.                                    │
│                                                   │
│  Type "FORMAT" to confirm:                        │
│  [ ________________ ]                             │
│                                                   │
│              [ Cancel ]   [ Format Drive ]        │
│                              (disabled until      │
│                               confirmed)          │
└───────────────────────────────────────────────────┘
```

### Reset Password Dialog (UC-3.7)

```
┌─ Reset Password — bob ───────────────────────────┐
│                                                    │
│  New Password:     [ _____________________ ]       │
│  Confirm Password: [ _____________________ ]       │
│                                                    │
│              [ Cancel ]   [ Reset Password ]       │
└────────────────────────────────────────────────────┘
```

---

## Error States

### API Error Display (401, 403, 409)

```
┌─ Error ──────────────────────────────────────────┐
│                                                   │
│  ❌ 403 — Insufficient Permissions                │
│                                                   │
│  You need the "manager" or "admin" role to        │
│  format drives.                                   │
│                                                   │
│  Your current roles: [processor]                  │
│                                                   │
│  Contact your administrator for access.           │
│                                                   │
│  Trace ID: abc-123-def                            │
│                                                   │
│                              [ Dismiss ]          │
└───────────────────────────────────────────────────┘
```

### State Conflict Display (409)

```
┌─ Error ──────────────────────────────────────────┐
│                                                   │
│  ⚠ 409 — State Conflict                          │
│                                                   │
│  Cannot format drive #1 — current state is        │
│  IN_USE. Drive must be AVAILABLE to format.       │
│                                                   │
│  Use "Eject" to return the drive to AVAILABLE     │
│  state first.                                     │
│                                                   │
│                              [ Dismiss ]          │
└───────────────────────────────────────────────────┘
```

### Project Isolation Violation (403)

```
┌─ Error ──────────────────────────────────────────┐
│                                                   │
│  🔒 Project Isolation Violation                   │
│                                                   │
│  Drive #1 is bound to project PROJ-001.           │
│  Job project PROJ-042 does not match.             │
│                                                   │
│  Select a drive initialized for PROJ-042,         │
│  or initialize a new drive for this project.      │
│                                                   │
│                              [ Dismiss ]          │
└───────────────────────────────────────────────────┘
```

---

## Use Case ↔ Wireframe Traceability

| Use Case | Wireframe Screen |
|----------|-----------------|
| UC-1.1 – UC-1.6 | Screen 1: Setup Wizard (Steps 1–3 + Confirmation) |
| UC-2.1 – UC-2.2 | Screen 2a: Login |
| UC-2.3 – UC-2.4 | Global Layout: Header bar |
| UC-2.5 | Screen 2b: Session Expired Dialog |
| UC-3.1 – UC-3.4 | Screen 8a: User List, Screen 8b: Edit Roles |
| UC-3.5 | Screen 8c: Create User Dialog |
| UC-3.6 – UC-3.9 | Screen 8a: User List (inline actions) |
| UC-3.7 | Modal: Reset Password |
| UC-3.10 – UC-3.12 | Screen 8d: OS Groups Tab |
| UC-4.1 – UC-4.2 | Screen 4a: Drive List |
| UC-4.3 | Screen 4a: Refresh button |
| UC-4.4 – UC-4.6 | Screen 4b: Drive Detail (action panels) |
| UC-4.7 | Screen 4b: Drive Detail (properties) |
| UC-4.8 – UC-4.10 | Screen 4c: Port Management Panel |
| UC-5.1 | Screen 5a: Mount List |
| UC-5.2 – UC-5.3 | Screen 5b: Add Mount Dialog |
| UC-5.4 – UC-5.6 | Screen 5a: Mount List (inline actions) |
| UC-6.1 | Screen 6c: Create Job Wizard |
| UC-6.2 | Screen 6b: Actions (Start button) |
| UC-6.3 | Screen 6a: Job List, Screen 6b: Progress |
| UC-6.4 | Screen 6b: Files table |
| UC-6.5 – UC-6.6 | Screen 6b: Actions (Verify, Manifest) |
| UC-6.7 | Screen 6d: File Hash Viewer |
| UC-6.8 | Screen 6d: File Compare |
| UC-7.1 – UC-7.6 | Screen 7a: Audit Log Viewer |
| UC-7.7 | Screen 7a: Export CSV button |
| UC-8.1 – UC-8.2 | Screen 9a: System Health + Footer |
| UC-8.3 | Screen 9b: USB Topology |
| UC-8.4 – UC-8.5 | Screen 9a: Block Devices / Mounts tabs |
| UC-8.6 | Screen 9d: Job Debug |
| UC-8.7 – UC-8.8 | Screen 9c: Logs Tab |
