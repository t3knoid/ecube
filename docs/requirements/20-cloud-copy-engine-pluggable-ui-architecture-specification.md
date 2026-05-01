# 20. ECUBE Cloud Copy Engine Pluggable UI Architecture Specification

| Field | Value |
|---|---|
| Document Title | ECUBE Cloud Copy Engine - Pluggable UI Architecture Specification |
| Version | 1.0 DRAFT |
| Date | May 2026 |
| Status | Draft for Review |
| Author | Frank Refol |
| Reviewers | TBD |
| Approval | TBD |

### Reference Documents

- ECUBE Cloud Copy Engine - Requirements & Specification v1.0
- ECUBE Cloud Copy Engine - Provider SDK Contract Specification v1.0
- ECUBE Development Guide (`00-development-guide.md`)

## 1. Introduction

### 1.1 The Problem

The ECUBE Cloud Copy Engine uses a pluggable backend contract (`ICloudProvider`) that allows any cloud source to integrate without the engine knowing platform specifics. If the UI is hardcoded to a specific provider's configuration fields, that pluggability breaks at the user interface layer. Every new provider would require frontend code changes, new views, and new forms, which defeats the purpose of the generic contract.

Concretely, a complex provider such as RelativityOne requires workspace IDs, OAuth2 credentials, export source types, view IDs, and advanced options, while a simpler provider such as Azure Blob Storage may require only an account URL, container name, and SAS token. Without a pluggable UI, ECUBE would need provider-specific forms like `RelativityOneConfigForm.vue` and `AzureBlobConfigForm.vue`, and that maintenance burden would scale linearly with provider count.

### 1.2 The Solution

The UI follows the same pluggable pattern as the backend. It is split into three layers:

1. Generic Shell: ECUBE-owned views and components that are the same for every provider, including job creation workflow, progress dashboard, device status, chain-of-custody viewer, file manifest browser, and error log viewer. These are standard Vue views inside the existing `AppShell.vue` layout.
2. Schema-Driven Provider Configuration: Each cloud provider declares its configuration requirements as a Pydantic model on the backend. The backend exposes that model as JSON Schema. The frontend renders it dynamically using a generic `DynamicSchemaForm.vue` component. No provider-specific frontend code is needed for basic configuration.
3. Optional Provider Widgets: For richer provider-specific UX, such as a RelativityOne workspace browser or an S3 bucket tree, providers can optionally contribute Vue SFC components. These load dynamically and attach to designated slots inside the generic shell.

Key insight: a provider that ships only a Pydantic config schema and an `ICloudProvider` implementation gets a fully functional UI automatically. Custom Vue widgets are optional progressive enhancements.

### 1.3 Design Principles

- Zero frontend changes for basic providers: a provider that ships only a Pydantic config schema and an `ICloudProvider` implementation gets a fully functional UI automatically.
- Progressive enhancement: providers can optionally ship Vue components for richer UX, but the baseline works without them.
- Capability-adaptive display: the frontend reads `CloudProviderCapabilities` flags and conditionally shows or hides UI elements such as hash columns, resume buttons, rate limit indicators, and concurrent download gauges.
- Alignment with existing ECUBE patterns: the design uses the same `AppShell` layout, Pinia stores, Axios API layer, Vue Router patterns, `vue-i18n`, and Vitest/Playwright testing approach as the rest of ECUBE.

## 2. ECUBE Stack Alignment

### 2.1 Existing Architecture Summary

All Cloud Copy Engine code must align with the following stack. Deviations are not permitted without architecture review.

| Layer | Technology | Pattern |
|---|---|---|
| Backend Framework | FastAPI (Python 3.11+) | Routers -> Services -> Repositories -> Models |
| ORM | SQLAlchemy | Models in `app/models/`, Base class in `app/database.py` |
| Migrations | Alembic | Repository migration workflow under `alembic/versions/` |
| API Schemas | Pydantic | Request and response models in `app/schemas/` |
| Authentication | JWT | `app/auth.py`, role-based guards, `useAuthStore` on frontend |
| Frontend Framework | Vue 3.5 (JavaScript) | SFC `.vue` files, Composition API |
| Build Tool | Vite 8 | `vite.config.js`, lazy-loaded route chunks |
| State Management | Pinia 3 | Stores in `src/stores/` |
| Routing | Vue Router 5 | `src/router/index.js`, role guards, telemetry hooks |
| HTTP Client | Axios | API modules in `src/api/` |
| i18n | vue-i18n | Locale files in `src/i18n/` |
| Styling | Vanilla CSS | Scoped `<style>` blocks in SFCs, no framework |
| Unit Tests | Vitest | `src/views/__tests__/` |
| E2E Tests | Playwright | `frontend/e2e/` |
| Accessibility | axe-core | Integrated with Playwright |
| Telemetry | Custom | `postUiNavigationTelemetry()` on route transitions |

