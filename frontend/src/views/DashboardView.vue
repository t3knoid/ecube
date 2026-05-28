<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSystemHealth } from '@/api/introspection.js'
import { getDrives } from '@/api/drives.js'
import { listAllJobs } from '@/api/jobs.js'
import { getShares } from '@/api/shares.js'
import { usePolling } from '@/composables/usePolling.js'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { useAuthStore } from '@/stores/auth.js'
import { formatDriveIdentity } from '@/utils/driveIdentity.js'
import { calculateJobProgress, isJobProgressActive } from '@/utils/jobProgress.js'
import { MOUNT_WORKFLOW_BUCKETS, buildMountWorkflowCounts } from '@/utils/mountWorkflow.js'
import { canStartJob, getDashboardFollowUpKey, getDashboardNextStepKey, normalizeJobStatus } from '@/utils/jobActions.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const PASSWORD_WARNING_DISMISS_KEY = 'ecube-password-warning-dismissed-days'

const health = ref({ status: 'unknown', database: 'unknown', active_jobs: 0 })
const drives = ref([])
const mounts = ref([])
const jobs = ref([])
const loading = ref(true)
const error = ref('')
const dismissedPasswordWarning = ref(sessionStorage.getItem(PASSWORD_WARNING_DISMISS_KEY) || '')
const canViewOperationalSummary = computed(() => !authStore.hasRole('auditor'))
const canViewRawMountPaths = computed(() => authStore.hasRole('admin') || authStore.hasRole('manager'))

const showPasswordWarning = computed(() => {
  if (!Number.isInteger(authStore.passwordWarningDays)) return false
  return String(authStore.passwordWarningDays) !== dismissedPasswordWarning.value
})

function dismissPasswordWarning() {
  const value = Number.isInteger(authStore.passwordWarningDays) ? String(authStore.passwordWarningDays) : ''
  dismissedPasswordWarning.value = value
  sessionStorage.setItem(PASSWORD_WARNING_DISMISS_KEY, value)
}

const driveCounts = computed(() => {
  const counts = { DISCONNECTED: 0, DISABLED: 0, AVAILABLE: 0, IN_USE: 0 }
  for (const drive of drives.value) {
    const key = String(drive.current_state || '').toUpperCase()
    if (counts[key] !== undefined) counts[key] += 1
  }
  return counts
})

const mountCounts = computed(() => buildMountWorkflowCounts(mounts.value))

const mountsByJobId = computed(() => {
  const mapping = new Map()

  for (const mount of mounts.value) {
    const jobId = Number(mount?.related_job?.job_id)
    if (!Number.isInteger(jobId) || jobId < 1 || mapping.has(jobId)) continue
    mapping.set(jobId, mount)
  }

  return mapping
})

const activeJobs = computed(() =>
  jobs.value.filter((job) => ['PENDING', 'PREPARING', 'RUNNING', 'VERIFYING'].includes(String(job.status || '').toUpperCase())),
)

const needsAttentionColumns = computed(() => [
  { key: 'id', label: t('dashboard.jobId') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'next_step', label: t('dashboard.nextStep') },
  { key: 'attention', label: t('dashboard.attentionType') },
])

const healthColumns = computed(() => [
  { key: 'id', label: t('dashboard.jobId') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'next_step', label: t('dashboard.nextStep') },
  { key: 'progress', label: t('dashboard.progress') },
])

const driveSummaryEntries = computed(() => [
  { key: 'DISCONNECTED', label: t('drives.states.disconnected'), count: driveCounts.value.DISCONNECTED },
  { key: 'DISABLED', label: t('drives.states.disabled'), count: driveCounts.value.DISABLED },
  { key: 'AVAILABLE', label: t('drives.states.available'), count: driveCounts.value.AVAILABLE },
  { key: 'IN_USE', label: t('drives.states.inUse'), count: driveCounts.value.IN_USE },
])

