<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { analyzeJob, archiveJob, continueJobOverflow, getJob, getJobChainOfCustody, refreshJobChainOfCustody, getJobFiles, startJob, retryFailedJob, pauseJob, verifyJob, downloadManifest, updateJob, completeJob, deleteJob, clearJobStartupAnalysisCache, confirmJobChainOfCustodyHandoff } from '@/api/jobs.js'
import { getFileHashes, compareFiles } from '@/api/files.js'
import { getDrives } from '@/api/drives.js'
import { getShares } from '@/api/shares.js'
import { usePolling } from '@/composables/usePolling.js'
import CocReport from '@/components/audit/CocReport.vue'
import JobEditorDialogContent from '@/components/jobs/JobEditorDialogContent.vue'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { formatDriveIdentity } from '@/utils/driveIdentity.js'
import { buildJobErrorMessage } from '@/utils/jobErrors.js'
import { canEditJob, canOperateOnInactiveJob, canReadJobCoc, getDashboardFollowUpKey, getDashboardNextStepKey, getJobDetailPrimaryActionKeys, getJobLifecycleToggleAction } from '@/utils/jobActions.js'
import { calculateJobProgress, isJobProgressActive } from '@/utils/jobProgress.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()
const COC_PRINT_BODY_CLASS = 'printing-coc-report'
const THREAD_COUNT_OPTIONS = Array.from({ length: 16 }, (_unused, index) => index + 1)

const jobId = computed(() => {
  const parsed = Number(route.params.id)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
})

const DEFAULT_JOB_FILES_PAGE_SIZE = 40

const job = ref(null)
const debug = ref({ files: [], total_files: 0, returned_files: 0, page: 1, page_size: DEFAULT_JOB_FILES_PAGE_SIZE })
const loading = ref(false)
const filesLoading = ref(false)
let latestDebugRequestId = 0
const acting = ref(false)
const error = ref('')
const infoMessage = ref('')
const currentTimeMs = ref(Date.now())
let currentTimeIntervalId = null
const isMobileViewport = ref(false)
let mobileViewportQuery = null

const selectedFileId = ref(null)
const fileHashes = ref(null)
const compareFileId = ref(null)
const compareResult = ref(null)
const selectedHashFileMeta = ref(null)
const supportingDrives = ref([])
const supportingMounts = ref([])
const filesPanelExpanded = ref(false)
const showEditDialog = ref(false)
const showEditSourceBrowser = ref(false)
const showDeleteDialog = ref(false)
const showArchiveDialog = ref(false)
const showStartupAnalysisCleanupDialog = ref(false)
const showOverflowDialog = ref(false)
const showPausePendingDialog = ref(false)
const showCocDialog = ref(false)
const showCocHandoffDialog = ref(false)
const showCocHandoffWarning = ref(false)
const showHashDialog = ref(false)
const showFileErrorDialog = ref(false)
const cocDialogRef = ref(null)
const cocHandoffDialogRef = ref(null)
const editDialogRef = ref(null)
const pauseDialogRef = ref(null)
const overflowDialogRef = ref(null)
const hashDialogRef = ref(null)
const fileErrorDialogRef = ref(null)
const cocDialogTriggerRef = ref(null)
const cocHandoffDialogTriggerRef = ref(null)
const dialogTriggerRef = ref(null)
const hashDialogTriggerRef = ref(null)
const fileErrorDialogTriggerRef = ref(null)
const selectedErrorFile = ref(null)

const editForm = ref({
  project_id: '',
  evidence_number: '',
  notes: '',
  mount_id: null,
  source_path: '/',
  drive_id: null,
  overflow_drive_ids: [],
  thread_count: 4,
  copy_chunk_size_bytes: null,
  copy_progress_flush_bytes: null,
  copy_file_fsync_enabled: null,
  callback_url: '',
})

const overflowForm = ref({
  drive_id: null,
  thread_count: null,
})

const cocLoading = ref(false)
const cocError = ref('')
const cocHandoffError = ref('')
const cocStatusMessage = ref('')
const cocGeneratedAt = ref('')
const cocReport = ref(null)
const handoffSaving = ref(false)
const showCocHandoffErrorDialog = ref(false)
const cocHandoffForm = ref({
  drive_id: '',
  project_id: '',
  evidence_number: '',
  possessor: '',
  delivery_time: '',
  received_by: '',
  receipt_ref: '',
  notes: '',
})

const canOperate = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor']))
const canArchiveJobs = computed(() => authStore.hasAnyRole(['admin', 'manager']))
const canManageStartupAnalysis = computed(() => authStore.hasAnyRole(['admin', 'manager']))
const canInspectHashes = computed(() => authStore.hasAnyRole(['admin', 'auditor']))
const hasCocAccess = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor', 'auditor']))
const currentStatus = computed(() => String(job.value?.status || '').toUpperCase())
const canReadCoc = computed(() => canReadJobCoc({
  hasAccess: hasCocAccess.value,
  jobStatus: currentStatus.value,
}))
const hasPendingCocHandoff = computed(() => (cocReport.value?.reports || []).some((report) => !report?.custody_complete))
const canRefreshCoc = computed(() => authStore.hasAnyRole(['admin', 'manager'])
  && currentStatus.value !== 'ARCHIVED'
  && (!cocReport.value || hasPendingCocHandoff.value))
const canConfirmCocHandoff = computed(() => authStore.hasAnyRole(['admin', 'manager'])
  && currentStatus.value !== 'ARCHIVED'
  && hasPendingCocHandoff.value)
const currentStartupAnalysisStatus = computed(() => String(job.value?.startup_analysis_status || 'NOT_ANALYZED').toUpperCase())
const archiveRelatedDrive = computed(() => {
  const drive = job.value?.drive
  if (!drive) return null

  const jobProjectId = normalizeProjectId(job.value?.project_id)
  const driveProjectId = normalizeProjectId(drive?.current_project_id)

  if (!jobProjectId || !driveProjectId || driveProjectId !== jobProjectId) {
    return null
  }

  return drive
})
const archiveDriveReady = computed(() => {
  const driveState = String(archiveRelatedDrive.value?.current_state || '').toUpperCase()
  return !archiveRelatedDrive.value || (driveState === 'AVAILABLE' && !archiveRelatedDrive.value?.is_mounted)
})
const archiveBlockedByDriveEject = computed(() => canArchiveJobs.value
  && ['COMPLETED', 'FAILED'].includes(currentStatus.value)
  && !!archiveRelatedDrive.value
  && !archiveDriveReady.value)
const archivePrerequisiteNotice = computed(() => (archiveBlockedByDriveEject.value ? t('jobs.archiveRequiresEject') : ''))
const canArchive = computed(() => canArchiveJobs.value
  && ['COMPLETED', 'FAILED'].includes(currentStatus.value)
  && archiveDriveReady.value)

function normalizeFileStatus(status) {
  return String(status || '').toUpperCase()
}

function fileStatusTone(status) {
  const value = normalizeFileStatus(status)

  if (['DONE', 'COMPLETED', 'COPIED', 'VERIFIED', 'OK', 'TRUE'].includes(value)) {
    return 'success'
  }
  if (['FAILED', 'ERROR', 'MISSING', 'SKIPPED', 'FALSE'].includes(value)) {
    return 'danger'
  }
  if (['RUNNING', 'COPYING', 'VERIFYING', 'HASHING', 'PAUSING'].includes(value)) {
    return 'warning'
  }
  if (['PENDING', 'PAUSED', 'QUEUED', 'UNKNOWN'].includes(value)) {
    return 'muted'
  }

  return 'info'
}

function fileStatusIcon(status) {
  const tone = fileStatusTone(status)

  if (tone === 'success') return '✓'
  if (tone === 'warning') return '!'
  if (tone === 'danger') return '×'
  if (tone === 'muted') return '•'
  return '?'
}

function fileErrorMessage(row) {
  return String(row?.error_message || '').trim()
}

function hasFileError(row) {
  return fileErrorMessage(row).length > 0
}

function fileRowClass(row) {
  return hasFileError(row) ? 'job-file-row-error' : ''
}

function fileErrorPreview(row) {
  const message = fileErrorMessage(row)
  if (!message) return '-'
  if (message.length <= 120) return message
  return `${message.slice(0, 117)}...`
}

const canEdit = computed(() => {
  return canEditJob({
    canOperate: canOperate.value,
    jobStatus: currentStatus.value,
    startupAnalysisStatus: currentStartupAnalysisStatus.value,
  })
})
const startedJobEditMode = computed(() => canEdit.value && currentStatus.value !== 'PENDING')
const canComplete = computed(() => {
  return canOperateOnInactiveJob({
    canOperate: canOperate.value,
    jobStatus: currentStatus.value,
    startupAnalysisStatus: currentStartupAnalysisStatus.value,
  })
})
const showDelete = computed(() => canOperate.value && currentStatus.value === 'PENDING')
const canDelete = computed(() => {
  return canOperate.value
    && currentStatus.value === 'PENDING'
    && currentStartupAnalysisStatus.value !== 'ANALYZING'
})
const canAnalyze = computed(() => {
  return canOperateOnInactiveJob({
    canOperate: canOperate.value,
    jobStatus: currentStatus.value,
    startupAnalysisStatus: currentStartupAnalysisStatus.value,
  })
})
const showClearStartupAnalysisCache = computed(() => {
  return canManageStartupAnalysis.value && !!job.value?.startup_analysis_cached
})
const canClearStartupAnalysisCache = computed(() => {
  return canManageStartupAnalysis.value
    && !!job.value?.startup_analysis_cached
    && currentStartupAnalysisStatus.value !== 'ANALYZING'
})

const startupAnalysisSummary = computed(() => {
  if (!job.value) return null
  const rawStatus = String(job.value.startup_analysis_status || 'NOT_ANALYZED').toUpperCase()
  const lastAnalyzedAt = formatTimestamp(job.value.startup_analysis_last_analyzed_at)
  return {
    status: rawStatus,
    statusLabel: t(`jobs.analysisStates.${rawStatus}`),
    lastAnalyzedAt,
    discoveredFiles: Number(job.value.startup_analysis_file_count || 0),
    estimatedBytes: formatBytes(Number(job.value.startup_analysis_total_bytes || 0)),
    readyToStart: !!job.value.startup_analysis_ready,
    failureReason: normalizeStartupAnalysisFailureReason(job.value.startup_analysis_failure_reason),
  }
})

const sourceFilesToCopyLabel = computed(() => {
  if (!job.value) return t('common.labels.notAvailable')

  const lastAnalyzedAt = job.value.startup_analysis_last_analyzed_at
  if (lastAnalyzedAt) {
    return String(Number(job.value.startup_analysis_file_count || 0))
  }

  const status = currentStatus.value
  const fileCount = Number(job.value.file_count || 0)
  if (['RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING', 'COMPLETED', 'FAILED', 'ARCHIVED'].includes(status)) {
    return String(fileCount)
  }

  return t('common.labels.notAvailable')
})

const sourceSizeToCopyLabel = computed(() => {
  if (!job.value) return t('common.labels.notAvailable')

  const lastAnalyzedAt = job.value.startup_analysis_last_analyzed_at
  if (lastAnalyzedAt) {
    return formatBytes(Number(job.value.startup_analysis_total_bytes || 0))
  }

  const status = currentStatus.value
  if (['RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING', 'COMPLETED', 'FAILED', 'ARCHIVED'].includes(status)) {
    return formatBytes(Number(job.value.total_bytes || 0))
  }

  return t('common.labels.notAvailable')
})

const fileColumns = computed(() => ([
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'relative_path', label: t('jobs.path'), width: isMobileViewport.value ? '12rem' : null },
  { key: 'destination_drive_label', label: t('jobs.destinationDrive') },
  { key: 'status', label: t('common.labels.status'), align: 'center' },
]))

