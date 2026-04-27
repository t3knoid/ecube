<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  getSystemHealth,
  getUsbTopology,
  getBlockDevices,
  getSystemMounts,
  getJobDebug,
  reconcileManagedMounts,
} from '@/api/introspection.js'
import { downloadLogFile, getLogFiles, getLogLines } from '@/api/admin.js'
import { listJobs } from '@/api/jobs.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useAuthStore } from '@/stores/auth.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const canViewLogs = computed(() => authStore.hasRole('admin'))
const canRunManagedMountReconciliation = computed(() => authStore.hasRole('admin') || authStore.hasRole('manager'))
const tabs = computed(() => {
  const items = ['health', 'usb', 'block', 'mounts']
  if (canViewLogs.value) {
    items.push('logs')
  }
  items.push('job-debug')
  return items
})
const activeTab = ref('health')
const loading = ref(false)
const error = ref('')
const reconcilingManagedMounts = ref(false)

const health = ref(null)
const usbDevices = ref([])
const blockDevices = ref([])
const mounts = ref([])
const logs = ref([])
const downloadingLogName = ref('')
const logViewer = ref({ source: '', search: '', limit: 200, offset: 0, reverse: true })
const logView = ref(null)
const jobDebug = ref(null)
const jobDebugId = ref('')
const jobs = ref([])
const jobsListUnavailable = ref(false)
const loadingLogPage = ref(false)
const logViewerElement = ref(null)
const suppressedLogViewerScrollTop = ref(null)

const LOG_SCROLL_THRESHOLD = 24

const page = ref(1)
const pageSize = ref(10)
const isMobileViewport = ref(false)
let mobileViewportQuery = null

