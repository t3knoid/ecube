import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DashboardView from '@/views/DashboardView.vue'

const mocks = vi.hoisted(() => ({
  getSystemHealth: vi.fn(),
  getDrives: vi.fn(),
  getShares: vi.fn(),
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

vi.mock('@/api/shares.js', () => ({
  getShares: (...args) => mocks.getShares(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  listJobs: (...args) => mocks.listJobs(...args),
}))

function createDeferred() {
  let resolve
  const promise = new Promise((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
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

describe('DashboardView polling integration', () => {
  beforeEach(() => {
    vi.useFakeTimers()

    mocks.getSystemHealth.mockReset()
    mocks.getDrives.mockReset()
    mocks.getShares.mockReset()
    mocks.listJobs.mockReset()
    mocks.push.mockReset()
    mocks.authStore.passwordWarningDays = null
    mocks.authStore.hasRole.mockReset()
    mocks.authStore.hasRole.mockReturnValue(false)
    sessionStorage.clear()
  })

  afterEach(async () => {
    await vi.runOnlyPendingTimersAsync()
    vi.useRealTimers()
  })

  it('auto-refreshes the full dashboard snapshot on the polling interval', async () => {
    mocks.getSystemHealth
      .mockResolvedValueOnce({ status: 'ok', database: 'connected', active_jobs: 1 })
      .mockResolvedValueOnce({ status: 'degraded', database: 'connected', active_jobs: 0 })
    mocks.getDrives
      .mockResolvedValueOnce([{ id: 1, current_state: 'AVAILABLE' }])
      .mockResolvedValueOnce([{ id: 2, current_state: 'DISABLED' }])
    mocks.getShares
      .mockResolvedValueOnce([
        { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
      ])
      .mockResolvedValueOnce([
        { id: 11, status: 'MOUNTED', project_id: 'PROJ-001', related_job: { job_id: 31, status: 'PENDING', custody_status: 'PENDING_HANDOFF' } },
      ])
    mocks.listJobs
      .mockResolvedValueOnce([
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
      .mockResolvedValueOnce([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('ok')
    expect(wrapper.text()).toContain(`${i18n.global.t('drives.states.available')}1`)
    expect(wrapper.text()).toContain(`${i18n.global.t('dashboard.mountUnassigned')}1`)
    expect(wrapper.find('.cell-link').text()).toBe('44')

    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()

    expect(wrapper.text()).toContain('degraded')
    expect(wrapper.text()).toContain(`${i18n.global.t('drives.states.disabled')}1`)
    expect(wrapper.text()).toContain(`${i18n.global.t('dashboard.mountAssigned')}1`)
    expect(wrapper.find('.cell-link').exists()).toBe(false)
    expect(mocks.getSystemHealth).toHaveBeenCalledTimes(2)
    expect(mocks.getDrives).toHaveBeenCalledTimes(2)
    expect(mocks.getShares).toHaveBeenCalledTimes(2)
    expect(mocks.listJobs).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })

  it('uses the guarded poller path for manual refreshes and stops timers after unmount', async () => {
    mocks.getSystemHealth.mockResolvedValueOnce({ status: 'ok', database: 'connected', active_jobs: 1 })
    mocks.getDrives.mockResolvedValueOnce([{ id: 1, current_state: 'AVAILABLE' }])
    mocks.getShares.mockResolvedValueOnce([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])
    mocks.listJobs.mockResolvedValueOnce([])

    const healthRefresh = createDeferred()
    const drivesRefresh = createDeferred()
    const mountsRefresh = createDeferred()
    const jobsRefresh = createDeferred()

    mocks.getSystemHealth.mockReturnValueOnce(healthRefresh.promise)
    mocks.getDrives.mockReturnValueOnce(drivesRefresh.promise)
    mocks.getShares.mockReturnValueOnce(mountsRefresh.promise)
    mocks.listJobs.mockReturnValueOnce(jobsRefresh.promise)

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.view-header .btn').trigger('click')
    await wrapper.find('.view-header .btn').trigger('click')
    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()

    expect(mocks.getSystemHealth).toHaveBeenCalledTimes(2)
    expect(mocks.getDrives).toHaveBeenCalledTimes(2)
    expect(mocks.getShares).toHaveBeenCalledTimes(2)
    expect(mocks.listJobs).toHaveBeenCalledTimes(2)

    healthRefresh.resolve({ status: 'ok', database: 'connected', active_jobs: 1 })
    drivesRefresh.resolve([{ id: 1, current_state: 'AVAILABLE' }])
    mountsRefresh.resolve([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])
    jobsRefresh.resolve([])
    await flushPromises()

    wrapper.unmount()

    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()

    expect(mocks.getSystemHealth).toHaveBeenCalledTimes(2)
    expect(mocks.getDrives).toHaveBeenCalledTimes(2)
    expect(mocks.getShares).toHaveBeenCalledTimes(2)
    expect(mocks.listJobs).toHaveBeenCalledTimes(2)
  })
})