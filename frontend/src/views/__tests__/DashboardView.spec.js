import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DashboardView from '@/views/DashboardView.vue'

const mocks = vi.hoisted(() => ({
  getSystemHealth: vi.fn(),
  getDrives: vi.fn(),
  getMounts: vi.fn(),
  listJobs: vi.fn(),
  push: vi.fn(),
  authStore: { passwordWarningDays: null, hasRole: vi.fn() },
  pollerStart: vi.fn(),
  pollerStop: vi.fn(),
  pollerTick: null,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mocks.push,
  }),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => mocks.authStore,
}))

vi.mock('@/api/introspection.js', () => ({
  getSystemHealth: (...args) => mocks.getSystemHealth(...args),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  listJobs: (...args) => mocks.listJobs(...args),
}))

vi.mock('@/composables/usePolling.js', () => ({
  usePolling: (tick) => {
    mocks.pollerTick = tick
    return {
      tick,
      start: (...args) => mocks.pollerStart(...args),
      stop: (...args) => mocks.pollerStop(...args),
    }
  },
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

function mountView() {
  return mount(DashboardView, {
    global: {
      plugins: [i18n],
      stubs: {
        DataTable: {
          props: ['rows'],
          template: `
            <div>
              <div v-for="row in rows" :key="row.id" class="row-stub">
                <slot name="cell-id" :row="row">
                  <span class="row-id">{{ row.id }}</span>
                </slot>
                <slot name="cell-project_id" :row="row" />
                <slot name="cell-status" :row="row" />
                <slot name="cell-attention" :row="row" />
                <slot name="cell-progress" :row="row" />
              </div>
            </div>
          `,
        },
        StatusBadge: {
          props: ['status'],
          template: '<span>{{ status }}</span>',
        },
        ProgressBar: {
          props: ['value', 'total', 'label'],
          template: '<div class="progress-stub">{{ value }}/{{ total }} {{ label }}</div>',
        },
      },
    },
  })
}

describe('DashboardView active jobs', () => {
  beforeEach(() => {
    mocks.getSystemHealth.mockReset()
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.listJobs.mockReset()
    mocks.push.mockReset()
    mocks.pollerStart.mockReset()
    mocks.pollerStop.mockReset()
    mocks.pollerTick = null
    mocks.authStore.passwordWarningDays = null
    mocks.authStore.hasRole.mockReset()
    mocks.authStore.hasRole.mockReturnValue(false)
    sessionStorage.clear()

    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 1 })
    mocks.getDrives.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([])
  })

  it('shows a dismissible password expiry warning banner', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.authStore.passwordWarningDays = 7

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Your password will expire in 7 day')

    await wrapper.find('.warning-banner .btn').trigger('click')
    await flushPromises()

    expect(wrapper.find('.warning-banner').exists()).toBe(false)
  })

  it('renders drive and mount summary entries as keyboard-operable buttons', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getDrives.mockResolvedValue([{ id: 1, current_state: 'AVAILABLE' }])
    mocks.getMounts.mockResolvedValue([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const driveButton = wrapper.findAll('.summary-link').find((node) => node.text().includes(i18n.global.t('drives.states.available')))
    const mountButton = wrapper.findAll('.summary-link').find((node) => node.text().includes(i18n.global.t('dashboard.mountUnassigned')))

    expect(driveButton.element.tagName).toBe('BUTTON')
    expect(driveButton.attributes('type')).toBe('button')
    expect(mountButton.element.tagName).toBe('BUTTON')
    expect(mountButton.attributes('type')).toBe('button')
  })

  it('routes drive summary entries to Drives with the matching state filter', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getDrives.mockResolvedValue([{ id: 1, current_state: 'AVAILABLE' }])

    const wrapper = mountView()
    await flushPromises()

    const driveButton = wrapper.findAll('.summary-link').find((node) => node.text().includes(i18n.global.t('drives.states.available')))

    await driveButton.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'drives', query: { state: 'AVAILABLE' } })
  })

  it('routes mount summary entries to Mounts with the matching workflow filter', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const mountButton = wrapper.findAll('.summary-link').find((node) => node.text().includes(i18n.global.t('dashboard.mountUnassigned')))

    await mountButton.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'mounts', query: { workflow: 'UNASSIGNED' } })
  })

  it('shows blocked, waiting-to-start, and custody-closeout work in Needs Attention', async () => {
    mocks.listJobs.mockResolvedValue([
      { id: 40, project_id: 'PROJ-040', status: 'FAILED', copied_bytes: 0, total_bytes: 0, file_count: 1, files_succeeded: 0, files_failed: 1 },
      { id: 41, project_id: 'PROJ-041', status: 'PAUSED', copied_bytes: 0, total_bytes: 0, file_count: 1, files_succeeded: 0, files_failed: 0 },
      { id: 42, project_id: 'PROJ-042', status: 'PENDING', copied_bytes: 0, total_bytes: 0, file_count: 1, files_succeeded: 0, files_failed: 0 },
    ])
    mocks.getMounts.mockResolvedValue([
      { id: 12, status: 'MOUNTED', project_id: 'PROJ-043', related_job: { job_id: 43, status: 'COMPLETED', custody_status: 'PENDING_HANDOFF' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.needsAttention'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionBlocked'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionWaitingToStart'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionWaitingForCustody'))

    const jobLinks = wrapper.findAll('.cell-link').map((node) => node.text())
    expect(jobLinks).toContain('40')
    expect(jobLinks).toContain('41')
    expect(jobLinks).toContain('42')
    expect(jobLinks).toContain('43')
  })

  it('does not classify pending jobs that are still analyzing as waiting to start', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 60,
        project_id: 'PROJ-060',
        status: 'PENDING',
        startup_analysis_status: 'ANALYZING',
        copied_bytes: 0,
        total_bytes: 0,
        file_count: 1,
        files_succeeded: 0,
        files_failed: 0,
      },
    ])
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.needsAttention'))
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.attentionWaitingToStart'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.noNeedsAttention'))
  })

  it('shows an empty needs-attention state when no follow-up items are present', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.noNeedsAttention'))
  })

  it('refreshes jobs, drives, and mounts on the same poll tick as system health', async () => {
    mocks.getSystemHealth.mockResolvedValueOnce({ status: 'ok', database: 'connected', active_jobs: 1 })
    mocks.getDrives.mockResolvedValueOnce([{ id: 1, current_state: 'AVAILABLE' }])
    mocks.getMounts.mockResolvedValueOnce([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])
    mocks.listJobs.mockResolvedValueOnce([
      {
        id: 44,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    mocks.getSystemHealth.mockResolvedValueOnce({ status: 'degraded', database: 'connected', active_jobs: 0 })
    mocks.getDrives.mockResolvedValueOnce([{ id: 2, current_state: 'DISABLED' }])
    mocks.getMounts.mockResolvedValueOnce([
      { id: 11, status: 'MOUNTED', project_id: 'PROJ-001', related_job: { job_id: 31, status: 'PENDING', custody_status: 'PENDING_HANDOFF' } },
    ])
    mocks.listJobs.mockResolvedValueOnce([])

    const wrapper = mountView()
    await flushPromises()

    expect(typeof mocks.pollerTick).toBe('function')
    expect(mocks.pollerStart).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('ok')
    expect(wrapper.text()).toContain(`${i18n.global.t('drives.states.available')}1`)
    expect(wrapper.text()).toContain(`${i18n.global.t('dashboard.mountUnassigned')}1`)
    expect(wrapper.find('.cell-link').text()).toBe('44')

    await mocks.pollerTick()
    await flushPromises()

    expect(wrapper.text()).toContain('degraded')
    expect(wrapper.text()).toContain(`${i18n.global.t('drives.states.disabled')}1`)
    expect(wrapper.text()).toContain(`${i18n.global.t('dashboard.mountAssigned')}1`)
    expect(wrapper.find('.cell-link').exists()).toBe(false)
    expect(mocks.getSystemHealth).toHaveBeenCalledTimes(2)
    expect(mocks.getDrives).toHaveBeenCalledTimes(2)
    expect(mocks.getMounts).toHaveBeenCalledTimes(2)
    expect(mocks.listJobs).toHaveBeenCalledTimes(2)
  })

  it('keeps running progress aligned with finished file counts', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 15,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.progress-stub').text()).toBe('40/100 40%')
  })

  it('does not show 100% when a running job is still below 1%', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 16,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 136 * 1024 * 1024,
        total_bytes: 27 * 1024 * 1024 * 1024,
        file_count: 5000,
        files_succeeded: 0,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.progress-stub').text()).toBe('0/100 0%')
  })

  it('shows a preparing indicator while a running job is still calculating totals', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 17,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 0,
        total_bytes: 0,
        file_count: 0,
        files_succeeded: 0,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.progress-stub').text()).toContain('Preparing...')
  })

  it('renders a compact progress label alongside the dashboard progress bar', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 18,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.dashboard-progress-mobile-label').text()).toBe('40%')
    expect(wrapper.find('.progress-stub').text()).toBe('40/100 40%')
  })

  it('includes disabled drives in the dashboard drive summary', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getDrives.mockResolvedValue([
      { id: 1, current_state: 'DISCONNECTED' },
      { id: 2, current_state: 'DISABLED' },
      { id: 3, current_state: 'AVAILABLE' },
      { id: 4, current_state: 'IN_USE' },
    ])

    const wrapper = mountView()
    await flushPromises()

    const summaryRows = wrapper
      .findAll('.summary-link')
      .map((row) => row.text())
      .filter((text) => text.includes(i18n.global.t('drives.states.disconnected')) || text.includes(i18n.global.t('drives.states.disabled')) || text.includes(i18n.global.t('drives.states.available')) || text.includes(i18n.global.t('drives.states.inUse')))
    expect(summaryRows).toContain(`${i18n.global.t('drives.states.disconnected')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('drives.states.disabled')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('drives.states.available')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('drives.states.inUse')}1`)
  })

  it('shows a mounts summary with counts by related job lifecycle buckets', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
      { id: 11, status: 'MOUNTED', project_id: 'PROJ-001', related_job: { job_id: 31, status: 'PENDING', custody_status: 'PENDING_HANDOFF' } },
      { id: 12, status: 'MOUNTED', project_id: 'PROJ-002', related_job: { job_id: 32, status: 'RUNNING', custody_status: 'PENDING_HANDOFF' } },
      { id: 13, status: 'ERROR', project_id: 'PROJ-003', related_job: { job_id: 33, status: 'PAUSED', custody_status: 'PENDING_HANDOFF' } },
      { id: 14, status: 'MOUNTED', project_id: 'PROJ-004', related_job: { job_id: 34, status: 'COMPLETED', custody_status: 'PENDING_HANDOFF' } },
      { id: 15, status: 'MOUNTED', project_id: 'PROJ-005', related_job: { job_id: 35, status: 'ARCHIVED', custody_status: 'HANDOFF_RECORDED' } },
      { id: 16, status: 'MOUNTED', project_id: 'PROJ-006', related_job: { job_id: 36, status: 'COMPLETED', custody_status: 'HANDOFF_RECORDED' } },
      { id: 18, status: 'UNMOUNTED', project_id: 'PROJ-008', related_job: { job_id: null, status: 'STATUS_UNAVAILABLE', custody_status: 'STATUS_UNAVAILABLE' } },
      { id: 19, status: 'ERROR', project_id: 'PROJ-009', related_job: { job_id: 37, status: 'FAILED', custody_status: 'PENDING_HANDOFF' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.mountsSummary'))

    const summaryRows = wrapper
      .findAll('.summary-link')
      .map((row) => row.text())
      .filter((text) => text.includes(i18n.global.t('dashboard.mountUnassigned')) || text.includes(i18n.global.t('dashboard.mountAssigned')) || text.includes(i18n.global.t('dashboard.mountInProgress')) || text.includes(i18n.global.t('dashboard.mountCompleted')) || text.includes(i18n.global.t('dashboard.mountUnavailable')))
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountUnassigned')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountAssigned')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountInProgress')}4`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountCompleted')}2`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountUnavailable')}1`)
  })

  it('shows unavailable mounts explicitly instead of silently dropping them', async () => {
    mocks.listJobs.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([
      { id: 21, status: 'MOUNTED', project_id: 'PROJ-021', related_job: { job_id: 41, status: 'COMPLETED', custody_status: 'STATUS_UNAVAILABLE' } },
      { id: 22, status: 'UNMOUNTED', project_id: 'PROJ-022', related_job: { job_id: null, status: 'STATUS_UNAVAILABLE', custody_status: 'STATUS_UNAVAILABLE' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const summaryRows = wrapper
      .findAll('.summary-link')
      .map((row) => row.text())
      .filter((text) => text.includes(i18n.global.t('dashboard.mountUnavailable')) || text.includes(i18n.global.t('dashboard.mountCompleted')))
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountUnavailable')}2`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountCompleted')}0`)
  })

  it('keeps active jobs visible when mounts fail but jobs still load', async () => {
    mocks.getMounts.mockRejectedValue(new Error('mounts unavailable'))
    mocks.listJobs.mockResolvedValue([
      {
        id: 52,
        project_id: 'PROJ-052',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.loadMountsError'))
    expect(wrapper.find('.cell-link').exists()).toBe(true)
    expect(wrapper.find('.cell-link').text()).toBe('52')
  })

  it('hides drive summary and active jobs sections from auditors', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 44,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])
    mocks.authStore.hasRole.mockImplementation((role) => role === 'auditor')

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.driveSummary'))
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.mountsSummary'))
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.needsAttention'))
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.activeJobs'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.systemHealth'))
  })

  it('renders the Job ID cell as a link to Job Detail for active jobs', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 44,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    const jobLink = wrapper.find('.cell-link')
    expect(jobLink.exists()).toBe(true)
    expect(jobLink.text()).toBe('44')

    await jobLink.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 44 } })
  })

  it('falls back to plain text when an active job row has no valid id', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: null,
        project_id: 'PROJ-001',
        status: 'RUNNING',
        copied_bytes: 1000,
        total_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.cell-link').exists()).toBe(false)
    expect(wrapper.find('.job-id-text').text()).toBe('-')
    expect(mocks.push).not.toHaveBeenCalled()
  })
})
