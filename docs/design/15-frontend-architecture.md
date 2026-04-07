# 15. Frontend Architecture — Design

**Version:** 1.0
**Last Updated:** April 2026
**Status:** Implemented (Living Document)

---

## Table of Contents

1. [Purpose & Scope](#1-purpose--scope)
2. [Technology Stack](#2-technology-stack)
3. [Project Structure](#3-project-structure)
4. [Application Shell & Routing](#4-application-shell--routing)
5. [State Management](#5-state-management)
6. [API Client Layer](#6-api-client-layer)
7. [Theme & Styling System](#7-theme--styling-system)
8. [Localization (i18n)](#8-localization-i18n)
9. [Component Inventory](#9-component-inventory)
10. [Role-Based UI Behavior](#10-role-based-ui-behavior)
11. [Deployment Architecture](#11-deployment-architecture)
12. [Testing Strategy](#12-testing-strategy)
13. [Browser Support](#13-browser-support)
14. [Open Questions & Future Considerations](#14-open-questions--future-considerations)

---

## 1. Purpose & Scope

This document defines the architecture for the ECUBE web frontend — a Vue 3 single-page application (SPA) served from a dedicated nginx Docker container.

### In Scope

- Frontend application architecture and project structure
- Component inventory mapped to wireframe screens
- API client design and error handling
- Theme system with user-customizable CSS
- Localization framework
- Deployment topology (nginx container, Docker Compose integration)
- Testing strategy

### Out of Scope

- Backend API changes (except CORS middleware, documented as a dependency)
- Backend business logic or data model changes
- Mobile-native application

### Related Documents

| Document | Relationship |
|----------|-------------|
| [14-ui-wireframes.md](14-ui-wireframes.md) | Screen layouts and visual structure this architecture implements |
| [04-ui-use-cases.md](../testing/04-ui-use-cases.md) | 47 use cases across 8 groups that define functional requirements |
| [06-rest-api-specification.md](06-rest-api-specification.md) | API contract the frontend consumes |
| [10-security-and-access-control.md](10-security-and-access-control.md) | Role model and authorization matrix |
| [03-system-architecture.md](03-system-architecture.md) | Overall system architecture and trust boundary |

---

## 2. Technology Stack

| Component | Choice | Version Target | Rationale |
|-----------|--------|---------------|-----------|
| **Framework** | Vue 3 | 3.5+ | Composition API with `<script setup>` SFCs; gentle learning curve; strong ecosystem |
| **Bundler** | Vite | 8.x | Fast HMR, native ES module dev server, optimized production builds |
| **Router** | Vue Router | 5.x | Official Vue router; supports navigation guards for auth/role gating |
| **State Management** | Pinia | 3.x | Official Vue store; Composition API native; devtools integration |
| **HTTP Client** | Axios | 1.x | Interceptors for Bearer token injection and error handling; request cancellation |
| **Localization** | Vue I18n | 9.x | Official i18n plugin for Vue 3; supports lazy-loaded locale files |
| **Testing (E2E)** | Playwright | Latest | Cross-browser testing (Chromium, WebKit); reliable auto-waiting |
| **Testing (Unit)** | Vitest | Latest | Vite-native test runner; Vue Test Utils integration |
| **CSS Architecture** | CSS Custom Properties | — | Theme tokens as variables; no build-time dependency; user-customizable |

### Why Not React?

Vue was selected for its template syntax (closer to standard HTML), simpler mental model for SFC components, and built-in reactivity without additional libraries. ECUBE is an internal appliance tool — ecosystem breadth matters less than development speed and maintainability.

---

## 3. Project Structure

```text
frontend/
├── public/
│   ├── favicon.ico
│   └── themes/                    # User-customizable theme CSS files
│       ├── default.css            # Built-in light theme
│       ├── dark.css               # Built-in dark theme
│       └── README.md              # Instructions for creating custom themes
├── src/
│   ├── main.js                    # App entry point
│   ├── App.vue                    # Root component
│   ├── api/                       # API client modules
│   │   ├── client.js              # Axios instance, interceptors
│   │   ├── auth.js                # POST /auth/token
│   │   ├── drives.js              # GET/POST /drives/*
│   │   ├── jobs.js                # GET/POST /jobs/*
│   │   ├── mounts.js              # GET/POST/DELETE /mounts/*
│   │   ├── audit.js               # GET /audit
│   │   ├── files.js               # GET /files/*, POST /files/compare
│   │   ├── users.js               # GET/PUT/DELETE /users/*
│   │   ├── admin.js               # POST/GET/DELETE /admin/os-users, /admin/os-groups
│   │   ├── setup.js               # GET/POST/PUT /setup/*
│   │   └── introspection.js       # GET /introspection/*
│   ├── assets/
│   │   ├── base.css               # Reset, typography, layout utilities
│   │   └── buttons.css            # Shared button primitives and disabled/hover states (imported by main.css)
│   ├── components/
│   │   ├── layout/                # Shell components
│   │   │   ├── AppShell.vue       # Main authenticated layout
│   │   │   ├── AppHeader.vue      # Logo, user info, logout, token timer
│   │   │   ├── AppSidebar.vue     # Role-filtered navigation
│   │   │   └── AppFooter.vue      # Version, DB status, active jobs
│   │   └── common/                # Reusable UI components
│   │       ├── StatusBadge.vue    # Colored status indicator
│   │       ├── ProgressBar.vue    # Determinate/indeterminate progress
│   │       ├── ConfirmDialog.vue  # Yes/No confirmation modal
│   │       ├── DataTable.vue      # Sortable, paginated table
│   │       ├── Pagination.vue     # Page navigation controls
│   │       └── ToastNotification.vue  # Auto-dismissing notifications
│   ├── composables/               # Shared composition functions
│   │   ├── usePolling.js          # Generic polling with start/stop/interval
│   │   └── useRoleGuard.js        # Role-checking helper
│   ├── i18n/                      # Localization
│   │   ├── index.js               # Vue I18n instance setup
│   │   └── locales/
│   │       └── en.json            # English (default locale)
│   ├── router/
│   │   └── index.js               # Route definitions + navigation guards
│   ├── stores/
│   │   ├── auth.js                # Authentication state + token lifecycle
│   │   └── theme.js               # Theme loading, switching, persistence
│   └── views/                     # One per wireframe screen
│       ├── SetupWizardView.vue    # Screen 1: First-time setup
│       ├── LoginView.vue          # Screen 2: Login form
│       ├── DashboardView.vue      # Screen 3: Overview dashboard
│       ├── DrivesView.vue         # Screen 4a: Drive list
│       ├── DriveDetailView.vue    # Screen 4b: Single drive detail/actions
│       ├── MountsView.vue         # Screen 5: Mount management
│       ├── JobsView.vue           # Screen 6a: Job list
│       ├── JobDetailView.vue      # Screen 6b–d: Job detail/progress/files
│       ├── AuditView.vue          # Screen 7: Audit log viewer
│       ├── UsersView.vue          # Screen 8: User & role administration
│       └── SystemView.vue         # Screen 9: System monitoring
├── e2e/                           # Playwright E2E tests
│   ├── playwright.config.js
│   ├── login.spec.js
│   ├── dashboard.spec.js
│   ├── drives.spec.js
│   ├── jobs.spec.js
│   └── ...
├── index.html                     # Vite entry HTML
├── vite.config.js                 # Vite configuration
├── package.json                   # Dependencies and scripts
├── .gitignore
├── nginx.conf                     # nginx site configuration
└── Dockerfile                     # Multi-stage build: npm build → nginx
```

---

## 4. Application Shell & Routing

### 4.1 Application Shell

The authenticated layout uses a persistent `AppShell` component wrapping all post-login views. The shell mirrors the wireframe Global Layout:

```
┌─────────────────────────────────────────────────────┐
│  AppHeader                                          │
│  [LOGO]  ECUBE      username [role] ⏱ Nm  [Logout] │
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ AppSidebar  <router-view />                         │
│          │                                          │
├──────────┴──────────────────────────────────────────┤
│  AppFooter   v1.0.0 │ DB: ● │ Jobs: 2              │
└─────────────────────────────────────────────────────┘
```

- **SetupWizardView** and **LoginView** render outside the shell (no sidebar/header).
- All other views render inside the shell via `<router-view />`.

### 4.2 Route Table

| Path | View Component | Auth Required | Roles (sidebar visibility) | Wireframe |
|------|---------------|---------------|---------------------------|-----------|
| `/setup` | SetupWizardView | No¹ | — | Screen 1 |
| `/login` | LoginView | No | — | Screen 2 |
| `/` | DashboardView | Yes | All | Screen 3 |
| `/drives` | DrivesView | Yes | All | Screen 4a |
| `/drives/:id` | DriveDetailView | Yes | All (actions gated by role) | Screen 4b |
| `/mounts` | MountsView | Yes | All | Screen 5 |
| `/jobs` | JobsView | Yes | All | Screen 6a |
| `/jobs/:id` | JobDetailView | Yes | All (actions gated by role) | Screen 6b–d |
| `/audit` | AuditView | Yes | admin, manager, auditor | Screen 7 |
| `/users` | UsersView | Yes | admin | Screen 8 |
| `/system` | SystemView | Yes | All | Screen 9 |

¹ Setup route is accessible only when the system is not yet initialized; the app redirects to `/setup` automatically if `GET /setup/status` indicates first-run.

### 4.3 Navigation Guards

```text
beforeEach(to, from):
  1. If to.path === '/setup' → allow (handled by setup status check)
  2. If to.meta.requiresAuth && !authStore.isAuthenticated → redirect('/login')
  3. If to.meta.roles && !authStore.hasAnyRole(to.meta.roles) → redirect('/')
  4. Otherwise → allow
```

Token expiry is checked in the auth store. When a token is within 5 minutes of expiry, the header displays a warning. When expired, the user is redirected to `/login` with a session-expired message.

---

## 5. State Management

### 5.1 Auth Store (`stores/auth.js`)

| Property | Type | Description |
|----------|------|-------------|
| `token` | `string \| null` | JWT Bearer token |
| `username` | `string \| null` | Current user's login name |
| `roles` | `string[]` | Resolved ECUBE roles: admin, manager, processor, auditor |
| `groups` | `string[]` | OS group memberships |
| `expiresAt` | `number \| null` | Token expiration timestamp (epoch ms) |
| `isAuthenticated` | `boolean` (getter) | `true` if token exists and not expired |

| Action | Description |
|--------|-------------|
| `login(username, password)` | Call `POST /auth/token`, decode JWT, persist to `sessionStorage` |
| `logout()` | Clear state, remove from `sessionStorage`, redirect to `/login` |
| `hasRole(role)` | Check if user has a specific role |
| `hasAnyRole(roles)` | Check if user has at least one of the specified roles |
| `checkExpiry()` | Called on interval; triggers logout if expired |

Token is stored in `sessionStorage` (not `localStorage`) so it does not persist across browser tabs or after the tab closes — matching the appliance security model.

### 5.2 Theme Store (`stores/theme.js`)

| Property | Type | Description |
|----------|------|-------------|
| `currentTheme` | `string` | Active theme name (e.g. `"default"`, `"dark"`) |
| `availableThemes` | `string[]` | Discovered theme definitions exposed to the theme selector |

| Action | Description |
|--------|-------------|
| `loadTheme(name)` | Apply theme stylesheet, update branding metadata, persist choice |
| `initialize()` | Restore saved preference and establish safe fallback behavior |

See [Section 7](#7-theme--styling-system) for the theme CSS contract.

---

## 6. API Client Layer

### 6.1 Axios Instance (`api/client.js`)

```text
Base URL:  '' (same-origin; nginx proxies /api/* to backend)
Timeout:   30 seconds
Headers:   Content-Type: application/json
```

**Request interceptor:** Attaches `Authorization: Bearer <token>` from the auth store.

**Response interceptor:**
- **401** → Clear auth state, redirect to `/login` with message
- **403** → Display toast: "Insufficient permissions" with role hint
- **409** → Display toast: conflict explanation from `ErrorResponse.message`
- **422** → Display toast: validation error details
- **5xx** → Display toast: "Server error — try again" with `trace_id` for support

All errors are mapped from the backend's `ErrorResponse { code, message, trace_id }` schema.

### 6.2 API Modules

Each module exports thin wrapper functions around Axios calls. Modules map 1:1 to backend router groups.

| Module | Endpoints Covered | Used By |
|--------|------------------|---------|
| `auth.js` | `POST /auth/token` | LoginView, auth store |
| `setup.js` | `GET /setup/status`, `POST /setup/initialize`, `POST /setup/database/test-connection`, `POST /setup/database/provision`, `GET /setup/database/provision-status`, `GET /setup/database/system-info`, `GET /setup/database/status`, `PUT /setup/database/settings` | SetupWizardView |
| `drives.js` | `GET /drives`, `POST /drives/{id}/initialize`, `POST /drives/{id}/format`, `POST /drives/{id}/prepare-eject` | DrivesView, DriveDetailView, DashboardView |
| `mounts.js` | `GET /mounts`, `POST /mounts`, `DELETE /mounts/{id}` | MountsView |
| `jobs.js` | `POST /jobs`, `POST /jobs/{id}/start`, `GET /jobs/{id}`, `POST /jobs/{id}/verify`, `POST /jobs/{id}/manifest` | JobsView, JobDetailView, DashboardView |
| `audit.js` | `GET /audit` | AuditView |
| `files.js` | `GET /files/{file_id}/hashes`, `POST /files/compare` | JobDetailView (hash viewer, file compare) |
| `users.js` | `GET /users`, `GET /users/{username}/roles`, `PUT /users/{username}/roles`, `DELETE /users/{username}/roles` | UsersView |
| `admin.js` | `POST /admin/os-users`, `GET /admin/os-users`, `DELETE /admin/os-users/{username}`, `PUT /admin/os-users/{username}/password`, `PUT /admin/os-users/{username}/groups`, `POST /admin/os-users/{username}/groups`, `GET /admin/os-groups` | UsersView (single users/roles editor) |
| `introspection.js` | `GET /introspection/usb/topology`, `GET /introspection/block-devices`, `GET /introspection/mounts`, `GET /introspection/system-health`, `GET /introspection/jobs/{id}/debug` | SystemView, DashboardView, AppFooter |

### 6.3 Job Progress Polling

Job progress is tracked via HTTP polling rather than WebSocket. Rationale:

- **Zero backend changes** — `GET /jobs/{id}` already returns `copied_bytes`, file statuses, and job state
- **ECUBE is a single-operator appliance** — polling load is negligible
- **Copy jobs run for minutes to hours** — sub-second latency provides no practical benefit
- **Simpler infrastructure** — no WebSocket upgrade in nginx, no Redis pub/sub channel

The `usePolling` composable provides a standard pattern:

```text
usePolling(fetchFn, intervalMs, options):
  - Calls fetchFn immediately, then every intervalMs
  - Stops automatically when component unmounts
  - Stops when fetchFn returns a terminal state (COMPLETED, FAILED)
  - Default interval: 3000ms (3 seconds)
  - Exposes: start(), stop(), isPolling, lastResponse
```

Used by `JobDetailView` and `DashboardView` for live progress display.

---

## 7. Theme & Styling System

### 7.1 Design Approach

The frontend theme system is based on CSS custom properties and a small runtime store that selects a stylesheet plus optional branding metadata. Components consume design tokens rather than hardcoded presentation values so that the selected theme can restyle the application shell and views without component-specific branching.

Architecturally, theming is a presentation-layer concern only:

- Theme selection lives in the frontend store.
- Theme assets are static files served by the UI layer.
- No backend theme API is required for the current model.
- Missing or invalid theme assets must degrade to a readable default presentation.

### 7.2 CSS Custom Properties Contract

Themes define the design-token contract used by application styles. At a minimum, the contract covers:

- surface colors,
- text and semantic colors,
- borders and focus states,
- button, badge, and progress styles,
- typography tokens,
- spacing tokens, and
- layout primitives such as header, footer, and sidebar dimensions.

The exhaustive token reference and authoring guidance belong in operations documentation, not in this architecture document.

### 7.3 Built-in Themes

The baseline product ships with two built-in themes:

- `default`: primary light theme.
- `dark`: alternate dark theme.

These provide a stable contract for the theme store, visual regression tests, and operator-supplied custom themes.

### 7.4 Runtime Responsibilities

The theme subsystem is responsible for:

- resolving the selected theme,
- loading the corresponding stylesheet,
- exposing available theme choices to the UI,
- coordinating optional logo metadata with the selected theme, and
- falling back safely when theme assets are unavailable.

Operational theme authoring, deployment, and customization procedures are documented in [docs/operations/11-theme-and-branding-guide.md](../operations/11-theme-and-branding-guide.md).

---

## 8. Localization (i18n)

### 8.1 Framework

Vue I18n 9.x provides the localization infrastructure. All user-visible strings are externalized to locale JSON files under `src/i18n/locales/`.

### 8.2 Locale File Structure

```json
{
  "app": {
    "name": "ECUBE",
    "title": "Evidence Copying & USB Based Export"
  },
  "nav": {
    "dashboard": "Dashboard",
    "drives": "Drives",
    "mounts": "Mounts",
    "jobs": "Jobs",
    "audit": "Audit",
    "users": "Users",
    "system": "System"
  },
  "auth": {
    "login": "Log In",
    "logout": "Log Out",
    "username": "Username",
    "password": "Password",
    "sessionExpired": "Your session has expired. Please log in again.",
    "insufficientPermissions": "You do not have permission to perform this action."
  },
  "drives": {
    "title": "Drive Management",
    "status": { ... },
    "actions": { ... }
  },
  ...
}
```

### 8.3 Implementation Rules

- **All user-facing text** must use `$t('key')` in templates or `t('key')` in `<script setup>` — never hardcoded strings.
- **English (`en.json`)** is the default and only locale shipped initially. Additional locales can be added by creating new JSON files (e.g. `fr.json`, `es.json`).
- **Lazy loading:** Non-default locales are loaded on demand to keep the initial bundle small.
- **Date/time formatting:** Use Vue I18n's date/time formatting with locale-appropriate patterns.
- **Pluralization:** Use Vue I18n's plural syntax for countable items (e.g. "{count} file | {count} files").
- **API error messages** from `ErrorResponse.message` are displayed as-is (they come from the backend and are not localized by the frontend).

---

## 9. Component Inventory

### 9.1 Layout Components

| Component | Purpose | Wireframe Reference |
|-----------|---------|-------------------|
| `AppShell.vue` | Authenticated layout wrapper (header + sidebar + content + footer) | Global Layout |
| `AppHeader.vue` | Theme-managed logo image, app name, username/role display, token timer, logout button | Header bar |
| `AppSidebar.vue` | Navigation links filtered by user role | Sidebar navigation |
| `AppFooter.vue` | App version, DB connection indicator, active job count | Footer status bar |

### 9.2 View Components

| Component | Wireframe Screen | Use Cases | Key Features |
|-----------|-----------------|-----------|-------------|
| `SetupWizardView.vue` | Screen 1 | UC-1.1 – UC-1.6 | Multi-step wizard (DB test → provision → create admin); renders outside AppShell |
| `LoginView.vue` | Screen 2 | UC-2.1 – UC-2.2 | Username/password form; error display; renders outside AppShell |
| `DashboardView.vue` | Screen 3 | UC-8.1 – UC-8.2 | Summary cards: drive counts by state, active jobs, system health; polls introspection |
| `DrivesView.vue` | Screen 4a | UC-4.1 – UC-4.3 | Drive list table with status badges; refresh/rescan button |
| `DriveDetailView.vue` | Screen 4b | UC-4.4 – UC-4.7 | Drive properties; format, initialize, eject action panels; role-gated actions |
| `MountsView.vue` | Screen 5 | UC-5.1 – UC-5.6 | Mount list with test/unmount/remove actions; add-mount dialog |
| `JobsView.vue` | Screen 6a | UC-6.1, UC-6.3 | Job list with status/progress; create-job button |
| `JobDetailView.vue` | Screen 6b–d | UC-6.2 – UC-6.8 | Progress bar with polling; file list table; start/verify/manifest actions; hash viewer; file compare |
| `AuditView.vue` | Screen 7 | UC-7.1 – UC-7.7 | Filterable audit log table; date range, user, action filters; CSV export |
| `UsersView.vue` | Screen 8 | UC-3.1 – UC-3.9 | Single editable users table: role selection, per-user save, password reset, and create-user flow; admin-only |
| `SystemView.vue` | Screen 9 | UC-8.1 – UC-8.8 | Tabbed: Health, USB Topology, Block Devices, Mounts, Logs, Job Debug |

### 9.3 Common/Shared Components

| Component | Purpose | Used By |
|-----------|---------|--------|
| `StatusBadge.vue` | Colored pill showing state (EMPTY, AVAILABLE, IN_USE, RUNNING, etc.) | DrivesView, JobsView, MountsView |
| `ProgressBar.vue` | Determinate bar with percentage and bytes label | JobDetailView, DashboardView |
| `ConfirmDialog.vue` | Modal with title, message, confirm/cancel buttons | Format drive, delete mount, eject drive, remove user |
| `DataTable.vue` | Sortable, paginated table with slot-based column rendering | All list views |
| `Pagination.vue` | Page number navigation with page-size selector | All list views |
| `ToastNotification.vue` | Auto-dismissing notification banner (success, error, warning, info) | Global (via provide/inject or event bus) |

### 9.4 Composables

| Composable | Purpose |
|------------|---------|
| `usePolling.js` | Generic polling with configurable interval, auto-stop on terminal state, cleanup on unmount |
| `useRoleGuard.js` | `canPerform(action)` helper that checks current user roles against required roles |

### 9.5 Wireframe → Component Traceability

| Use Case Range | Wireframe Screen | Vue Component |
|---------------|-----------------|---------------|
| UC-1.1 – UC-1.6 | Screen 1: Setup Wizard | `SetupWizardView` |
| UC-2.1 – UC-2.2 | Screen 2: Login | `LoginView` |
| UC-2.3 – UC-2.4 | Global Layout: Header | `AppHeader` |
| UC-2.5 | Session Expired Dialog | `LoginView` (redirect with message) |
| UC-3.1 – UC-3.4 | Screen 8a/8b: User List, Edit Roles | `UsersView` |
| UC-3.5 | Screen 8c: Create User Dialog | `UsersView` (dialog) |
| UC-3.6 – UC-3.9 | Screen 8a: Inline actions | `UsersView` |
| UC-3.7 | Modal: Reset Password | `UsersView` (dialog) |
| UC-3.10 | Group listing | API only in current UI build |
| UC-4.1 – UC-4.2 | Screen 4a: Drive List | `DrivesView` |
| UC-4.3 | Screen 4a: Refresh | `DrivesView` |
| UC-4.4 – UC-4.6 | Screen 4b: Actions | `DriveDetailView` |
| UC-4.7 | Screen 4b: Properties | `DriveDetailView` |
| UC-5.1 | Screen 5a: Mount List | `MountsView` |
| UC-5.2 – UC-5.3 | Screen 5b: Add Mount | `MountsView` (dialog) |
| UC-5.4 – UC-5.6 | Screen 5a: Inline actions | `MountsView` |
| UC-6.1 | Screen 6c: Create Job | `JobsView` (wizard dialog) |
| UC-6.2 | Screen 6b: Start | `JobDetailView` |
| UC-6.3 | Screen 6a/6b: Progress | `JobsView`, `JobDetailView` |
| UC-6.4 | Screen 6b: Files table | `JobDetailView` |
| UC-6.5 – UC-6.6 | Screen 6b: Verify, Manifest | `JobDetailView` |
| UC-6.7 | Screen 6d: Hash Viewer | `JobDetailView` (panel) |
| UC-6.8 | Screen 6d: File Compare | `JobDetailView` (panel) |
| UC-7.1 – UC-7.6 | Screen 7a: Audit Log | `AuditView` |
| UC-7.7 | Screen 7a: Export CSV | `AuditView` |
| UC-8.1 – UC-8.2 | Screen 9a + Footer | `SystemView`, `AppFooter` |
| UC-8.3 | Screen 9b: USB Topology | `SystemView` (tab) |
| UC-8.4 – UC-8.5 | Screen 9a: Block Devices / Mounts | `SystemView` (tabs) |
| UC-8.6 | Screen 9d: Job Debug | `SystemView` (tab) |
| UC-8.7 – UC-8.8 | Screen 9c: Logs Tab | `SystemView` (tab) |

---

## 10. Role-Based UI Behavior

### 10.1 Sidebar Visibility

| Navigation Item | admin | manager | processor | auditor |
|----------------|:-----:|:-------:|:---------:|:-------:|
| Dashboard | ✔ | ✔ | ✔ | ✔ |
| Drives | ✔ | ✔ | ✔ | ✔ |
| Mounts | ✔ | ✔ | ✔ | ✔ |
| Jobs | ✔ | ✔ | ✔ | ✔ |
| Audit | ✔ | ✔ | ✗ | ✔ |
| Users | ✔ | ✗ | ✗ | ✗ |
| System | ✔ | ✔ | ✔ | ✔ |

### 10.2 Action Visibility Within Views

| Action | admin | manager | processor | auditor |
|--------|:-----:|:-------:|:---------:|:-------:|
| Format drive | ✔ | ✔ | ✗ | ✗ |
| Initialize drive | ✔ | ✔ | ✗ | ✗ |
| Eject drive | ✔ | ✔ | ✗ | ✗ |
| Add/remove mount | ✔ | ✔ | ✗ | ✗ |
| Create job | ✔ | ✔ | ✔ | ✗ |
| Start job | ✔ | ✔ | ✔ | ✗ |
| Verify/manifest | ✔ | ✔ | ✔ | ✗ |
| View file hashes | ✔ | ✗ | ✗ | ✔ |
| Compare files | ✔ | ✗ | ✗ | ✔ |
| Manage users/roles | ✔ | ✗ | ✗ | ✗ |
| Manage users/groups | ✔ | ✗ | ✗ | ✗ |
| Export audit CSV | ✔ | ✔ | ✗ | ✔ |

### 10.3 Implementation Pattern

Actions are hidden (not just disabled) when the user's role cannot perform them. The `useRoleGuard` composable provides a standard check:

```vue
<template>
  <button v-if="canPerform('format-drive')" @click="formatDrive">
    {{ $t('drives.actions.format') }}
  </button>
</template>
```

**Important:** UI role gating is a UX convenience only. The backend enforces authorization on every request via `require_roles()`. A hidden button does not replace server-side validation.

---

## 11. Deployment Architecture

### 11.1 Container Topology

```text
┌──────────────┐       ┌───────────────┐       ┌──────────────┐
│              │  :443  │               │ :8000  │              │
│   Browser    │───────▶│   ecube-ui    │───────▶│  ecube-app   │
│              │  TLS   │   (nginx)     │  proxy │  (FastAPI)   │
│              │        │               │        │              │
└──────────────┘        └───────────────┘        └──────┬───────┘
                                                        │
                                                 ┌──────▼───────┐
                                                 │   postgres   │
                                                 │  (PostgreSQL)│
                                                 └──────────────┘
```

### 11.2 nginx Configuration

At the architectural level, the frontend web tier is responsible for:

| Request Path | Action |
|-------------|--------|
| `/api/*` | Proxy to `http://ecube-app:8000/*` (strip `/api` prefix) |
| `/docs`, `/redoc`, `/openapi.json` | Proxy to `http://ecube-app:8000/` (API docs passthrough) |
| `/themes/*.css` | Serve from `/usr/share/nginx/html/themes/` |
| `/*` (everything else) | Serve SPA; fall back to `index.html` for client-side routing |

This separation keeps static asset serving and browser-facing TLS concerns out of the FastAPI runtime.

### 11.3 Deployment Shape

The frontend is packaged as a separate UI service that depends on the backend API service and optionally consumes mounted certificate and theme assets from deployment-managed paths.

### 11.4 Dockerfile (Multi-Stage)

The UI image uses a multi-stage build so dependency-heavy frontend compilation remains separate from the lean nginx runtime image.

### 11.5 Backend CORS Requirement

When the frontend and API are not presented through a single browser origin, the backend must support an explicit CORS policy. In same-origin reverse-proxy deployments, this concern is largely absorbed by the proxy layer.

---

## 12. Testing Strategy

### 12.1 Unit Tests (Vitest + Vue Test Utils)

| Target | What to Test |
|--------|-------------|
| **Auth store** | Login/logout flow, token parsing, role checking, expiry detection |
| **Theme store** | Theme loading, persistence, switching |
| **API client interceptors** | Token injection, 401/403/5xx error mapping |
| **usePolling composable** | Interval behavior, stop on terminal state, cleanup |
| **useRoleGuard composable** | Role checking against various user configurations |
| **Common components** | StatusBadge renders correct colors; ProgressBar computes percentage; ConfirmDialog emits events |

Unit tests should isolate presentation and state-management concerns from live backend dependencies.

### 12.2 End-to-End Tests (Playwright)

End-to-end tests validate complete user flows against a real backend or a controlled mock backend, with emphasis on auth, routing, role-gated actions, and theme-sensitive rendering.

Representative end-to-end coverage areas include login, dashboard refresh behavior, drive and job workflows, audit visibility, user administration, role gating, and theme switching.

### 12.3 Accessibility Testing

- Integrate `@axe-core/playwright` into E2E tests for automated WCAG 2.1 AA checks
- Each E2E test includes an accessibility scan of the final page state
- Manual keyboard navigation testing for modals and form flows

### 12.4 Visual Regression

- Use Playwright's screenshot comparison (`toHaveScreenshot()`) for theme consistency
- Capture baseline screenshots for both default and dark themes
- Flag visual differences on PR builds

Detailed test invocation, file organization, and CI execution procedures belong in testing documentation rather than this architecture document.

---

## 13. Browser Support

| Browser | Minimum Version | Engine |
|---------|----------------|--------|
| Google Chrome | Latest 2 major versions | Chromium |
| Microsoft Edge | Latest 2 major versions | Chromium |
| Apple Safari | Latest 2 major versions | WebKit |

The application does not target Firefox, Internet Explorer, or mobile browsers. ECUBE is an appliance accessed from workstations on a local network.

Playwright's engine coverage (Chromium + WebKit) provides automated testing for all three supported browsers (Chrome and Edge share Chromium).

---

## 14. Open Questions & Future Considerations

| Topic | Status | Notes |
|-------|--------|-------|
| **Component library** | Open | Evaluate PrimeVue, Vuetify, or Naive UI vs. hand-built components. Decision deferred to Phase 2 implementation. |
| **Audit CSV export endpoint** | Open | Use cases mention CSV export (UC-7.7) but the current API only supports JSON. May require a new backend endpoint or client-side CSV generation. |
| **Real-time upgrades** | Deferred | Polling (3s interval) is the baseline. WebSocket can be added later if multi-user concurrent viewing becomes a requirement. |
| **PWA / offline support** | Not planned | ECUBE requires network access to the API; offline mode is not applicable. |
| **Additional locales** | Future | Only `en.json` ships initially. Translation contributions can add new locale files without code changes. |