const mountSummaryEntries = computed(() => [
  { key: MOUNT_WORKFLOW_BUCKETS.UNASSIGNED, label: t('dashboard.mountUnassigned'), count: mountCounts.value.UNASSIGNED },
  { key: MOUNT_WORKFLOW_BUCKETS.ASSIGNED, label: t('dashboard.mountAssigned'), count: mountCounts.value.ASSIGNED },
  { key: MOUNT_WORKFLOW_BUCKETS.ACTIVE, label: t('dashboard.mountActive'), count: mountCounts.value.ACTIVE },
  { key: MOUNT_WORKFLOW_BUCKETS.BLOCKED, label: t('dashboard.mountBlocked'), count: mountCounts.value.BLOCKED },
  { key: MOUNT_WORKFLOW_BUCKETS.CUSTODY_PENDING, label: t('dashboard.mountCustodyPending'), count: mountCounts.value.CUSTODY_PENDING },
  { key: MOUNT_WORKFLOW_BUCKETS.COMPLETED, label: t('dashboard.mountCompleted'), count: mountCounts.value.COMPLETED },
  { key: MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE, label: t('dashboard.mountUnavailable'), count: mountCounts.value.UNAVAILABLE },
])

const needsAttentionItems = computed(() => {
  const items = []
  const seenJobIds = new Set()
  const attentionPriorityByKey = {
    'dashboard.attentionBlocked': 0,
    'dashboard.attentionWaitingToStart': 1,
    'dashboard.attentionWaitingForCustody': 2,
    'dashboard.attentionReadyForEject': 3,
  }
  const jobsById = new Map(
    jobs.value
      .map((job) => [Number(job.id), job])
      .filter(([jobId]) => Number.isInteger(jobId) && jobId > 0),
  )

  for (const job of jobs.value) {
    const jobId = Number(job.id)
    const status = normalizeJobStatus(job.status)
    const followUpKey = getDashboardFollowUpKey({
      jobStatus: status,
      startupAnalysisStatus: job.startup_analysis_status,
      custodyStatus: job.custody_status,
      driveState: job?.drive?.current_state,
      driveIsMounted: job?.drive?.is_mounted,
    })
    if (!Number.isInteger(jobId) || jobId < 1) continue

    if (attentionPriorityByKey[followUpKey] !== undefined) {
      items.push({
        ...job,
        attention: t(followUpKey),
        attentionPriority: attentionPriorityByKey[followUpKey],
      })
      seenJobIds.add(jobId)
    }
  }

  for (const mount of mounts.value) {
    const relatedJobId = Number(mount?.related_job?.job_id)
    const relatedJobStatus = normalizeJobStatus(mount?.related_job?.status)
    const custodyStatus = String(mount?.related_job?.custody_status || '').toUpperCase()
    const matchedJob = jobsById.get(relatedJobId)

    if (!Number.isInteger(relatedJobId) || relatedJobId < 1 || seenJobIds.has(relatedJobId)) continue
    const followUpKey = getDashboardFollowUpKey({
      jobStatus: relatedJobStatus,
      startupAnalysisStatus: matchedJob?.startup_analysis_status,
      custodyStatus,
      driveState: matchedJob?.drive?.current_state,
      driveIsMounted: matchedJob?.drive?.is_mounted,
    })

    if (!['dashboard.attentionWaitingForCustody', 'dashboard.attentionReadyForEject'].includes(followUpKey)) continue

    items.push({
      ...(matchedJob || {}),
      id: relatedJobId,
      project_id: matchedJob?.project_id || mount.project_id,
      status: relatedJobStatus,
      custody_status: custodyStatus,
      attention: t(followUpKey),
      attentionPriority: followUpKey === 'dashboard.attentionWaitingForCustody' ? 2 : 3,
    })
    seenJobIds.add(relatedJobId)
  }

  return items.sort((left, right) => {
    if (left.attentionPriority !== right.attentionPriority) {
      return left.attentionPriority - right.attentionPriority
    }
    return Number(left.id) - Number(right.id)
  })
})

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function openJobDetail(jobId) {
  const normalizedJobId = Number(jobId)
  if (!Number.isInteger(normalizedJobId) || normalizedJobId < 1) return
  router.push({ name: 'job-detail', params: { id: normalizedJobId } })
}

function openDriveSummary(state) {
  router.push({ name: 'drives', query: { state } })
}

