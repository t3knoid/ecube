<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { listJobs, createJob, startJob, pauseJob } from '@/api/jobs.js'
import { getDrives } from '@/api/drives.js'
import { getMounts } from '@/api/mounts.js'
import { normalizeErrorMessage } from '@/api/client.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'
import { formatDriveIdentity } from '@/utils/driveIdentity.js'
import { calculateJobProgress } from '@/utils/jobProgress.js'
import { classifySourcePathOverlap, resolveMountedSourcePath } from '@/utils/pathOverlap.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const router = useRouter()
const { t } = useI18n()
const { jobStatusLabel } = useStatusLabels()
const authStore = useAuthStore()

const jobs = ref([])
const drives = ref([])
const mounts = ref([])
const loading = ref(false)
const saving = ref(false)
const actingJobId = ref(null)
const jobsRefreshTimer = ref(null)
const pageError = ref('')
const pageInfo = ref('')
const createDialogError = ref('')
const compatibilityNote = ref('')

const showCreateDialog = ref(false)
const showPausePendingDialog = ref(false)
const pausePendingJobId = ref(null)
const createDialogRef = ref(null)
const createDialogTriggerRef = ref(null)

const search = ref('')
const statusFilter = ref('ALL')
const showArchivedJobs = ref(false)
const page = ref(1)
const pageSize = ref(10)
const isMobileViewport = ref(false)
let mobileViewportQuery = null

const form = ref({
  project_id: '',
  evidence_number: '',
  drive_id: null,
  mount_id: null,
  source_path: '/',
  thread_count: 4,
  notes: '',
  run_immediately: false,
})

const canOperate = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor']))
const ACTIVE_OVERLAP_STATUSES = new Set(['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'])
const OVERLAP_QUERY_LIMIT = 1000

const columns = computed(() => {
  const nextColumns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'project_id', label: t('dashboard.project') },
    { key: 'evidence_number', label: t('jobs.evidence') },
    { key: 'device', label: t('jobs.device') },
    { key: 'status', label: t('common.labels.status') },
    { key: 'progress', label: t('dashboard.progress') },
    { key: 'actions', label: '', align: 'center' },
  ]

  if (isMobileViewport.value) {
    return nextColumns.filter(
      (column) => column.key !== 'evidence_number' && column.key !== 'progress',
    )
  }

  return nextColumns
})

function normalizeJobStatus(status) {
  return String(status || '').toUpperCase()
}

function normalizeStartupAnalysisStatus(status) {
  return String(status || '').toUpperCase()
}

function jobStatusTone(status) {
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

function jobStatusIcon(status) {
  const tone = jobStatusTone(status)

  if (tone === 'success') return '✓'
  if (tone === 'warning') return '!'
  if (tone === 'danger') return '×'
  if (tone === 'muted') return '•'
  return '?'
}

function isRowActionBusy(job) {
  return Number(actingJobId.value) === Number(job?.id)
}

function canStartJob(job) {
  return canOperate.value && ['PENDING', 'FAILED', 'PAUSED'].includes(normalizeJobStatus(job?.status))
}

function canPauseJob(job) {
  return canOperate.value && normalizeJobStatus(job?.status) === 'RUNNING'
}

const pausePendingJob = computed(() => (
  jobs.value.find((job) => Number(job.id) === Number(pausePendingJobId.value)) || null
))

async function runJobAction(job, action) {
  if (!job || isRowActionBusy(job)) return

  const allowStart = action === 'start' && canStartJob(job)
  const allowPause = action === 'pause' && canPauseJob(job)
  if (!allowStart && !allowPause) return

  actingJobId.value = job.id
  pageError.value = ''
  try {
    const updated = normalizeProjectRecord(
      action === 'start'
        ? await startJob(job.id, { thread_count: Number(job.thread_count || 4) })
        : await pauseJob(job.id),
      ['project_id'],
    )

    jobs.value = jobs.value.map((item) => (Number(item.id) === Number(updated.id) ? updated : item))
    if (action === 'pause' && normalizeJobStatus(updated.status) === 'PAUSING') {
      pausePendingJobId.value = updated.id
      showPausePendingDialog.value = true
    }
    if (action === 'start') {
      pausePendingJobId.value = null
      showPausePendingDialog.value = false
    }
    await loadJobs()
  } catch (err) {
    pageError.value = buildJobError(err)
  } finally {
    actingJobId.value = null
  }
}

function progressLabel(job) {
  const metrics = calculateJobProgress(job)
  if (metrics.initializing) {
    return t('jobs.progressPreparingShort')
  }
  return `${metrics.percent}%`
}

function syncViewportState() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return

  if (!mobileViewportQuery) {
    mobileViewportQuery = window.matchMedia('(max-width: 768px)')
  }

  isMobileViewport.value = mobileViewportQuery.matches
}

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function formatDriveLabel(drive) {
  return formatDriveIdentity(drive)
}

