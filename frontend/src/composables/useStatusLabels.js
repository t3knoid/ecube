import { useI18n } from 'vue-i18n'

const DRIVE_STATE_KEYS = {
  EMPTY: 'drives.states.empty',
  AVAILABLE: 'drives.states.available',
  IN_USE: 'drives.states.inUse',
}

const JOB_STATUS_KEYS = {
  PENDING: 'jobs.statuses.pending',
  RUNNING: 'jobs.statuses.running',
  VERIFYING: 'jobs.statuses.verifying',
  COMPLETED: 'jobs.statuses.completed',
  FAILED: 'jobs.statuses.failed',
}

export function useStatusLabels() {
  const { t } = useI18n()

  function driveStateLabel(state) {
    const key = DRIVE_STATE_KEYS[String(state).toUpperCase()]
    return key ? t(key) : String(state ?? '')
  }

  function jobStatusLabel(status) {
    const key = JOB_STATUS_KEYS[String(status).toUpperCase()]
    return key ? t(key) : String(status ?? '')
  }

  return { driveStateLabel, jobStatusLabel }
}