function openMountSummary(workflow) {
  router.push({ name: 'shares', query: { workflow } })
}

function progressPercent(job) {
  return calculateJobProgress(job).percent
}

function progressLabel(job) {
  const metrics = calculateJobProgress(job)
  if (metrics.initializing) {
    return t('jobs.progressPreparingShort')
  }
  return `${metrics.percent}%`
}

function progressActive(job) {
  return isJobProgressActive(job)
}

function formatTimestamp(value) {
  if (!value) return t('common.labels.notAvailable')
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return t('common.labels.notAvailable')
  return parsed.toLocaleString()
}

function formatDuration(totalSeconds) {
  if (typeof totalSeconds !== 'number' || totalSeconds < 0) return t('common.labels.notAvailable')
  if (totalSeconds === 0) return '0s'

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function formatCopyRate(bytesValue, totalSeconds) {
  if (typeof bytesValue !== 'number' || bytesValue < 0 || typeof totalSeconds !== 'number') {
    return t('common.labels.notAvailable')
  }
  if (totalSeconds <= 0 || bytesValue === 0) return '0.0 Mb/s'

  const mbPerSecond = (bytesValue * 8) / (1024 * 1024) / totalSeconds
  return `${mbPerSecond.toFixed(1)} Mb/s`
}

function calculateDurationSeconds(job) {
  const storedSeconds = Number(job?.active_duration_seconds || 0)
  const status = normalizeJobStatus(job?.status)

  if (['PREPARING', 'RUNNING', 'VERIFYING', 'PAUSING'].includes(status) && job?.started_at) {
    const started = new Date(job.started_at)
    if (!Number.isNaN(started.getTime())) {
      const liveSeconds = Math.max(0, Math.round((Date.now() - started.getTime()) / 1000))
      return storedSeconds + liveSeconds
    }
  }

  if (storedSeconds > 0) return storedSeconds

  if (job?.started_at && job?.completed_at) {
    const started = new Date(job.started_at)
    const completed = new Date(job.completed_at)
    if (!Number.isNaN(started.getTime()) && !Number.isNaN(completed.getTime())) {
      return Math.max(0, Math.round((completed.getTime() - started.getTime()) / 1000))
    }
  }

  return null
}

function calculateCopyDurationSeconds(job) {
  const storedSeconds = Number(job?.active_duration_seconds || 0)
  const status = normalizeJobStatus(job?.status)

  if (['RUNNING', 'PAUSING'].includes(status) && job?.copy_started_at) {
    const started = new Date(job.copy_started_at)
    if (!Number.isNaN(started.getTime())) {
      const liveSeconds = Math.max(0, Math.round((Date.now() - started.getTime()) / 1000))
      return storedSeconds + liveSeconds
    }
  }

  if (storedSeconds > 0) return storedSeconds
  return 0
}

function resolveSourceMount(job) {
  const jobId = Number(job?.id)
  if (!Number.isInteger(jobId) || jobId < 1) return null
  return mountsByJobId.value.get(jobId) || null
}

function sourceMountLabel(job) {
  const sourceMount = resolveSourceMount(job)
  if (!sourceMount?.remote_path) return t('common.labels.notAvailable')
  return canViewRawMountPaths.value ? sourceMount.remote_path : t('shares.redactedValue')
}

function sourcePathLabel(job) {
  const sourcePath = String(job?.source_path || '').trim()
  return sourcePath || t('common.labels.notAvailable')
}

function destinationDriveLabel(job) {
  if (job?.drive) return formatDriveIdentity(job.drive)
  return t('common.labels.notAvailable')
}

function jobActivityEntry(job) {
  const status = normalizeJobStatus(job?.status)

  if (status === 'FAILED' && job?.completed_at) {
    return { label: t('jobs.failedAt'), value: formatTimestamp(job.completed_at) }
  }
  if (['COMPLETED', 'ARCHIVED'].includes(status) && job?.completed_at) {
    return { label: t('jobs.completedAt'), value: formatTimestamp(job.completed_at) }
  }
  if (['PREPARING', 'RUNNING', 'VERIFYING', 'PAUSING', 'PAUSED'].includes(status) && job?.started_at) {
    return { label: t('jobs.startedAt'), value: formatTimestamp(job.started_at) }
  }
  return null
}

function failureEntries(job) {
  const entries = []
  const failedFiles = Number(job?.files_failed || 0)
  const timedOutFiles = Number(job?.files_timed_out || 0)

  if (failedFiles > 0) {
    entries.push({ label: t('jobs.filesFailed'), value: String(failedFiles) })
  }
  if (timedOutFiles > 0) {
    entries.push({ label: t('jobs.filesTimedOut'), value: String(timedOutFiles) })
  }

  return entries
}

function liveTransferEntries(job) {
  const status = normalizeJobStatus(job?.status)
  if (!['PREPARING', 'RUNNING', 'VERIFYING', 'PAUSING'].includes(status)) return []

  const durationSeconds = calculateDurationSeconds(job)
  const copyDurationSeconds = calculateCopyDurationSeconds(job)
  const copiedBytes = Number(job?.copied_bytes || 0)
  const totalBytes = Number(job?.total_bytes || 0)
  const remainingBytes = Math.max(0, totalBytes - copiedBytes)
  const rateBytesPerSecond = copyDurationSeconds > 0 ? copiedBytes / copyDurationSeconds : 0
  const remainingSeconds = rateBytesPerSecond > 0 && remainingBytes > 0
    ? Math.ceil(remainingBytes / rateBytesPerSecond)
    : null
  const entries = []

  if (['RUNNING', 'PAUSING'].includes(status) && durationSeconds != null && copyDurationSeconds > 0) {
    entries.push({ label: t('jobs.copyRate'), value: formatCopyRate(copiedBytes, copyDurationSeconds) })
  }
  if (remainingSeconds != null) {
    entries.push({ label: t('jobs.timeRemaining'), value: formatDuration(remainingSeconds) })
    entries.push({
      label: t('jobs.estimatedCompletion'),
      value: formatTimestamp(new Date(Date.now() + (remainingSeconds * 1000)).toISOString()),
    })
  }

  return entries
}

function dashboardStatusTone(status) {
  const value = normalizeJobStatus(status)

  if (['COMPLETED', 'DONE', 'MOUNTED', 'CONNECTED', 'AVAILABLE', 'OK', 'TRUE'].includes(value)) {
    return 'success'
  }
  if (['FAILED', 'ERROR', 'DISCONNECTED', 'UNMOUNTED', 'FALSE'].includes(value)) {
    return 'danger'
  }
  if (['RUNNING', 'VERIFYING', 'COPYING', 'IN_USE', 'DEGRADED', 'PAUSING'].includes(value)) {
    return 'warning'
  }
  if (['PENDING', 'PAUSED', 'UNKNOWN'].includes(value)) {
    return 'muted'
  }

  return 'info'
}

function dashboardStatusIcon(status) {
  const tone = dashboardStatusTone(status)

  if (tone === 'success') return '✓'
  if (tone === 'warning') return '!'
  if (tone === 'danger') return '×'
  if (tone === 'muted') return '•'
  return '?'
}

function nextStepLabel(job) {
  return t(getDashboardNextStepKey({
    jobStatus: job?.status,
    startupAnalysisStatus: job?.startup_analysis_status,
    custodyStatus: job?.custody_status,
    failedFiles: job?.files_failed,
    timedOutFiles: job?.files_timed_out,
    driveState: job?.drive?.current_state,
    driveIsMounted: job?.drive?.is_mounted,
  }))
}

async function refreshDashboard() {
  const warnings = []
  const results = await Promise.allSettled([
    getSystemHealth(),
    getDrives({ include_disconnected: true }),
    getShares(),
    listAllJobs({ include_archived: true }),
  ])

  if (results[0].status === 'fulfilled') {
    health.value = results[0].value
  } else {
    warnings.push(t('common.errors.networkError'))
  }

  if (results[1].status === 'fulfilled') {
    drives.value = Array.isArray(results[1].value)
      ? results[1].value.map((item) => normalizeProjectRecord(item, ['current_project_id']))
      : []
  } else {
    warnings.push(t('dashboard.loadDrivesError'))
  }

  if (results[2].status === 'fulfilled') {
    mounts.value = Array.isArray(results[2].value)
      ? results[2].value.map((item) => normalizeProjectRecord(item, ['project_id']))
      : []
  } else {
    warnings.push(t('dashboard.loadMountsError'))
  }

  if (results[3].status === 'fulfilled') {
    jobs.value = Array.isArray(results[3].value)
      ? results[3].value.map((item) => normalizeProjectRecord(item, ['project_id']))
      : []
  } else {
    // Backward compatibility for servers that do not yet expose GET /jobs.
    jobs.value = []
  }

  error.value = warnings.join(' ')
}

const dashboardPoller = usePolling(refreshDashboard, { intervalMs: 10000, immediate: false })

function requestDashboardRefresh() {
  return dashboardPoller.tick()
}

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    await requestDashboardRefresh()
    dashboardPoller.start()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  dashboardPoller.stop()
})
</script>

