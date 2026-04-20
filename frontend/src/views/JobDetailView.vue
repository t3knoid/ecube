<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { getJob, getJobFiles, startJob, pauseJob, verifyJob, generateManifest, updateJob, completeJob, deleteJob } from '@/api/jobs.js'
import { normalizeErrorMessage } from '@/api/client.js'
import { getFileHashes, compareFiles } from '@/api/files.js'
import { getDrives } from '@/api/drives.js'
import { getMounts } from '@/api/mounts.js'
import { usePolling } from '@/composables/usePolling.js'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const route = useRoute()
const router = useRouter()
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
const infoMessage = ref('')
const lastFileSnapshotKey = ref('')

const selectedFileId = ref(null)
const fileHashes = ref(null)
const compareA = ref(null)
const compareB = ref(null)
const compareResult = ref(null)
const supportingDrives = ref([])
const supportingMounts = ref([])
const showEditDialog = ref(false)
const showDeleteDialog = ref(false)
const showPausePendingDialog = ref(false)

const editForm = ref({
  project_id: '',
  evidence_number: '',
  mount_id: null,
  source_path: '/',
  drive_id: null,
  thread_count: 4,
})

const canOperate = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor']))
const canInspectHashes = computed(() => authStore.hasAnyRole(['admin', 'auditor']))
const currentStatus = computed(() => String(job.value?.status || '').toUpperCase())
const canEdit = computed(() => canOperate.value && ['PENDING', 'PAUSED', 'FAILED'].includes(currentStatus.value))
const canComplete = computed(() => canOperate.value && ['PENDING', 'PAUSED', 'FAILED'].includes(currentStatus.value))
const canDelete = computed(() => canOperate.value && currentStatus.value === 'PENDING')

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

  const percent = (status === 'RUNNING' || status === 'PAUSING' || status === 'VERIFYING')
    ? Math.min(bytePercent || 100, filePercent || 100)
    : (totalBytes > 0 ? bytePercent : filePercent)

  const displayCopiedBytes = (status === 'RUNNING' || status === 'PAUSING' || status === 'VERIFYING') && totalBytes > 0 && bytePercent > percent
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
  return status === 'RUNNING' || status === 'PAUSING' || status === 'VERIFYING'
})

const canStart = computed(() => {
  const status = String(job.value?.status || '').toUpperCase()
  return canOperate.value && ['PENDING', 'FAILED', 'PAUSED'].includes(status)
})

const canPause = computed(() => canOperate.value && currentStatus.value === 'RUNNING')
const isJobFullyComplete = computed(() => {
  const status = currentStatus.value
  if (status !== 'COMPLETED') return false
  return progressMetrics.value.percent >= 100
})
const canVerify = computed(() => canOperate.value && isJobFullyComplete.value)
const canGenerateManifest = computed(() => canOperate.value && isJobFullyComplete.value)

const editEligibleMounts = computed(() => {
  const projectId = normalizeProjectId(editForm.value.project_id)
  if (!projectId) return []
  return supportingMounts.value.filter(
    (mount) => String(mount?.status || '').toUpperCase() === 'MOUNTED'
      && normalizeProjectId(mount?.project_id) === projectId,
  )
})

const editEligibleDrives = computed(() => {
  const projectId = normalizeProjectId(editForm.value.project_id)
  if (!projectId) return []
  return supportingDrives.value.filter((drive) => {
    const state = String(drive?.current_state || '').toUpperCase()
    const boundProject = normalizeProjectId(drive?.current_project_id)
    return ['AVAILABLE', 'IN_USE'].includes(state)
      && !!drive?.mount_path
      && (!boundProject || boundProject === projectId)
  })
})

function calculateDurationSeconds(currentJob) {
  if (!currentJob) return null

  const status = String(currentJob.status || '').toUpperCase()
  const storedSeconds = Number(currentJob.active_duration_seconds || 0)
  if (['RUNNING', 'PAUSING', 'VERIFYING'].includes(status) && currentJob.started_at) {
    const started = new Date(currentJob.started_at)
    if (!Number.isNaN(started.getTime())) {
      const liveSeconds = Math.max(0, Math.round((Date.now() - started.getTime()) / 1000))
      return storedSeconds + liveSeconds
    }
  }

  if (storedSeconds > 0) return storedSeconds

  if (currentJob.started_at && currentJob.completed_at) {
    const started = new Date(currentJob.started_at)
    const completed = new Date(currentJob.completed_at)
    if (!Number.isNaN(started.getTime()) && !Number.isNaN(completed.getTime())) {
      return Math.max(0, Math.round((completed.getTime() - started.getTime()) / 1000))
    }
  }

  return null
}

