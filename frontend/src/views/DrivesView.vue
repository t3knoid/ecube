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
import { useAuthStore } from '@/stores/auth.js'
import { formatDriveIdentity } from '@/utils/driveIdentity.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'
import { buildDriveJobMap, buildProjectEvidenceMap, getDriveJob, getProjectEvidenceJobId } from '@/utils/projectEvidence.js'

const { t } = useI18n()
const { driveStateLabel } = useStatusLabels()
const authStore = useAuthStore()
const router = useRouter()

const drives = ref([])
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const search = ref('')
const stateFilter = ref('ALL')
const showDisconnected = ref(false)
const sortKey = ref('id')
const sortDir = ref('asc')
const page = ref(1)
const pageSize = ref(10)
const isMobileViewport = ref(false)
const driveJobById = ref(new Map())
let mobileViewportQuery = null

/** Drive ID currently being browsed (null = none open). */
const browsingDriveId = ref(null)

/** The currently-browsed drive object. */
const activeBrowsedDrive = computed(() =>
  browsingDriveId.value !== null
    ? drives.value.find((d) => d.id === browsingDriveId.value) || null
    : null
)
const canManageDrives = computed(() => authStore.hasAnyRole(['admin', 'manager']))

const columns = computed(() => {
  return [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'display_device_label', label: t('drives.device') },
    { key: 'current_project_id', label: t('dashboard.project') },
    { key: 'current_state', label: t('common.labels.status') },
    { key: 'current_project_job_id', label: t('jobs.jobId'), align: 'right' },
  ]
})

function isValidJobId(value) {
  const normalizedJobId = Number(value)
  return Number.isInteger(normalizedJobId) && normalizedJobId > 0
}

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function driveBrowseTitle(drive) {
  if (!drive) return t('browse.browseContents')
  return t('browse.browseDriveContentsTitle', { device: formatDriveIdentity(drive) })
}

function normalizeStatusValue(status) {
  return String(status ?? 'unknown').toUpperCase()
}

function driveStatusTone(status) {
  const value = normalizeStatusValue(status)

  if (['COMPLETED', 'DONE', 'MOUNTED', 'CONNECTED', 'AVAILABLE', 'OK', 'TRUE'].includes(value)) {
    return 'success'
  }
  if (['FAILED', 'ERROR', 'DISCONNECTED', 'FALSE'].includes(value)) {
    return 'danger'
  }
  if (['DISABLED'].includes(value)) {
    return 'warning'
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
    if (showDisconnected.value) {
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

    driveJobById.value = buildDriveJobMap(jobs)
    const evidenceByProject = buildProjectEvidenceMap(jobs)

    drives.value = (driveResult.value || []).map((item) => {
      const drive = normalizeProjectRecord(item, ['current_project_id'])
      const hasActiveProjectBinding = Boolean(normalizeProjectId(drive.current_project_id))
      const assignedJob = hasActiveProjectBinding ? getDriveJob(drive.id, driveJobById.value) : null
      return {
        ...drive,
        current_project_job_id: hasActiveProjectBinding
          ? assignedJob?.jobId ?? getProjectEvidenceJobId(drive.current_project_id, evidenceByProject)
          : null,
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
      drive.current_project_id,
      drive.current_project_job_id,
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
  if (stateFilter.value !== 'ALL') {
    stateFilter.value = 'ALL'
  }

  await loadDrives()
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
  if (!canManageDrives.value) return
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

watch(stateFilter, () => {
  page.value = 1
})

watch(showDisconnected, () => {
  page.value = 1
  loadDrives()
})

function openRelatedJob(jobId) {
  const normalizedJobId = Number(jobId)
  if (!Number.isInteger(normalizedJobId) || normalizedJobId < 1) return
  router.push({ name: 'job-detail', params: { id: normalizedJobId } })
}

function openDriveById(driveId) {
  const normalizedDriveId = Number(driveId)
  if (!Number.isInteger(normalizedDriveId) || normalizedDriveId < 1) return
  router.push({ name: 'drive-detail', params: { id: normalizedDriveId } })
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
        <button v-if="canManageDrives" class="btn btn-primary" :disabled="refreshing" @click="rescan">
          {{ refreshing ? t('common.labels.loading') : t('drives.rescan') }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="filters">
      <input v-model="search" type="text" :placeholder="t('drives.searchPlaceholder')" :aria-label="t('drives.searchPlaceholder')" />
      <select v-model="stateFilter" :aria-label="t('drives.allStates')">
        <option value="ALL">{{ t('drives.allStates') }}</option>
        <option value="DISABLED">{{ t('drives.states.disabled') }}</option>
        <option value="AVAILABLE">{{ t('drives.states.available') }}</option>
        <option value="IN_USE">{{ t('drives.states.inUse') }}</option>
      </select>
      <label>
        <input v-model="showDisconnected" type="checkbox" />
        {{ t('drives.showDisconnected') }}
      </label>
      <select v-model="sortKey" :aria-label="t('drives.sortBy')">
        <option value="id">{{ t('common.labels.id') }}</option>
        <option value="display_device_label">{{ t('drives.device') }}</option>
        <option value="current_project_id">{{ t('dashboard.project') }}</option>
        <option value="current_state">{{ t('common.labels.status') }}</option>
        <option value="current_project_job_id">{{ t('jobs.jobId') }}</option>
      </select>
      <button class="btn" @click="setSort(sortKey)">
        {{ sortDir === 'asc' ? t('drives.sortAsc') : t('drives.sortDesc') }}
      </button>
    </div>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('drives.empty')">
      <template #cell-id="{ row }">
        <button class="cell-link drive-id-link" type="button" @click="openDriveById(row.id)">
          {{ row.id }}
        </button>
      </template>
      <template #cell-display_device_label="{ row }">
        <button
          v-if="row.mount_path"
          class="cell-link drive-device-link"
          type="button"
          @click="toggleBrowse(row.id)"
        >
          {{ formatDriveIdentity(row) }}
        </button>
        <span v-else>{{ formatDriveIdentity(row) }}</span>
      </template>
      <template #cell-current_project_id="{ row }">
        <span>{{ formatProjectId(row.current_project_id) }}</span>
      </template>
      <template #cell-current_project_job_id="{ row }">
        <button
          v-if="isValidJobId(row.current_project_job_id)"
          class="cell-link"
          type="button"
          @click="openRelatedJob(row.current_project_job_id)"
        >
          {{ row.current_project_job_id }}
        </button>
        <span v-else>-</span>
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
    </DataTable>

    <section
      v-if="activeBrowsedDrive?.mount_path"
      ref="browsePanelRef"
      class="browse-panel"
    >
      <header class="browse-panel-header">
        <h2>{{ driveBrowseTitle(activeBrowsedDrive) }}</h2>
        <button class="btn" @click="toggleBrowse(activeBrowsedDrive.id)">
          {{ t('common.actions.close') }}
        </button>
      </header>
      <DirectoryBrowser :mount-path="activeBrowsedDrive.mount_path" root-label="" />
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
.filters {
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

:deep(.data-table th),
:deep(.data-table th > span),
:deep(.data-table th .sort-button),
:deep(.data-table th .sort-button > span) {
  font-weight: var(--font-weight-bold);
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
}
</style>