<template>
  <section class="view-root">
    <header class="view-header">
      <h1>{{ t('nav.dashboard') }}</h1>
      <button class="btn" @click="requestDashboardRefresh">{{ t('common.actions.refresh') }}</button>
    </header>

    <div v-if="showPasswordWarning" class="warning-banner">
      <p>{{ t('dashboard.passwordExpiryWarning', { days: authStore.passwordWarningDays }) }}</p>
      <button class="btn" type="button" @click="dismissPasswordWarning">{{ t('common.actions.dismiss') }}</button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>

    <div class="card-grid">
      <article class="summary-card">
        <h2>{{ t('dashboard.systemHealth') }}</h2>
        <div class="summary-row">
          <span>{{ t('common.labels.status') }}</span>
          <StatusBadge :status="health.status" />
        </div>
        <div class="summary-row">
          <span>{{ t('common.labels.db') }}</span>
          <StatusBadge :status="health.database" />
        </div>
        <div v-if="canViewOperationalSummary" class="summary-row">
          <span>{{ t('jobs.activeJobs') }}</span>
          <strong>{{ health.active_jobs || 0 }}</strong>
        </div>
      </article>

      <article v-if="canViewOperationalSummary" class="summary-card">
        <h2>{{ t('dashboard.driveSummary') }}</h2>
        <button
          v-for="entry in driveSummaryEntries"
          :key="entry.key"
          class="summary-link"
          type="button"
          @click="openDriveSummary(entry.key)"
        >
          <span>{{ entry.label }}</span>
          <strong>{{ entry.count }}</strong>
        </button>
      </article>

      <article v-if="canViewOperationalSummary" class="summary-card">
        <h2>{{ t('dashboard.sharesSummary') }}</h2>
        <button
          v-for="entry in mountSummaryEntries"
          :key="entry.key"
          class="summary-link"
          type="button"
          @click="openMountSummary(entry.key)"
        >
          <span>{{ entry.label }}</span>
          <strong>{{ entry.count }}</strong>
        </button>
      </article>
    </div>

    <article v-if="canViewOperationalSummary" class="panel">
      <h2>{{ t('dashboard.needsAttention') }}</h2>
      <p v-if="!needsAttentionItems.length" class="muted">{{ t('dashboard.noNeedsAttention') }}</p>
      <DataTable
        v-else
        class="needs-attention-table"
        :columns="needsAttentionColumns"
        :rows="needsAttentionItems"
        row-key="id"
      >
        <template #cell-id="{ row }">
          <div class="dashboard-cell-stack dashboard-job-id-cell">
            <button class="cell-link" type="button" @click="openJobDetail(row.id)">
              {{ row.id }}
            </button>
          </div>
        </template>
        <template #cell-project_id="{ row }">
          <div class="dashboard-cell-stack">
            <span>{{ formatProjectId(row.project_id) }}</span>
            <div class="dashboard-cell-meta dashboard-cell-meta-block dashboard-source-context">
              <div class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ t('dashboard.sourceMount') }}</span>
                <span class="dashboard-meta-value wrap-anywhere">{{ sourceMountLabel(row) }}</span>
              </div>
              <div class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ t('jobs.sourcePath') }}</span>
                <span class="dashboard-meta-value wrap-anywhere">{{ sourcePathLabel(row) }}</span>
              </div>
              <div class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ t('jobs.destinationDrive') }}</span>
                <span class="dashboard-meta-value wrap-anywhere">{{ destinationDriveLabel(row) }}</span>
              </div>
              <div v-if="jobActivityEntry(row)" class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ jobActivityEntry(row).label }}</span>
                <span class="dashboard-meta-value">{{ jobActivityEntry(row).value }}</span>
              </div>
            </div>
          </div>
        </template>
        <template #cell-status="{ row }">
          <span
            class="dashboard-status-icon"
            :class="`dashboard-status-icon--${dashboardStatusTone(row.status)}`"
            :aria-label="String(row.status || 'unknown')"
            :title="String(row.status || 'unknown')"
            role="img"
          >
            <span aria-hidden="true">{{ dashboardStatusIcon(row.status) }}</span>
          </span>
          <StatusBadge class="dashboard-status-badge" :status="row.status" />
        </template>
        <template #cell-next_step="{ row }">
          <div class="dashboard-cell-stack">
            <span class="next-step-label">{{ nextStepLabel(row) }}</span>
            <div v-if="failureEntries(row).length" class="dashboard-cell-meta dashboard-cell-meta-block active-jobs-next-step-meta">
              <div v-for="entry in failureEntries(row)" :key="`${row.id}-${entry.label}`" class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ entry.label }}</span>
                <span class="dashboard-meta-value">{{ entry.value }}</span>
              </div>
            </div>
          </div>
        </template>
        <template #cell-attention="{ row }">
          <span class="attention-label">{{ row.attention }}</span>
        </template>
      </DataTable>
    </article>

    <article v-if="canViewOperationalSummary" class="panel">
      <h2>{{ t('jobs.activeJobs') }}</h2>
      <DataTable class="active-jobs-table" :columns="healthColumns" :rows="activeJobs" row-key="id" :empty-text="t('dashboard.noActiveJobs')">
        <template #cell-id="{ row }">
          <div class="dashboard-cell-stack active-jobs-job-id-cell">
            <button
              v-if="Number.isInteger(Number(row.id)) && Number(row.id) > 0"
              class="cell-link"
              type="button"
              @click="openJobDetail(row.id)"
            >
              {{ row.id }}
            </button>
            <span v-else class="job-id-text">{{ row.id ?? '-' }}</span>
          </div>
        </template>
        <template #cell-project_id="{ row }">
          <div class="dashboard-cell-stack">
            <span>{{ formatProjectId(row.project_id) }}</span>
            <div class="dashboard-cell-meta dashboard-cell-meta-block active-jobs-project-meta">
              <div class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ t('dashboard.sourceMount') }}</span>
                <span class="dashboard-meta-value wrap-anywhere">{{ sourceMountLabel(row) }}</span>
              </div>
              <div class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ t('jobs.sourcePath') }}</span>
                <span class="dashboard-meta-value wrap-anywhere">{{ sourcePathLabel(row) }}</span>
              </div>
              <div class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ t('jobs.destinationDrive') }}</span>
                <span class="dashboard-meta-value wrap-anywhere">{{ destinationDriveLabel(row) }}</span>
              </div>
              <div v-if="jobActivityEntry(row)" class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ jobActivityEntry(row).label }}</span>
                <span class="dashboard-meta-value">{{ jobActivityEntry(row).value }}</span>
              </div>
            </div>
          </div>
        </template>
        <template #cell-status="{ row }">
          <span
            class="dashboard-status-icon"
            :class="`dashboard-status-icon--${dashboardStatusTone(row.status)}`"
            :aria-label="String(row.status || 'unknown')"
            :title="String(row.status || 'unknown')"
            role="img"
          >
            <span aria-hidden="true">{{ dashboardStatusIcon(row.status) }}</span>
          </span>
          <StatusBadge class="dashboard-status-badge" :status="row.status" />
        </template>
        <template #cell-next_step="{ row }">
          <div class="dashboard-cell-stack">
            <span class="next-step-label">{{ nextStepLabel(row) }}</span>
            <div v-if="failureEntries(row).length" class="dashboard-cell-meta dashboard-cell-meta-block active-jobs-next-step-meta">
              <div v-for="entry in failureEntries(row)" :key="`${row.id}-${entry.label}`" class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ entry.label }}</span>
                <span class="dashboard-meta-value">{{ entry.value }}</span>
              </div>
            </div>
          </div>
        </template>
        <template #cell-progress="{ row }">
          <div class="dashboard-cell-stack">
            <div class="dashboard-progress-cell">
              <ProgressBar
                class="dashboard-progress-bar"
                :value="progressPercent(row)"
                :total="100"
                :label="progressLabel(row)"
                :active="progressActive(row)"
              />
              <span class="dashboard-progress-mobile-label">{{ progressLabel(row) }}</span>
            </div>
            <div class="dashboard-cell-meta dashboard-cell-meta-block active-jobs-progress-meta">
              <div v-for="entry in liveTransferEntries(row)" :key="`${row.id}-${entry.label}`" class="dashboard-meta-line">
                <span class="dashboard-meta-label">{{ entry.label }}</span>
                <span class="dashboard-meta-value">{{ entry.value }}</span>
              </div>
            </div>
          </div>
        </template>
      </DataTable>
    </article>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-lg);
}

