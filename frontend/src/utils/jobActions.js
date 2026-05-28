import { normalizeProjectId } from './projectId.js'

export function normalizeJobStatus(status) {
  return String(status || '').toUpperCase()
}

export function normalizeStartupAnalysisStatus(status) {
  return String(status || '').toUpperCase()
}

const INACTIVE_JOB_STATUSES = ['PENDING', 'FAILED', 'PAUSED']
const COC_READABLE_JOB_STATUSES = ['COMPLETED', 'ARCHIVED']
const ACTIVE_JOB_POLLING_STATUSES = ['PREPARING', 'RUNNING', 'PAUSING', 'VERIFYING']
const PAUSE_VISIBLE_JOB_STATUSES = ['PREPARING', 'RUNNING', 'PAUSING']
const EDITABLE_JOB_STATUSES = ['PENDING', 'PREPARING', 'RUNNING', 'PAUSING', 'PAUSED', 'FAILED']

export function canOperateOnInactiveJob({ canOperate, jobStatus, startupAnalysisStatus }) {
  return Boolean(canOperate)
    && INACTIVE_JOB_STATUSES.includes(normalizeJobStatus(jobStatus))
    && normalizeStartupAnalysisStatus(startupAnalysisStatus) !== 'ANALYZING'
}

export function canStartJob({ canOperate, jobStatus, startupAnalysisStatus }) {
  return canOperateOnInactiveJob({ canOperate, jobStatus, startupAnalysisStatus })
}

export function canEditJob({ canOperate, jobStatus, startupAnalysisStatus }) {
  return Boolean(canOperate)
    && EDITABLE_JOB_STATUSES.includes(normalizeJobStatus(jobStatus))
    && normalizeStartupAnalysisStatus(startupAnalysisStatus) !== 'ANALYZING'
}

export function canPauseJob({ canOperate, jobStatus }) {
  return Boolean(canOperate) && normalizeJobStatus(jobStatus) === 'RUNNING'
}

export function getJobLifecycleToggleAction({ canOperate, jobStatus, startupAnalysisStatus }) {
  const status = normalizeJobStatus(jobStatus)

  if (status === 'PAUSING') {
    return {
      key: 'pause',
      enabled: false,
    }
  }

  if (status === 'PREPARING') {
    return {
      key: 'pause',
      enabled: false,
    }
  }

  if (INACTIVE_JOB_STATUSES.includes(status)) {
    return {
      key: 'start',
      enabled: canStartJob({ canOperate, jobStatus, startupAnalysisStatus }),
    }
  }

  if (PAUSE_VISIBLE_JOB_STATUSES.includes(status)) {
    return {
      key: 'pause',
      enabled: canPauseJob({ canOperate, jobStatus }),
    }
  }

  return null
}

export function getJobListLifecycleActions({ canOperate, jobStatus, startupAnalysisStatus }) {
  const action = getJobLifecycleToggleAction({ canOperate, jobStatus, startupAnalysisStatus })
  return action ? [action] : []
}

export function shouldPollJobListEntry({ jobStatus, startupAnalysisStatus }) {
  return ACTIVE_JOB_POLLING_STATUSES.includes(normalizeJobStatus(jobStatus))
    || normalizeStartupAnalysisStatus(startupAnalysisStatus) === 'ANALYZING'
}

export function canReadJobCoc({ hasAccess, jobStatus }) {
  return Boolean(hasAccess) && COC_READABLE_JOB_STATUSES.includes(normalizeJobStatus(jobStatus))
}

function hasRetryableFiles({ failedFiles, timedOutFiles }) {
  return Number(failedFiles || 0) + Number(timedOutFiles || 0) > 0
}

function hasKnownFileOutcomeState({ failedFiles, timedOutFiles }) {
  return Number.isFinite(Number(failedFiles)) && Number.isFinite(Number(timedOutFiles))
}

function isDriveAwaitingEject({ driveState, driveIsMounted, jobProjectId, driveProjectId }) {
  const normalizedJobProjectId = normalizeProjectId(jobProjectId)
  const normalizedDriveProjectId = normalizeProjectId(driveProjectId)

  if (normalizedJobProjectId || normalizedDriveProjectId) {
    if (!normalizedJobProjectId || normalizedDriveProjectId !== normalizedJobProjectId) {
      return false
    }
  }

  const normalizedDriveState = String(driveState || '').toUpperCase()
  if (normalizedDriveState === 'IN_USE') return true
  return Boolean(driveIsMounted)
}