const retryableFileCount = computed(() => Number(job.value?.files_failed || 0) + Number(job.value?.files_timed_out || 0))
const fileListRefreshKey = computed(() => ([
  Number(job.value?.file_count || 0),
  Number(job.value?.files_succeeded || 0),
  Number(job.value?.files_failed || 0),
  Number(job.value?.files_timed_out || 0),
  String(job.value?.status || '').toUpperCase(),
].join(':')))

const canContinueOverflow = computed(() => {
  const status = String(job.value?.status || '').toUpperCase()
  if (!canOperate.value || currentStartupAnalysisStatus.value === 'ANALYZING') return false
  if (status === 'COMPLETED') return retryableFileCount.value > 0
  return ['PENDING', 'FAILED', 'PAUSED'].includes(status)
})

const overflowEligibleDrives = computed(() => {
  const projectId = normalizeProjectId(job.value?.project_id)
  const activeDriveId = Number(job.value?.drive?.id || 0)
  if (!projectId) return []
  return supportingDrives.value.filter((drive) => {
    const state = String(drive?.current_state || '').toUpperCase()
    const boundProject = normalizeProjectId(drive?.current_project_id)
    return Number(drive?.id) !== activeDriveId
      && state === 'AVAILABLE'
      && !!drive?.mount_path
      && boundProject === projectId
  })
})

const jobFailureReason = computed(() => {
  if (!job.value) return ''
  const status = String(job.value.status || '').toUpperCase()
  if (status !== 'FAILED') return ''

  const persistedReason = String(job.value.failure_reason || '').trim()
  if (persistedReason) return persistedReason

  const summary = String(job.value.error_summary || '').trim()
  if (summary) return summary

  return t('jobs.failureReasonFallback')
})

const fileListNotice = computed(() => {
  const total = Number(debug.value.total_files || 0)
  const shown = Number(debug.value.returned_files || 0)
  if (total === 0 || shown === 0) return ''
  const page = Number(debug.value.page || 1)
  const pageSize = Number(debug.value.page_size || DEFAULT_JOB_FILES_PAGE_SIZE)
  const start = (page - 1) * pageSize + 1
  const end = Math.min(start + shown - 1, total)
  return t('jobs.showingFiles', { start, end, total })
})

const selectedCompareFile = computed(() => (
  (debug.value.files || []).find((file) => Number(file.id) === Number(compareFileId.value)) || null
))

const selectedHashFile = computed(() => {
  const currentPageFile = (debug.value.files || []).find((file) => Number(file.id) === Number(selectedFileId.value))
  if (currentPageFile) {
    return currentPageFile
  }
  return selectedHashFileMeta.value
})

const progressMetrics = computed(() => {
  const metrics = calculateJobProgress(job.value)

  return {
    total: 100,
    value: metrics.percent,
    percent: metrics.percent,
    totalBytes: metrics.totalBytes,
    copiedBytes: metrics.copiedBytes,
    totalFiles: metrics.totalFiles,
    finishedFiles: metrics.finishedFiles,
    initializing: metrics.initializing,
  }
})

const isVerificationState = computed(() => currentStatus.value === 'VERIFYING')

const progressLabel = computed(() => {
  if (isVerificationState.value) {
    return t('jobs.verificationProgressLabel')
  }

  const metrics = progressMetrics.value
  if (metrics.initializing) {
    return t('jobs.progressPreparing')
  }
  if (metrics.totalFiles > 0) {
    return `${metrics.percent}% • ${metrics.finishedFiles}/${metrics.totalFiles} ${t('jobs.files').toLowerCase()}`
  }
  return `${metrics.percent}%`
})

const progressActive = computed(() => {
  return isJobProgressActive(job.value)
})

const currentTaskSummary = computed(() => {
  if (!job.value) return []

  const entries = [
    {
      label: t('dashboard.nextStep'),
      value: t(getDashboardNextStepKey({
        jobStatus: job.value.status,
        startupAnalysisStatus: job.value.startup_analysis_status,
        custodyStatus: job.value.custody_status,
        failedFiles: job.value.files_failed,
        timedOutFiles: job.value.files_timed_out,
      })),
    },
  ]

  const followUpKey = getDashboardFollowUpKey({
    jobStatus: job.value.status,
    startupAnalysisStatus: job.value.startup_analysis_status,
    custodyStatus: job.value.custody_status,
  })

  if (followUpKey) {
    entries.push({
      label: t('dashboard.attentionType'),
      value: t(followUpKey),
    })
  }

  const failedFiles = Number(job.value.files_failed || 0)
  const timedOutFiles = Number(job.value.files_timed_out || 0)

  if (failedFiles > 0) {
    entries.push({ label: t('jobs.filesFailed'), value: String(failedFiles) })
  }
  if (timedOutFiles > 0) {
    entries.push({ label: t('jobs.filesTimedOut'), value: String(timedOutFiles) })
  }

  if (liveTransferSummary.value) {
    entries.push(
      { label: t('jobs.startedAt'), value: liveTransferSummary.value.startedAt },
      { label: t('jobs.duration'), value: liveTransferSummary.value.duration },
      { label: t('jobs.copyRate'), value: liveTransferSummary.value.copyRate },
      { label: t('jobs.timeRemaining'), value: liveTransferSummary.value.timeRemaining },
      { label: t('jobs.estimatedCompletion'), value: liveTransferSummary.value.estimatedCompletion },
    )
  }

  return entries
})

const destinationFilesCopiedLabel = computed(() => {
  if (!job.value) return '-'

  const finishedFiles = Number(progressMetrics.value.finishedFiles || 0)
  const totalFiles = Number(progressMetrics.value.totalFiles || 0)
  if (totalFiles > 0) {
    return `${finishedFiles} of ${totalFiles}`
  }
  if (Number.isFinite(finishedFiles) && finishedFiles > 0) {
    return String(finishedFiles)
  }
  return '-'
})

const completionPanelRows = computed(() => {
  return [
    { label: t('jobs.startedAt'), value: completionSummary.value?.startedAt || '-' },
    { label: t('jobs.copyThreads'), value: completionSummary.value?.copyThreads ?? '-' },
    {
      label: t('jobs.filesCopied'),
      value: completionSummary.value
        ? `${completionSummary.value.filesCopied} of ${completionSummary.value.totalFiles}`
        : destinationFilesCopiedLabel.value,
    },
    { label: t('jobs.filesFailed'), value: completionSummary.value?.filesFailed ?? Number(job.value?.files_failed || 0) },
    { label: t('jobs.filesTimedOut'), value: completionSummary.value?.filesTimedOut ?? Number(job.value?.files_timed_out || 0) },
    { label: t('jobs.totalCopied'), value: completionSummary.value?.totalCopied || formatBytes(Number(job.value?.copied_bytes || 0)) },
    { label: t('jobs.duration'), value: completionSummary.value?.duration || '-' },
    { label: t('jobs.copyRate'), value: completionSummary.value?.copyRate || '-' },
    { label: t('jobs.completedAt'), value: completionSummary.value?.completedAt || '-' },
    { label: t('jobs.lastManifestCreated'), value: manifestSummary.value?.createdAtLabel || '-' },
    { label: t('jobs.manifestStatus'), value: manifestSummary.value?.statusLabel || '-' },
  ]
})

const lifecycleToggleAction = computed(() => {
  const action = getJobLifecycleToggleAction({
    canOperate: canOperate.value,
    jobStatus: currentStatus.value,
    startupAnalysisStatus: currentStartupAnalysisStatus.value,
  })

  if (!action) return null

  return {
    ...action,
    label: t(`jobs.${action.key}`),
  }
})

const canRetryFailed = computed(() => {
  const status = String(job.value?.status || '').toUpperCase()
  return canOperate.value
    && status === 'COMPLETED'
    && currentStartupAnalysisStatus.value !== 'ANALYZING'
    && (Number(job.value?.files_failed || 0) > 0 || Number(job.value?.files_timed_out || 0) > 0)
})

const isJobFullyComplete = computed(() => {
  const status = currentStatus.value
  if (status !== 'COMPLETED') return false
  if (progressMetrics.value.percent < 100) return false
  return Number(job.value?.files_failed || 0) === 0 && Number(job.value?.files_timed_out || 0) === 0
})
const canVerify = computed(() => canOperate.value && isJobFullyComplete.value)
const hasGeneratedManifest = computed(() => Boolean(job.value?.latest_manifest_created_at))
const canDownloadManifest = computed(() => canOperate.value && isJobFullyComplete.value && hasGeneratedManifest.value)

const primaryActionKeys = computed(() => {
  return getJobDetailPrimaryActionKeys({
    jobStatus: currentStatus.value,
    canRetryFailed: canRetryFailed.value,
    canReadCoc: canReadCoc.value,
  })
})

const actionItems = computed(() => {
  const items = [
    {
      key: 'edit',
      label: t('common.actions.edit'),
      disabled: !canEdit.value || acting.value,
      run: () => openEditDialog(),
      visible: canEdit.value,
    },
    {
      key: 'analyze',
      label: t('jobs.analyze'),
      disabled: !canAnalyze.value || acting.value,
      run: () => runAnalyze(),
      visible: true,
    },
    {
      key: 'lifecycle-toggle',
      label: lifecycleToggleAction.value?.label || t('jobs.start'),
      disabled: !lifecycleToggleAction.value?.enabled || acting.value,
      run: () => runAction(lifecycleToggleAction.value?.key),
      visible: lifecycleToggleAction.value != null,
    },
    {
      key: 'overflow',
      label: t('jobs.continueOverflow'),
      disabled: !canContinueOverflow.value || acting.value,
      run: () => openOverflowDialog(),
      visible: true,
    },
    {
      key: 'retry-failed',
      label: t('jobs.retryFailedFiles'),
      disabled: !canRetryFailed.value || acting.value,
      run: () => runAction('retry-failed'),
      visible: true,
    },
    {
      key: 'complete',
      label: t('jobs.complete'),
      disabled: !canComplete.value || acting.value,
      run: () => runComplete(),
      visible: true,
    },
    {
      key: 'verify',
      label: t('jobs.verify'),
      disabled: !canVerify.value || acting.value,
      run: () => runAction('verify'),
      visible: true,
    },
    {
      key: 'manifest',
      label: t('jobs.manifest'),
      disabled: !canDownloadManifest.value || acting.value,
      run: () => runAction('manifest'),
      visible: true,
    },
    {
      key: 'coc',
      label: t('jobs.closeOutWithHandoff'),
      disabled: !canReadCoc.value,
      run: () => openCocDialog(),
      visible: canReadCoc.value,
    },
    {
      key: 'clear-startup-analysis',
      label: t('jobs.clearStartupAnalysis'),
      disabled: !canClearStartupAnalysisCache.value || acting.value,
      run: () => {
        showStartupAnalysisCleanupDialog.value = true
      },
      visible: showClearStartupAnalysisCache.value,
    },
    {
      key: 'archive',
      label: t('jobs.archiveWithoutHandoff'),
      disabled: !canArchive.value || acting.value,
      run: () => {
        showArchiveDialog.value = true
      },
      visible: canArchiveJobs.value && currentStatus.value !== 'ARCHIVED',
      tone: 'danger',
    },
    {
      key: 'delete',
      label: t('common.actions.delete'),
      disabled: !canDelete.value || acting.value,
      run: () => {
        showDeleteDialog.value = true
      },
      visible: showDelete.value,
      tone: 'danger',
    },
  ]

  return items.filter((item) => item.visible)
})

const primaryActions = computed(() => {
  const keys = new Set(primaryActionKeys.value)
  const items = actionItems.value.filter((item) => keys.has(item.key))

  if (items.length > 0) {
    return items
  }

  return actionItems.value.slice(0, 3)
})

