<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { getJob, getJobFiles, startJob, verifyJob, generateManifest } from '@/api/jobs.js'
import { normalizeErrorMessage } from '@/api/client.js'
import { getFileHashes, compareFiles } from '@/api/files.js'
import { usePolling } from '@/composables/usePolling.js'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'
import { useStatusLabels } from '@/composables/useStatusLabels.js'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const jobId = computed(() => {
  const parsed = Number(route.params.id)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const MAX_JOB_FILE_ROWS = 200

const job = ref(null)
const debug = ref({ files: [], total_files: 0, returned_files: 0 })
const loading = ref(false)
const filesLoading = ref(false)
const acting = ref(false)
const error = ref('')
const lastFileSnapshotKey = ref('')

const selectedFileId = ref(null)
const fileHashes = ref(null)
const compareA = ref(null)
const compareB = ref(null)
const compareResult = ref(null)

const canOperate = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor']))
const canInspectHashes = computed(() => authStore.hasAnyRole(['admin', 'auditor']))

const fileColumns = computed(() => {
  const columns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'relative_path', label: t('jobs.path') },
    { key: 'status', label: t('common.labels.status') },
    { key: 'checksum', label: t('jobs.checksum') },
  ]

  if ((debug.value.files || []).some((row) => String(row?.error_message || '').trim())) {
    columns.push({ key: 'error_message', label: t('common.labels.details') })
  }

  columns.push({ key: 'actions', label: t('common.actions.edit'), align: 'center' })
  return columns
})

const jobFailureReason = computed(() => {
  if (!job.value) return ''
  const status = String(job.value.status || '').toUpperCase()
  if (status !== 'FAILED') return ''

  const summary = String(job.value.error_summary || '').trim()
  if (summary) return summary

  return t('jobs.failureReasonFallback')
})

const fileListNotice = computed(() => {
  const total = Number(debug.value.total_files || 0)
  const shown = Number(debug.value.returned_files || 0)
  return total > shown ? t('jobs.showingFiles', { shown, total }) : ''
})

const progressMetrics = computed(() => {
  const currentJob = job.value || {}
  const status = String(currentJob.status || '').toUpperCase()
  const totalBytes = Number(currentJob.total_bytes || 0)
  const copiedBytes = Number(currentJob.copied_bytes || 0)
  const totalFiles = Number(currentJob.file_count || 0)
  const filesSucceeded = Number(currentJob.files_succeeded || 0)
  const filesFailed = Number(currentJob.files_failed || 0)
  const finishedFiles = Math.min(totalFiles, filesSucceeded + filesFailed)

  const bytePercent = totalBytes > 0
    ? Math.max(0, Math.min(100, Math.round((copiedBytes / totalBytes) * 100)))
    : 0
  const filePercent = totalFiles > 0
    ? Math.max(0, Math.min(100, Math.round((finishedFiles / totalFiles) * 100)))
    : bytePercent

  const percent = (status === 'RUNNING' || status === 'VERIFYING')
    ? Math.min(bytePercent || 100, filePercent || 100)
    : (totalBytes > 0 ? bytePercent : filePercent)

  const displayCopiedBytes = (status === 'RUNNING' || status === 'VERIFYING') && totalBytes > 0 && bytePercent > percent
    ? Math.min(copiedBytes, Math.floor((percent / 100) * totalBytes))
    : copiedBytes

  return {
    total: 100,
    value: percent,
    percent,
    totalBytes,
    copiedBytes: displayCopiedBytes,
    totalFiles,
    finishedFiles,
  }
})

const progressLabel = computed(() => {
  const metrics = progressMetrics.value
  if (metrics.totalFiles > 0) {
    return `${metrics.percent}% • ${metrics.finishedFiles}/${metrics.totalFiles} ${t('jobs.files').toLowerCase()}`
  }
  return `${metrics.percent}%`
})

const progressActive = computed(() => {
  const status = String(job.value?.status || '').toUpperCase()
  return status === 'RUNNING' || status === 'VERIFYING'
})