export function getDashboardNextStepKey({
  jobStatus,
  startupAnalysisStatus,
  custodyStatus,
  failedFiles,
  timedOutFiles,
  driveState,
  driveIsMounted,
  jobProjectId,
  driveProjectId,
}) {
  const status = normalizeJobStatus(jobStatus)
  const normalizedStartupAnalysisStatus = normalizeStartupAnalysisStatus(startupAnalysisStatus)
  const normalizedCustodyStatus = String(custodyStatus || '').toUpperCase()
  const retryableFiles = hasRetryableFiles({ failedFiles, timedOutFiles })
  const knownFileOutcomeState = hasKnownFileOutcomeState({ failedFiles, timedOutFiles })

  if (status === 'PENDING') {
    if (normalizedStartupAnalysisStatus === 'ANALYZING') return 'dashboard.nextStepAwaitAnalysis'
    if (canStartJob({ canOperate: true, jobStatus: status, startupAnalysisStatus })) {
      return 'dashboard.nextStepReviewAndStart'
    }
    return 'dashboard.nextStepOpenDetail'
  }

  if (['PREPARING', 'RUNNING', 'PAUSING', 'VERIFYING'].includes(status)) {
    return 'dashboard.nextStepMonitorProgress'
  }

  if (status === 'FAILED' || status === 'PAUSED') {
    return retryableFiles ? 'dashboard.nextStepReviewFailedFiles' : 'dashboard.nextStepReviewAndResume'
  }

  if (status === 'ARCHIVED') {
    return 'dashboard.nextStepOpenDetail'
  }

  if (status === 'COMPLETED') {
    if (normalizedCustodyStatus === 'HANDOFF_RECORDED' && isDriveAwaitingEject({ driveState, driveIsMounted, jobProjectId, driveProjectId })) {
      return 'dashboard.nextStepPrepareEject'
    }

    if (!knownFileOutcomeState) {
      return 'dashboard.nextStepOpenDetail'
    }

    if (normalizedCustodyStatus === 'PENDING_HANDOFF') {
      return retryableFiles ? 'dashboard.nextStepReviewFailedFiles' : 'dashboard.nextStepReviewVerificationAndHandoff'
    }

    const primaryActionKeys = getJobDetailPrimaryActionKeys({
      jobStatus: status,
      canRetryFailed: retryableFiles,
      canReadCoc: canReadJobCoc({ hasAccess: true, jobStatus: status }),
    })

    if (primaryActionKeys.includes('retry-failed')) return 'dashboard.nextStepReviewFailedFiles'
    if (primaryActionKeys.includes('verify')) return 'dashboard.nextStepReviewVerification'
    if (primaryActionKeys.includes('coc')) return 'dashboard.nextStepReviewHandoff'
  }

  return 'dashboard.nextStepOpenDetail'
}

export function getDashboardFollowUpKey({
  jobStatus,
  startupAnalysisStatus,
  custodyStatus,
  driveState,
  driveIsMounted,
  jobProjectId,
  driveProjectId,
}) {
  const status = normalizeJobStatus(jobStatus)
  const normalizedStartupAnalysisStatus = normalizeStartupAnalysisStatus(startupAnalysisStatus)
  const normalizedCustodyStatus = String(custodyStatus || '').toUpperCase()

  if (status === 'ARCHIVED') {
    return ''
  }

  if (status === 'FAILED' || status === 'PAUSED') {
    return 'dashboard.attentionBlocked'
  }

  if (status === 'PENDING' && canStartJob({ canOperate: true, jobStatus: status, startupAnalysisStatus: normalizedStartupAnalysisStatus })) {
    return 'dashboard.attentionWaitingToStart'
  }

  if (status === 'COMPLETED' && normalizedCustodyStatus === 'PENDING_HANDOFF') {
    return 'dashboard.attentionWaitingForCustody'
  }

  if (
    status === 'COMPLETED'
    && normalizedCustodyStatus === 'HANDOFF_RECORDED'
    && isDriveAwaitingEject({ driveState, driveIsMounted, jobProjectId, driveProjectId })
  ) {
    return 'dashboard.attentionReadyForEject'
  }

  return ''
}

export function getJobDetailPrimaryActionKeys({ jobStatus, canRetryFailed, canReadCoc }) {
  const status = normalizeJobStatus(jobStatus)

  if (status === 'PENDING') {
    return ['edit', 'analyze', 'lifecycle-toggle']
  }
  if (status === 'FAILED' || status === 'PAUSED') {
    return ['edit', 'analyze', 'lifecycle-toggle']
  }
  if (status === 'ARCHIVED') {
    return ['analyze', 'lifecycle-toggle']
  }
  if (status === 'PREPARING' || status === 'RUNNING' || status === 'PAUSING') {
    return ['edit', 'lifecycle-toggle']
  }
  if (status === 'COMPLETED') {
    const keys = canRetryFailed ? ['retry-failed'] : ['verify', 'manifest']
    return canReadCoc ? [...keys, 'coc'] : keys
  }

  return ['edit', 'analyze', 'lifecycle-toggle']
}