const secondaryActions = computed(() => {
  const primaryKeys = new Set(primaryActions.value.map((item) => item.key))
  return actionItems.value.filter((item) => !primaryKeys.has(item.key))
})

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
      && boundProject === projectId
  })
})

const editOverflowEligibleDrives = computed(() => {
  const projectId = normalizeProjectId(editForm.value.project_id)
  const activeDriveId = Number(job.value?.drive?.id || 0)
  const selectedOverflowDriveIds = new Set(
    Array.isArray(editForm.value.overflow_drive_ids)
      ? editForm.value.overflow_drive_ids.map((value) => Number(value)).filter((value) => Number.isInteger(value))
      : [],
  )

  if (!projectId) return []

  return supportingDrives.value.filter((drive) => {
    const driveId = Number(drive?.id || 0)
    const state = String(drive?.current_state || '').toUpperCase()
    const boundProject = normalizeProjectId(drive?.current_project_id)
    return driveId !== activeDriveId
      && !!drive?.mount_path
      && boundProject === projectId
      && (['AVAILABLE', 'IN_USE'].includes(state) || selectedOverflowDriveIds.has(driveId))
  })
})

const editSelectedMountRecord = computed(() => (
  editEligibleMounts.value.find((mount) => Number(mount.id) === Number(editForm.value.mount_id)) || null
))

const canBrowseEditMount = computed(() => Number.isInteger(Number(editSelectedMountRecord.value?.id || NaN)))

function calculateDurationSeconds(currentJob) {
  if (!currentJob) return null

  const status = String(currentJob.status || '').toUpperCase()
  const storedSeconds = Number(currentJob.active_duration_seconds || 0)
  if (['PREPARING', 'RUNNING', 'PAUSING', 'VERIFYING'].includes(status) && currentJob.started_at) {
    const started = new Date(currentJob.started_at)
    if (!Number.isNaN(started.getTime())) {
      const liveSeconds = Math.max(0, Math.round((currentTimeMs.value - started.getTime()) / 1000))
      return storedSeconds + liveSeconds
    }
  }

  if (currentJob.started_at && currentJob.completed_at) {
    const started = new Date(currentJob.started_at)
    const completed = new Date(currentJob.completed_at)
    if (!Number.isNaN(started.getTime()) && !Number.isNaN(completed.getTime())) {
      return Math.max(0, Math.round((completed.getTime() - started.getTime()) / 1000))
    }
  }

  if (storedSeconds > 0) return storedSeconds

  return null
}

function calculateCopyDurationSeconds(currentJob) {
  if (!currentJob) return 0

  const status = String(currentJob.status || '').toUpperCase()
  const storedSeconds = Number(currentJob.active_duration_seconds || 0)
  if (['RUNNING', 'PAUSING'].includes(status) && currentJob.copy_started_at) {
    const started = new Date(currentJob.copy_started_at)
    if (!Number.isNaN(started.getTime())) {
      const liveSeconds = Math.max(0, Math.round((currentTimeMs.value - started.getTime()) / 1000))
      return storedSeconds + liveSeconds
    }
  }

  if (storedSeconds > 0) return storedSeconds
  return 0
}

const liveTransferSummary = computed(() => {
  if (!job.value) return null

  const status = String(job.value.status || '').toUpperCase()
  if (!['RUNNING', 'PAUSING'].includes(status)) return null

  const durationSeconds = calculateDurationSeconds(job.value)
  const copyDurationSeconds = calculateCopyDurationSeconds(job.value)
  const copiedBytes = Number(job.value.copied_bytes || 0)
  const totalBytes = Number(job.value.total_bytes || 0)
  const remainingBytes = Math.max(0, totalBytes - copiedBytes)
  const rateBytesPerSecond = copyDurationSeconds > 0 ? copiedBytes / copyDurationSeconds : 0
  const remainingSeconds = rateBytesPerSecond > 0 && remainingBytes > 0
    ? Math.ceil(remainingBytes / rateBytesPerSecond)
    : null

  return {
    startedAt: formatTimestamp(job.value.started_at),
    duration: formatDuration(durationSeconds),
    copyRate: formatCopyRate(copiedBytes, copyDurationSeconds),
    timeRemaining: formatDuration(remainingSeconds),
    estimatedCompletion: remainingSeconds != null
      ? formatTimestamp(new Date(currentTimeMs.value + (remainingSeconds * 1000)).toISOString())
      : '-',
  }
})

const completionSummary = computed(() => {
  if (!job.value) return null
  const status = String(job.value.status || '').toUpperCase()
  if (status !== 'COMPLETED' && status !== 'FAILED' && status !== 'PAUSED') return null

  const durationSeconds = calculateDurationSeconds(job.value)
  const copyDurationSeconds = calculateCopyDurationSeconds(job.value)

  return {
    startedAt: formatTimestamp(job.value.started_at),
    copyThreads: Number(getEffectiveThreadCount(job.value) || 0),
    filesCopied: Number(job.value.files_succeeded || 0),
    filesFailed: Number(job.value.files_failed || 0),
    filesTimedOut: Number(job.value.files_timed_out || 0),
    totalFiles: Number(job.value.file_count || 0),
    totalCopied: formatBytes(Number(job.value.copied_bytes || 0)),
    duration: formatDuration(durationSeconds),
    copyRate: formatCopyRate(Number(job.value.copied_bytes || 0), copyDurationSeconds),
    completedAt: formatTimestamp(job.value.completed_at),
  }
})

const completionSummaryHasFailures = computed(() => {
  if (!completionSummary.value) return false
  return completionSummary.value.filesFailed > 0 || completionSummary.value.filesTimedOut > 0
})

const overflowAssignments = computed(() => {
  if (!Array.isArray(job.value?.overflow_assignments)) return []
  return job.value.overflow_assignments
})

const reservedOverflowAssignments = computed(() => {
  return overflowAssignments.value.filter((assignment) => String(assignment?.state || '').toUpperCase() === 'RESERVED')
})

