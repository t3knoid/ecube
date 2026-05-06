export function normalizeJobStatus(status) {
  return String(status || '').toUpperCase()
}

export function normalizeStartupAnalysisStatus(status) {
  return String(status || '').toUpperCase()
}

const INACTIVE_JOB_STATUSES = ['PENDING', 'FAILED', 'PAUSED']
const COC_READABLE_JOB_STATUSES = ['COMPLETED', 'ARCHIVED']
const ACTIVE_JOB_POLLING_STATUSES = ['RUNNING', 'PAUSING', 'VERIFYING']

export function canOperateOnInactiveJob({ canOperate, jobStatus, startupAnalysisStatus }) {
  return Boolean(canOperate)
    && INACTIVE_JOB_STATUSES.includes(normalizeJobStatus(jobStatus))
    && normalizeStartupAnalysisStatus(startupAnalysisStatus) !== 'ANALYZING'
}

export function canStartJob({ canOperate, jobStatus, startupAnalysisStatus }) {
  return canOperateOnInactiveJob({ canOperate, jobStatus, startupAnalysisStatus })
}

export function canPauseJob({ canOperate, jobStatus }) {
  return Boolean(canOperate) && normalizeJobStatus(jobStatus) === 'RUNNING'
}

export function getJobListLifecycleActions({ canOperate, jobStatus, startupAnalysisStatus }) {
  return [
    {
      key: 'start',
      enabled: canStartJob({ canOperate, jobStatus, startupAnalysisStatus }),
    },
    {
      key: 'pause',
      enabled: canPauseJob({ canOperate, jobStatus }),
    },
  ]
}

export function shouldPollJobListEntry({ jobStatus, startupAnalysisStatus }) {
  return ACTIVE_JOB_POLLING_STATUSES.includes(normalizeJobStatus(jobStatus))
    || normalizeStartupAnalysisStatus(startupAnalysisStatus) === 'ANALYZING'
}

export function canReadJobCoc({ hasAccess, jobStatus }) {
  return Boolean(hasAccess) && COC_READABLE_JOB_STATUSES.includes(normalizeJobStatus(jobStatus))
}

export function getJobDetailPrimaryActionKeys({ jobStatus, canRetryFailed, canReadCoc }) {
  const status = normalizeJobStatus(jobStatus)

  if (INACTIVE_JOB_STATUSES.includes(status) || status === 'ARCHIVED') {
    return ['edit', 'analyze', 'start']
  }
  if (status === 'RUNNING' || status === 'PAUSING') {
    return ['pause']
  }
  if (status === 'COMPLETED') {
    const keys = canRetryFailed ? ['retry-failed'] : ['verify', 'manifest']
    return canReadCoc ? [...keys, 'coc'] : keys
  }

  return ['edit', 'analyze', 'start']
}