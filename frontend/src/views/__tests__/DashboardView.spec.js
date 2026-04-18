import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DashboardView from '@/views/DashboardView.vue'

const mocks = vi.hoisted(() => ({
  getSystemHealth: vi.fn(),
  getDrives: vi.fn(),
  listJobs: vi.fn(),
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
          props: ['value', 'total'],
          template: '<div class="progress-stub">{{ value }}/{{ total }}</div>',
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

    expect(wrapper.find('.progress-stub').text()).toBe('40/100')
  })
})
