import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DashboardView from '@/views/DashboardView.vue'

const mocks = vi.hoisted(() => ({
  getSystemHealth: vi.fn(),
  getDrives: vi.fn(),
  listJobs: vi.fn(),
  push: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mocks.push,
  }),
}))

vi.mock('@/api/introspection.js', () => ({
  getSystemHealth: (...args) => mocks.getSystemHealth(...args),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
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
    mocks.listJobs.mockReset()
    mocks.push.mockReset()

    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 1 })
    mocks.getDrives.mockResolvedValue([])
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