### 2.2 Existing Views Structure

The current ECUBE frontend views that the Cloud Copy Engine views will sit alongside are:

```text
src/views/
├── DashboardView.vue
├── DrivesView.vue
├── DriveDetailView.vue
├── JobsView.vue
├── JobDetailView.vue
├── MountsView.vue
├── AuditView.vue
├── ConfigurationView.vue
├── SystemView.vue
├── ReconciliationResultsView.vue
├── UsersView.vue
├── LoginView.vue
├── SetupWizardView.vue
└── AboutView.vue
```

### 2.3 New CCE Views

The Cloud Copy Engine adds four new views to the existing structure:

```text
src/views/
├── ...
├── CloudJobsView.vue
├── CloudJobCreateView.vue
├── CloudJobDetailView.vue
└── CloudProviderConfigView.vue
```

All new views follow the same SFC structure, Composition API patterns, and scoped CSS conventions as existing ECUBE views. They are lazy-loaded via Vue Router dynamic imports.

## 3. Layer 1 - Generic Shell

The generic shell consists of four Vue views that provide the complete cloud job workflow. These views are provider-agnostic. Provider-specific content is injected through schema-driven forms in Layer 2 and optional widgets in Layer 3.

### 3.1 CloudJobsView.vue

The cloud jobs list view displays all cloud export jobs in a filterable table, aligned with the existing `JobsView.vue` patterns.

- Columns: Job ID, Provider, Source Description or Label, Status, Progress, Devices, Files, Created, Updated.
- Controls: Row click navigates to `CloudJobDetailView`. A New Cloud Export action opens `CloudJobCreateView`. Status and provider filters are populated dynamically.

Representative script shape:

```javascript
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useCloudJobStore } from '@/stores/cloudJob.js'
import { useCloudProviderStore } from '@/stores/cloudProvider.js'

const router = useRouter()
const jobStore = useCloudJobStore()
const providerStore = useCloudProviderStore()
const statusFilter = ref('all')
const providerFilter = ref('all')

const filteredJobs = computed(() => {
  let result = jobStore.jobs
  if (statusFilter.value !== 'all') {
    result = result.filter((job) => job.status === statusFilter.value)
  }
  if (providerFilter.value !== 'all') {
    result = result.filter((job) => job.provider_id === providerFilter.value)
  }
  return result
})

onMounted(async () => {
  await Promise.all([jobStore.fetchJobs(), providerStore.fetchAll()])
})
```

### 3.2 CloudJobCreateView.vue - The Job Creation Wizard

This is the most important generic view. It is a multi-step wizard that works for any provider without modification.

| Step | Title | Description |
|---|---|---|
| 1 | Select Provider | Displays cards for each registered provider with icon, name, description, and version. Populated dynamically from `GET /api/cloud/providers/`. On selection, fetches the provider's UI schema and capabilities. |
| 2 | Configure Provider | Renders `DynamicSchemaForm.vue` with the selected provider's JSON Schema. This step is entirely dynamic and may also show or hide sections based on `CloudProviderCapabilities`. |
| 3 | Select Target Devices | Lists available USB devices from the existing device management layer. This step is generic for all providers. |
| 4 | Review & Submit | Presents a full summary and submits the job. |

Representative wizard state:

```javascript
const currentStep = ref(1)
const totalSteps = 4
const selectedProviderId = ref(null)
const providerConfig = ref({})
const credentialConfig = ref({})
const configFormValid = ref(false)
const availableDevices = ref([])
const selectedDeviceIds = ref([])
```

Representative submission shape:

```javascript
async function submitJob() {
  const job = await jobStore.create({
    provider_id: selectedProviderId.value,
    provider_config: providerConfig.value,
    credential_config: credentialConfig.value,
    target_device_ids: selectedDeviceIds.value,
    job_label: providerConfig.value._job_label || '',
  })
  router.push({ name: 'cloud-job-detail', params: { id: job.id } })
}
```

### 3.3 CloudJobDetailView.vue

The cloud job detail view is the primary monitoring interface for a running or completed cloud export job. It adapts its display based on the provider's capability flags.

| Panel | Content |
|---|---|
| Header | Job ID, provider name or icon, status badge, created and updated timestamps |
| Progress Section | Overall progress bar, file counts, bytes transferred, ETA, transfer rate |
| Device Status Panel | Per-device progress bars, health indicators, and current file per device |
| File Manifest Table | File name, path, size, status, hash match, retry count, with capability-driven columns |
| Chain-of-Custody Panel | Full custody record for completed files, with links into audit views |
| Error Log Panel | Error classifications, timestamps, retry state, and expandable details |
| Controls | Pause, Resume, Cancel, Retry Failed, depending on job state and capabilities |

Capability-adaptive rendering pattern:

```javascript
const capabilities = computed(() => providerStore.getCapabilities(job.value?.provider_id))
const showHashColumn = computed(() => capabilities.value?.supports_hash ?? false)
const showResumeButton = computed(() => capabilities.value?.supports_resumable_download ?? false)
const showRateLimitIndicator = computed(() => capabilities.value?.rate_limited ?? false)
const showGroupTransactions = computed(() => capabilities.value?.supports_groups ?? false)
const showConcurrencyGauge = computed(() => capabilities.value?.supports_concurrent_downloads ?? false)
const showSizeColumn = computed(() => capabilities.value?.supports_file_size ?? false)
```

### 3.4 CloudProviderConfigView.vue (Admin)

The provider management view is restricted to administrator roles. It provides:

- Provider List: registered providers with name, version, status, and capability summary.
- Test Connection: a per-provider action that instantiates the provider, calls `authenticate()`, and reports success or failure.
- Global Overrides: system-level settings such as maximum concurrent downloads, bandwidth throttle, and default retry policy.
- Access Control: route guarding and backend enforcement for admin-only behavior.

## 4. Layer 2 - Schema-Driven Provider Configuration

This is the core of the pluggable UI. Providers declare their configuration as a Pydantic model. The system converts it to JSON Schema and the frontend renders it as a form automatically. No provider-specific frontend code is required.

### 4.1 Backend: Provider UI Schema Registration

Each provider registers a `ProviderUISchema` alongside its `ICloudProvider`. This Pydantic model contains the JSON Schema for the configuration form plus layout hints that control grouping, ordering, and conditional visibility.

Core schema definitions:

```python
from pydantic import BaseModel
from typing import Optional, Any


class FieldGrouping(BaseModel):
    id: str
    label: str
    description: str = ""
    collapsed_by_default: bool = False
    fields: list[str]


class ConditionalVisibility(BaseModel):
    field: str
    depends_on: str
    show_when: list[Any]


class ProviderSummary(BaseModel):
    provider_id: str
    display_name: str
    description: str
    icon_url: Optional[str] = None
    version: str


class ProviderUISchema(BaseModel):
    provider_id: str
    display_name: str
    description: str
    icon_url: Optional[str] = None
    version: str
    config_schema: dict
    field_groups: list[FieldGrouping] = []
    field_order: list[str] = []
    conditional_visibility: list[ConditionalVisibility] = []
    documentation_url: Optional[str] = None
    setup_instructions: Optional[str] = None
```

Concrete example: RelativityOne registers a rich schema with grouped fields, conditional visibility, credential inputs, and advanced settings.

Contrasting example: Azure Blob Storage registers a minimal schema with only a few fields. Both render through the same `DynamicSchemaForm.vue` component without provider-specific frontend code.

### 4.2 Backend: FastAPI Endpoints

The Cloud Copy Engine API is served under the `/api/cloud` prefix. All endpoints require JWT authentication. Provider management endpoints are restricted to admin roles.