function formatJobDevice(job) {
  return formatDriveIdentity(job?.drive)
}

function closeRowActionsMenu(event) {
  const menu = event?.currentTarget instanceof HTMLElement ? event.currentTarget.closest('details') : null
  if (menu instanceof HTMLDetailsElement) {
    menu.removeAttribute('open')
  }
}

function openJobDetails(job, event) {
  closeRowActionsMenu(event)
  router.push({ name: 'job-detail', params: { id: job.id } })
}

function handleMenuStart(job, event) {
  closeRowActionsMenu(event)
  void runJobAction(job, 'start')
}

function handleMenuPause(job, event) {
  closeRowActionsMenu(event)
  void runJobAction(job, 'pause')
}

function formatMountLabel(mount) {
  return mount?.remote_path || t('jobs.chooseMount')
}

function resetForm() {
  form.value = {
    project_id: '',
    evidence_number: '',
    drive_id: null,
    mount_id: null,
    source_path: '/',
    thread_count: 4,
    notes: '',
    run_immediately: false,
  }
}

function trapFocusWithin(event, container) {
  if (!container) return
  const focusable = Array.from(
    container.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'),
  ).filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true')

  if (!focusable.length) return

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement

  if (event.shiftKey && active === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return jobs.value.filter((job) => {
    const status = String(job.status || '').toUpperCase()
    if (!showArchivedJobs.value && status === 'ARCHIVED') {
      return false
    }
    const matchesStatus = statusFilter.value === 'ALL' || status === statusFilter.value
    const text = [job.project_id, job.evidence_number, formatJobDevice(job), String(job.id), job.source_path]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    const matchesQuery = !query || text.includes(query)
    return matchesStatus && matchesQuery
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const availableProjects = computed(() =>
  [...new Set(
    mounts.value
      .filter((mount) => String(mount?.status || '').toUpperCase() === 'MOUNTED')
      .map((mount) => normalizeProjectId(mount?.project_id))
      .filter((value) => value && value !== 'UNASSIGNED'),
  )].sort((left, right) => left.localeCompare(right)),
)

const selectedProject = computed(() => normalizeProjectId(form.value.project_id))
const projectSelected = computed(() => Boolean(selectedProject.value))

const eligibleMounts = computed(() => {
  if (!projectSelected.value) return []
  return mounts.value.filter(
    (mount) => String(mount?.status || '').toUpperCase() === 'MOUNTED'
      && normalizeProjectId(mount?.project_id) === selectedProject.value,
  )
})

const eligibleDrives = computed(() => {
  if (!projectSelected.value) return []
  return drives.value.filter((drive) => {
    const state = String(drive?.current_state || '').toUpperCase()
    const boundProject = normalizeProjectId(drive?.current_project_id)
    return ['AVAILABLE', 'IN_USE'].includes(state)
      && !!drive?.mount_path
      && (!boundProject || boundProject === selectedProject.value)
  })
})

function formReady() {
  return projectSelected.value
    && !!form.value.evidence_number.trim()
    && !!form.value.source_path.trim()
    && form.value.mount_id != null
    && form.value.mount_id !== ''
    && form.value.drive_id != null
    && form.value.drive_id !== ''
}

async function loadSupportingData() {
  const [driveResult, mountResult] = await Promise.allSettled([getDrives(), getMounts()])
  drives.value = driveResult.status === 'fulfilled'
    ? (driveResult.value || []).map((item) => normalizeProjectRecord(item, ['current_project_id']))
    : []
  mounts.value = mountResult.status === 'fulfilled'
    ? (mountResult.value || []).map((item) => normalizeProjectRecord(item, ['project_id']))
    : []
}

async function loadOverlapCandidates(driveId) {
  if (!driveId) return []

  const overlapCandidates = []
  let offset = 0

  while (true) {
    const response = await listJobs({
      limit: OVERLAP_QUERY_LIMIT,
      offset,
      drive_id: Number(driveId),
      statuses: Array.from(ACTIVE_OVERLAP_STATUSES),
    })
    const batch = (response || []).map((item) => normalizeProjectRecord(item, ['project_id']))
    overlapCandidates.push(...batch)
    if (batch.length < OVERLAP_QUERY_LIMIT) {
      return overlapCandidates
    }
    offset += batch.length
  }
}

function stopJobsRefreshTimer() {
  if (jobsRefreshTimer.value != null) {
    window.clearInterval(jobsRefreshTimer.value)
    jobsRefreshTimer.value = null
  }
}

function buildStartupAnalysisCompletionMessage(previousJobs, nextJobs) {
  const previousById = new Map(previousJobs.map((job) => [Number(job.id), job]))

  for (const job of nextJobs) {
    const previous = previousById.get(Number(job.id))
    if (!previous) continue

    const previousStatus = normalizeStartupAnalysisStatus(previous.startup_analysis_status)
    const nextStatus = normalizeStartupAnalysisStatus(job.startup_analysis_status)
    if (previousStatus !== 'ANALYZING' || nextStatus === 'ANALYZING' || !nextStatus) continue

    return t('jobs.startupAnalysisCompletedFromList', {
      jobId: Number(job.id),
      status: t(`jobs.analysisStates.${nextStatus}`),
    })
  }

  return ''
}

function syncJobsRefreshTimer() {
  stopJobsRefreshTimer()
  const hasActiveJobs = jobs.value.some((job) => (
    ['RUNNING', 'PAUSING', 'VERIFYING'].includes(normalizeJobStatus(job?.status))
      || normalizeStartupAnalysisStatus(job?.startup_analysis_status) === 'ANALYZING'
  ))
  if (!hasActiveJobs) return
  jobsRefreshTimer.value = window.setInterval(() => {
    void loadJobs()
  }, 3000)
}

async function loadJobs() {
  loading.value = true
  pageError.value = ''
  compatibilityNote.value = ''
  try {
    const previousJobs = jobs.value
    const response = await listJobs({ limit: 200, include_archived: showArchivedJobs.value })
    const nextJobs = (response || []).map((item) => normalizeProjectRecord(item, ['project_id']))
    const analysisCompletionMessage = buildStartupAnalysisCompletionMessage(previousJobs, nextJobs)
    jobs.value = nextJobs
    if (analysisCompletionMessage) {
      pageInfo.value = analysisCompletionMessage
    }
  } catch {
    jobs.value = []
    compatibilityNote.value = t('jobs.listUnavailable')
  } finally {
    loading.value = false
  }
}

function syncEligibleSelections() {
  if (!projectSelected.value) {
    form.value.drive_id = null
    form.value.mount_id = null
    return
  }

  const hasDrive = eligibleDrives.value.some((drive) => Number(drive.id) === Number(form.value.drive_id))
  const hasMount = eligibleMounts.value.some((mount) => Number(mount.id) === Number(form.value.mount_id))

  if (!hasDrive) {
    form.value.drive_id = eligibleDrives.value[0]?.id ?? null
  }
  if (!hasMount) {
    form.value.mount_id = eligibleMounts.value[0]?.id ?? null
  }
}

function resolveSourcePath() {
  const source = form.value.source_path.trim()
  return source || '/'
}

function selectedMountRoot() {
  const mount = mounts.value.find((item) => Number(item?.id) === Number(form.value.mount_id))
  return String(mount?.local_mount_point || '').trim()
}

function buildOverlapErrorMessage(job, overlapType) {
  const jobId = Number(job?.id)
  if (overlapType === 'exact') {
    return t('jobs.overlapConflictExact', { jobId })
  }
  if (overlapType === 'ancestor') {
    return t('jobs.overlapConflictAncestor', { jobId })
  }
  return t('jobs.overlapConflictDescendant', { jobId })
}

function findSourceOverlapConflict(candidateJobs) {
  const driveId = Number(form.value.drive_id)
  const mountRoot = selectedMountRoot()
  const sourcePath = resolveMountedSourcePath(resolveSourcePath(), mountRoot)

  if (!driveId || !mountRoot || !sourcePath) {
    return null
  }

  for (const job of candidateJobs) {
    if (!ACTIVE_OVERLAP_STATUSES.has(normalizeJobStatus(job?.status))) continue
    if (Number(job?.drive?.id) !== driveId) continue

    const overlapType = classifySourcePathOverlap(job?.source_path, sourcePath)
    if (overlapType !== 'none') {
      return { job, overlapType }
    }
  }

  return null
}

function buildJobError(err) {
  const status = err?.response?.status
  const detail = normalizeErrorMessage(err?.response?.data, '')

  if (!status) return t('common.errors.networkError')
  if (status === 403) return detail || t('common.errors.insufficientPermissions')
  if (status === 404) return detail || t('common.errors.notFound')
  if (status === 409) return detail || t('common.errors.requestConflict')
  if (status === 422) return detail || t('common.errors.validationFailed')
  if (status >= 500) return t('common.errors.serverError', { status })
  return detail || t('common.errors.serverErrorGeneric')
}

async function submitCreateJob() {
  if (!formReady()) return

  saving.value = true
  createDialogError.value = ''
  try {
    await loadSupportingData()
    syncEligibleSelections()

    const driveStillEligible = eligibleDrives.value.some((drive) => Number(drive.id) === Number(form.value.drive_id))
    const mountStillEligible = eligibleMounts.value.some((mount) => Number(mount.id) === Number(form.value.mount_id))

    if (!driveStillEligible || !mountStillEligible) {
      createDialogError.value = t('jobs.selectionUnavailable')
      return
    }

    const overlapCandidates = await loadOverlapCandidates(form.value.drive_id)
    const overlapConflict = findSourceOverlapConflict(overlapCandidates)
    if (overlapConflict) {
      createDialogError.value = buildOverlapErrorMessage(overlapConflict.job, overlapConflict.overlapType)
      return
    }

    const payload = {
      project_id: selectedProject.value,
      evidence_number: form.value.evidence_number.trim(),
      mount_id: Number(form.value.mount_id),
      source_path: resolveSourcePath(),
      drive_id: Number(form.value.drive_id),
      thread_count: Number(form.value.thread_count),
    }

    const created = normalizeProjectRecord(await createJob(payload), ['project_id'])

    if (form.value.run_immediately) {
      try {
        const started = normalizeProjectRecord(await startJob(created.id), ['project_id'])
        jobs.value = [started, ...jobs.value.filter((job) => job.id !== started.id)]
        closeCreateDialog()
        router.push({ name: 'job-detail', params: { id: started.id } })
        return
      } catch (err) {
        jobs.value = [created, ...jobs.value.filter((job) => job.id !== created.id)]
        closeCreateDialog()
        pageError.value = buildJobError(err) || t('jobs.autoStartFailed')
        return
      }
    }

    jobs.value = [created, ...jobs.value.filter((job) => job.id !== created.id)]
    closeCreateDialog()
    router.push({ name: 'job-detail', params: { id: created.id } })
  } catch (err) {
    createDialogError.value = buildJobError(err)
  } finally {
    saving.value = false
  }
}

function openCreateDialog(event) {
  createDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  resetForm()
  createDialogError.value = ''
  showCreateDialog.value = true
  void loadSupportingData()
}

function closeCreateDialog() {
  showCreateDialog.value = false
  createDialogError.value = ''
  resetForm()
}

function handleCreateDialogKeydown(event) {
  if (!showCreateDialog.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeCreateDialog()
    return
  }
  if (event.key === 'Tab') {
    trapFocusWithin(event, createDialogRef.value)
  }
}

watch(
  () => form.value.project_id,
  (value) => {
    const normalized = normalizeProjectId(value)
    if (value !== normalized) {
      form.value.project_id = normalized
      return
    }
    syncEligibleSelections()
  },
)

watch(showArchivedJobs, async (nextValue) => {
  page.value = 1
  await loadJobs()
})

watch(showCreateDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleCreateDialogKeydown)
    await nextTick()
    const target = createDialogRef.value?.querySelector('#job-project')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  document.removeEventListener('keydown', handleCreateDialogKeydown)
  const trigger = createDialogTriggerRef.value
  createDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(jobs, () => {
  syncJobsRefreshTimer()
  if (pausePendingJobId.value == null) return
  const status = normalizeJobStatus(pausePendingJob.value?.status)
  if (!status || status !== 'PAUSING') {
    pausePendingJobId.value = null
    showPausePendingDialog.value = false
  }
})

onMounted(async () => {
  syncViewportState()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    if (!mobileViewportQuery) {
      mobileViewportQuery = window.matchMedia('(max-width: 768px)')
    }
    mobileViewportQuery.addEventListener('change', syncViewportState)
  }

  await Promise.all([loadJobs(), loadSupportingData()])
  syncJobsRefreshTimer()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleCreateDialogKeydown)
  stopJobsRefreshTimer()
  mobileViewportQuery?.removeEventListener('change', syncViewportState)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('jobs.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadJobs">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" :disabled="!canOperate" @click="openCreateDialog">
          {{ t('jobs.create') }}
        </button>
      </div>
    </header>

    <p v-if="pageError" class="error-banner" role="alert" aria-live="assertive">{{ pageError }}</p>
    <p v-if="pageInfo" class="info-banner" role="status" aria-live="polite">{{ pageInfo }}</p>
    <p v-if="compatibilityNote" class="muted">{{ compatibilityNote }}</p>

    <div class="filters">
      <input v-model="search" type="text" :placeholder="t('jobs.searchPlaceholder')" :aria-label="t('jobs.searchPlaceholder')" />
      <select v-model="statusFilter" :aria-label="t('common.labels.status')">
        <option value="ALL">{{ t('jobs.allStatuses') }}</option>
        <option value="PENDING">{{ t('jobs.statuses.pending') }}</option>
        <option value="RUNNING">{{ t('jobs.statuses.running') }}</option>
        <option value="PAUSING">{{ t('jobs.statuses.pausing') }}</option>
        <option value="PAUSED">{{ t('jobs.statuses.paused') }}</option>
        <option value="VERIFYING">{{ t('jobs.statuses.verifying') }}</option>
        <option value="COMPLETED">{{ t('jobs.statuses.completed') }}</option>
        <option value="FAILED">{{ t('jobs.statuses.failed') }}</option>
      </select>
      <label class="jobs-show-archived-toggle" for="jobs-show-archived">
        <input id="jobs-show-archived" v-model="showArchivedJobs" type="checkbox" />
        {{ t('jobs.showArchivedJobs') }}
      </label>
    </div>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('jobs.empty')">
      <template #cell-project_id="{ row }">{{ formatProjectId(row.project_id) }}</template>
      <template #cell-device="{ row }">{{ formatJobDevice(row) }}</template>
      <template #cell-status="{ row }">
        <span
          v-if="isMobileViewport"
          class="job-status-icon"
          :class="`job-status-icon--${jobStatusTone(row.status)}`"
          :aria-label="jobStatusLabel(row.status)"
          :title="jobStatusLabel(row.status)"
          role="img"
        >
          <span aria-hidden="true">{{ jobStatusIcon(row.status) }}</span>
        </span>
        <StatusBadge v-else :status="row.status" :label="jobStatusLabel(row.status)" />
      </template>
      <template #cell-progress="{ row }">{{ progressLabel(row) }}</template>
      <template #cell-actions="{ row }">
        <div v-if="!isMobileViewport" class="row-actions">
          <button class="btn" @click="openJobDetails(row)">
            {{ t('jobs.details') }}
          </button>
          <button class="btn" :disabled="!canStartJob(row) || isRowActionBusy(row)" @click="runJobAction(row, 'start')">
            {{ t('jobs.start') }}
          </button>
          <button class="btn" :disabled="!canPauseJob(row) || isRowActionBusy(row)" @click="runJobAction(row, 'pause')">
            {{ t('jobs.pause') }}
          </button>
        </div>
        <details v-else class="row-actions-menu">
          <summary class="row-actions-toggle" :aria-label="`${formatProjectId(row.project_id)} job actions`">
            <span class="row-actions-toggle-dots" aria-hidden="true">
              <span class="row-actions-toggle-dot" />
              <span class="row-actions-toggle-dot" />
              <span class="row-actions-toggle-dot" />
            </span>
          </summary>
          <div class="row-actions-popover">
            <button class="btn row-action-menu-details" @click="openJobDetails(row, $event)">
              {{ t('jobs.details') }}
            </button>
            <button
              class="btn row-action-menu-start"
              :disabled="!canStartJob(row) || isRowActionBusy(row)"
              @click="handleMenuStart(row, $event)"
            >
              {{ t('jobs.start') }}
            </button>
            <button
              class="btn row-action-menu-pause"
              :disabled="!canPauseJob(row) || isRowActionBusy(row)"
              @click="handleMenuPause(row, $event)"
            >
              {{ t('jobs.pause') }}
            </button>
          </div>
        </details>
      </template>
    </DataTable>

    <Pagination v-model:page="page" :page-size="pageSize" :total="filtered.length" />

    <teleport to="body">
      <div v-if="showPausePendingDialog" class="dialog-overlay" @click.self="showPausePendingDialog = false">
        <div class="dialog-panel pause-wait-dialog" role="dialog" aria-modal="true" aria-labelledby="pause-wait-title">
          <h2 id="pause-wait-title">{{ t('jobs.pauseRequestedTitle') }}</h2>
          <p>{{ t('jobs.pauseRequestedMessage') }}</p>
          <p v-if="pausePendingJob" class="muted">#{{ pausePendingJob.id }} • {{ jobStatusLabel(pausePendingJob.status) }}</p>
          <div class="dialog-actions">
            <button class="btn" @click="showPausePendingDialog = false">{{ t('common.actions.close') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showCreateDialog" class="dialog-overlay" @click.self="closeCreateDialog">
        <div ref="createDialogRef" class="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="job-create-title">
          <div class="dialog-header job-create-summary">
            <h2 id="job-create-title">{{ t('jobs.createDialog') }}</h2>
            <p class="muted">{{ t('jobs.dialogDescription') }}</p>
            <p v-if="createDialogError" class="error-banner dialog-error-banner" role="alert" aria-live="assertive">{{ createDialogError }}</p>
            <p v-if="!availableProjects.length" class="muted">{{ t('jobs.noProjectsAvailable') }}</p>
            <p v-else-if="projectSelected && !eligibleMounts.length" class="muted">{{ t('jobs.noEligibleMounts') }}</p>
            <p v-else-if="projectSelected && !eligibleDrives.length" class="muted">{{ t('jobs.noEligibleDrives') }}</p>
          </div>

          <div class="dialog-body job-create-scroll-region">
            <div class="dialog-groups">
              <fieldset class="dialog-group">
                <legend>{{ t('jobs.jobDetailsGroup') }}</legend>

                <label for="job-project">{{ t('dashboard.project') }}</label>
                <select id="job-project" v-model="form.project_id">
                  <option value="">{{ t('jobs.chooseProject') }}</option>
                  <option v-for="project in availableProjects" :key="project" :value="project">{{ project }}</option>
                </select>

                <label for="job-evidence">{{ t('jobs.evidence') }}</label>
                <input id="job-evidence" v-model="form.evidence_number" type="text" :disabled="!projectSelected" />

                <label for="job-notes">{{ t('jobs.additionalNotes') }}</label>
                <textarea id="job-notes" v-model="form.notes" rows="3" :disabled="!projectSelected" :placeholder="t('jobs.notesHint')"></textarea>

                <label for="job-thread-count">{{ t('jobs.threadCount') }}</label>
                <input id="job-thread-count" v-model.number="form.thread_count" type="number" min="1" max="8" :disabled="!projectSelected" />
              </fieldset>

              <fieldset class="dialog-group">
                <legend>{{ t('jobs.sourceGroup') }}</legend>

                <label for="job-mount">{{ t('jobs.selectMount') }}</label>
                <select id="job-mount" v-model="form.mount_id" :disabled="!projectSelected">
                  <option :value="null">{{ t('jobs.chooseMount') }}</option>
                  <option v-for="mount in eligibleMounts" :key="mount.id" :value="mount.id">
                    {{ formatMountLabel(mount) }}
                  </option>
                </select>

                <label for="job-source-path">{{ t('jobs.sourcePath') }}</label>
                <input id="job-source-path" v-model="form.source_path" type="text" :disabled="!projectSelected" :placeholder="t('jobs.sourcePathHint')" />
              </fieldset>

              <fieldset class="dialog-group">
                <legend>{{ t('jobs.destinationGroup') }}</legend>

                <label for="job-drive">{{ t('jobs.selectDrive') }}</label>
                <select id="job-drive" v-model="form.drive_id" :disabled="!projectSelected">
                  <option :value="null">{{ t('jobs.chooseDrive') }}</option>
                  <option v-for="drive in eligibleDrives" :key="drive.id" :value="drive.id">
                    {{ formatDriveLabel(drive) }}
                  </option>
                </select>
              </fieldset>

              <fieldset class="dialog-group">
                <legend>{{ t('jobs.executionGroup') }}</legend>
                <label class="checkbox-row" for="job-run-immediately">
                  <input id="job-run-immediately" v-model="form.run_immediately" type="checkbox" :disabled="!projectSelected" />
                  <span>{{ t('jobs.runImmediately') }}</span>
                </label>
              </fieldset>
            </div>
          </div>

          <div class="dialog-actions dialog-footer">
            <button class="btn" @click="closeCreateDialog">{{ t('common.actions.cancel') }}</button>
            <button id="job-submit" class="btn btn-primary" :disabled="saving || !formReady()" @click="submitCreateJob">
              {{ saving ? t('common.labels.loading') : t('jobs.create') }}
            </button>
          </div>
        </div>
      </div>
    </teleport>
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
  justify-content: space-between;
  align-items: center;
}

.filters {
  flex-wrap: wrap;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-sm);
}

.job-status-icon {
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

.job-status-icon--success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.job-status-icon--warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.job-status-icon--danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.job-status-icon--info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.job-status-icon--muted {
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

.row-actions :deep(.btn),
.row-actions .btn {
  min-width: 5.75rem;
}

input,
select,
textarea {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

textarea {
  resize: vertical;
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.info-banner {
  color: var(--color-alert-success-text);
  background: var(--color-alert-success-bg);
  border: 1px solid var(--color-alert-success-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
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
  overflow: hidden;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
  display: grid;
  gap: var(--space-md);
  grid-template-rows: auto minmax(0, 1fr) auto;
}

.dialog-header,
.dialog-footer {
  flex-shrink: 0;
}

.dialog-body {
  min-height: 0;
  overflow-y: auto;
  padding-right: var(--space-xs);
}

.job-create-summary {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--color-bg-secondary);
  padding-bottom: var(--space-xs);
  border-bottom: 1px solid var(--color-border);
}

.dialog-error-banner {
  margin: 0;
}

.job-create-scroll-region {
  display: grid;
}

.dialog-groups {
  display: grid;
  gap: var(--space-md);
  grid-template-columns: repeat(2, minmax(0, 1fr));
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

.checkbox-row {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

@media (max-width: 768px) {
  .row-actions {
    display: none;
  }

  .row-actions-menu {
    display: inline-block;
  }

  .dialog-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .dialog-groups {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
