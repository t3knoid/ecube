<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  getSystemHealth,
  getUsbTopology,
  getBlockDevices,
  getSystemMounts,
  getJobDebug,
} from '@/api/introspection.js'
import { downloadLogFile, getLogFiles } from '@/api/admin.js'
import { listJobs } from '@/api/jobs.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const { t } = useI18n()

const tabs = ['health', 'usb', 'block', 'mounts', 'logs', 'job-debug']
const activeTab = ref('health')
const loading = ref(false)
const error = ref('')

const health = ref(null)
const usbDevices = ref([])
const blockDevices = ref([])
const mounts = ref([])
const logs = ref([])
const downloadingLogName = ref('')
const jobDebug = ref(null)
const jobDebugId = ref('')
const jobs = ref([])
const jobsListUnavailable = ref(false)

const page = ref(1)
const pageSize = ref(10)

const tabColumns = computed(() => {
  if (activeTab.value === 'usb') {
    return [
      { key: 'device', label: t('system.device') },
      { key: 'manufacturer', label: t('system.manufacturer') },
      { key: 'product', label: t('system.product') },
      { key: 'idVendor', label: t('system.vendorId') },
      { key: 'idProduct', label: t('system.productId') },
    ]
  }
  if (activeTab.value === 'block') {
    return [
      { key: 'name', label: t('common.labels.name') },
      { key: 'major', label: t('system.major') },
      { key: 'minor', label: t('system.minor') },
    ]
  }
  if (activeTab.value === 'mounts') {
    return [
      { key: 'device', label: t('system.device') },
      { key: 'mount_point', label: t('system.mountPoint') },
      { key: 'fs_type', label: t('system.fsType') },
      { key: 'options', label: t('system.options') },
    ]
  }
  if (activeTab.value === 'logs') {
    return [
      { key: 'name', label: t('common.labels.name') },
      { key: 'size', label: t('common.labels.size'), align: 'right' },
      { key: 'modified', label: t('common.labels.date') },
      { key: 'download', label: t('system.download'), align: 'center' },
    ]
  }
  return []
})

const tabRows = computed(() => {
  if (activeTab.value === 'usb') return usbDevices.value
  if (activeTab.value === 'block') return blockDevices.value
  if (activeTab.value === 'mounts') return mounts.value
  if (activeTab.value === 'logs') return logs.value
  return []
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return tabRows.value.slice(start, start + pageSize.value)
})