Representative endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /api/cloud/providers` | List registered cloud providers with summary info |
| `GET /api/cloud/providers/{provider_id}/schema` | Return the full UI schema for a provider |
| `GET /api/cloud/providers/{provider_id}/capabilities` | Return capability flags for display adaptation |
| `POST /api/cloud/providers/{provider_id}/test-connection` | Test authentication with provider credentials |
| `POST /api/cloud/jobs` | Create a new cloud export job |
| `GET /api/cloud/jobs` | List cloud export jobs with optional filters |
| `GET /api/cloud/jobs/{job_id}` | Return cloud job detail including file manifest |
| `GET /api/cloud/jobs/{job_id}/progress` | Return a real-time progress snapshot |
| `POST /api/cloud/jobs/{job_id}/pause` | Pause a running job |
| `POST /api/cloud/jobs/{job_id}/resume` | Resume a paused job |
| `POST /api/cloud/jobs/{job_id}/cancel` | Cancel a running or paused job |
| `POST /api/cloud/jobs/{job_id}/retry-failed` | Retry failed files |

### 4.3 Frontend: DynamicSchemaForm.vue

This is the core generic form renderer. It takes JSON Schema plus layout hints from `ProviderUISchema` and renders a complete, validated form. This single component replaces the need for provider-specific form components.

JSON Schema to form field mapping:

| JSON Schema Type | Extra Annotation | Rendered As |
|---|---|---|
| `string` | none | text input |
| `string` | `format: uri` | URL input with format validation |
| `string` | `format: password` or `sensitive: true` | password input |
| `string` | `enum` present | select dropdown |
| `integer` | numeric constraints | number input with min and max |
| `boolean` | none | checkbox |
| `array` | enum items | multi-select checkbox group |
| nullable scalar | Optional or nullable | base field type with empty value mapping to `null` |

Representative component responsibilities:

- initialize form data from schema defaults
- resolve field ordering and grouping
- evaluate conditional visibility
- map JSON Schema shapes to form controls
- split credential and non-credential values on emit
- validate fields inline
- support test-connection actions for auth groups

### 4.4 Frontend: API Layer

The Axios API module follows existing ECUBE patterns under `src/api/`. All functions return unwrapped response data.

Representative exports:

```javascript
export async function fetchProviders() {}
export async function fetchProviderSchema(providerId) {}
export async function fetchProviderCapabilities(providerId) {}
export async function testProviderConnection(providerId, config) {}
export async function fetchCloudJobs(filters = {}) {}
export async function fetchCloudJob(jobId) {}
export async function fetchCloudJobProgress(jobId) {}
export async function createCloudJob(jobData) {}
export async function pauseCloudJob(jobId) {}
export async function resumeCloudJob(jobId) {}
export async function cancelCloudJob(jobId) {}
export async function retryFailedFiles(jobId) {}
```

### 4.5 Frontend: Pinia Stores

#### Cloud Provider Store

The provider store caches provider summaries, schemas, and capability flags, and exposes actions such as:

- `fetchAll()`
- `loadSchema(providerId)`
- `loadCapabilities(providerId)`
- `getCapabilities(providerId)`
- `testConnection(providerId, config)`

#### Cloud Job Store

The job store manages:

- job listing
- single-job detail
- real-time progress polling
- lifecycle commands such as create, pause, resume, cancel, and retry failed

### 4.6 Router Registration

The new cloud routes are added as children of the `AppShell` layout route, alongside existing views. All routes are lazy-loaded via dynamic imports.

Representative route additions:

```javascript
{
  path: 'cloud/jobs',
  name: 'cloud-jobs',
  component: () => import('@/views/CloudJobsView.vue'),
}
{
  path: 'cloud/jobs/new',
  name: 'cloud-job-create',
  component: () => import('@/views/CloudJobCreateView.vue'),
}
{
  path: 'cloud/jobs/:id',
  name: 'cloud-job-detail',
  component: () => import('@/views/CloudJobDetailView.vue'),
}
{
  path: 'cloud/providers',
  name: 'cloud-providers',
  component: () => import('@/views/CloudProviderConfigView.vue'),
  meta: { roles: USERS_ROLES },
}
```

Navigation integration: the AppShell sidebar should include a Cloud Exports group with links to `cloud-jobs` and `cloud-providers` where appropriate. The dashboard should include a cloud jobs summary widget showing active and failed counts.

## 5. Layer 3 - Optional Provider Widgets

The generic shell defines named slots where providers can inject custom Vue components for richer UX. If no widget is provided, the slot renders a sensible default or is hidden. This is an optional layer. The system remains fully functional without any provider widgets.

### 5.1 The Widget Slot System

| Slot Name | Location | Purpose | Default If Empty |
|---|---|---|---|
| `source-browser` | CloudJobCreateView Step 2 | Interactive browser for selecting export source | Standard form field for artifact ID |
| `job-summary-header` | CloudJobDetailView header | Provider-specific status summary | Generic provider name plus source ID |
| `file-preview` | CloudJobDetailView file manifest | Preview or thumbnail for individual files | No preview |
| `progress-detail` | CloudJobDetailView progress section | Provider-specific progress indicators | Standard progress bar and stats |

### 5.2 Widget Registration

Providers register widgets through a JavaScript manifest file. Each entry maps a slot name to a dynamically imported Vue SFC component. These components are not bundled with the core ECUBE frontend and instead load at runtime.

```javascript
export default {
  'source-browser': () => import('./RelativitySourceBrowser.vue'),
  'progress-detail': () => import('./RelativityRateLimitGauge.vue'),
}
```

### 5.3 Widget Loading in the Generic Shell

The widget-loading composable looks up the provider's manifest and dynamically imports the component for a given slot. If the provider has no widget for that slot, or if loading fails, the generic shell falls back to default rendering.

Key behavior:

- lazy load widgets at runtime
- allow provider-specific bundles outside the core app bundle
- handle failures gracefully by returning `widget = null`
- never let widget-loading failure break the generic shell

## 6. Capability-Adaptive UI Reference

The frontend reads `CloudProviderCapabilities` flags from the backend and conditionally renders UI elements. This ensures that the interface only shows features the provider actually supports.

| Capability Flag | UI Effect When true | UI Effect When false |
|---|---|---|
| `supports_hash` | Show Expected Hash and Hash Match columns in file manifest and chain-of-custody views | Hide hash columns and use size-only verification display |
| `supports_file_size` | Show file size column, byte-level progress, and ETA | Hide size column and use file-count-only progress |
| `supports_resumable_download` | Show Resume button and partial download indicators | Show Restart Download instead |
| `supports_concurrent_downloads` | Show concurrency gauge and per-stream indicators | Show a single-download indicator only |
| `max_concurrent_downloads` | Cap concurrency display and show values like Active: 3 / 8 | Use a system default or show no upper limit |
| `supports_groups` | Group files by document with document-level transaction status | Show a flat file list |
| `supports_metadata_export` | Show Generate Load File toggle and load-file manifest entry | Hide metadata-export UI |
| `rate_limited` | Show rate-limit indicators, 429 counts, and throttling warnings | Hide rate-limit-specific UI |

Implementation pattern:

```javascript
const capabilities = computed(() => providerStore.getCapabilities(job.value?.provider_id))
const showHashColumn = computed(() => capabilities.value?.supports_hash ?? false)
const showSizeColumn = computed(() => capabilities.value?.supports_file_size ?? false)
const showResumeButton = computed(() => capabilities.value?.supports_resumable_download ?? false)
```

Default behavior: if capabilities have not yet loaded, all capability-gated UI elements default to hidden. This prevents flicker where unsupported controls appear briefly and then disappear.

## 7. Data Models - Backend Schemas

### 7.1 Pydantic Schemas for Jobs

The backend defines request and response models for Cloud Copy Engine job APIs.

Representative models:

```python
class CloudJobStatus(str, Enum):
    pending = 'pending'
    running = 'running'
    paused = 'paused'
    completed = 'completed'
    completed_with_errors = 'completed_with_errors'
    failed = 'failed'
    cancelled = 'cancelled'