const manifestSummary = computed(() => {
  if (!completionSummary.value || !job.value) return null

  const latestManifestCreatedAt = job.value.latest_manifest_created_at
  if (!latestManifestCreatedAt) {
    return {
      createdAtLabel: t('jobs.manifestNeverGenerated'),
      statusLabel: t('jobs.manifestStatusMissing'),
      tone: 'muted',
    }
  }

  const manifestCreatedAt = new Date(latestManifestCreatedAt)
  const completedAt = job.value.completed_at ? new Date(job.value.completed_at) : null
  const hasValidManifestTime = !Number.isNaN(manifestCreatedAt.getTime())
  const hasValidCompletedTime = completedAt && !Number.isNaN(completedAt.getTime())
  const isStale = Boolean(hasValidManifestTime && hasValidCompletedTime && manifestCreatedAt.getTime() < completedAt.getTime())

  return {
    createdAtLabel: formatTimestamp(latestManifestCreatedAt),
    statusLabel: isStale ? t('jobs.manifestStatusStale') : t('jobs.manifestStatusCurrent'),
    tone: isStale ? 'danger' : 'success',
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

function getJobThreadCountOverride(record) {
  if (!record) return null
  if (record.thread_count_override != null) return Number(record.thread_count_override)
  if (Object.prototype.hasOwnProperty.call(record, 'thread_count_source')) {
    return String(record.thread_count_source || '').toLowerCase() === 'job' ? Number(record.thread_count) : null
  }
  return record.thread_count != null ? Number(record.thread_count) : null
}

function getEffectiveThreadCount(record) {
  if (!record) return null
  if (record.effective_thread_count != null) return Number(record.effective_thread_count)
  return record.thread_count != null ? Number(record.thread_count) : null
}

function copyTuningSourceLabel(source) {
  return String(source || '').toLowerCase() === 'job'
    ? t('jobs.copyTuningSourceJob')
    : t('jobs.copyTuningSourceDefault')
}

function formatCopyTuningBytes(value, source) {
  if (value == null) return '-'
  return `${formatBytes(Number(value))} (${copyTuningSourceLabel(source)})`
}

function formatCopyTuningBoolean(value, source) {
  if (value == null) return '-'
  const label = value ? t('common.labels.enabled') : t('common.labels.disabled')
  return `${label} (${copyTuningSourceLabel(source)})`
}

function formatTimestamp(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString()
}

function localDateTimeAsUtcIso(value) {
  if (!value) return undefined
  return new Date(value).toISOString()
}

function isoToLocalDateTimeValue(value) {
  const parsed = value ? new Date(value) : new Date()
  if (Number.isNaN(parsed.getTime())) return ''
  const offsetMinutes = parsed.getTimezoneOffset()
  const local = new Date(parsed.getTime() - (offsetMinutes * 60 * 1000))
  return local.toISOString().slice(0, 16)
}

function normalizeStartupAnalysisFailureReason(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''

  const labelPrefix = `${t('jobs.analysisFailureReason')}:`
  let normalized = raw
  while (normalized.startsWith(labelPrefix)) {
    normalized = normalized.slice(labelPrefix.length).trim()
  }
  return normalized
}

function formatDuration(totalSeconds) {
  if (typeof totalSeconds !== 'number' || totalSeconds < 0) return '-'
  if (totalSeconds === 0) return '0s'

  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function formatTransferRate(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '-'
  return `${value.toFixed(1)} MB/s`
}

function formatCopyRate(bytesValue, totalSeconds) {
  if (typeof bytesValue !== 'number' || bytesValue < 0 || typeof totalSeconds !== 'number') return '-'
  if (totalSeconds <= 0 || bytesValue === 0) return '0.0 MB/s'

  const mbPerSecond = bytesValue / (1024 * 1024) / totalSeconds
  return `${mbPerSecond.toFixed(1)} MB/s`
}

function formatDriveLabel(drive) {
  return formatDriveIdentity(drive)
}

function overflowAssignmentStateLabel(state) {
  const normalized = String(state || 'RESERVED').toUpperCase()
  return t(`jobs.overflowAssignmentStates.${normalized}`)
}

function overflowAssignmentDriveLabel(assignment) {
  if (assignment?.drive) {
    return formatDriveLabel(assignment.drive)
  }
  const driveId = Number(assignment?.drive_id || 0)
  return driveId > 0 ? `#${driveId}` : '-'
}

function formatMountLabel(mount) {
  return mount?.remote_path || t('jobs.chooseMount')
}

function resolveJobDestinationLabel(currentJob) {
  const driveId = Number(currentJob?.drive?.id)
  const targetPath = String(currentJob?.target_mount_path || '').trim()
  const matchedDrive = supportingDrives.value.find((drive) => {
    if (Number.isInteger(driveId) && driveId > 0 && Number(drive?.id) === driveId) {
      return true
    }
    return targetPath && String(drive?.mount_path || '').trim() === targetPath
  })

  if (matchedDrive) {
    return formatDriveIdentity(matchedDrive)
  }
  return targetPath || '-'
}

function buildManifestPath(currentJob) {
  const targetPath = String(currentJob?.target_mount_path || '').trim().replace(/\/+$/, '')
  if (!targetPath) return ''
  return `${targetPath}/manifest.json`
}

function extractDownloadFilename(response, fallback = 'manifest.json') {
  const contentDisposition = response?.headers?.['content-disposition'] || response?.headers?.['Content-Disposition']
  if (!contentDisposition) return fallback

  const match = String(contentDisposition).match(/filename="?([^";]+)"?/i)
  return match?.[1] || fallback
}

async function downloadGeneratedManifest(jobId) {
  const response = await downloadManifest(jobId)
  const contentType = response?.headers?.['content-type'] || response?.headers?.['Content-Type'] || 'application/json'
  const blob = response?.data instanceof Blob ? response.data : new Blob([response?.data], { type: contentType })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = extractDownloadFilename(response)
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

function saveJobCocReport() {
  if (!cocReport.value) return
  const blob = new Blob([JSON.stringify(cocReport.value, null, 2)], { type: 'application/json;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `chain-of-custody-job-${job.value?.id || 'unknown'}.json`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function saveJobCocCsvReport() {
  if (!cocReport.value?.reports?.length) return

  const header = ['event_id', 'drive_sn', 'drive_manufacturer', 'drive_model', 'timestamp', 'actor', 'action', 'event_type', 'details']
  const rows = cocReport.value.reports.flatMap((report) =>
    (report.chain_of_custody_events || []).map((event) => ({
      event_id: event.event_id ?? '',
      drive_sn: report.drive_sn || '',
      drive_manufacturer: report.drive_manufacturer || '',
      drive_model: report.drive_model || '',
      timestamp: event.timestamp || '',
      actor: event.actor || '',
      action: event.action || '',
      event_type: event.event_type || '',
      details: JSON.stringify(event.details || {}),
    })),
  )

  const lines = [
    header.join(','),
    ...rows.map((row) => header.map((key) => `"${String(row[key]).replace(/"/g, '""')}"`).join(',')),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `chain-of-custody-job-${job.value?.id || 'unknown'}.csv`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function printJobCocReport() {
  if (!cocReport.value) return
  document.body.classList.add(COC_PRINT_BODY_CLASS)
  window.print()
}

function handleBeforePrint() {
  if (!showCocDialog.value || !cocReport.value) return
  document.body.classList.add(COC_PRINT_BODY_CLASS)
}

function handleAfterPrint() {
  document.body.classList.remove(COC_PRINT_BODY_CLASS)
}

function applyCocSnapshot(report) {
  cocGeneratedAt.value = report?.snapshot_updated_at || report?.snapshot_stored_at || new Date().toISOString()
  cocReport.value = report
}

async function loadJobChainOfCustody() {
  if (!job.value || !canReadCoc.value) return
  cocLoading.value = true
  cocError.value = ''
  cocStatusMessage.value = ''
  try {
    applyCocSnapshot(await getJobChainOfCustody(job.value.id))
  } catch (err) {
    cocReport.value = null
    cocError.value = buildJobError(err)
  } finally {
    cocLoading.value = false
  }
}

async function refreshStoredJobChainOfCustody() {
  if (!job.value || !canRefreshCoc.value) return
  cocLoading.value = true
  cocError.value = ''
  cocStatusMessage.value = ''
  try {
    applyCocSnapshot(await refreshJobChainOfCustody(job.value.id))
    cocStatusMessage.value = t('audit.snapshotRefreshed')
  } catch (err) {
    cocError.value = buildJobError(err)
  } finally {
    cocLoading.value = false
  }
}

function prepareCocHandoff(report) {
  const defaultDeliveryTime = isoToLocalDateTimeValue()
  cocHandoffForm.value = {
    drive_id: String(report.drive_id || ''),
    project_id: normalizeProjectId(report.project_id || job.value?.project_id) || '',
    evidence_number: String(job.value?.evidence_number || report?.manifest_summary?.[0]?.evidence_number || ''),
    possessor: '',
    delivery_time: defaultDeliveryTime,
    received_by: '',
    receipt_ref: '',
    notes: '',
  }
}

function showCocHandoffError(message) {
  cocHandoffError.value = message
  showCocHandoffErrorDialog.value = true
}

function closeCocHandoffErrorDialog() {
  showCocHandoffErrorDialog.value = false
  cocHandoffError.value = ''
}

function submitCocHandoff() {
  const driveId = Number(cocHandoffForm.value.drive_id)
  if (!Number.isInteger(driveId) || driveId <= 0 || !cocHandoffForm.value.possessor.trim() || !cocHandoffForm.value.delivery_time) {
    showCocHandoffError(t('audit.handoffInvalid'))
    return
  }
  showCocHandoffWarning.value = true
}

function openCocHandoffDialog() {
  if (!canConfirmCocHandoff.value) return
  prepareCocHandoff(cocReport.value?.reports?.[0] || {})
  cocHandoffDialogTriggerRef.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
  showCocHandoffDialog.value = true
}

function closeCocHandoffDialog() {
  showCocHandoffDialog.value = false
}

async function confirmCocHandoffSubmission() {
  if (!job.value) return
  showCocHandoffWarning.value = false
  handoffSaving.value = true
  cocError.value = ''
  cocHandoffError.value = ''
  showCocHandoffErrorDialog.value = false
  cocStatusMessage.value = ''
  try {
    await confirmJobChainOfCustodyHandoff(job.value.id, {
      drive_id: Number(cocHandoffForm.value.drive_id),
      project_id: normalizeProjectId(cocHandoffForm.value.project_id) || undefined,
      possessor: cocHandoffForm.value.possessor.trim(),
      delivery_time: localDateTimeAsUtcIso(cocHandoffForm.value.delivery_time),
      received_by: cocHandoffForm.value.received_by.trim() || undefined,
      receipt_ref: cocHandoffForm.value.receipt_ref.trim() || undefined,
      notes: cocHandoffForm.value.notes.trim() || undefined,
    })
    await Promise.all([loadJobChainOfCustody(), refreshAll()])
    showCocHandoffDialog.value = false
    cocStatusMessage.value = t('audit.handoffSaved')
  } catch (err) {
    showCocHandoffError(buildJobError(err))
  } finally {
    handoffSaving.value = false
  }
}

function cancelCocHandoffSubmission() {
  showCocHandoffWarning.value = false
}

async function loadSupportingData() {
  const [driveResult, mountResult] = await Promise.allSettled([getDrives(), getShares()])
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

function displaySourcePath(currentJob) {
  return buildEditSourcePath(currentJob, inferMountForJob(currentJob))
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

function closeEditDialog() {
  showEditSourceBrowser.value = false
  showEditDialog.value = false
}

function toggleEditSourceBrowser() {
  if (!canBrowseEditMount.value) return
  showEditSourceBrowser.value = !showEditSourceBrowser.value
}

function closeOverflowDialog() {
  showOverflowDialog.value = false
}

function closeCocDialog() {
  showCocDialog.value = false
  showCocHandoffDialog.value = false
  showCocHandoffWarning.value = false
  handleAfterPrint()
}

function closePausePendingDialog() {
  showPausePendingDialog.value = false
}

function syncViewportState() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return

  if (!mobileViewportQuery) {
    mobileViewportQuery = window.matchMedia('(max-width: 768px)')
  }

  isMobileViewport.value = mobileViewportQuery.matches
}

function closeHashDialog() {
  showHashDialog.value = false
}

function openCocDialog() {
  if (!job.value || !canReadCoc.value) return
  cocDialogTriggerRef.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
  showCocDialog.value = true
  void loadJobChainOfCustody()
}

function shouldOpenCocFromRoute() {
  return route.query?.coc === '1'
}

function closeFileErrorDialog() {
  showFileErrorDialog.value = false
}

function openFileErrorDialog(row, event) {
  if (!hasFileError(row)) return
  fileErrorDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement
    ? event.currentTarget
    : document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
  selectedErrorFile.value = row
  showFileErrorDialog.value = true
}

function closeActionMenu(event) {
  const menu = event?.currentTarget instanceof HTMLElement ? event.currentTarget.closest('details') : null
  if (menu instanceof HTMLDetailsElement) {
    menu.removeAttribute('open')
  }
}

function runOverflowAction(action, event) {
  closeActionMenu(event)
  action.run()
}

function handleDialogKeydown(event) {
  if (showEditDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeEditDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, editDialogRef.value)
    }
    return
  }

  if (showOverflowDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeOverflowDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, overflowDialogRef.value)
    }
    return
  }

  if (showCocHandoffDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeCocHandoffDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, cocHandoffDialogRef.value)
    }
    return
  }

  if (showCocDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeCocDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, cocDialogRef.value)
    }
    return
  }

  if (showPausePendingDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closePausePendingDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, pauseDialogRef.value)
    }
    return
  }

  if (showHashDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeHashDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, hashDialogRef.value)
    }
    return
  }

  if (showFileErrorDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeFileErrorDialog()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, fileErrorDialogRef.value)
    }
  }
}

async function openEditDialog() {
  if (!job.value || !canEdit.value) return
  dialogTriggerRef.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
  error.value = ''
  await loadSupportingData()
  const inferredMount = inferMountForJob(job.value)
  editForm.value = {
    project_id: normalizeProjectId(job.value.project_id) || '',
    evidence_number: String(job.value.evidence_number || ''),
    notes: String(job.value.notes || ''),
    mount_id: inferredMount?.id ?? null,
    source_path: buildEditSourcePath(job.value, inferredMount),
    drive_id: job.value.drive?.id ?? null,
    overflow_drive_ids: reservedOverflowAssignments.value.map((assignment) => Number(assignment.drive_id)),
    thread_count: getJobThreadCountOverride(job.value),
    copy_chunk_size_bytes: job.value.copy_chunk_size_bytes ?? null,
    copy_progress_flush_bytes: job.value.copy_progress_flush_bytes ?? null,
    copy_file_fsync_enabled: job.value.copy_file_fsync_enabled ?? null,
    callback_url: String(job.value.callback_url || ''),
  }
  showEditSourceBrowser.value = false
  showEditDialog.value = true
}

async function openOverflowDialog() {
  if (!job.value || !canContinueOverflow.value) return
  dialogTriggerRef.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
  error.value = ''
  await loadSupportingData()
  overflowForm.value = {
    drive_id: overflowEligibleDrives.value[0]?.id ?? null,
    thread_count: Number(getEffectiveThreadCount(job.value) || 4),
  }
  showOverflowDialog.value = true
}

async function submitOverflowContinuation() {
  if (!job.value || !overflowForm.value.drive_id) return
  acting.value = true
  error.value = ''
  try {
    job.value = normalizeProjectRecord(await continueJobOverflow(job.value.id, {
      drive_id: Number(overflowForm.value.drive_id),
      thread_count: Number(overflowForm.value.thread_count || getEffectiveThreadCount(job.value) || 4),
    }), ['project_id'])
    closeOverflowDialog()
    await refreshAll()
    jobPoller.start()
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
}

function editFormReady() {
  if (startedJobEditMode.value) {
    return editForm.value.thread_count == null || Number.isInteger(Number(editForm.value.thread_count || NaN))
  }

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
      overflow_drive_ids: Array.isArray(editForm.value.overflow_drive_ids)
        ? editForm.value.overflow_drive_ids.map((value) => Number(value)).filter((value) => Number.isInteger(value))
        : [],
      thread_count: editForm.value.thread_count == null ? null : Number(editForm.value.thread_count),
      copy_chunk_size_bytes: editForm.value.copy_chunk_size_bytes == null ? null : Number(editForm.value.copy_chunk_size_bytes),
      copy_progress_flush_bytes: editForm.value.copy_progress_flush_bytes == null ? null : Number(editForm.value.copy_progress_flush_bytes),
      copy_file_fsync_enabled: editForm.value.copy_file_fsync_enabled,
      max_file_retries: Number(job.value.max_file_retries || 3),
      retry_delay_seconds: Number(job.value.retry_delay_seconds || 1),
      callback_url: String(editForm.value.callback_url || '').trim() || null,
    })
    job.value = normalizeProjectRecord(updated, ['project_id'])
    closeEditDialog()
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