const completionSummary = computed(() => {
  if (!job.value) return null
  const status = String(job.value.status || '').toUpperCase()
  if (status !== 'COMPLETED' && status !== 'FAILED') return null

  return {
    startedAt: formatTimestamp(job.value.started_at),
    copyThreads: Number(job.value.thread_count || 0),
    filesCopied: Number(job.value.files_succeeded || 0),
    totalFiles: Number(job.value.file_count || 0),
    totalCopied: formatBytes(Number(job.value.copied_bytes || 0)),
    duration: formatDuration(job.value.started_at, job.value.completed_at),
    copyRate: formatCopyRate(Number(job.value.copied_bytes || 0), job.value.started_at, job.value.completed_at),
    completedAt: formatTimestamp(job.value.completed_at),
  }
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

function formatTimestamp(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString()
}

function formatDuration(startedAt, completedAt) {
  if (!startedAt || !completedAt) return '-'
  const started = new Date(startedAt)
  const completed = new Date(completedAt)
  if (Number.isNaN(started.getTime()) || Number.isNaN(completed.getTime())) return '-'

  const totalSeconds = Math.max(0, Math.round((completed.getTime() - started.getTime()) / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function formatCopyRate(bytesValue, startedAt, completedAt) {
  if (typeof bytesValue !== 'number' || bytesValue < 0 || !startedAt || !completedAt) return '-'
  const started = new Date(startedAt)
  const completed = new Date(completedAt)
  if (Number.isNaN(started.getTime()) || Number.isNaN(completed.getTime())) return '-'

  const totalSeconds = Math.max(0, (completed.getTime() - started.getTime()) / 1000)
  if (totalSeconds <= 0 || bytesValue === 0) return '0.0 MB/s'

  const mbPerSecond = bytesValue / (1024 * 1024) / totalSeconds
  return `${mbPerSecond.toFixed(1)} MB/s`
}

async function loadDebug(force = false) {
  if (!jobId.value) return
  if (filesLoading.value && !force) return

  filesLoading.value = true
  try {
    const response = await getJobFiles(jobId.value, { limit: MAX_JOB_FILE_ROWS })
    debug.value = {
      files: Array.isArray(response?.files) ? response.files : [],
      total_files: Number(response?.total_files || 0),
      returned_files: Number(response?.returned_files || 0),
    }
  } catch {
    if (force) {
      debug.value = { files: [], total_files: 0, returned_files: 0 }
    }
  } finally {
    filesLoading.value = false
  }
}

const jobPoller = usePolling(
  async () => {
    const next = await getJob(jobId.value)
    job.value = normalizeProjectRecord(next, ['project_id'])

    const snapshotKey = [
      job.value?.id ?? '',
      String(job.value?.status || '').toUpperCase(),
      job.value?.files_failed ?? 0,
      job.value?.files_succeeded ?? 0,
    ].join(':')

    if (snapshotKey !== lastFileSnapshotKey.value) {
      lastFileSnapshotKey.value = snapshotKey
      void loadDebug()
    }

    return next
  },
  {
    intervalMs: 3000,
    isTerminal: (next) => {
      const status = String(next?.status || '').toUpperCase()
      return status === 'COMPLETED' || status === 'FAILED'
    },
  },
)

function isTerminalStatus(status) {
  const normalized = String(status || '').toUpperCase()
  return normalized === 'COMPLETED' || normalized === 'FAILED'
}

async function refreshAll() {
  if (!jobId.value) {
    error.value = t('common.errors.invalidRequest')
    job.value = null
    debug.value = { files: [], total_files: 0, returned_files: 0 }
    return
  }

  loading.value = true
  error.value = ''
  try {
    await jobPoller.tick()
    void loadDebug(true)
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    loading.value = false
  }
}

function buildJobError(err) {
  const status = err?.response?.status
  const detail = normalizeErrorMessage(err?.response?.data, '')

  if (err instanceof TypeError && String(err.message || '').includes('Invalid job id')) {
    return t('common.errors.invalidRequest')
  }
  if (!status) return t('common.errors.networkError')
  if (status === 403) return detail || t('common.errors.insufficientPermissions')
  if (status === 404) return detail || t('common.errors.notFound')
  if (status === 409) return detail || t('common.errors.requestConflict')
  if (status === 422) return detail || t('common.errors.validationFailed')
  if (status >= 500) return t('common.errors.serverError', { status })
  return detail || t('common.errors.serverErrorGeneric')
}

async function runAction(action) {
  if (!job.value) return
  acting.value = true
  error.value = ''
  try {
    if (action === 'start') {
      job.value = await startJob(job.value.id, { thread_count: job.value.thread_count || 4 })
    } else if (action === 'verify') {
      job.value = await verifyJob(job.value.id)
    } else {
      job.value = await generateManifest(job.value.id)
    }
    await refreshAll()
    if (isTerminalStatus(job.value?.status)) {
      jobPoller.stop()
    } else {
      jobPoller.start()
    }
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
}

async function loadHashes(fileId) {
  if (!canInspectHashes.value) return
  selectedFileId.value = fileId
  fileHashes.value = null
  try {
    fileHashes.value = await getFileHashes(fileId)
  } catch (err) {
    error.value = buildJobError(err)
  }
}

async function runCompare() {
  if (!compareA.value || !compareB.value) return
  compareResult.value = null
  try {
    compareResult.value = await compareFiles({ file_id_a: Number(compareA.value), file_id_b: Number(compareB.value) })
  } catch (err) {
    error.value = buildJobError(err)
  }
}

onMounted(async () => {
  await refreshAll()
  if (!isTerminalStatus(job.value?.status)) {
    jobPoller.start()
  }
})

onUnmounted(() => {
  jobPoller.stop()
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('jobs.detail') }} #{{ jobId }}</h1>
      <button class="btn" @click="refreshAll">{{ t('common.actions.refresh') }}</button>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article v-if="job" class="panel">
      <div class="job-header">
        <StatusBadge :status="job.status" />
        <span>{{ t('dashboard.project') }}: {{ normalizeProjectId(job.project_id) || '-' }}</span>
        <span>{{ t('jobs.evidence') }}: {{ job.evidence_number }}</span>
      </div>

      <div class="hash-grid">
        <span>{{ t('jobs.sourceGroup') }}</span><strong class="mono wrap-anywhere">{{ job.source_path || '-' }}</strong>
        <span>{{ t('jobs.destinationGroup') }}</span><strong class="mono wrap-anywhere">{{ job.target_mount_path || '-' }}</strong>
      </div>

      <ProgressBar
        :value="progressMetrics.value"
        :total="progressMetrics.total"
        :label="progressLabel"
        :full-width="true"
        :active="progressActive"
      />
      <p class="muted">{{ formatBytes(progressMetrics.copiedBytes) }} / {{ formatBytes(progressMetrics.totalBytes) }}</p>

      <div v-if="completionSummary" class="completion-summary" aria-live="polite">
        <strong>{{ t('jobs.completionSummary') }}</strong>
        <div class="hash-grid">
          <span>{{ t('jobs.startedAt') }}</span><strong>{{ completionSummary.startedAt }}</strong>
          <span>{{ t('jobs.copyThreads') }}</span><strong>{{ completionSummary.copyThreads }}</strong>
          <span>{{ t('jobs.filesCopied') }}</span><strong>{{ completionSummary.filesCopied }} of {{ completionSummary.totalFiles }}</strong>
          <span>{{ t('jobs.totalCopied') }}</span><strong>{{ completionSummary.totalCopied }}</strong>
          <span>{{ t('jobs.duration') }}</span><strong>{{ completionSummary.duration }}</strong>
          <span>{{ t('jobs.copyRate') }}</span><strong>{{ completionSummary.copyRate }}</strong>
          <span>{{ t('jobs.completedAt') }}</span><strong>{{ completionSummary.completedAt }}</strong>
        </div>
      </div>

      <div v-if="jobFailureReason" class="failure-summary" role="alert" aria-live="polite">
        <strong>{{ t('jobs.failureReason') }}</strong>
        <div class="hash-grid">
          <span>{{ t('jobs.jobId') }}</span><strong>#{{ job.id }}</strong>
          <span>{{ t('jobs.failedAt') }}</span><strong>{{ formatTimestamp(job.completed_at) }}</strong>
        </div>
        <span>{{ jobFailureReason }}</span>
        <div class="log-entry-block">
          <strong>{{ t('jobs.relatedLogEntry') }}</strong>
          <pre v-if="job.failure_log_entry" class="log-entry-text">{{ job.failure_log_entry }}</pre>
          <p v-else class="muted">{{ t('jobs.relatedLogEntryMissing') }}</p>
        </div>
      </div>

      <div class="actions">
        <button class="btn" :disabled="!canOperate || acting" @click="runAction('start')">{{ t('jobs.start') }}</button>
        <button class="btn" :disabled="!canOperate || acting" @click="runAction('verify')">{{ t('jobs.verify') }}</button>
        <button class="btn" :disabled="!canOperate || acting" @click="runAction('manifest')">{{ t('jobs.manifest') }}</button>
      </div>
    </article>

    <article class="panel">
      <h2>{{ t('jobs.files') }}</h2>
      <p v-if="filesLoading" class="muted">{{ t('common.labels.loading') }}</p>
      <p v-else-if="fileListNotice" class="muted">{{ fileListNotice }}</p>
      <DataTable :columns="fileColumns" :rows="debug.files || []" row-key="id" :empty-text="t('jobs.noFiles')">
        <template #cell-status="{ row }">
          <StatusBadge :status="row.status" />
        </template>
        <template #cell-checksum="{ row }">
          <span class="mono">{{ row.checksum || '-' }}</span>
        </template>
        <template #cell-error_message="{ row }">
          <span class="error-text">{{ row.error_message || '-' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <button class="btn" :disabled="!canInspectHashes" @click="loadHashes(row.id)">{{ t('jobs.hashes') }}</button>
        </template>
      </DataTable>
    </article>

    <div class="split-grid">
      <article class="panel">
        <h2>{{ t('jobs.hashViewer') }}</h2>
        <p class="muted" v-if="!selectedFileId">{{ t('jobs.hashViewerEmpty') }}</p>
        <div v-else-if="fileHashes" class="hash-grid">
          <span>{{ t('common.labels.id') }}</span><strong>{{ fileHashes.file_id }}</strong>
          <span>{{ t('jobs.md5') }}</span><strong class="mono">{{ fileHashes.md5 || '-' }}</strong>
          <span>{{ t('jobs.sha256') }}</span><strong class="mono">{{ fileHashes.sha256 || '-' }}</strong>
          <span>{{ t('common.labels.size') }}</span><strong>{{ fileHashes.size_bytes || '-' }}</strong>
        </div>
      </article>

      <article class="panel">
        <h2>{{ t('jobs.compareTitle') }}</h2>
        <div class="compare-form">
          <label for="compare-file-a">{{ t('jobs.fileA') }}</label>
          <select id="compare-file-a" v-model="compareA">
            <option :value="null">-</option>
            <option v-for="file in debug.files || []" :key="`a-${file.id}`" :value="file.id">
              #{{ file.id }} {{ file.relative_path }}
            </option>
          </select>
          <label for="compare-file-b">{{ t('jobs.fileB') }}</label>
          <select id="compare-file-b" v-model="compareB">
            <option :value="null">-</option>
            <option v-for="file in debug.files || []" :key="`b-${file.id}`" :value="file.id">
              #{{ file.id }} {{ file.relative_path }}
            </option>
          </select>
          <button class="btn" :disabled="!compareA || !compareB" @click="runCompare">
            {{ t('jobs.compare') }}
          </button>
        </div>

        <div v-if="compareResult" class="hash-grid">
          <span>{{ t('jobs.compareMatch') }}</span><StatusBadge :status="compareResult.match" />
          <span>{{ t('jobs.hashMatch') }}</span><StatusBadge :status="compareResult.hash_match" />
          <span>{{ t('jobs.sizeMatch') }}</span><StatusBadge :status="compareResult.size_match" />
          <span>{{ t('jobs.pathMatch') }}</span><StatusBadge :status="compareResult.path_match" />
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.job-header,
.actions,
.split-grid {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
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

.job-header {
  flex-wrap: wrap;
  align-items: center;
}

select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.split-grid {
  display: grid;
  gap: var(--space-md);
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}

.compare-form,
.hash-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: var(--space-xs) var(--space-sm);
  align-items: center;
}

.mono {
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
}

.wrap-anywhere {
  overflow-wrap: anywhere;
}

.completion-summary {
  display: grid;
  gap: var(--space-xs);
  color: var(--color-text-primary);
  background: color-mix(in srgb, var(--color-success, #16a34a) 10%, var(--color-bg-secondary));
  border: 1px solid color-mix(in srgb, var(--color-success, #16a34a) 35%, var(--color-border));
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.failure-summary {
  display: grid;
  gap: var(--space-xs);
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.error-text {
  color: var(--color-alert-danger-text);
}

.log-entry-block {
  display: grid;
  gap: var(--space-xs);
}

.log-entry-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
  background: rgba(0, 0, 0, 0.08);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
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
