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

    const summaryRows = wrapper.findAll('.summary-row').map((row) => row.text())
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

    const summaryRows = wrapper.findAll('.summary-row').map((row) => row.text())
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

    const summaryRows = wrapper.findAll('.summary-row').map((row) => row.text())
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
