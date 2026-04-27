<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getDrives } from '@/api/drives.js'
import { getMounts } from '@/api/mounts.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const { t } = useI18n()
const { driveStateLabel } = useStatusLabels()
const router = useRouter()

const props = defineProps({
  reconciliationResult: {
    type: Object,
    default: null,
  },
})

// Get the reconciliation result from props or navigation state
const reconciliationResult = ref(
  props.reconciliationResult || history.state?.reconciliationResult || null
)
const drives = ref([])
const mounts = ref([])
const loading = ref(false)
const error = ref('')
const isMobileViewport = ref(false)
let mobileViewportQuery = null

const usbDrivesPage = ref(1)
const usbDrivesPageSize = ref(5)
const sharedMountsPage = ref(1)
const sharedMountsPageSize = ref(5)

const usbDrivesColumns = computed(() => {
  const columns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'display_device_label', label: t('drives.device') },
    { key: 'serial_number', label: t('drives.serialNumber') },
    { key: 'filesystem_type', label: t('drives.filesystem') },
    { key: 'capacity_bytes', label: t('common.labels.size'), align: 'right' },
    { key: 'current_state', label: t('common.labels.status') },
    { key: 'current_project_id', label: t('dashboard.project') },
  ]

  if (isMobileViewport.value) {
    return columns.filter(
      (column) =>
        column.key !== 'serial_number' &&
        column.key !== 'filesystem_type' &&
        column.key !== 'capacity_bytes',
    )
  }

  return columns
})