.warning-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-alert-warning-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-alert-warning-bg);
  color: var(--color-alert-warning-text);
}

.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-md);
}

.summary-card,
.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  box-shadow: var(--shadow-sm);
  padding: var(--space-md);
}

.summary-card h2,
.panel h2 {
  font-size: var(--font-size-lg);
  margin-bottom: var(--space-sm);
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-xs) 0;
}

.summary-link {
  display: flex;
  width: 100%;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-xs) 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.summary-link:hover,
.summary-link:focus-visible {
  text-decoration: underline;
  text-decoration-thickness: 2px;
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

.attention-label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.dashboard-cell-stack {
  display: grid;
  gap: var(--space-xs);
}

.dashboard-cell-meta {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.dashboard-cell-meta-block {
  display: grid;
  gap: 0.2rem;
}

.dashboard-meta-line {
  display: flex;
  gap: var(--space-xs);
  align-items: baseline;
  flex-wrap: wrap;
}

.dashboard-meta-label {
  font-weight: 600;
}

.dashboard-meta-value {
  min-width: 0;
}

.next-step-label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.wrap-anywhere {
  overflow-wrap: anywhere;
}

.dashboard-progress-cell {
  display: flex;
  align-items: center;
}

.dashboard-progress-mobile-label {
  display: none;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  white-space: nowrap;
}

.dashboard-status-icon {
  display: none;
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

.dashboard-status-icon--success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.dashboard-status-icon--warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.dashboard-status-icon--danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.dashboard-status-icon--info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.dashboard-status-icon--muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
}

@media (max-width: 768px) {
  .view-root {
    gap: var(--space-md);
  }

  .view-header {
    gap: var(--space-sm);
  }

  .card-grid {
    grid-template-columns: 1fr;
  }

  .summary-card,
  .panel {
    padding: var(--space-sm);
  }

  .summary-row,
  .summary-link {
    display: grid;
    grid-template-columns: minmax(0, 11rem) auto;
    justify-content: start;
    align-items: center;
    column-gap: var(--space-sm);
  }

  .dashboard-progress-bar {
    display: none;
  }

  .dashboard-progress-mobile-label {
    display: inline;
  }

  .dashboard-status-icon {
    display: inline-flex;
  }

  :deep(.dashboard-status-badge) {
    display: none;
  }

  :deep(.active-jobs-table th:nth-child(2)),
  :deep(.active-jobs-table td:nth-child(2)) {
    display: none;
  }

  :deep(.active-jobs-table .active-jobs-project-meta) {
    display: none;
  }

  :deep(.active-jobs-table .active-jobs-progress-meta) {
    display: none;
  }

  :deep(.needs-attention-table th:nth-child(2)),
  :deep(.needs-attention-table td:nth-child(2)) {
    display: none;
  }
}
</style>
