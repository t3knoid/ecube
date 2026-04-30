<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getDrives, refreshDrives } from '@/api/drives.js'
import { listAllJobs } from '@/api/jobs.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'
import { formatDriveIdentity } from '@/utils/driveIdentity.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'
import { buildDriveJobMap, buildProjectEvidenceMap, getDriveJob, getProjectEvidence } from '@/utils/projectEvidence.js'

const { t } = useI18n()
const { driveStateLabel } = useStatusLabels()
const router = useRouter()

const drives = ref([])
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const search = ref('')
const stateFilter = ref('ALL')
const sortKey = ref('id')
const sortDir = ref('asc')
const page = ref(1)
const pageSize = ref(10)
const isMobileViewport = ref(false)
const driveJobById = ref(new Map())
const projectEvidenceById = ref(new Map())
let mobileViewportQuery = null

/** Drive ID currently being browsed (null = none open). */
const browsingDriveId = ref(null)

/** The currently-browsed drive object. */
const activeBrowsedDrive = computed(() =>
  browsingDriveId.value !== null
    ? drives.value.find((d) => d.id === browsingDriveId.value) || null
    : null
)

const columns = computed(() => {
  const nextColumns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'display_device_label', label: t('drives.device') },
    { key: 'serial_number', label: t('drives.serialNumber') },
    { key: 'capacity_bytes', label: t('common.labels.size'), align: 'right' },
    { key: 'current_state', label: t('common.labels.status') },
    { key: 'current_project_id', label: t('dashboard.project') },
    { key: 'current_project_evidence_number', label: t('jobs.evidence') },
    { key: 'actions', label: '', align: 'center' },
  ]

  if (isMobileViewport.value) {
    return nextColumns.filter(
      (column) =>
        column.key !== 'serial_number' &&
        column.key !== 'capacity_bytes',
    )
  }

  return nextColumns
})

function formatBytes(value) {
  if (typeof value !== 'number' || value <= 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let next = value
  let unit = 0
  while (next >= 1024 && unit < units.length - 1) {
    next /= 1024
    unit += 1
  }
  return `${next.toFixed(next >= 10 ? 0 : 1)} ${units[unit]}`
}

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function normalizeStatusValue(status) {
  return String(status ?? 'unknown').toUpperCase()
}

function driveStatusTone(status) {
  const value = normalizeStatusValue(status)

  if (['COMPLETED', 'DONE', 'MOUNTED', 'CONNECTED', 'AVAILABLE', 'OK', 'TRUE'].includes(value)) {
    return 'success'
  }
  if (['FAILED', 'ERROR', 'DISCONNECTED', 'UNMOUNTED', 'FALSE'].includes(value)) {
    return 'danger'
  }
  if (['RUNNING', 'VERIFYING', 'COPYING', 'IN_USE', 'DEGRADED'].includes(value)) {
    return 'warning'
  }
  if (['PENDING', 'UNKNOWN'].includes(value)) {
    return 'muted'
  }

  return 'info'
}

function driveStatusIcon(status) {
  const tone = driveStatusTone(status)

  if (tone === 'success') return '✓'
  if (tone === 'warning') return '!'
  if (tone === 'danger') return '×'
  if (tone === 'muted') return '•'
  return '?'
}

function syncViewportState() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return

  if (!mobileViewportQuery) {
    mobileViewportQuery = window.matchMedia('(max-width: 768px)')
  }

  isMobileViewport.value = mobileViewportQuery.matches
}