function formatBytes(value) {
  if (typeof value !== 'number' || value <= 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let next = value
  let idx = 0
  while (next >= 1024 && idx < units.length - 1) {
    next /= 1024
    idx += 1
  }
  return `${next.toFixed(next >= 10 ? 0 : 1)} ${units[idx]}`
}

function asLocalDate(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

function extractApiMessage(err) {
  const data = err?.response?.data || {}
  return String(data.message || data.detail || '').trim()
}

async function loadTabData() {
  loading.value = true
  error.value = ''
  try {
    if (activeTab.value === 'health') {
      health.value = await getSystemHealth()
    } else if (activeTab.value === 'usb') {
      const response = await getUsbTopology()
      usbDevices.value = response.devices || []
    } else if (activeTab.value === 'block') {
      const response = await getBlockDevices()
      blockDevices.value = response.block_devices || []
    } else if (activeTab.value === 'mounts') {
      const response = await getSystemMounts()
      mounts.value = response.mounts || []
    } else if (activeTab.value === 'logs') {
      const response = await getLogFiles()
      logs.value = response.log_files || []
    }
  } catch (err) {
    const status = err?.response?.status
    if (activeTab.value === 'logs' && status === 404) {
      error.value = t('system.logsNotConfigured')
    } else {
      error.value = extractApiMessage(err) || t('common.errors.requestConflict')
    }
  } finally {
    loading.value = false
  }
}

async function loadJobDebug() {
  if (!jobDebugId.value) {
    error.value = t('system.enterJobId')
    return
  }
  loading.value = true
  error.value = ''
  try {
    jobDebug.value = await getJobDebug(Number(jobDebugId.value))
  } catch (err) {
    const status = err?.response?.status
    if (status === 404) {
      error.value = t('system.jobNotFound')
      jobDebug.value = null
    } else {
      error.value = extractApiMessage(err) || t('common.errors.requestConflict')
    }
  } finally {
    loading.value = false
  }
}

async function loadJobOptions() {
  jobsListUnavailable.value = false
  try {
    const response = await listJobs({ limit: 200 })
    jobs.value = Array.isArray(response) ? response : []
  } catch {
    jobs.value = []
    jobsListUnavailable.value = true
  }
}

function onJobPickerChange(event) {
  const selected = String(event?.target?.value || '')
  jobDebugId.value = selected
  if (selected) {
    loadJobDebug()
  }
}

async function downloadLog(row) {
  const name = String(row?.name || '')
  if (!name) return

  downloadingLogName.value = name
  error.value = ''
  try {
    const response = await downloadLogFile(name)
    const contentType = response?.headers?.['content-type'] || 'application/octet-stream'
    const blob = response.data instanceof Blob ? response.data : new Blob([response.data], { type: contentType })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = name
    document.body.appendChild(anchor)
    anchor.click()
    document.body.removeChild(anchor)
    URL.revokeObjectURL(url)
  } catch (err) {
    error.value = extractApiMessage(err) || t('common.errors.requestConflict')
  } finally {
    downloadingLogName.value = ''
  }
}

watch(activeTab, async () => {
  page.value = 1
  if (activeTab.value === 'job-debug') {
    await loadJobOptions()
  } else {
    await loadTabData()
  }
})

onMounted(loadTabData)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('system.title') }}</h1>
      <button class="btn" @click="activeTab === 'job-debug' ? loadJobDebug() : loadTabData()">
        {{ t('common.actions.refresh') }}
      </button>
    </header>

    <div class="tabs">
      <button
        v-for="tab in tabs"
        :key="tab"
        class="btn"
        :class="{ active: activeTab === tab }"
        @click="activeTab = tab"
      >
        {{ t(`system.tabs.${tab}`) }}
      </button>
    </div>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article v-if="activeTab === 'health'" class="panel">
      <div class="health-grid">
        <span>{{ t('common.labels.status') }}</span><StatusBadge :status="health?.status || 'unknown'" />
        <span>{{ t('common.labels.db') }}</span><StatusBadge :status="health?.database || 'unknown'" />
        <span>{{ t('jobs.activeJobs') }}</span><strong>{{ health?.active_jobs || 0 }}</strong>
        <span>{{ t('system.cpu') }}</span><strong>N/A</strong>
        <span>{{ t('system.memory') }}</span><strong>N/A</strong>
        <span>{{ t('system.diskIo') }}</span><strong>N/A</strong>
        <span>{{ t('system.workerQueue') }}</span><strong>N/A</strong>
      </div>
    </article>

    <article v-else-if="activeTab === 'job-debug'" class="panel">
      <div class="job-debug-form">
        <label class="job-picker-label" for="job-picker">{{ t('system.jobPickerLabel') }}</label>
        <select id="job-picker" class="job-picker" :value="jobDebugId" @change="onJobPickerChange">
          <option value="">{{ t('system.jobPickerPlaceholder') }}</option>
          <option v-for="job in jobs" :key="job.id" :value="String(job.id)">
            #{{ job.id }} - {{ job.project_id || 'project' }} - {{ job.status || 'unknown' }}
          </option>
        </select>
        <input v-model="jobDebugId" type="number" min="1" :placeholder="t('jobs.jobId')" />
        <button class="btn" @click="loadJobDebug">{{ t('system.loadDebug') }}</button>
      </div>
      <p v-if="jobsListUnavailable" class="muted">{{ t('system.jobPickerUnavailable') }}</p>

      <div v-if="jobDebug" class="health-grid">
        <span>{{ t('jobs.jobId') }}</span><strong>{{ jobDebug.job_id }}</strong>
        <span>{{ t('common.labels.status') }}</span><StatusBadge :status="jobDebug.status" />
        <span>{{ t('dashboard.project') }}</span><strong>{{ jobDebug.project_id }}</strong>
        <span>{{ t('dashboard.progress') }}</span><strong>{{ jobDebug.copied_bytes }} / {{ jobDebug.total_bytes }}</strong>
      </div>

      <DataTable
        :columns="[
          { key: 'id', label: 'ID', align: 'right' },
          { key: 'relative_path', label: t('jobs.path') },
          { key: 'status', label: t('common.labels.status') },
          { key: 'checksum', label: t('jobs.checksum') },
          { key: 'error_message', label: t('system.error') },
        ]"
        :rows="jobDebug?.files || []"
      >
        <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
      </DataTable>
    </article>

    <article v-else class="panel">
      <DataTable :columns="tabColumns" :rows="pagedRows" :empty-text="t('system.empty')">
        <template #cell-size="{ row }">{{ formatBytes(row.size) }}</template>
        <template #cell-modified="{ row }">{{ asLocalDate(row.modified) }}</template>
        <template #cell-download="{ row }">
          <button class="btn" :disabled="downloadingLogName === row.name" @click="downloadLog(row)">
            {{ t('system.download') }}
          </button>
        </template>
      </DataTable>
      <Pagination v-model:page="page" :page-size="pageSize" :total="tabRows.length" />
    </article>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.tabs,
.job-debug-form {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

.tabs,
.job-debug-form {
  flex-wrap: wrap;
}

.job-picker-label {
  align-self: center;
  color: var(--color-text-secondary);
}

.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-sm);
}

.health-grid {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: var(--space-xs) var(--space-sm);
  align-items: center;
}

input,
.job-picker {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