const tabColumns = computed(() => {
  if (activeTab.value === 'usb') {
    if (isMobileViewport.value) {
      return [
        { key: 'device', label: t('system.device') },
        { key: 'product', label: t('system.product') },
        { key: 'details', label: '', align: 'center' },
      ]
    }

    return [
      { key: 'device', label: t('system.device') },
      { key: 'serial', label: t('system.serialNumber') },
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
    if (isMobileViewport.value) {
      return [
        { key: 'device', label: t('system.device') },
        { key: 'mount_point', label: t('system.mountPoint') },
        { key: 'details', label: '', align: 'center' },
      ]
    }

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


// Hide only if Serial Number, Manufacturer, Product, Vendor ID, and Product ID are all empty
function isUsbDeviceEmpty(device) {
  if (!device) return true
  const fields = ['serial', 'manufacturer', 'product', 'idVendor', 'idProduct']
  return fields.every((key) => {
    const v = device[key]
    return v === undefined || v === null || String(v).trim() === ''
  })
}

const filteredSortedUsbDevices = computed(() => {
  return usbDevices.value
    .filter((dev) => !isUsbDeviceEmpty(dev))
    .slice() // shallow copy for sort
    .sort((a, b) => {
      const av = a.device || ''
      const bv = b.device || ''
      return av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' })
    })
})

const tabRows = computed(() => {
  if (activeTab.value === 'usb') return filteredSortedUsbDevices.value
  if (activeTab.value === 'block') return blockDevices.value
  if (activeTab.value === 'mounts') return mounts.value
  return []
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return tabRows.value.slice(start, start + pageSize.value)
})

const logSourceOptions = computed(() => {
  const options = []
  for (const row of logs.value || []) {
    const name = String(row?.name || '').trim()
    if (!name || options.some((option) => option.value === name)) continue
    options.push({ value: name, label: name })
  }
  return options
})

const selectedLogDownloadName = computed(() => {
  const source = String(logViewer.value.source || '').trim()
  if (!source) return ''
  return logSourceOptions.value.some((option) => option.value === source) ? source : ''
})

const canPageOlderLogLines = computed(() => {
  return Boolean(logViewer.value.source && logView.value?.has_more && !loading.value)
})

const canPageNewerLogLines = computed(() => {
  return Boolean(logViewer.value.source && logViewer.value.offset > 0 && !loading.value)
})

const canLoadOlderLogLines = computed(() => {
  return Boolean(canPageOlderLogLines.value && !loadingLogPage.value)
})

const canLoadNewerLogLines = computed(() => {
  return Boolean(canPageNewerLogLines.value && !loadingLogPage.value)
})

function formatBytes(value) {
  if (typeof value !== 'number' || value < 0) return '-'
  if (value === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
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

function displayLogSourcePath(value) {
  if (!value) return '-'
  const normalized = String(value).trim().replace(/\\/g, '/')
  if (!normalized) return '-'
  const parts = normalized.split('/').filter(Boolean)
  return parts.length ? parts[parts.length - 1] : normalized
}

const logViewerText = computed(() => {
  const selectedPath = displayLogSourcePath(logView.value?.source?.path)
  const lines = Array.isArray(logView.value?.lines) ? logView.value.lines : []

  return lines
    .map((line) => {
      const content = String(line?.content || '')
      const lineSource = displayLogSourcePath(line?.source_path)
      if (!content) return ''
      if (lineSource !== '-' && lineSource !== selectedPath) {
        return `[${lineSource}] ${content}`
      }
      return content
    })
    .join('\n')
})

const cpuDisplay = computed(() => {
  const p = health.value?.cpu_percent
  return p != null ? `${p.toFixed(1)}%` : t('common.labels.notAvailable')
})

const memoryDisplay = computed(() => {
  const h = health.value
  if (h?.memory_percent == null) return t('common.labels.notAvailable')
  if (h.memory_used_bytes != null && h.memory_total_bytes != null) {
    return `${h.memory_percent.toFixed(1)}% (${formatBytes(h.memory_used_bytes)} / ${formatBytes(h.memory_total_bytes)})`
  }
  return `${h.memory_percent.toFixed(1)}%`
})

const diskIoDisplay = computed(() => {
  const h = health.value
  if (h?.disk_read_bytes == null || h?.disk_write_bytes == null) return t('common.labels.notAvailable')
  return `${formatBytes(h.disk_read_bytes)} R / ${formatBytes(h.disk_write_bytes)} W`
})

const workerQueueDisplay = computed(() => {
  const q = health.value?.worker_queue_size
  if (q == null) return t('common.labels.notAvailable')
  return q
})

function formatProjectId(value) {
  return normalizeProjectId(value) || t('dashboard.project')
}

function closeUsbDetailsMenu(event) {
  const menu = event?.currentTarget instanceof HTMLElement ? event.currentTarget.closest('details') : null
  if (menu instanceof HTMLDetailsElement) {
    menu.removeAttribute('open')
  }
}

function syncViewportState() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return

  if (!mobileViewportQuery) {
    mobileViewportQuery = window.matchMedia('(max-width: 768px)')
  }

  isMobileViewport.value = mobileViewportQuery.matches
}

function extractApiMessage(err) {
  const data = err?.response?.data || {}
  return String(data.message || data.detail || '').trim()
}

function resolveLogViewError(err, fallbackMessage) {
  const status = err?.response?.status
  if (status === 403) {
    return t('auth.insufficientPermissions')
  }
  if (status === 404) {
    return extractApiMessage(err) || fallbackMessage
  }
  if (status === 503) {
    return t('system.logsUnavailable')
  }
  return extractApiMessage(err) || t('common.errors.requestConflict')
}

async function fetchLogLines() {
  if (!logViewer.value.source) {
    logView.value = null
    return
  }

  const response = await getLogLines({
    source: logViewer.value.source,
    search: logViewer.value.search || undefined,
    limit: logViewer.value.limit,
    offset: logViewer.value.offset,
    reverse: logViewer.value.reverse,
  })

  logView.value = response
}

async function setLogViewerScrollPosition(position = 'top') {
  await nextTick()

  const element = logViewerElement.value
  if (!element) return

  const maxScrollTop = Math.max(element.scrollHeight - element.clientHeight, 0)
  let nextScrollTop = 0

  if (position === 'bottom') {
    nextScrollTop = Math.max(maxScrollTop - LOG_SCROLL_THRESHOLD, 0)
  } else if (maxScrollTop > 0) {
    nextScrollTop = Math.min(LOG_SCROLL_THRESHOLD, maxScrollTop)
  }

  suppressedLogViewerScrollTop.value = nextScrollTop
  element.scrollTop = nextScrollTop
}

async function runManagedMountReconciliation() {
  if (!canRunManagedMountReconciliation.value || reconcilingManagedMounts.value) {
    return
  }

  reconcilingManagedMounts.value = true
  error.value = ''
  try {
    const result = await reconcileManagedMounts()
    // Navigate to results page with the reconciliation result
    router.push({
      name: 'reconciliation-results',
      state: { reconciliationResult: result },
    })
  } catch (err) {
    error.value = extractApiMessage(err) || t('common.errors.requestConflict')
  } finally {
    reconcilingManagedMounts.value = false
  }
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
      let filesError = null
      let linesError = null

      try {
        const filesResponse = await getLogFiles()
        logs.value = filesResponse.log_files || []
      } catch (err) {
        logs.value = []
        filesError = err
      }

      const availableSourceNames = (logs.value || [])
        .map((row) => String(row?.name || '').trim())
        .filter(Boolean)

      if (!availableSourceNames.includes(logViewer.value.source)) {
        logViewer.value.source = availableSourceNames[0] || ''
        logViewer.value.offset = 0
      }

      if (logViewer.value.source) {
        try {
          await fetchLogLines()
          if (logViewer.value.offset === 0) {
            await setLogViewerScrollPosition('top')
          }
        } catch (err) {
          logView.value = null
          linesError = err
        }
      } else {
        logView.value = null
      }

      const err = linesError || filesError
      if (err) {
        if (err === filesError && err?.response?.status === 404) {
          error.value = t('system.logsNotConfigured')
        } else {
          error.value = resolveLogViewError(err, t('system.logsUnavailable'))
        }
      }
    }
  } catch (err) {
    const status = err?.response?.status
    if (activeTab.value === 'logs' && status === 403) {
      error.value = t('auth.insufficientPermissions')
    } else if (activeTab.value === 'logs' && status === 404) {
      error.value = t('system.logsNotConfigured')
    } else if (activeTab.value === 'logs' && status === 503) {
      error.value = t('system.logsUnavailable')
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
    jobDebug.value = normalizeProjectRecord(await getJobDebug(Number(jobDebugId.value)), ['project_id'])
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
  loading.value = true
  error.value = ''
  jobsListUnavailable.value = false
  try {
    const response = await listJobs({ limit: 200 })
    jobs.value = Array.isArray(response)
      ? response.map((item) => normalizeProjectRecord(item, ['project_id']))
      : []
  } catch {
    jobs.value = []
    jobsListUnavailable.value = true
  } finally {
    loading.value = false
  }
}

function onJobPickerChange(event) {
  const selected = String(event?.target?.value || '')
  jobDebugId.value = selected
  if (selected) {
    loadJobDebug()
  }
}

async function downloadLog() {
  const name = selectedLogDownloadName.value
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

async function refreshLogViewer() {
  if (activeTab.value !== 'logs') return
  logViewer.value.offset = 0
  await loadTabData()
}

async function loadOlderLogLines() {
  if (!canLoadOlderLogLines.value) return

  loadingLogPage.value = true
  error.value = ''
  const previousOffset = logViewer.value.offset
  try {
    logViewer.value.offset += Number(logView.value?.returned || logViewer.value.limit)
    await fetchLogLines()
    await setLogViewerScrollPosition('top')
  } catch (err) {
    logViewer.value.offset = previousOffset
    logView.value = null
    error.value = resolveLogViewError(err, t('system.logsUnavailable'))
  } finally {
    loadingLogPage.value = false
  }
}

async function loadNewerLogLines() {
  if (!canLoadNewerLogLines.value) return

  loadingLogPage.value = true
  error.value = ''
  const previousOffset = logViewer.value.offset
  try {
    logViewer.value.offset = Math.max(logViewer.value.offset - Number(logView.value?.returned || logViewer.value.limit), 0)
    await fetchLogLines()
    await setLogViewerScrollPosition('bottom')
  } catch (err) {
    logViewer.value.offset = previousOffset
    logView.value = null
    error.value = resolveLogViewError(err, t('system.logsUnavailable'))
  } finally {
    loadingLogPage.value = false
  }
}

async function onLogViewerScroll(event) {
  const element = event?.target
  if (!element || loading.value || loadingLogPage.value) return

  if (suppressedLogViewerScrollTop.value != null) {
    const expectedScrollTop = suppressedLogViewerScrollTop.value
    suppressedLogViewerScrollTop.value = null
    if (Math.abs(element.scrollTop - expectedScrollTop) <= 1) {
      return
    }
  }

  if (element.scrollHeight <= element.clientHeight + LOG_SCROLL_THRESHOLD) return

  const nearTop = element.scrollTop <= LOG_SCROLL_THRESHOLD
  const nearBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - LOG_SCROLL_THRESHOLD

  if (nearTop && canLoadNewerLogLines.value) {
    await loadNewerLogLines()
    return
  }

  if (nearBottom && canLoadOlderLogLines.value) {
    await loadOlderLogLines()
  }
}

watch(activeTab, async () => {
  page.value = 1
  error.value = ''
  if (activeTab.value === 'job-debug') {
    await loadJobOptions()
  } else {
    await loadTabData()
  }
})

watch(canViewLogs, (isAdmin) => {
  if (!isAdmin && activeTab.value === 'logs') {
    activeTab.value = 'health'
  }
})

onMounted(() => {
  syncViewportState()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    if (!mobileViewportQuery) {
      mobileViewportQuery = window.matchMedia('(max-width: 768px)')
    }
    mobileViewportQuery.addEventListener('change', syncViewportState)
  }

  void loadTabData()
})

onBeforeUnmount(() => {
  mobileViewportQuery?.removeEventListener('change', syncViewportState)
})
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
      <template v-for="tab in tabs" :key="tab">
        <button
          v-if="tab !== 'logs'"
          class="btn"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          {{ t(`system.tabs.${tab}`) }}
        </button>
        <button
          v-if="tab === 'mounts' && canRunManagedMountReconciliation"
          class="btn"
          :disabled="loading || reconcilingManagedMounts"
          @click="runManagedMountReconciliation"
        >
          {{ reconcilingManagedMounts ? t('common.labels.loading') : t('system.reconcileManagedMounts') }}
        </button>
        <button
          v-if="tab === 'logs'"
          class="btn"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          {{ t(`system.tabs.${tab}`) }}
        </button>
      </template>
    </div>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article v-if="activeTab === 'health'" class="panel">
      <div class="health-grid">
        <span>{{ t('common.labels.status') }}</span><StatusBadge :status="health?.status || 'unknown'" />
        <span>{{ t('common.labels.db') }}</span><StatusBadge :status="health?.database || 'unknown'" />
        <span>{{ t('jobs.activeJobs') }}</span><strong>{{ health?.active_jobs || 0 }}</strong>
        <span>{{ t('system.cpu') }}</span><strong>{{ cpuDisplay }}</strong>
        <span>{{ t('system.memory') }}</span><strong>{{ memoryDisplay }}</strong>
        <span>{{ t('system.diskIo') }}</span><strong>{{ diskIoDisplay }}</strong>
        <span>{{ t('system.workerQueue') }}</span><strong>{{ workerQueueDisplay }}</strong>
      </div>
    </article>

    <article v-else-if="activeTab === 'job-debug'" class="panel">
      <div class="job-debug-form">
        <label class="job-picker-label" for="job-picker">{{ t('system.jobPickerLabel') }}</label>
        <select id="job-picker" class="job-picker" :value="jobDebugId" @change="onJobPickerChange">
          <option value="">{{ t('system.jobPickerPlaceholder') }}</option>
          <option v-for="job in jobs" :key="job.id" :value="String(job.id)">
            #{{ job.id }} - {{ formatProjectId(job.project_id) }} - {{ job.status || t('common.labels.unknown') }}
          </option>
        </select>
        <input v-model="jobDebugId" type="number" min="1" :placeholder="t('jobs.jobId')" />
        <button class="btn" @click="loadJobDebug">{{ t('system.loadDebug') }}</button>
      </div>
      <p v-if="jobsListUnavailable" class="muted">{{ t('system.jobPickerUnavailable') }}</p>

      <div v-if="jobDebug" class="health-grid">
        <span>{{ t('jobs.jobId') }}</span><strong>{{ jobDebug.job_id }}</strong>
        <span>{{ t('common.labels.status') }}</span><StatusBadge :status="jobDebug.status" />
        <span>{{ t('dashboard.project') }}</span><strong>{{ formatProjectId(jobDebug.project_id) }}</strong>
        <span>{{ t('dashboard.progress') }}</span><strong>{{ jobDebug.copied_bytes || 0 }} / {{ jobDebug.total_bytes || 0 }}</strong>
      </div>

      <DataTable
        :columns="[
          { key: 'id', label: t('common.labels.id'), align: 'right' },
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

    <article v-else-if="activeTab === 'logs'" class="panel">
      <div class="log-controls">
        <label for="log-source">{{ t('system.logSource') }}</label>
        <select id="log-source" v-model="logViewer.source" class="job-picker" @change="refreshLogViewer">
          <option v-for="option in logSourceOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
        <label for="log-search">{{ t('system.logSearch') }}</label>
        <input
          id="log-search"
          v-model="logViewer.search"
          type="text"
          :placeholder="t('system.logSearchPlaceholder')"
          @keyup.enter="refreshLogViewer"
        />
        <button class="btn" @click="refreshLogViewer">{{ t('common.actions.refresh') }}</button>
        <button class="btn" :disabled="!selectedLogDownloadName || downloadingLogName === selectedLogDownloadName" @click="downloadLog">
          {{ t('system.download') }}
        </button>
      </div>

      <div class="log-meta">
        <span>{{ t('system.logSourcePath') }}: <strong>{{ displayLogSourcePath(logView?.source?.path) }}</strong></span>
        <span>{{ t('system.logFetchedAt') }}: <strong>{{ asLocalDate(logView?.fetched_at) }}</strong></span>
        <span>{{ t('system.logFileModifiedAt') }}: <strong>{{ asLocalDate(logView?.file_modified_at) }}</strong></span>
      </div>

      <div class="log-viewer-actions">
        <button class="btn" :disabled="!canPageNewerLogLines" @click="loadNewerLogLines">
          {{ t('system.logLoadNewer') }}
        </button>
        <button class="btn" :disabled="!canPageOlderLogLines" @click="loadOlderLogLines">
          {{ t('system.logLoadOlder') }}
        </button>
      </div>

      <div ref="logViewerElement" class="log-viewer" tabindex="0" @scroll="onLogViewerScroll">
        <pre class="log-viewer-content">{{ logViewerText || t('system.logViewerEmpty') }}</pre>
      </div>
    </article>

    <article v-else class="panel">
      <DataTable :class="{ 'usb-topology-table': activeTab === 'usb' && isMobileViewport, 'system-mounts-table': activeTab === 'mounts' && isMobileViewport }" :columns="tabColumns" :rows="pagedRows" :empty-text="t('system.empty')">
        <template #cell-product="{ row }">
          <span
            v-if="activeTab === 'usb' && isMobileViewport"
            class="usb-product-cell"
            :title="row.product || '-'"
          >
            {{ row.product || '-' }}
          </span>
          <span v-else>{{ row.product || '-' }}</span>
        </template>
        <template #cell-mount_point="{ row }">
          <span
            v-if="activeTab === 'mounts' && isMobileViewport"
            class="mount-point-cell"
            :title="row.mount_point || '-'"
          >
            {{ row.mount_point || '-' }}
          </span>
          <span v-else>{{ row.mount_point || '-' }}</span>
        </template>
        <template #cell-details="{ row }">
          <details v-if="(activeTab === 'usb' || activeTab === 'mounts') && isMobileViewport" class="usb-topology-menu">
            <summary class="usb-topology-menu-toggle" :aria-label="`${row.device || t('system.device')} ${t('drives.details')}`">
              <span class="usb-topology-menu-toggle-dots" aria-hidden="true">
                <span class="usb-topology-menu-toggle-dot" />
                <span class="usb-topology-menu-toggle-dot" />
                <span class="usb-topology-menu-toggle-dot" />
              </span>
            </summary>
            <div class="usb-topology-menu-popover">
              <div v-if="activeTab === 'usb'" class="usb-topology-menu-grid">
                <span>{{ t('system.manufacturer') }}</span><strong>{{ row.manufacturer || '-' }}</strong>
                <span>{{ t('system.serialNumber') }}</span><strong>{{ row.serial || '-' }}</strong>
                <span>{{ t('system.vendorId') }}</span><strong>{{ row.idVendor || '-' }}</strong>
                <span>{{ t('system.productId') }}</span><strong>{{ row.idProduct || '-' }}</strong>
              </div>
              <div v-else class="usb-topology-menu-grid">
                <span>{{ t('system.fsType') }}</span><strong>{{ row.fs_type || '-' }}</strong>
                <span>{{ t('system.options') }}</span><strong>{{ row.options || '-' }}</strong>
              </div>
              <button class="btn usb-topology-menu-close" @click="closeUsbDetailsMenu($event)">{{ t('common.actions.close') }}</button>
            </div>
          </details>
        </template>
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
.job-debug-form,
.header-actions {
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

.log-controls {
  display: flex;
  gap: var(--space-sm);
  align-items: center;
  flex-wrap: wrap;
}

.log-meta {
  display: grid;
  gap: var(--space-xs);
  color: var(--color-text-secondary);
}

.log-viewer-actions {
  display: flex;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.log-viewer {
  min-height: 220px;
  max-height: 420px;
  overflow-x: auto;
  overflow-y: scroll;
  scrollbar-gutter: stable;
  scrollbar-width: auto;
  scrollbar-color: var(--color-border) var(--color-bg-secondary);
  padding: var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
}

.log-viewer-content {
  margin: 0;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 0.85rem;
  line-height: 1.4;
  min-width: 100%;
}

.log-viewer::-webkit-scrollbar {
  width: 12px;
  height: 12px;
}

.log-viewer::-webkit-scrollbar-track {
  background: var(--color-bg-secondary);
  border-left: 1px solid var(--color-border);
}

.log-viewer::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 999px;
  border: 2px solid var(--color-bg-secondary);
}

.log-viewer::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-secondary);
}

.usb-topology-menu {
  position: relative;
  display: inline-block;
}

.usb-topology-menu-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.75rem;
  height: 1.75rem;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  cursor: pointer;
}

.usb-topology-menu-toggle::-webkit-details-marker {
  display: none;
}

.usb-topology-menu-toggle-dots {
  display: inline-flex;
  gap: 0.15rem;
}

.usb-topology-menu-toggle-dot {
  width: 0.25rem;
  height: 0.25rem;
  border-radius: 9999px;
  background: currentColor;
}

.usb-topology-menu-popover {
  position: absolute;
  top: calc(100% + var(--space-2xs));
  right: 0;
  z-index: 2;
  min-width: 14rem;
  display: grid;
  gap: var(--space-2xs);
  padding: var(--space-2xs);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.12));
}

.usb-topology-menu-grid {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--space-xs) var(--space-sm);
  align-items: start;
}