async function loadDrives() {
  loading.value = true
  error.value = ''
  try {
    const params = {}
    if (stateFilter.value === 'ALL' || stateFilter.value === 'DISCONNECTED') {
      params.include_disconnected = true
    }
    const [driveResult, jobResult] = await Promise.allSettled([
      getDrives(params),
      listAllJobs({ include_archived: true }),
    ])

    if (driveResult.status !== 'fulfilled') {
      throw driveResult.reason
    }

    const jobs = jobResult.status === 'fulfilled' ? (jobResult.value || []) : []

    projectEvidenceById.value = buildProjectEvidenceMap(jobs)
    driveJobById.value = buildDriveJobMap(jobs)

    drives.value = (driveResult.value || []).map((item) => {
      const drive = normalizeProjectRecord(item, ['current_project_id'])
      const assignedJob = getDriveJob(drive.id, driveJobById.value)
      return {
        ...drive,
        current_project_job_id: assignedJob?.jobId ?? null,
        current_project_evidence_number: assignedJob?.evidenceNumber || getProjectEvidence(drive.current_project_id, projectEvidenceById.value),
      }
    })
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return drives.value.filter((drive) => {
    const state = String(drive.current_state || '').toUpperCase()
    const stateMatch = stateFilter.value === 'ALL' || state === stateFilter.value
    const text = [
      drive.display_device_label,
      drive.manufacturer,
      drive.product_name,
      drive.port_system_path,
      drive.serial_number,
      drive.current_project_id,
      drive.current_project_evidence_number,
      drive.filesystem_path,
      String(drive.id),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    const queryMatch = !query || text.includes(query)
    return stateMatch && queryMatch
  })
})

const sorted = computed(() => {
  const list = [...filtered.value]
  list.sort((a, b) => {
    const left = a[sortKey.value]
    const right = b[sortKey.value]
    if (left === right) return 0
    const order = sortDir.value === 'asc' ? 1 : -1
    if (left === undefined || left === null) return 1
    if (right === undefined || right === null) return -1
    if (typeof left === 'number' && typeof right === 'number') {
      return (left - right) * order
    }
    return String(left).localeCompare(String(right)) * order
  })
  return list
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return sorted.value.slice(start, start + pageSize.value)
})

function setSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

async function resetToAllAndReload() {
  const previousState = stateFilter.value
  const previousIncludesDisconnected = previousState === 'ALL' || previousState === 'DISCONNECTED'

  if (previousState !== 'ALL') {
    stateFilter.value = 'ALL'
  }

  if (previousIncludesDisconnected) {
    await loadDrives()
  }
}

async function refreshList() {
  error.value = ''
  try {
    await resetToAllAndReload()
  } catch {
    error.value = t('common.errors.networkError')
  }
}

async function rescan() {
  refreshing.value = true
  error.value = ''
  try {
    await refreshDrives()
    await resetToAllAndReload()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    refreshing.value = false
  }
}

watch(stateFilter, (newValue, oldValue) => {
  page.value = 1

  const nextIncludesDisconnected = newValue === 'ALL' || newValue === 'DISCONNECTED'
  const previousIncludesDisconnected = oldValue === 'ALL' || oldValue === 'DISCONNECTED'

  if (nextIncludesDisconnected !== previousIncludesDisconnected) {
    loadDrives()
  }
})

function openDrive(drive) {
  router.push({ name: 'drive-detail', params: { id: drive.id } })
}

function openRelatedJob(jobId) {
  const normalizedJobId = Number(jobId)
  if (!Number.isInteger(normalizedJobId) || normalizedJobId < 1) return
  router.push({ name: 'job-detail', params: { id: normalizedJobId } })
}

function closeRowActionsMenu(event) {
  const menu = event?.currentTarget instanceof HTMLElement ? event.currentTarget.closest('details') : null
  if (menu instanceof HTMLDetailsElement) {
    menu.removeAttribute('open')
  }
}

function handleMenuOpenDrive(drive, event) {
  closeRowActionsMenu(event)
  openDrive(drive)
}

function handleMenuBrowse(drive, event) {
  closeRowActionsMenu(event)
  void toggleBrowse(drive.id)
}

const browsePanelRef = ref(null)

async function toggleBrowse(driveId) {
  browsingDriveId.value = browsingDriveId.value === driveId ? null : driveId
  if (browsingDriveId.value !== null) {
    await nextTick()
    if (typeof browsePanelRef.value?.scrollIntoView === 'function') {
      browsePanelRef.value.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }
}

onMounted(() => {
  syncViewportState()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    if (!mobileViewportQuery) {
      mobileViewportQuery = window.matchMedia('(max-width: 768px)')
    }
    mobileViewportQuery.addEventListener('change', syncViewportState)
  }

  void loadDrives()
})

onBeforeUnmount(() => {
  mobileViewportQuery?.removeEventListener('change', syncViewportState)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('drives.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="refreshList">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" :disabled="refreshing" @click="rescan">
          {{ refreshing ? t('common.labels.loading') : t('drives.rescan') }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="filters">
      <input v-model="search" type="text" :placeholder="t('drives.searchPlaceholder')" :aria-label="t('drives.searchPlaceholder')" />
      <select v-model="stateFilter" :aria-label="t('drives.allStates')">
        <option value="ALL">{{ t('drives.allStates') }}</option>
        <option value="DISCONNECTED">{{ t('drives.states.disconnected') }}</option>
        <option value="AVAILABLE">{{ t('drives.states.available') }}</option>
        <option value="IN_USE">{{ t('drives.states.inUse') }}</option>
        <option value="ARCHIVED">{{ t('drives.states.archived') }}</option>
      </select>
      <select v-model="sortKey" :aria-label="t('drives.sortBy')">
        <option value="id">{{ t('common.labels.id') }}</option>
        <option value="display_device_label">{{ t('drives.device') }}</option>
        <option value="serial_number">{{ t('drives.serialNumber') }}</option>
        <option value="current_state">{{ t('common.labels.status') }}</option>
        <option value="current_project_id">{{ t('dashboard.project') }}</option>
        <option value="current_project_evidence_number">{{ t('jobs.evidence') }}</option>
      </select>
      <button class="btn" @click="setSort(sortKey)">
        {{ sortDir === 'asc' ? t('drives.sortAsc') : t('drives.sortDesc') }}
      </button>
    </div>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('drives.empty')">
      <template #cell-display_device_label="{ row }">
        {{ formatDriveIdentity(row) }}
      </template>
      <template #cell-serial_number="{ row }">
        {{ row.serial_number || '-' }}
      </template>
      <template #cell-current_project_id="{ row }">
        <button
          v-if="row.current_project_job_id"
          class="cell-link"
          type="button"
          @click="openRelatedJob(row.current_project_job_id)"
        >
          {{ formatProjectId(row.current_project_id) }}
        </button>
        <span v-else>{{ formatProjectId(row.current_project_id) }}</span>
      </template>
      <template #cell-current_project_evidence_number="{ row }">
        <button
          v-if="row.current_project_job_id && row.current_project_evidence_number"
          class="cell-link"
          type="button"
          @click="openRelatedJob(row.current_project_job_id)"
        >
          {{ row.current_project_evidence_number }}
        </button>
        <span v-else>{{ row.current_project_evidence_number || '-' }}</span>
      </template>
      <template #cell-current_state="{ row }">
        <span
          v-if="isMobileViewport"
          class="drive-status-icon"
          :class="`drive-status-icon--${driveStatusTone(row.current_state)}`"
          :aria-label="driveStateLabel(row.current_state)"
          :title="driveStateLabel(row.current_state)"
          role="img"
        >
          <span aria-hidden="true">{{ driveStatusIcon(row.current_state) }}</span>
        </span>
        <StatusBadge v-else :status="row.current_state" :label="driveStateLabel(row.current_state)" />
      </template>
      <template #cell-capacity_bytes="{ row }">
        {{ formatBytes(row.capacity_bytes) }}
      </template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn" @click="openDrive(row)">{{ t('drives.details') }}</button>
          <button
            v-if="row.mount_path"
            class="btn"
            @click="toggleBrowse(row.id)"
          >
            {{ t('drives.browse') }}
          </button>
        </div>
        <details class="row-actions-menu">
          <summary class="row-actions-toggle" :aria-label="`${formatDriveIdentity(row)} drive actions`">
            <span class="row-actions-toggle-dots" aria-hidden="true">
              <span class="row-actions-toggle-dot" />
              <span class="row-actions-toggle-dot" />
              <span class="row-actions-toggle-dot" />
            </span>
          </summary>
          <div class="row-actions-popover">
            <button class="btn row-action-menu-details" @click="handleMenuOpenDrive(row, $event)">
              {{ t('drives.details') }}
            </button>
            <button
              v-if="row.mount_path"
              class="btn row-action-menu-browse"
              @click="handleMenuBrowse(row, $event)"
            >
              {{ t('drives.browse') }}
            </button>
          </div>
        </details>
      </template>
    </DataTable>

    <section
      v-if="activeBrowsedDrive?.mount_path"
      ref="browsePanelRef"
      class="browse-panel"
    >
      <header class="browse-panel-header">
        <h2>{{ t('browse.browseContents') }}</h2>
        <button class="btn" @click="toggleBrowse(activeBrowsedDrive.id)">
          {{ t('common.actions.close') }}
        </button>
      </header>
      <DirectoryBrowser :mount-path="activeBrowsedDrive.mount_path" />
    </section>

    <Pagination v-model:page="page" :page-size="pageSize" :total="sorted.length" />
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.actions,
.filters,
.row-actions {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  align-items: center;
  justify-content: space-between;
}

.filters {
  flex-wrap: wrap;
}

.cell-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-link);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.cell-link:hover,
.cell-link:focus-visible {
  text-decoration-thickness: 2px;
}

.row-actions {
  flex-wrap: wrap;
  justify-content: center;
}

.drive-status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border: 1px solid transparent;
  border-radius: 9999px;
  font-size: 0.9rem;
  font-weight: var(--font-weight-bold);
  line-height: 1;
}

.drive-status-icon--success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.drive-status-icon--warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.drive-status-icon--danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.drive-status-icon--info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.drive-status-icon--muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}

.row-actions-menu {
  display: none;
  position: relative;
}

.row-actions-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  cursor: pointer;
}

.row-actions-toggle-dots {
  display: inline-grid;
  gap: 0.15rem;
}

.row-actions-toggle-dot {
  width: 0.25rem;
  height: 0.25rem;
  border-radius: 9999px;
  background: currentColor;
}

.row-actions-toggle::-webkit-details-marker {
  display: none;
}

.row-actions-popover {
  position: absolute;
  top: calc(100% + var(--space-2xs));
  right: 0;
  z-index: 2;
  min-width: 8.5rem;
  display: grid;
  gap: var(--space-2xs);
  padding: var(--space-2xs);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.12));
}

.browse-panel {
  display: grid;
  gap: var(--space-sm);
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
}

.browse-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

input,
select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

@media (max-width: 768px) {
  :deep(.table-scroll-wrapper) {
    overflow: visible;
  }

  .row-actions {
    display: none;
  }

  .row-actions-menu {
    display: inline-block;
  }
}
</style>