class CloudJobCreate(BaseModel):
    provider_id: str
    provider_config: dict[str, Any]
    credential_config: dict[str, Any]
    target_device_ids: list[int]
    job_label: str = ''
```

Additional schemas cover per-file status, real-time progress snapshots, full job responses, and paginated job list responses.

### 7.2 SQLAlchemy Models

Representative persisted entities are:

- `CloudJob`
- `CloudJobFile`
- `CloudProviderRegistration`

These models store provider registration metadata, cloud job state, file-level status, retries, provider metadata, progress totals, and safe timestamps needed for UI display and backend orchestration.

## 8. Alembic Migration

The source artifact includes a sample migration that creates tables for:

- `cloud_provider_registrations`
- `cloud_jobs`
- `cloud_job_files`

Repository note: in this codebase, any schema change for the current unreleased cycle MUST follow ECUBE's release-scoped Alembic workflow and update the current release migration file instead of introducing a new standalone unreleased migration. The artifact's sample migration is therefore an architectural example, not a repository-specific instruction to create a new numbered file.

## 9. Testing Strategy

### 9.1 Backend Tests (pytest)

All backend tests follow ECUBE's existing pytest patterns, using SQLite in-memory databases and FastAPI `TestClient`.

| Test Category | Test Cases |
|---|---|
| Provider Schema Endpoints | Provider listing, schema retrieval, 404 handling, schema output matching Pydantic model output |
| Job CRUD | Valid job creation, invalid config rejection, list and detail retrieval, filter behavior, pagination |
| Job State Machine | Valid transitions, invalid transition conflicts, terminal-state restrictions |
| Provider Config Validation | Required field handling, type mismatches, range constraints, extra field behavior |
| Test Connection | Success and failure responses, timeout handling, mock provider isolation |
| Authentication | JWT enforcement and admin-only endpoint restrictions |

### 9.2 Frontend Unit Tests (Vitest)

| Component / Store | Test Cases |
|---|---|
| `DynamicSchemaForm.vue` | Field rendering, enum handling, multi-select behavior, conditional visibility, validation, collapsed groups, model emission, test-connection flow |
| `useCloudProviderStore` | Provider cache behavior, schema loading, capability loading, cache-hit behavior |
| `useCloudJobStore` | Job list state, detail loading, progress polling, terminal-state stop behavior, lifecycle commands, API failure handling |
| Capability-Adaptive Rendering | Show or hide hash, resume, rate-limit, and size-based UI depending on capability flags |

### 9.3 E2E Tests (Playwright)

| Scenario | Description |
|---|---|
| Job Creation Wizard | Full create flow from provider selection through submission |
| Job Detail Progress | Verify progress polling, status transitions, and manifest population |
| Schema Form Rendering | Complex schema rendering, conditional visibility, validation display |
| Role-Based Access | Admin access to provider config, operator restrictions, navigation visibility |

### 9.4 Accessibility (axe-core)

All Playwright E2E tests include axe-core scans. The artifact enforces at least these accessibility requirements:

- all form fields have associated labels or `aria-label`
- collapsible groups are keyboard navigable with `tabindex`, `Enter`, `Space`, and `aria-expanded`
- progress bars expose `aria-valuenow`, `aria-valuemin`, `aria-valuemax`, and `aria-label`
- color is not the only status indicator
- provider cards use radio-style semantics with `role="radio"` and `aria-checked`
- error messages use `role="alert"`
- all interactive elements have visible focus indicators

## 10. i18n Considerations

All user-facing strings are externalized through `vue-i18n` locale keys. The artifact adds a `cloud` namespace that includes labels for:

- cloud jobs list and detail screens
- provider selection and testing
- wizard step labels and actions
- status values and table column names

Provider-supplied labels from JSON Schema, such as field `title` and `description`, are not automatically managed by ECUBE core i18n. Providers that require multi-language support should embed translated strings in their schemas or contribute locale extensions.

## 11. Summary: What Each Stakeholder Ships

| Stakeholder | Ships | Frontend Code? | Backend Code? |
|---|---|---|---|
| ECUBE Core Team | Generic shell views, `DynamicSchemaForm.vue`, `useProviderWidget`, Pinia stores, Axios API module, FastAPI router and endpoints, Pydantic schemas, SQLAlchemy models, migration support, i18n keys, test infrastructure | Yes (once) | Yes (once) |
| Basic Provider Developer | `ICloudProvider` implementation and Pydantic config model via `ProviderUISchema` with `config_schema`, `field_groups`, `field_order`, and `conditional_visibility` | No | Yes |
| Advanced Provider Developer | Everything from the basic provider, plus optional widget manifest and Vue widget components | Optional | Yes |

The core promise of this architecture is that a provider developer who writes only backend Python, specifically a Pydantic config model and an `ICloudProvider` implementation, gets a fully functional, validated, capability-adaptive UI without writing a single line of JavaScript. Optional widgets exist to enhance UX, not to make the system usable.