.usb-topology-menu-grid strong {
  overflow-wrap: anywhere;
}

.usb-topology-menu-close {
  justify-self: end;
}

.usb-product-cell {
  display: inline-block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: top;
}

.mount-point-cell {
  display: inline-block;
  max-width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: top;
}

@media (max-width: 768px) {
  .usb-topology-table :deep(.data-table) {
    table-layout: fixed;
  }

  .usb-topology-table :deep(.data-table th),
  .usb-topology-table :deep(.data-table td) {
    padding: var(--space-xs) var(--space-sm);
  }

  .usb-topology-table :deep(.data-table th:nth-child(1)),
  .usb-topology-table :deep(.data-table td:nth-child(1)) {
    width: 6.5rem;
  }

  .usb-topology-table :deep(.data-table th:nth-child(2)),
  .usb-topology-table :deep(.data-table td:nth-child(2)) {
    width: auto;
  }

  .usb-topology-table :deep(.data-table th:nth-child(3)),
  .usb-topology-table :deep(.data-table td:nth-child(3)) {
    width: 2.5rem;
  }

  .system-mounts-table :deep(.data-table) {
    table-layout: fixed;
  }

  .system-mounts-table :deep(.data-table th),
  .system-mounts-table :deep(.data-table td) {
    padding: var(--space-xs) var(--space-sm);
  }

  .system-mounts-table :deep(.data-table th:nth-child(1)),
  .system-mounts-table :deep(.data-table td:nth-child(1)) {
    width: 6rem;
  }

  .system-mounts-table :deep(.data-table th:nth-child(2)),
  .system-mounts-table :deep(.data-table td:nth-child(2)) {
    width: auto;
  }

  .system-mounts-table :deep(.data-table th:nth-child(3)),
  .system-mounts-table :deep(.data-table td:nth-child(3)) {
    width: 2.5rem;
  }
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
