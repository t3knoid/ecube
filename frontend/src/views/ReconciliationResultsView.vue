<script setup>
import { computed, onBeforeMount, onMounted, ref } from 'vue'
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

const usbDrivesPage = ref(1)
const usbDrivesPageSize = ref(5)
const sharedMountsPage = ref(1)
const sharedMountsPageSize = ref(5)

const usbDrivesColumns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'display_device_label', label: t('drives.device') },
  { key: 'serial_number', label: t('drives.serialNumber') },
  { key: 'filesystem_type', label: t('drives.filesystem') },
  { key: 'capacity_bytes', label: t('common.labels.size'), align: 'right' },
  { key: 'current_state', label: t('common.labels.status') },
  { key: 'current_project_id', label: t('dashboard.project') },
])

const sharedMountsColumns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'type', label: t('common.labels.type') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'local_mount_point', label: t('mounts.mountPoint') },
])

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
          <StatusBadge :status="row.current_state || 'unknown'" />
        </template>
        <template #cell-current_project_id="{ row }">{{ formatProjectId(row.current_project_id) }}</template>
      </DataTable>
      <Pagination v-model:page="usbDrivesPage" :page-size="usbDrivesPageSize" :total="drives.length" />
    </article>

    <article v-if="!loading && mounts.length > 0" class="panel">
      <h2>{{ t('system.reconciledSharedMounts') }}</h2>
      <DataTable :columns="sharedMountsColumns" :rows="pagedSharedMounts" :empty-text="t('system.empty')">
        <template #cell-status="{ row }">
          <StatusBadge :status="row.status || 'unknown'" />
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
</style>