async function runAnalyze() {
  if (!job.value || !canAnalyze.value) return
  acting.value = true
  error.value = ''
  infoMessage.value = ''
  try {
    job.value = normalizeProjectRecord(await analyzeJob(job.value.id, {}), ['project_id'])
    infoMessage.value = t('jobs.startupAnalysisStarted')
    await refreshAll()
    jobPoller.start()
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

async function confirmArchive() {
  if (!job.value || !canArchive.value) return
  acting.value = true
  error.value = ''
  try {
    job.value = normalizeProjectRecord(await archiveJob(job.value.id, { confirm: true }), ['project_id'])
    showArchiveDialog.value = false
    await refreshAll()
    jobPoller.stop()
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
}

async function confirmStartupAnalysisCleanup() {
  if (!job.value || !canClearStartupAnalysisCache.value) return
  acting.value = true
  error.value = ''
  infoMessage.value = ''
  try {
    job.value = normalizeProjectRecord(await clearJobStartupAnalysisCache(job.value.id, { confirm: true }), ['project_id'])
    showStartupAnalysisCleanupDialog.value = false
    infoMessage.value = t('jobs.startupAnalysisCacheCleared')
    await refreshAll()
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    acting.value = false
  }
}

async function loadDebug(force = false) {
  if (!jobId.value) return
  if (filesLoading.value && !force) return

  const requestId = ++latestDebugRequestId
  filesLoading.value = true
  try {
    const response = await getJobFiles(jobId.value, {
      page: Number(debug.value.page || 1),
    })
    if (requestId !== latestDebugRequestId) return

    const totalFiles = Number(response?.total_files || 0)
    const pageSize = Number(response?.page_size || DEFAULT_JOB_FILES_PAGE_SIZE)
    const page = Number(response?.page || debug.value.page || 1)
    const totalPages = totalFiles > 0 ? Math.ceil(totalFiles / pageSize) : 1

    if (page > totalPages) {
      debug.value = { ...debug.value, page: totalPages, page_size: pageSize }
      return
    }

    debug.value = {
      files: Array.isArray(response?.files) ? response.files : [],
      total_files: totalFiles,
      returned_files: Number(response?.returned_files || 0),
      page,
      page_size: pageSize,
    }
  } catch {
    if (requestId !== latestDebugRequestId) return
    if (force) {
      debug.value = { files: [], total_files: 0, returned_files: 0, page: 1, page_size: DEFAULT_JOB_FILES_PAGE_SIZE }
    }
  } finally {
    if (requestId === latestDebugRequestId) {
      filesLoading.value = false
    }
  }
}

const jobPoller = usePolling(
  async () => {
    const next = await getJob(jobId.value)
    job.value = normalizeProjectRecord(next, ['project_id'])

    return next
  },
  {
    intervalMs: 3000,
    isTerminal: (next) => {
      const status = String(next?.status || '').toUpperCase()
      return status === 'COMPLETED' || status === 'FAILED' || status === 'ARCHIVED'
    },
  },
)

function isTerminalStatus(status) {
  const normalized = String(status || '').toUpperCase()
  return normalized === 'COMPLETED' || normalized === 'FAILED' || normalized === 'ARCHIVED'
}

async function refreshAll() {
  if (!jobId.value) {
    error.value = t('common.errors.invalidRequest')
    job.value = null
    debug.value = { files: [], total_files: 0, returned_files: 0, page: 1, page_size: DEFAULT_JOB_FILES_PAGE_SIZE }
    return
  }

  loading.value = true
  error.value = ''
  try {
    await Promise.all([jobPoller.tick(), loadSupportingData()])
    void loadDebug(true)
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    loading.value = false
  }
}

watch(() => debug.value.page, (nextPage, previousPage) => {
  if (nextPage === previousPage) return
  void loadDebug(true)
})

watch(filesPanelExpanded, (expanded) => {
  if (!expanded) return
  void loadDebug(true)
})

watch(fileListRefreshKey, (nextKey, previousKey) => {
  if (!filesPanelExpanded.value) return
  if (nextKey === previousKey) return
  void loadDebug(true)
})

watch(() => debug.value.files, (files) => {
  const hasSelectedFile = (files || []).some((file) => Number(file.id) === Number(compareFileId.value))
  if (hasSelectedFile) return
  compareFileId.value = null
}, { deep: false })

function buildJobError(err) {
  return buildJobErrorMessage(err, t, { includeInvalidId: true })
}

async function runAction(action) {
  if (!job.value || !action) return
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
      closePausePendingDialog()
      const threadCountOverride = getJobThreadCountOverride(job.value)
      const startPayload = threadCountOverride == null ? {} : { thread_count: Number(threadCountOverride) }
      job.value = await startJob(job.value.id, startPayload)
    } else if (action === 'retry-failed') {
      closePausePendingDialog()
      job.value = await retryFailedJob(job.value.id)
    } else if (action === 'pause') {
      dialogTriggerRef.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
      job.value = await pauseJob(job.value.id)
      if (String(job.value?.status || '').toUpperCase() === 'PAUSING') {
        showPausePendingDialog.value = true
      }
    } else if (action === 'verify') {
      job.value = await verifyJob(job.value.id)
    } else if (action === 'manifest') {
      await downloadGeneratedManifest(job.value.id)
    } else {
      throw new Error(`Unsupported action: ${action}`)
    }

    if (action === 'manifest') {
      const manifestPath = buildManifestPath(job.value || manifestContext)
      infoMessage.value = manifestPath
        ? t('jobs.manifestSuccessWithPath', { path: manifestPath })
        : t('jobs.manifestSuccess')
    } else {
      await refreshAll()
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

function formatCompareValue(value) {
  return value == null || value === '' ? '-' : String(value)
}

async function loadHashes(fileId, event) {
  if (!canInspectHashes.value) return
  const selectedFile = (debug.value.files || []).find((file) => Number(file.id) === Number(fileId)) || null
  hashDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement instanceof HTMLElement ? document.activeElement : null
  selectedFileId.value = fileId
  selectedHashFileMeta.value = selectedFile
  compareFileId.value = fileId
  fileHashes.value = null
  compareResult.value = null
  showHashDialog.value = true
  try {
    fileHashes.value = await getFileHashes(fileId)
  } catch (err) {
    error.value = buildJobError(err)
  }
}

async function runCompare() {
  if (!selectedCompareFile.value) return
  compareResult.value = null
  error.value = ''
  try {
    compareResult.value = await compareFiles({
      file_id_a: Number(compareFileId.value),
      file_id_b: Number(selectedFileId.value),
    })
  } catch (err) {
    error.value = buildJobError(err)
  }
}

watch(currentStatus, (status) => {
  if (!['PREPARING', 'RUNNING', 'PAUSING'].includes(status)) {
    closePausePendingDialog()
  }
})

watch(currentStartupAnalysisStatus, (nextStatus, previousStatus) => {
  if (previousStatus !== 'ANALYZING' || nextStatus === 'ANALYZING') {
    return
  }

  if (infoMessage.value !== t('jobs.startupAnalysisStarted')) {
    return
  }

  if (nextStatus === 'READY' || nextStatus === 'STALE') {
    infoMessage.value = t('jobs.startupAnalysisCompleted')
    return
  }

  infoMessage.value = ''
})

watch(showEditDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = editDialogRef.value?.querySelector('#job-evidence')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showPausePendingDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = dialogTriggerRef.value
  dialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showOverflowDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = overflowDialogRef.value?.querySelector('#job-overflow-drive')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showEditDialog.value && !showCocDialog.value && !showPausePendingDialog.value && !showHashDialog.value && !showFileErrorDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = dialogTriggerRef.value
  dialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showCocDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = cocDialogRef.value?.querySelector('button')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showEditDialog.value && !showPausePendingDialog.value && !showHashDialog.value && !showFileErrorDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = cocDialogTriggerRef.value
  cocDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showCocHandoffDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = cocHandoffDialogRef.value?.querySelector('button, input, textarea')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showEditDialog.value && !showCocDialog.value && !showPausePendingDialog.value && !showHashDialog.value && !showFileErrorDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = cocHandoffDialogTriggerRef.value
  cocHandoffDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showPausePendingDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = pauseDialogRef.value?.querySelector('button')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showEditDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = dialogTriggerRef.value
  dialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showHashDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = hashDialogRef.value?.querySelector('button')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showEditDialog.value && !showCocDialog.value && !showPausePendingDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = hashDialogTriggerRef.value
  hashDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showFileErrorDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleDialogKeydown)
    await nextTick()
    const target = fileErrorDialogRef.value?.querySelector('button')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  if (!showEditDialog.value && !showCocDialog.value && !showPausePendingDialog.value && !showHashDialog.value) {
    document.removeEventListener('keydown', handleDialogKeydown)
  }
  const trigger = fileErrorDialogTriggerRef.value
  fileErrorDialogTriggerRef.value = null
  selectedErrorFile.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
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

  currentTimeIntervalId = window.setInterval(() => {
    currentTimeMs.value = Date.now()
  }, 1000)
  window.addEventListener('beforeprint', handleBeforePrint)
  window.addEventListener('afterprint', handleAfterPrint)
  currentTimeMs.value = Date.now()
  await refreshAll()
  if (shouldOpenCocFromRoute()) {
    openCocDialog()
  }
  if (!isTerminalStatus(job.value?.status)) {
    jobPoller.start()
  }
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleDialogKeydown)
  jobPoller.stop()
  mobileViewportQuery?.removeEventListener('change', syncViewportState)
  window.removeEventListener('beforeprint', handleBeforePrint)
  window.removeEventListener('afterprint', handleAfterPrint)
  handleAfterPrint()
  if (currentTimeIntervalId != null) {
    window.clearInterval(currentTimeIntervalId)
    currentTimeIntervalId = null
  }
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

      <section class="detail-section current-task-panel" aria-labelledby="job-detail-current-task-title">
        <div class="detail-section-header">
          <h2 id="job-detail-current-task-title">{{ t('jobs.currentTask') }}</h2>
        </div>

        <ProgressBar
          :value="progressMetrics.value"
          :total="progressMetrics.total"
          :label="progressLabel"
          :full-width="true"
          :active="progressActive"
        />
        <p v-if="progressMetrics.initializing" class="muted">{{ t('jobs.progressPreparingDetail') }}</p>
        <p v-else-if="isVerificationState" class="muted">{{ t('jobs.verificationProgressDetail') }}</p>
        <p class="muted">{{ formatBytes(progressMetrics.copiedBytes) }} / {{ formatBytes(progressMetrics.totalBytes) }}</p>

        <div class="detail-grid">
          <div v-for="entry in currentTaskSummary" :key="entry.label" class="detail-grid-item">
            <span>{{ entry.label }}</span><strong>{{ entry.value }}</strong>
          </div>
        </div>

      </section>

      <section class="detail-section job-information-panel" aria-labelledby="job-detail-information-title">
        <div class="detail-section-header">
          <h2 id="job-detail-information-title">{{ t('jobs.jobInformation') }}</h2>
        </div>

        <div class="detail-subpanel-grid">
          <section class="detail-subpanel" aria-labelledby="job-detail-neutral-information-title">
            <h3 id="job-detail-neutral-information-title">{{ t('jobs.jobDetailsGroup') }}</h3>
            <div class="detail-grid">
              <div class="detail-grid-item">
                <span>{{ t('jobs.threadCount') }}</span><strong>{{ getEffectiveThreadCount(job) ?? '-' }}{{ getEffectiveThreadCount(job) != null ? ` (${copyTuningSourceLabel(job.thread_count_source)})` : '' }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('configuration.fields.copy_chunk_size_bytes.label') }}</span><strong>{{ formatCopyTuningBytes(job.effective_copy_chunk_size_bytes, job.copy_chunk_size_source) }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('configuration.fields.copy_progress_flush_bytes.label') }}</span><strong>{{ formatCopyTuningBytes(job.effective_copy_progress_flush_bytes, job.copy_progress_flush_source) }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('configuration.fields.copy_file_fsync_enabled.label') }}</span><strong>{{ formatCopyTuningBoolean(job.effective_copy_file_fsync_enabled, job.copy_file_fsync_source) }}</strong>
              </div>
              <div class="detail-grid-item detail-grid-item--wide">
                <span>{{ t('jobs.callbackUrl') }}</span><strong class="mono wrap-anywhere">{{ job.callback_url || '-' }}</strong>
              </div>
              <div class="detail-grid-item detail-grid-item--wide">
                <span>{{ t('audit.notes') }}</span>
                <strong v-if="job.notes" class="wrap-anywhere">{{ job.notes }}</strong>
                <strong v-else>-</strong>
              </div>
            </div>
          </section>

          <section class="detail-subpanel" aria-labelledby="job-detail-source-information-title">
            <h3 id="job-detail-source-information-title">{{ t('jobs.sourceInformation') }}</h3>
            <div class="detail-grid analysis-summary">
              <div class="detail-grid-item">
                <span>{{ t('jobs.sourcePath') }}</span><strong class="mono wrap-anywhere">{{ displaySourcePath(job) || '-' }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('jobs.analysisDiscoveredFiles') }}</span><strong>{{ sourceFilesToCopyLabel }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('jobs.analysisEstimatedBytes') }}</span><strong>{{ sourceSizeToCopyLabel }}</strong>
              </div>
              <div v-if="startupAnalysisSummary" class="detail-grid-item">
                <span>{{ t('jobs.analysisSummary') }}</span><strong>{{ startupAnalysisSummary.statusLabel }}</strong>
              </div>
              <div v-if="startupAnalysisSummary" class="detail-grid-item">
                <span>{{ t('jobs.analysisLastAnalyzedAt') }}</span><strong>{{ startupAnalysisSummary.lastAnalyzedAt }}</strong>
              </div>
              <div v-if="startupAnalysisSummary" class="detail-grid-item">
                <span>{{ t('jobs.analysisReadyToStart') }}</span>
                <strong>{{ startupAnalysisSummary.readyToStart ? t('jobs.analysisReadyYes') : t('jobs.analysisReadyNo') }}</strong>
              </div>
            </div>
            <p v-if="startupAnalysisSummary?.failureReason" class="error-text">{{ t('jobs.analysisFailureReason') }}: {{ startupAnalysisSummary.failureReason }}</p>
          </section>

          <section class="detail-subpanel" aria-labelledby="job-detail-destination-information-title">
            <h3 id="job-detail-destination-information-title">{{ t('jobs.destinationInformation') }}</h3>
            <div class="detail-grid">
              <div class="detail-grid-item">
                <span>{{ t('jobs.destinationDrive') }}</span><strong class="mono wrap-anywhere">{{ resolveJobDestinationLabel(job) }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('drives.availableSpace') }}</span><strong>{{ formatBytes(job.drive?.available_bytes) }}</strong>
              </div>
              <div class="detail-grid-item">
                <span>{{ t('jobs.filesCopied') }}</span><strong>{{ destinationFilesCopiedLabel }}</strong>
              </div>
              <div class="detail-grid-item detail-grid-item--wide">
                <span>{{ t('jobs.overflowPanelTitle') }}</span>
                <strong v-if="overflowAssignments.length" class="mono wrap-anywhere">{{ overflowAssignments.map((assignment) => overflowAssignmentDriveLabel(assignment)).join(', ') }}</strong>
                <strong v-else>{{ t('common.labels.none') }}</strong>
              </div>
            </div>

            <div v-if="overflowAssignments.length" class="detail-callout" aria-live="polite">
              <strong>{{ t('jobs.overflowPanelTitle') }}</strong>
              <div v-for="assignment in overflowAssignments" :key="assignment.id" class="detail-overflow-assignment">
                <div class="detail-grid">
                  <div class="detail-grid-item">
                    <span>{{ t('jobs.destinationDrive') }}</span><strong class="mono wrap-anywhere">{{ overflowAssignmentDriveLabel(assignment) }}</strong>
                  </div>
                  <div class="detail-grid-item">
                    <span>{{ t('common.labels.status') }}</span><strong>{{ overflowAssignmentStateLabel(assignment.state) }}</strong>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      </section>

      <section
        :class="['detail-section', 'completion-summary', { 'completion-summary--danger': completionSummaryHasFailures }]"
        aria-labelledby="job-detail-completion-title"
        aria-live="polite"
      >
        <div class="detail-section-header">
          <h2 id="job-detail-completion-title">{{ t('jobs.completionSummary') }}</h2>
        </div>
        <div class="detail-grid">
          <div v-for="entry in completionPanelRows" :key="entry.label" class="detail-grid-item">
            <span>{{ entry.label }}</span>
            <strong :class="entry.label === t('jobs.manifestStatus') ? ['manifest-status-text', `manifest-status-text--${manifestSummary?.tone || 'muted'}`] : null">{{ entry.value }}</strong>
          </div>
        </div>
      </section>

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
        <template v-if="!isMobileViewport">
          <button
            v-for="action in actionItems"
            :key="action.key"
            class="btn"
            :class="{ 'btn-danger': action.tone === 'danger' }"
            :disabled="action.disabled"
            @click="action.run()"
          >
            {{ action.label }}
          </button>
        </template>
        <template v-else>
          <button
            v-for="action in primaryActions"
            :key="action.key"
            class="btn"
            :class="{ 'btn-danger': action.tone === 'danger' }"
            :disabled="action.disabled"
            @click="action.run()"
          >
            {{ action.label }}
          </button>
        </template>
        <details v-if="isMobileViewport && secondaryActions.length" class="actions-menu">
          <summary class="actions-menu-toggle" :aria-label="`${t('jobs.detail')} actions`">
            <span class="actions-menu-toggle-dots" aria-hidden="true">
              <span class="actions-menu-toggle-dot" />
              <span class="actions-menu-toggle-dot" />
              <span class="actions-menu-toggle-dot" />
            </span>
          </summary>
          <div class="actions-menu-popover">
            <button
              v-for="action in secondaryActions"
              :key="action.key"
              class="btn"
              :class="[
                `detail-action-menu-${action.key}`,
                { 'btn-danger': action.tone === 'danger' },
              ]"
              :disabled="action.disabled"
              @click="runOverflowAction(action, $event)"
            >
              {{ action.label }}
            </button>
          </div>
        </details>
      </div>
      <p v-if="archivePrerequisiteNotice" class="muted">{{ archivePrerequisiteNotice }}</p>
    </article>

    <article class="panel files-panel">
      <div class="files-panel-header">
        <h2>{{ t('jobs.files') }}</h2>
        <button
          type="button"
          class="btn files-panel-toggle"
          :aria-expanded="filesPanelExpanded"
          aria-controls="job-files-panel"
          @click="filesPanelExpanded = !filesPanelExpanded"
        >
          {{ filesPanelExpanded ? t('jobs.hideFiles') : t('jobs.showFiles') }}
        </button>
      </div>
      <div v-if="filesPanelExpanded" id="job-files-panel" class="files-panel-body">
        <p v-if="filesLoading" class="muted">{{ t('common.labels.loading') }}</p>
        <p v-else-if="fileListNotice" class="muted">{{ fileListNotice }}</p>
        <DataTable class="job-files-table" :columns="fileColumns" :rows="debug.files || []" row-key="id" :row-class="fileRowClass" :empty-text="t('jobs.noFiles')">
          <template #cell-relative_path="{ row }">
            <button
              class="file-path-button"
              :class="{ 'file-path-button-error': hasFileError(row) }"
              :disabled="!canInspectHashes"
              :title="row.relative_path"
              :aria-label="row.relative_path"
              @click="loadHashes(row.id, $event)"
            >
              {{ row.relative_path }}
            </button>
          </template>
          <template #cell-destination_drive_label="{ row }">
            <span class="wrap-anywhere">{{ row.destination_drive_label || t('common.labels.notAvailable') }}</span>
          </template>
          <template #cell-status="{ row }">
            <button
              v-if="hasFileError(row)"
              type="button"
              class="file-status-button"
              :class="{ 'file-status-button-mobile': isMobileViewport }"
              :aria-label="`${t('jobs.fileErrorDetailsOpen')}: ${row.relative_path}`"
              :title="fileErrorMessage(row)"
              @click="openFileErrorDialog(row, $event)"
            >
              <span
                v-if="isMobileViewport"
                class="file-status-icon file-status-icon-button"
                :class="`file-status-icon--${fileStatusTone(row.status)}`"
                aria-hidden="true"
              >
                <span aria-hidden="true">{{ fileStatusIcon(row.status) }}</span>
              </span>
              <StatusBadge v-else :status="row.status" />
            </button>
            <span
              v-else-if="isMobileViewport"
              class="file-status-icon"
              :class="`file-status-icon--${fileStatusTone(row.status)}`"
              :aria-label="normalizeFileStatus(row.status)"
              :title="normalizeFileStatus(row.status)"
              role="img"
            >
              <span aria-hidden="true">{{ fileStatusIcon(row.status) }}</span>
            </span>
            <StatusBadge v-else :status="row.status" />
          </template>
        </DataTable>
        <Pagination
          v-if="debug.total_files > debug.page_size"
          :page="debug.page"
          :page-size="debug.page_size"
          :total="debug.total_files"
          :show-page-window="true"
          :window-size="isMobileViewport ? 5 : 10"
          @update:page="debug.page = $event"
        />
      </div>
    </article>

    <teleport to="body">
      <div v-if="showOverflowDialog" class="dialog-overlay" @click.self="closeOverflowDialog">
        <div ref="overflowDialogRef" class="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="job-overflow-title">
          <h2 id="job-overflow-title">{{ t('jobs.continueOverflow') }}</h2>
          <p class="muted">{{ t('jobs.overflowDialogDescription') }}</p>

          <div class="dialog-groups">
            <fieldset class="dialog-group">
              <legend>{{ t('jobs.destinationGroup') }}</legend>

              <label for="job-overflow-drive">{{ t('jobs.selectOverflowDrive') }}</label>
              <select id="job-overflow-drive" v-model="overflowForm.drive_id">
                <option :value="null">{{ t('jobs.chooseDrive') }}</option>
                <option v-for="drive in overflowEligibleDrives" :key="drive.id" :value="drive.id">
                  {{ formatDriveLabel(drive) }}
                </option>
              </select>

              <label for="job-overflow-thread-count">{{ t('jobs.threadCount') }}</label>
              <select id="job-overflow-thread-count" v-model.number="overflowForm.thread_count">
                <option v-for="count in THREAD_COUNT_OPTIONS" :key="count" :value="count">{{ count }}</option>
              </select>
            </fieldset>
          </div>

          <div class="dialog-actions">
            <button class="btn" :disabled="acting" @click="closeOverflowDialog">{{ t('common.actions.cancel') }}</button>
            <button class="btn btn-primary" :disabled="acting || !overflowForm.drive_id" @click="submitOverflowContinuation">
              {{ acting ? t('common.labels.loading') : t('jobs.continueOverflowConfirm') }}
            </button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showEditDialog" class="dialog-overlay" @click.self="closeEditDialog">
        <div ref="editDialogRef" class="dialog-panel job-editor-dialog-panel" role="dialog" aria-modal="true" aria-labelledby="job-editor-title">
          <JobEditorDialogContent
            :title="t('jobs.editDialog')"
            :description="t('jobs.editDialogDescription')"
            :project-selected="true"
            :project-editable="false"
            :evidence-editable="!startedJobEditMode"
            :show-notes-field="false"
            :notes-editable="false"
            :show-overflow-panel="true"
            :overflow-selection-enabled="true"
            :show-execution-group="false"
            :show-source-group="!startedJobEditMode"
            :source-editable="!startedJobEditMode"
            :show-primary-drive-field="!startedJobEditMode"
            :primary-drive-editable="!startedJobEditMode"
            :show-callback-url-field="!startedJobEditMode"
            :callback-url-editable="!startedJobEditMode"
            :show-source-browser-toggle="!startedJobEditMode"
            :show-source-browser="showEditSourceBrowser"
            :can-browse-selected-mount="canBrowseEditMount"
            :selected-mount-record="editSelectedMountRecord"
            :available-projects="[]"
            :eligible-mounts="editEligibleMounts"
            :primary-eligible-drives="editEligibleDrives"
            :overflow-eligible-drives="editOverflowEligibleDrives"
            :form="editForm"
            :saving="acting"
            :can-submit="editFormReady()"
            :submit-label="t('jobs.saveChanges')"
            :loading-label="t('common.labels.loading')"
            :cancel-label="t('common.actions.cancel')"
            :close-label="t('common.actions.close')"
            :browse-label="t('jobs.browseSourcePath')"
            :project-label="t('dashboard.project')"
            :choose-project-label="t('jobs.chooseProject')"
            :evidence-label="t('jobs.evidence')"
            :notes-label="t('jobs.additionalNotes')"
            :notes-hint="t('jobs.notesHint')"
            :callback-url-label="t('jobs.callbackUrl')"
            :callback-url-hint="t('jobs.callbackUrlHint')"
            :thread-count-label="t('jobs.threadCount')"
            :copy-chunk-size-label="t('configuration.fields.copy_chunk_size_bytes.label')"
            :copy-chunk-size-hint="t('configuration.fields.copy_chunk_size_bytes.help')"
            :copy-progress-flush-label="t('configuration.fields.copy_progress_flush_bytes.label')"
            :copy-progress-flush-hint="t('configuration.fields.copy_progress_flush_bytes.help')"
            :copy-file-fsync-label="t('configuration.fields.copy_file_fsync_enabled.label')"
            :copy-file-fsync-hint="t('configuration.fields.copy_file_fsync_enabled.help')"
            :allow-thread-count-default-option="true"
            :thread-count-default-option-label="t('jobs.threadCountUseConfiguredDefault')"
            :job-details-group-label="t('jobs.jobDetailsGroup')"
            :source-group-label="t('jobs.sourceGroup')"
            :select-mount-label="t('jobs.selectMount')"
            :choose-mount-label="t('jobs.chooseMount')"
            :source-path-label="t('jobs.sourcePath')"
            :source-path-hint="t('jobs.sourcePathHint')"
            :destination-group-label="t('jobs.destinationGroup')"
            :select-drive-label="t('jobs.selectDrive')"
            :choose-drive-label="t('jobs.chooseDrive')"
            :overflow-panel-title="t('jobs.overflowPanelTitle')"
            :overflow-panel-help="t('jobs.overflowPanelHelp')"
            :no-eligible-overflow-drives-label="t('jobs.noEligibleOverflowDrives')"
            :execution-group-label="t('jobs.executionGroup')"
            :run-immediately-label="t('jobs.runImmediately')"
            :enabled-label="t('common.labels.enabled')"
            :disabled-label="t('common.labels.disabled')"
            :format-mount-label="formatMountLabel"
            :format-drive-label="formatDriveLabel"
            @close="closeEditDialog"
            @submit="submitEditJob"
            @toggle-source-browser="toggleEditSourceBrowser"
          />
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showCocDialog" class="dialog-overlay" @click.self="closeCocDialog">
        <div ref="cocDialogRef" class="dialog-panel coc-dialog" role="dialog" aria-modal="true" aria-labelledby="job-coc-title">
          <div class="dialog-header">
            <h2 id="job-coc-title">{{ t('audit.chainTitle') }}</h2>
            <div class="actions coc-toolbar">
              <button v-if="canRefreshCoc" class="btn" @click="refreshStoredJobChainOfCustody">{{ t('common.actions.refresh') }}</button>
              <button class="btn" :disabled="!cocReport" @click="printJobCocReport">{{ t('audit.printCoc') }}</button>
              <button class="btn" :disabled="!cocReport" @click="saveJobCocCsvReport">{{ t('audit.exportCsv') }}</button>
              <button class="btn btn-primary" :disabled="!cocReport" @click="saveJobCocReport">{{ t('audit.saveCoc') }}</button>
              <button v-if="canConfirmCocHandoff" class="btn" @click="openCocHandoffDialog">{{ t('audit.handoffTitle') }}</button>
            </div>
          </div>

          <div class="coc-status">
            <p v-if="cocLoading" class="muted">{{ t('common.labels.loading') }}</p>
            <p v-if="cocError" class="error-banner">{{ cocError }}</p>
            <p v-if="cocStatusMessage" class="ok-banner">{{ cocStatusMessage }}</p>
          </div>

          <div v-if="cocReport" class="coc-results">
            <div v-for="report in cocReport.reports" :key="report.drive_id" class="coc-report-shell">
              <CocReport
                :report="report"
                :selector-mode="cocReport.selector_mode"
                :project-id="normalizeProjectId(cocReport.project_id) || ''"
                :generated-at="cocGeneratedAt"
                :generated-by="authStore.username || ''"
                :manifest-totals-footnote="t('audit.manifestTotalsFootnote')"
              />
            </div>
          </div>

          <div class="dialog-actions">
            <button class="btn" @click="closeCocDialog">{{ t('common.actions.close') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showCocHandoffDialog" class="dialog-overlay" @click.self="closeCocHandoffDialog">
        <div ref="cocHandoffDialogRef" class="dialog-panel handoff-dialog" role="dialog" aria-modal="true" aria-labelledby="job-coc-handoff-title">
          <h2 id="job-coc-handoff-title">{{ t('audit.handoffTitle') }}</h2>
          <p class="muted">{{ t('audit.handoffGuidance') }}</p>
          <div class="handoff-grid">
            <input v-model="cocHandoffForm.drive_id" type="text" :placeholder="t('audit.driveIdLabel')" :aria-label="t('audit.driveIdLabel')" />
            <input v-model="cocHandoffForm.project_id" type="text" :placeholder="t('audit.projectBinding')" :aria-label="t('audit.projectBinding')" />
            <input v-model="cocHandoffForm.evidence_number" type="text" :placeholder="t('jobs.evidence')" :aria-label="t('jobs.evidence')" readonly />
            <input v-model="cocHandoffForm.possessor" type="text" :placeholder="t('audit.possessor')" :aria-label="t('audit.possessor')" />
            <div class="datetime-field">
              <input
                v-model="cocHandoffForm.delivery_time"
                type="datetime-local"
                :placeholder="t('audit.deliveryTimeLocalInput')"
                :aria-label="t('audit.deliveryTimeLocalInput')"
              />
            </div>
            <input v-model="cocHandoffForm.received_by" type="text" :placeholder="t('audit.receivedBy')" :aria-label="t('audit.receivedBy')" />
            <input v-model="cocHandoffForm.receipt_ref" type="text" :placeholder="t('audit.receiptRef')" :aria-label="t('audit.receiptRef')" />
          </div>
          <textarea v-model="cocHandoffForm.notes" rows="3" :placeholder="t('audit.notes')" :aria-label="t('audit.notes')"></textarea>
          <div class="dialog-actions">
            <button class="btn" @click="closeCocHandoffDialog">{{ t('common.actions.close') }}</button>
            <button class="btn btn-primary" :disabled="handoffSaving" @click="submitCocHandoff">{{ t('audit.confirmHandoff') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showHashDialog" class="dialog-overlay" @click.self="closeHashDialog">
        <div ref="hashDialogRef" class="dialog-panel hash-dialog" role="dialog" aria-modal="true" aria-labelledby="hash-viewer-title">
          <h2 id="hash-viewer-title">{{ t('jobs.hashViewer') }}</h2>
          <p v-if="!selectedFileId" class="muted">{{ t('jobs.hashViewerEmpty') }}</p>
          <p v-else-if="!fileHashes" class="muted">{{ t('common.labels.loading') }}</p>
          <div v-else class="hash-grid">
            <span>{{ t('common.labels.id') }}</span><strong>{{ fileHashes.file_id }}</strong>
            <span>{{ t('jobs.md5') }}</span><strong class="mono wrap-anywhere">{{ fileHashes.md5 || '-' }}</strong>
            <span>{{ t('jobs.sha256') }}</span><strong class="mono wrap-anywhere">{{ fileHashes.sha256 || '-' }}</strong>
            <span>{{ t('common.labels.size') }}</span><strong>{{ fileHashes.size_bytes || '-' }}</strong>
          </div>
          <div v-if="selectedHashFile" class="compare-section">
            <strong>{{ t('jobs.compareTitle') }}</strong>
            <p class="muted">{{ t('jobs.compareHelp') }}</p>
            <div class="compare-form">
              <label for="compare-file-source">{{ t('jobs.fileA') }}</label>
              <select id="compare-file-source" v-model="compareFileId">
                <option :value="null">-</option>
                <option v-for="file in debug.files || []" :key="`compare-${file.id}`" :value="file.id">
                  #{{ file.id }} {{ file.relative_path }}
                </option>
              </select>
              <label>{{ t('jobs.fileB') }}</label>
              <strong class="mono wrap-anywhere">#{{ selectedHashFile.id }} {{ selectedHashFile.relative_path }}</strong>
              <button class="btn" :disabled="!selectedCompareFile" @click="runCompare">
                {{ t('jobs.compare') }}
              </button>
            </div>

            <div v-if="compareResult" class="compare-results">
              <div class="hash-grid">
                <span>{{ t('jobs.compareMatch') }}</span><StatusBadge :status="compareResult.match" />
                <span>{{ t('jobs.hashMatch') }}</span><StatusBadge :status="compareResult.hash_match" />
                <span>{{ t('jobs.sizeMatch') }}</span><StatusBadge :status="compareResult.size_match" />
                <span>{{ t('jobs.pathMatch') }}</span><StatusBadge :status="compareResult.path_match" />
              </div>
              <div class="compare-detail-grid">
                <span></span><strong>{{ t('jobs.fileA') }}</strong><strong>{{ t('jobs.fileB') }}</strong>
                <span>{{ t('jobs.path') }}</span><strong class="mono wrap-anywhere">{{ formatCompareValue(compareResult.file_a?.relative_path) }}</strong><strong class="mono wrap-anywhere">{{ formatCompareValue(compareResult.file_b?.relative_path) }}</strong>
                <span>{{ t('common.labels.size') }}</span><strong>{{ formatCompareValue(compareResult.file_a?.size_bytes) }}</strong><strong>{{ formatCompareValue(compareResult.file_b?.size_bytes) }}</strong>
                <span>{{ t('jobs.sha256') }}</span><strong class="mono wrap-anywhere">{{ formatCompareValue(compareResult.file_a?.sha256 || compareResult.file_a?.md5) }}</strong><strong class="mono wrap-anywhere">{{ formatCompareValue(compareResult.file_b?.sha256 || compareResult.file_b?.md5) }}</strong>
              </div>
            </div>
          </div>
          <div class="dialog-actions">
            <button class="btn" @click="closeHashDialog">{{ t('common.actions.close') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showFileErrorDialog" class="dialog-overlay" @click.self="closeFileErrorDialog">
        <div
          ref="fileErrorDialogRef"
          class="dialog-panel hash-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="file-error-dialog-title"
        >
          <h2 id="file-error-dialog-title">{{ t('jobs.fileErrorDetails') }}</h2>
          <div v-if="selectedErrorFile" class="hash-grid">
            <span>{{ t('common.labels.id') }}</span><strong>{{ selectedErrorFile.id }}</strong>
            <span>{{ t('jobs.path') }}</span><strong class="mono wrap-anywhere">{{ selectedErrorFile.relative_path || '-' }}</strong>
            <span>{{ t('common.labels.status') }}</span><strong>{{ selectedErrorFile.status || '-' }}</strong>
          </div>
          <p v-if="!selectedErrorFile || !hasFileError(selectedErrorFile)" class="muted">{{ t('jobs.fileErrorDetailsEmpty') }}</p>
          <div v-else class="compare-section">
            <strong>{{ t('jobs.details') }}</strong>
            <pre class="file-error-detail-text">{{ fileErrorMessage(selectedErrorFile) }}</pre>
          </div>
          <div class="dialog-actions">
            <button class="btn" @click="closeFileErrorDialog">{{ t('common.actions.close') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <teleport to="body">
      <div v-if="showPausePendingDialog" class="dialog-overlay" @click.self="closePausePendingDialog">
        <div ref="pauseDialogRef" class="dialog-panel pause-wait-dialog" role="dialog" aria-modal="true" aria-labelledby="pause-wait-title">
          <h2 id="pause-wait-title">{{ t('jobs.pauseRequestedTitle') }}</h2>
          <p>{{ t('jobs.pauseRequestedMessage') }}</p>
          <p v-if="job" class="muted">#{{ job.id }} • {{ job.status }}</p>
          <div class="dialog-actions">
            <button class="btn" @click="closePausePendingDialog">{{ t('common.actions.close') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <ConfirmDialog
      v-model="showStartupAnalysisCleanupDialog"
      :title="t('jobs.clearStartupAnalysisConfirmTitle')"
      :message="t('jobs.clearStartupAnalysisConfirmBody')"
      :confirm-label="t('jobs.clearStartupAnalysis')"
      :cancel-label="t('common.actions.cancel')"
      :busy="acting"
      @confirm="confirmStartupAnalysisCleanup"
    />

    <ConfirmDialog
      v-model="showArchiveDialog"
      :title="t('jobs.archiveConfirmTitle')"
      :message="t('jobs.archiveConfirmBody')"
      :confirm-label="t('jobs.archiveWithoutHandoff')"
      :cancel-label="t('common.actions.cancel')"
      :busy="acting"
      dangerous
      @confirm="confirmArchive"
    >
      <div class="archive-confirm-copy">
        <p>{{ t('jobs.archiveConfirmBodyLead') }}</p>
        <p>{{ t('jobs.archiveConfirmBodyRestore') }}</p>
        <p>{{ t('jobs.archiveConfirmBodyNoHandoff') }}</p>
        <p>{{ t('jobs.archiveConfirmBodyUseHandoff') }}</p>
      </div>
    </ConfirmDialog>

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

    <ConfirmDialog
      v-model="showCocHandoffWarning"
      :title="t('audit.handoffWarning')"
      :message="t('audit.handoffWarningMessage')"
      :confirm-label="t('audit.handoffWarningConfirm')"
      :cancel-label="t('audit.handoffWarningCancel')"
      :dangerous="true"
      :busy="handoffSaving"
      @confirm="confirmCocHandoffSubmission"
      @cancel="cancelCocHandoffSubmission"
    />

    <ConfirmDialog
      v-model="showCocHandoffErrorDialog"
      :title="t('audit.handoffErrorTitle')"
      :message="''"
      :confirm-label="t('common.actions.close')"
      :cancel-label="t('common.actions.cancel')"
      :show-cancel="false"
      @confirm="closeCocHandoffErrorDialog"
      @cancel="closeCocHandoffErrorDialog"
    >
      <p class="error-banner" role="alert" aria-live="assertive">{{ cocHandoffError }}</p>
    </ConfirmDialog>
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

.analysis-summary {
  display: grid;
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

.job-editor-dialog-panel {
  overflow: hidden;
  grid-template-rows: auto minmax(0, 1fr) auto;
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

.field-hint {
  margin-top: calc(var(--space-xs) * -1);
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

.actions {
  flex-wrap: wrap;
  align-items: center;
}

.actions-menu {
  position: relative;
}

.actions-menu-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  cursor: pointer;
}

.actions-menu-toggle::-webkit-details-marker {
  display: none;
}

.actions-menu-toggle-dots {
  display: inline-grid;
  gap: 0.15rem;
}

.actions-menu-toggle-dot {
  width: 0.25rem;
  height: 0.25rem;
  border-radius: 9999px;
  background: currentColor;
}

.actions-menu-popover {
  position: absolute;
  top: calc(100% + var(--space-2xs));
  right: 0;
  z-index: 3;
  min-width: 12rem;
  display: grid;
  gap: var(--space-2xs);
  padding: var(--space-2xs);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.12));
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
  grid-template-columns: 120px minmax(0, 1fr);
  gap: var(--space-xs) var(--space-sm);
  align-items: center;
}

.hash-grid > span {
  font-weight: var(--font-weight-bold);
}

.compare-form select,
.compare-form strong {
  min-width: 0;
  max-width: 100%;
}

.compare-form select {
  width: 100%;
}

.file-path-button {
  display: inline-flex;
  max-width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  text-decoration: underline;
  cursor: pointer;
}

.file-path-button-error {
  font-weight: var(--font-weight-bold);
}

.file-path-button:disabled {
  color: var(--color-text-secondary);
  text-decoration: none;
  cursor: default;
}

.file-status-icon {
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

.file-status-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.file-status-button-mobile {
  line-height: 0;
}

.file-status-button:focus-visible {
  outline: 2px solid var(--color-link, var(--color-info));
  outline-offset: 3px;
  border-radius: 9999px;
}

.file-status-icon-button {
  cursor: pointer;
}

.file-status-icon--success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.file-status-icon--warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.file-status-icon--danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.file-status-icon--info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.file-status-icon--muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}

.compare-results {
  display: grid;
  gap: var(--space-sm);
}

.file-error-detail-text {
  margin: 0;
  padding: var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.job-files-table :deep(.job-file-row-error td) {
  color: var(--color-alert-danger-text, #991b1b);
}

.compare-section {
  display: grid;
  gap: var(--space-sm);
}

.compare-detail-grid {
  display: grid;
  grid-template-columns: 120px repeat(2, minmax(0, 1fr));
  gap: var(--space-xs) var(--space-sm);
  align-items: start;
}

.files-panel {
  display: grid;
  gap: var(--space-sm);
}

.files-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.files-panel-body {
  display: grid;
  gap: var(--space-sm);
}

.coc-section,
.coc-results,
.coc-report-shell,
.handoff-dialog {
  display: grid;
  gap: var(--space-sm);
}

.coc-status {
  display: grid;
  gap: var(--space-xs);
}

.coc-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--space-xs);
}

.handoff-header {
  gap: var(--space-sm);
}

.handoff-grid {
  display: grid;
  gap: var(--space-sm);
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.archive-confirm-copy {
  display: grid;
  gap: var(--space-sm);
}

.archive-confirm-copy p {
  margin: 0;
}

.handoff-dialog textarea,
.handoff-dialog input {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

@media (max-width: 420px) {
  .job-files-table :deep(.data-table) {
    table-layout: fixed;
  }

  .job-files-table :deep(.data-table th),
  .job-files-table :deep(.data-table td) {
    padding: var(--space-xs) var(--space-sm);
  }

  .job-files-table :deep(.data-table th:nth-child(1)),
  .job-files-table :deep(.data-table td:nth-child(1)) {
    width: 3rem;
  }

  .job-files-table :deep(.data-table th:nth-child(2)),
  .job-files-table :deep(.data-table td:nth-child(2)) {
    width: 12rem;
    max-width: 12rem;
  }

  .job-files-table :deep(.data-table th:nth-child(3)),
  .job-files-table :deep(.data-table td:nth-child(3)) {
    width: 3.5rem;
  }

  .file-path-button {
    display: block;
    width: 100%;
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.mono {
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
}

.wrap-anywhere {
  overflow-wrap: anywhere;
}

.detail-section {
  display: grid;
  gap: var(--space-sm);
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
}

.detail-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.detail-section-header h2,
.detail-subpanel h3 {
  margin: 0;
}

.current-task-panel {
  background: color-mix(in srgb, var(--color-info, #2563eb) 6%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info, #2563eb) 28%, var(--color-border));
}

.current-task-panel .muted {
  color: var(--color-text-primary);
}

.current-task-panel :deep(.progress-label) {
  color: var(--color-text-primary);
}

.job-information-panel {
  background: color-mix(in srgb, var(--color-info, #2563eb) 6%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info, #2563eb) 28%, var(--color-border));
}

.detail-subpanel-grid {
  display: grid;
  gap: var(--space-md);
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
}

@media (max-width: 1080px) {
  .detail-subpanel-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .detail-subpanel-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.detail-subpanel {
  display: grid;
  align-content: start;
  gap: var(--space-sm);
  height: 100%;
  container-type: inline-size;
  padding: var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
}

.detail-subpanel .detail-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

@container (max-width: 32rem) {
  .detail-subpanel .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .detail-subpanel .detail-grid-item--wide {
    grid-column: auto;
  }
}

.detail-grid {
  display: grid;
  gap: var(--space-sm);
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.detail-grid-item {
  display: grid;
  gap: var(--space-2xs);
  min-width: 0;
}

.detail-grid-item > span {
  font-weight: var(--font-weight-bold);
}

.detail-grid-item--wide {
  grid-column: 1 / -1;
}

.detail-callout {
  display: grid;
  gap: var(--space-sm);
  padding: var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
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

.completion-summary--danger {
  background: var(--color-alert-danger-bg, #fef2f2);
  border-color: var(--color-alert-danger-border, #fca5a5);
}

.manifest-status-text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.125rem 0.5rem;
  border: 1px solid transparent;
  border-radius: 999px;
  background: var(--color-bg-hover);
  color: var(--color-text-primary, #1f2937);
  font-weight: 600;
}

.manifest-status-text--success {
  background: color-mix(in srgb, var(--color-success, #16a34a) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success, #16a34a) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.manifest-status-text--danger {
  background: color-mix(in srgb, var(--color-danger, #dc2626) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger, #dc2626) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.manifest-status-text--muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}

.failure-summary {
  display: grid;
  gap: var(--space-xs);
  color: var(--color-text-primary, #1f2937);
  background: var(--color-alert-danger-bg, #fef2f2);
  border: 1px solid var(--color-alert-danger-border, #fca5a5);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.failure-summary .muted {
  color: var(--color-text-primary, #1f2937);
  opacity: 0.85;
}

.error-text {
  color: var(--color-alert-danger-text);
}

.log-entry-block {
  display: grid;
  gap: var(--space-xs);
}

.detail-notes {
  margin-top: 1rem;
}

.detail-notes p {
  margin: 0.5rem 0 0;
}

.detail-overflow-assignment + .detail-overflow-assignment {
  margin-top: 0.75rem;
}

.log-entry-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
  color: var(--color-text-primary, #1f2937);
  background: var(--color-bg-input, #ffffff);
  border: 1px solid var(--color-alert-danger-border, #fca5a5);
  box-shadow: inset 0.25rem 0 0 var(--color-alert-danger-text, #dc2626);
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

<style>
@media print {
  body.printing-coc-report > *:not(.dialog-overlay) {
    display: none !important;
  }

  body.printing-coc-report > .dialog-overlay {
    position: static !important;
    inset: auto !important;
    display: block !important;
    background: transparent !important;
    place-items: stretch !important;
  }

  body.printing-coc-report > .dialog-overlay .dialog-panel,
  body.printing-coc-report > .dialog-overlay .coc-dialog {
    width: auto !important;
    max-height: none !important;
    overflow: visible !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 0 !important;
    background: transparent !important;
  }
}
</style>