const completionSummary = computed(() => {
  if (!job.value) return null
  const status = String(job.value.status || '').toUpperCase()
  if (status !== 'COMPLETED' && status !== 'FAILED' && status !== 'PAUSED') return null

  const durationSeconds = calculateDurationSeconds(job.value)

  return {
    startedAt: formatTimestamp(job.value.started_at),
    copyThreads: Number(job.value.thread_count || 0),
    filesCopied: Number(job.value.files_succeeded || 0),
    totalFiles: Number(job.value.file_count || 0),
    totalCopied: formatBytes(Number(job.value.copied_bytes || 0)),
    duration: formatDuration(durationSeconds),
    copyRate: formatCopyRate(Number(job.value.copied_bytes || 0), durationSeconds),
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

function formatDuration(totalSeconds) {
  if (typeof totalSeconds !== 'number' || totalSeconds < 0) return '-'

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function formatCopyRate(bytesValue, totalSeconds) {
  if (typeof bytesValue !== 'number' || bytesValue < 0 || typeof totalSeconds !== 'number') return '-'
  if (totalSeconds <= 0 || bytesValue === 0) return '0.0 MB/s'

  const mbPerSecond = bytesValue / (1024 * 1024) / totalSeconds
  return `${mbPerSecond.toFixed(1)} MB/s`
}

function formatDriveLabel(drive) {
  return `#${drive.id} - ${drive.device_identifier || '-'}`
}

function formatMountLabel(mount) {
  return mount?.remote_path || t('jobs.chooseMount')
}

function buildManifestPath(currentJob) {
  const targetPath = String(currentJob?.target_mount_path || '').trim().replace(/\/+$/, '')
  if (!targetPath) return ''
  return `${targetPath}/manifest.json`
}

async function loadSupportingData() {
  const [driveResult, mountResult] = await Promise.allSettled([getDrives(), getMounts()])
  supportingDrives.value = driveResult.status === 'fulfilled'
    ? (driveResult.value || []).map((item) => normalizeProjectRecord(item, ['current_project_id']))
    : []
  supportingMounts.value = mountResult.status === 'fulfilled'
    ? (mountResult.value || []).map((item) => normalizeProjectRecord(item, ['project_id']))
    : []
}

function inferMountForJob(currentJob) {
  const projectId = normalizeProjectId(currentJob?.project_id)
  const sourcePath = String(currentJob?.source_path || '')
  const match = supportingMounts.value
    .filter((mount) => String(mount?.status || '').toUpperCase() === 'MOUNTED' && normalizeProjectId(mount?.project_id) === projectId)
    .sort((left, right) => String(right?.local_mount_point || '').length - String(left?.local_mount_point || '').length)
    .find((mount) => {
      const root = String(mount?.local_mount_point || '')
      return root && (sourcePath === root || sourcePath.startsWith(`${root}/`))
    })
  return match || null
}

function buildEditSourcePath(currentJob, mount) {
  const sourcePath = String(currentJob?.source_path || '').trim()
  const root = String(mount?.local_mount_point || '').trim()
  if (!sourcePath) return '/'
  if (!root) return sourcePath
  if (sourcePath === root) return '/'
  if (sourcePath.startsWith(`${root}/`)) {
    return sourcePath.slice(root.length) || '/'
  }
  return sourcePath
}

async function openEditDialog() {
  if (!job.value || !canEdit.value) return
  error.value = ''
  await loadSupportingData()
  const inferredMount = inferMountForJob(job.value)
  editForm.value = {
    project_id: normalizeProjectId(job.value.project_id) || '',
    evidence_number: String(job.value.evidence_number || ''),
    mount_id: inferredMount?.id ?? null,
    source_path: buildEditSourcePath(job.value, inferredMount),
    drive_id: job.value.drive?.id ?? null,
    thread_count: Number(job.value.thread_count || 4),
  }
  showEditDialog.value = true
}

function editFormReady() {
  return !!normalizeProjectId(editForm.value.project_id)
    && !!String(editForm.value.evidence_number || '').trim()
    && !!String(editForm.value.source_path || '').trim()
    && editForm.value.mount_id != null
    && editForm.value.drive_id != null
}

async function submitEditJob() {
  if (!job.value || !editFormReady()) return
  acting.value = true
  error.value = ''
  try {
    const updated = await updateJob(job.value.id, {
      project_id: normalizeProjectId(editForm.value.project_id),
      evidence_number: String(editForm.value.evidence_number || '').trim(),
      mount_id: Number(editForm.value.mount_id),
      source_path: String(editForm.value.source_path || '').trim(),
      drive_id: Number(editForm.value.drive_id),
      thread_count: Number(editForm.value.thread_count || 4),
      max_file_retries: Number(job.value.max_file_retries || 3),
      retry_delay_seconds: Number(job.value.retry_delay_seconds || 1),
      callback_url: job.value.callback_url || null,
    })
    job.value = normalizeProjectRecord(updated, ['project_id'])
    showEditDialog.value = false
    await refreshAll()
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
}

async function runComplete() {
  if (!job.value || !canComplete.value) return
  acting.value = true
  error.value = ''
  try {
    job.value = normalizeProjectRecord(await completeJob(job.value.id), ['project_id'])
    await refreshAll()
    jobPoller.stop()
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
}

async function confirmDelete() {
  if (!job.value || !canDelete.value) return
  acting.value = true
  error.value = ''
  try {
    await deleteJob(job.value.id)
    showDeleteDialog.value = false
    jobPoller.stop()
    router.push({ name: 'jobs' })
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
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
  infoMessage.value = ''
  const manifestContext = action === 'manifest'
    ? {
        id: job.value.id,
        target_mount_path: job.value.target_mount_path,
      }
    : null

  try {
    if (action === 'start') {
      showPausePendingDialog.value = false
      job.value = await startJob(job.value.id, { thread_count: job.value.thread_count || 4 })
    } else if (action === 'pause') {
      job.value = await pauseJob(job.value.id)
      if (String(job.value?.status || '').toUpperCase() === 'PAUSING') {
        showPausePendingDialog.value = true
      }
    } else if (action === 'verify') {
      job.value = await verifyJob(job.value.id)
    } else {
      job.value = await generateManifest(job.value.id)
    }
    await refreshAll()

    if (action === 'manifest') {
      const manifestPath = buildManifestPath(job.value || manifestContext)
      infoMessage.value = manifestPath
        ? t('jobs.manifestSuccessWithPath', { path: manifestPath })
        : t('jobs.manifestSuccess')
    }

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

watch(currentStatus, (status) => {
  if (!['RUNNING', 'PAUSING'].includes(status)) {
    showPausePendingDialog.value = false
  }
})

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
    <p v-if="infoMessage" class="ok-banner wrap-anywhere" role="status" aria-live="polite">{{ infoMessage }}</p>

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
        <button class="btn" :disabled="!canEdit || acting" @click="openEditDialog">{{ t('common.actions.edit') }}</button>
        <button class="btn" :disabled="!canStart || acting" @click="runAction('start')">{{ t('jobs.start') }}</button>
        <button class="btn" :disabled="!canPause || acting" @click="runAction('pause')">{{ t('jobs.pause') }}</button>
        <button class="btn" :disabled="!canComplete || acting" @click="runComplete">{{ t('jobs.complete') }}</button>
        <button class="btn" :disabled="!canVerify || acting" @click="runAction('verify')">{{ t('jobs.verify') }}</button>
        <button class="btn" :disabled="!canGenerateManifest || acting" @click="runAction('manifest')">{{ t('jobs.manifest') }}</button>
        <button v-if="canDelete" class="btn btn-danger" :disabled="acting" @click="showDeleteDialog = true">{{ t('common.actions.delete') }}</button>
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

    <teleport to="body">
      <div v-if="showEditDialog" class="dialog-overlay" @click.self="showEditDialog = false">
        <div class="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="job-edit-title">
          <h2 id="job-edit-title">{{ t('jobs.editDialog') }}</h2>
          <p class="muted">{{ t('jobs.editDialogDescription') }}</p>

          <div class="dialog-groups">
            <fieldset class="dialog-group">
              <legend>{{ t('jobs.jobDetailsGroup') }}</legend>

              <label for="job-project">{{ t('dashboard.project') }}</label>
              <input id="job-project" :value="editForm.project_id" type="text" disabled />

              <label for="job-evidence">{{ t('jobs.evidence') }}</label>
              <input id="job-evidence" v-model="editForm.evidence_number" type="text" />

              <label for="job-thread-count">{{ t('jobs.threadCount') }}</label>
              <input id="job-thread-count" v-model.number="editForm.thread_count" type="number" min="1" max="8" />
            </fieldset>

            <fieldset class="dialog-group">
              <legend>{{ t('jobs.sourceGroup') }}</legend>

              <label for="job-mount">{{ t('jobs.selectMount') }}</label>
              <select id="job-mount" v-model="editForm.mount_id">
                <option :value="null">{{ t('jobs.chooseMount') }}</option>
                <option v-for="mount in editEligibleMounts" :key="mount.id" :value="mount.id">
                  {{ formatMountLabel(mount) }}
                </option>
              </select>

              <label for="job-source-path">{{ t('jobs.sourcePath') }}</label>
              <input id="job-source-path" v-model="editForm.source_path" type="text" :placeholder="t('jobs.sourcePathHint')" />
            </fieldset>

            <fieldset class="dialog-group">
              <legend>{{ t('jobs.destinationGroup') }}</legend>

              <label for="job-drive">{{ t('jobs.selectDrive') }}</label>
              <select id="job-drive" v-model="editForm.drive_id">
                <option :value="null">{{ t('jobs.chooseDrive') }}</option>
                <option v-for="drive in editEligibleDrives" :key="drive.id" :value="drive.id">
                  {{ formatDriveLabel(drive) }}
                </option>
              </select>
            </fieldset>
          </div>

          <div class="dialog-actions">
            <button class="btn" :disabled="acting" @click="showEditDialog = false">{{ t('common.actions.cancel') }}</button>
            <button id="job-submit" class="btn btn-primary" :disabled="acting || !editFormReady()" @click="submitEditJob">
              {{ acting ? t('common.labels.loading') : t('jobs.saveChanges') }}
            </button>
          </div>
        </div>
      </div>
    </teleport>

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

    <teleport to="body">
      <div v-if="showPausePendingDialog" class="dialog-overlay" @click.self="showPausePendingDialog = false">
        <div class="dialog-panel pause-wait-dialog" role="dialog" aria-modal="true" aria-labelledby="pause-wait-title">
          <h2 id="pause-wait-title">{{ t('jobs.pauseRequestedTitle') }}</h2>
          <p>{{ t('jobs.pauseRequestedMessage') }}</p>
          <p v-if="job" class="muted">#{{ job.id }} • {{ job.status }}</p>
          <div class="dialog-actions">
            <button class="btn" @click="showPausePendingDialog = false">{{ t('common.actions.close') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <ConfirmDialog
      v-model="showDeleteDialog"
      :title="t('jobs.deleteConfirmTitle')"
      :message="t('jobs.deleteConfirmBody')"
      :confirm-label="t('common.actions.delete')"
      :cancel-label="t('common.actions.cancel')"
      :busy="acting"
      dangerous
      @confirm="confirmDelete"
    />
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

.dialog-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--color-bg-primary) 30%, #000000);
  display: grid;
  place-items: center;
  z-index: 1000;
}

.dialog-panel {
  width: min(760px, 100%);
  max-height: min(90vh, 900px);
  overflow: auto;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
  display: grid;
  gap: var(--space-md);
}

.dialog-groups {
  display: grid;
  gap: var(--space-md);
}

.dialog-group {
  display: grid;
  gap: var(--space-xs);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-md);
}

.dialog-group legend {
  padding: 0 var(--space-xs);
  font-weight: 600;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
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

.ok-banner {
  color: var(--color-ok-banner-text, #14532d);
  background: var(--color-ok-banner-bg, #dcfce7);
  border: 1px solid var(--color-ok-banner-border, #86efac);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
