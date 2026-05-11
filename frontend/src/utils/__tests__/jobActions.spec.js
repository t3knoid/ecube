import { describe, expect, it } from 'vitest'

import { canEditJob, canOperateOnInactiveJob, canPauseJob, canReadJobCoc, canStartJob, getDashboardNextStepKey, getJobDetailPrimaryActionKeys, getJobLifecycleToggleAction, getJobListLifecycleActions, shouldPollJobListEntry } from '../jobActions.js'
import { buildJobErrorMessage } from '../jobErrors.js'

describe('job action helpers', () => {
  it('allows start only for startable states when startup analysis is not running', () => {
    expect(canStartJob({ canOperate: true, jobStatus: 'PENDING', startupAnalysisStatus: 'READY' })).toBe(true)
    expect(canStartJob({ canOperate: true, jobStatus: 'PAUSED', startupAnalysisStatus: 'STALE' })).toBe(true)
    expect(canStartJob({ canOperate: true, jobStatus: 'FAILED', startupAnalysisStatus: null })).toBe(true)
  })

  it('blocks start while startup analysis is still running', () => {
    expect(canStartJob({ canOperate: true, jobStatus: 'PENDING', startupAnalysisStatus: 'ANALYZING' })).toBe(false)
  })

  it('shares the inactive-job eligibility rule across edit, analyze, complete, and start states', () => {
    expect(canOperateOnInactiveJob({ canOperate: true, jobStatus: 'FAILED', startupAnalysisStatus: 'READY' })).toBe(true)
    expect(canOperateOnInactiveJob({ canOperate: true, jobStatus: 'RUNNING', startupAnalysisStatus: 'READY' })).toBe(false)
  })

  it('allows edit only while the job is still pending', () => {
    expect(canEditJob({ canOperate: true, jobStatus: 'PENDING', startupAnalysisStatus: 'READY' })).toBe(true)
    expect(canEditJob({ canOperate: true, jobStatus: 'PENDING', startupAnalysisStatus: 'ANALYZING' })).toBe(false)
    expect(canEditJob({ canOperate: true, jobStatus: 'PAUSED', startupAnalysisStatus: 'READY' })).toBe(false)
    expect(canEditJob({ canOperate: true, jobStatus: 'FAILED', startupAnalysisStatus: 'READY' })).toBe(false)
  })

  it('allows pause only for running jobs', () => {
    expect(canPauseJob({ canOperate: true, jobStatus: 'RUNNING' })).toBe(true)
    expect(canPauseJob({ canOperate: true, jobStatus: 'PAUSING' })).toBe(false)
    expect(canPauseJob({ canOperate: true, jobStatus: 'PAUSED' })).toBe(false)
  })

  it('derives one lifecycle toggle action from the trusted job status', () => {
    expect(getJobLifecycleToggleAction({ canOperate: true, jobStatus: 'PENDING', startupAnalysisStatus: 'READY' })).toEqual({
      key: 'start',
      enabled: true,
    })
    expect(getJobLifecycleToggleAction({ canOperate: true, jobStatus: 'RUNNING', startupAnalysisStatus: 'READY' })).toEqual({
      key: 'pause',
      enabled: true,
    })
    expect(getJobLifecycleToggleAction({ canOperate: true, jobStatus: 'PAUSING', startupAnalysisStatus: 'READY' })).toEqual({
      key: 'pause',
      enabled: false,
    })
    expect(getJobLifecycleToggleAction({ canOperate: true, jobStatus: 'COMPLETED', startupAnalysisStatus: 'READY' })).toBeNull()
  })

  it('gates CoC access to completed and archived jobs', () => {
    expect(canReadJobCoc({ hasAccess: true, jobStatus: 'COMPLETED' })).toBe(true)
    expect(canReadJobCoc({ hasAccess: true, jobStatus: 'ARCHIVED' })).toBe(true)
    expect(canReadJobCoc({ hasAccess: true, jobStatus: 'PENDING' })).toBe(false)
  })

  it('derives Jobs list lifecycle actions from one shared helper', () => {
    expect(getJobListLifecycleActions({ canOperate: true, jobStatus: 'PENDING', startupAnalysisStatus: 'READY' })).toEqual([
      { key: 'start', enabled: true },
    ])
    expect(getJobListLifecycleActions({ canOperate: true, jobStatus: 'RUNNING', startupAnalysisStatus: 'READY' })).toEqual([
      { key: 'pause', enabled: true },
    ])
    expect(getJobListLifecycleActions({ canOperate: true, jobStatus: 'PAUSING', startupAnalysisStatus: 'READY' })).toEqual([
      { key: 'pause', enabled: false },
    ])
    expect(getJobListLifecycleActions({ canOperate: true, jobStatus: 'PAUSED', startupAnalysisStatus: 'ANALYZING' })).toEqual([
      { key: 'start', enabled: false },
    ])
    expect(getJobListLifecycleActions({ canOperate: true, jobStatus: 'COMPLETED', startupAnalysisStatus: 'READY' })).toEqual([])
  })

  it('shares the Jobs list polling rule for active and analyzing jobs', () => {
    expect(shouldPollJobListEntry({ jobStatus: 'RUNNING', startupAnalysisStatus: 'READY' })).toBe(true)
    expect(shouldPollJobListEntry({ jobStatus: 'PAUSING', startupAnalysisStatus: 'READY' })).toBe(true)
    expect(shouldPollJobListEntry({ jobStatus: 'COMPLETED', startupAnalysisStatus: 'ANALYZING' })).toBe(true)
    expect(shouldPollJobListEntry({ jobStatus: 'COMPLETED', startupAnalysisStatus: 'READY' })).toBe(false)
  })

  it('derives primary Job Detail actions from one shared status helper', () => {
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'PENDING', canRetryFailed: false, canReadCoc: false })).toEqual(['edit', 'analyze', 'lifecycle-toggle'])
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'PAUSED', canRetryFailed: false, canReadCoc: false })).toEqual(['analyze', 'lifecycle-toggle'])
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'FAILED', canRetryFailed: false, canReadCoc: false })).toEqual(['analyze', 'lifecycle-toggle'])
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'RUNNING', canRetryFailed: false, canReadCoc: false })).toEqual(['lifecycle-toggle'])
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'COMPLETED', canRetryFailed: false, canReadCoc: true })).toEqual(['verify', 'manifest', 'coc'])
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'COMPLETED', canRetryFailed: true, canReadCoc: true })).toEqual(['retry-failed', 'coc'])
    expect(getJobDetailPrimaryActionKeys({ jobStatus: 'COMPLETED', canRetryFailed: false, canReadCoc: false })).toEqual(['verify', 'manifest'])
  })

  it('derives dashboard next-step guidance from trusted job and custody state', () => {
    expect(getDashboardNextStepKey({ jobStatus: 'PENDING', startupAnalysisStatus: 'READY' })).toBe('dashboard.nextStepReviewAndStart')
    expect(getDashboardNextStepKey({ jobStatus: 'PENDING', startupAnalysisStatus: 'ANALYZING' })).toBe('dashboard.nextStepAwaitAnalysis')
    expect(getDashboardNextStepKey({ jobStatus: 'RUNNING', startupAnalysisStatus: 'READY' })).toBe('dashboard.nextStepMonitorProgress')
    expect(getDashboardNextStepKey({ jobStatus: 'FAILED', failedFiles: 1, timedOutFiles: 0 })).toBe('dashboard.nextStepReviewFailedFiles')
    expect(getDashboardNextStepKey({ jobStatus: 'PAUSED', failedFiles: 0, timedOutFiles: 0 })).toBe('dashboard.nextStepReviewAndResume')
    expect(getDashboardNextStepKey({ jobStatus: 'COMPLETED', custodyStatus: 'PENDING_HANDOFF', failedFiles: 0, timedOutFiles: 0 })).toBe('dashboard.nextStepReviewVerificationAndHandoff')
  })

  it('falls back to opening Job Detail when trusted next-step inputs are unavailable', () => {
    expect(getDashboardNextStepKey({ jobStatus: 'STATUS_UNAVAILABLE' })).toBe('dashboard.nextStepOpenDetail')
    expect(getDashboardNextStepKey({ jobStatus: null })).toBe('dashboard.nextStepOpenDetail')
    expect(getDashboardNextStepKey({ jobStatus: 'COMPLETED', custodyStatus: 'PENDING_HANDOFF' })).toBe('dashboard.nextStepOpenDetail')
    expect(getDashboardNextStepKey({ jobStatus: 'ARCHIVED', custodyStatus: 'PENDING_HANDOFF', failedFiles: 0, timedOutFiles: 0 })).toBe('dashboard.nextStepOpenDetail')
  })

  it('builds consistent job error messages across views', () => {
    const t = (key, params) => (key === 'common.errors.serverError' ? `${key}:${params.status}` : key)

    expect(buildJobErrorMessage({ response: { status: 409, data: { detail: 'Conflict detail' } } }, t)).toBe('Conflict detail')
    expect(buildJobErrorMessage({ response: { status: 500, data: {} } }, t)).toBe('common.errors.serverError:500')
    expect(buildJobErrorMessage(new TypeError('Invalid job id'), t, { includeInvalidId: true })).toBe('common.errors.invalidRequest')
  })
})