const sharedMountsColumns = computed(() => {
  const columns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'type', label: t('common.labels.type') },
    { key: 'project_id', label: t('dashboard.project') },
    { key: 'status', label: t('common.labels.status') },
  ]

  if (isMobileViewport.value) {
    return columns.filter((column) => column.key !== 'type')
  }

  return columns
})

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
  if (['PENDING', 'PAUSED', 'UNKNOWN'].includes(value)) {
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

function mountStatusTone(status) {
  const value = normalizeStatusValue(status)

  if (['MOUNTED', 'COMPLETED', 'DONE', 'OK', 'TRUE'].includes(value)) {
    return 'success'
  }
  if (['FAILED', 'ERROR', 'UNMOUNTED', 'FALSE'].includes(value)) {
    return 'danger'
  }
  if (['VERIFYING', 'CHECKING', 'DEGRADED'].includes(value)) {
    return 'warning'
  }
  if (['PENDING', 'UNKNOWN'].includes(value)) {
    return 'muted'
  }

  return 'info'
}

function mountStatusIcon(status) {
  const tone = mountStatusTone(status)

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

async function loadDrives() {
  try {
    const response = await getDrives()
    drives.value = (response || []).map((item) =>
      normalizeProjectRecord(item, ['current_project_id'])
    )
  } catch {
    error.value = t('common.errors.networkError')
  }
}

async function loadMounts() {
  try {
    const response = await getMounts()
    mounts.value = (response || []).map((item) =>
      normalizeProjectRecord(item, ['project_id'])
    )
  } catch {
    error.value = t('common.errors.networkError')
  }
}

const pagedUsbDrives = computed(() => {
  const start = (usbDrivesPage.value - 1) * usbDrivesPageSize.value
  return drives.value.slice(start, start + usbDrivesPageSize.value)
})

const pagedSharedMounts = computed(() => {
  const start = (sharedMountsPage.value - 1) * sharedMountsPageSize.value
  return mounts.value.slice(start, start + sharedMountsPageSize.value)
})

const statusBadgeType = computed(() => {
  if (!reconciliationResult.value) return 'unknown'
  return reconciliationResult.value.status === 'ok' ? 'ok' : 'warning'
})

const statusDisplay = computed(() => {
  if (!reconciliationResult.value) return '-'
  return t(`system.reconcileStatuses.${reconciliationResult.value.status}`)
})

onMounted(async () => {
  syncViewportState()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    if (!mobileViewportQuery) {
      mobileViewportQuery = window.matchMedia('(max-width: 768px)')
    }
    mobileViewportQuery.addEventListener('change', syncViewportState)
  }

  if (!reconciliationResult.value) {
    error.value = t('system.reconciliationResultsNotAvailable')
    return
  }

  loading.value = true
  try {
    await Promise.all([loadDrives(), loadMounts()])
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  mobileViewportQuery?.removeEventListener('change', syncViewportState)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('system.reconciliationResults') }}</h1>
      <button class="btn" @click="router.back()">
        {{ t('common.actions.back') }}
      </button>
    </header>

    <div v-if="error" class="error-banner">{{ error }}</div>

    <article v-if="reconciliationResult" class="panel summary-panel">
      <h2>{{ t('system.reconciliationSummary') }}</h2>
      <div class="summary-grid">
        <span>{{ t('common.labels.status') }}</span>
        <StatusBadge :status="statusBadgeType">{{ statusDisplay }}</StatusBadge>

        <span>{{ t('system.networkMountsChecked') }}</span>
        <strong>{{ reconciliationResult.network_mounts_checked }}</strong>

        <span>{{ t('system.networkMountsCorrected') }}</span>
        <strong>{{ reconciliationResult.network_mounts_corrected }}</strong>

        <span>{{ t('system.usbMountsChecked') }}</span>
        <strong>{{ reconciliationResult.usb_mounts_checked }}</strong>

        <span>{{ t('system.usbMountsCorrected') }}</span>
        <strong>{{ reconciliationResult.usb_mounts_corrected }}</strong>

        <span>{{ t('system.failureCount') }}</span>
        <strong :class="reconciliationResult.failure_count > 0 ? 'error-text' : ''">
          {{ reconciliationResult.failure_count }}
        </strong>
      </div>
    </article>

    <div v-if="loading" class="muted">{{ t('common.labels.loading') }}</div>

    <article v-if="!loading && drives.length > 0" class="panel">
      <h2>{{ t('system.reconciledUsbMounts') }}</h2>
      <DataTable :columns="usbDrivesColumns" :rows="pagedUsbDrives" :empty-text="t('system.empty')">
        <template #cell-capacity_bytes="{ row }">{{ formatBytes(row.capacity_bytes) }}</template>
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
          <StatusBadge v-else :status="row.current_state || 'unknown'" :label="driveStateLabel(row.current_state)" />
        </template>
        <template #cell-current_project_id="{ row }">{{ formatProjectId(row.current_project_id) }}</template>
      </DataTable>
      <Pagination v-model:page="usbDrivesPage" :page-size="usbDrivesPageSize" :total="drives.length" />
    </article>

    <article v-if="!loading && mounts.length > 0" class="panel">
      <h2>{{ t('system.reconciledSharedMounts') }}</h2>
      <DataTable :columns="sharedMountsColumns" :rows="pagedSharedMounts" :empty-text="t('system.empty')">
        <template #cell-status="{ row }">
          <span
            v-if="isMobileViewport"
            class="mount-status-icon"
            :class="`mount-status-icon--${mountStatusTone(row.status)}`"
            :aria-label="row.status || 'UNKNOWN'"
            :title="row.status || 'UNKNOWN'"
            role="img"
          >
            <span aria-hidden="true">{{ mountStatusIcon(row.status) }}</span>
          </span>
          <StatusBadge v-else :status="row.status || 'unknown'" />
        </template>
        <template #cell-project_id="{ row }">{{ formatProjectId(row.project_id) }}</template>
      </DataTable>
      <Pagination v-model:page="sharedMountsPage" :page-size="sharedMountsPageSize" :total="mounts.length" />
    </article>

    <div v-if="!loading && drives.length === 0 && mounts.length === 0" class="muted">
      {{ t('system.reconciliationNoData') }}
    </div>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.summary-panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-md);
}

.summary-grid {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--space-xs) var(--space-md);
  align-items: center;
}

.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-sm);
}

.panel h2 {
  margin: 0;
  padding: 0;
  font-size: 1.1rem;
  color: var(--color-text-primary);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.error-text {
  color: var(--color-alert-danger-text);
}

.muted {
  color: var(--color-text-secondary);
  padding: var(--space-md);
}

.drive-status-icon,
.mount-status-icon {
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

.drive-status-icon--success,
.mount-status-icon--success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.drive-status-icon--warning,
.mount-status-icon--warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.drive-status-icon--danger,
.mount-status-icon--danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.drive-status-icon--info,
.mount-status-icon--info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.drive-status-icon--muted,
.mount-status-icon--muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}
</style>
