import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DashboardView from '@/views/DashboardView.vue'

const mocks = vi.hoisted(() => ({
  getSystemHealth: vi.fn(),
  getDrives: vi.fn(),
  getShares: vi.fn(),
  listAllJobs: vi.fn(),
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

vi.mock('@/api/shares.js', () => ({
  getShares: (...args) => mocks.getShares(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  listAllJobs: (...args) => mocks.listAllJobs(...args),
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
          props: ['columns', 'rows', 'emptyText'],
          template: `
            <div class="table-wrap-stub">
              <table class="data-table-stub">
                <thead>
                  <tr>
                    <th v-for="column in columns" :key="column.key">{{ column.label }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="!rows.length">
                    <td :colspan="columns.length || 1" class="empty-state-stub">{{ emptyText }}</td>
                  </tr>
                  <tr v-for="row in rows" :key="row.id" class="row-stub">
                    <td v-for="column in columns" :key="column.key">
                      <slot :name="'cell-' + column.key" :row="row">
                        <span class="row-id">{{ row[column.key] }}</span>
                      </slot>
                    </td>
                  </tr>
                </tbody>
              </table>
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
    mocks.getShares.mockReset()
    mocks.listAllJobs.mockReset()
    mocks.push.mockReset()
    mocks.pollerStart.mockReset()
    mocks.pollerStop.mockReset()
    mocks.pollerTick = null
    mocks.authStore.passwordWarningDays = null
    mocks.authStore.hasRole.mockReset()
    mocks.authStore.hasRole.mockImplementation(() => false)
    sessionStorage.clear()

    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 1 })
    mocks.getDrives.mockResolvedValue([])
    mocks.getShares.mockResolvedValue([])
  })

  it('shows a dismissible password expiry warning banner', async () => {
    mocks.listAllJobs.mockResolvedValue([])
    mocks.authStore.passwordWarningDays = 7

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Your password will expire in 7 day')

    await wrapper.find('.warning-banner .btn').trigger('click')
    await flushPromises()

    expect(wrapper.find('.warning-banner').exists()).toBe(false)
  })

  it('renders drive and mount summary entries as keyboard-operable buttons', async () => {
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getDrives.mockResolvedValue([{ id: 1, current_state: 'AVAILABLE' }])
    mocks.getShares.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getDrives.mockResolvedValue([{ id: 1, current_state: 'AVAILABLE' }])

    const wrapper = mountView()
    await flushPromises()

    const driveButton = wrapper.findAll('.summary-link').find((node) => node.text().includes(i18n.global.t('drives.states.available')))

    await driveButton.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'drives', query: { state: 'AVAILABLE' } })
  })

  it('routes mount summary entries to Mounts with the matching workflow filter', async () => {
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getShares.mockResolvedValue([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const mountButton = wrapper.findAll('.summary-link').find((node) => node.text().includes(i18n.global.t('dashboard.mountUnassigned')))

    await mountButton.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'shares', query: { workflow: 'UNASSIGNED' } })
  })

  it('shows blocked, waiting-to-start, custody-closeout, and ready-to-eject work in Needs Attention', async () => {
    mocks.listAllJobs.mockResolvedValue([
      { id: 40, project_id: 'PROJ-040', status: 'FAILED', copied_bytes: 0, total_bytes: 0, file_count: 1, files_succeeded: 0, files_failed: 1 },
      { id: 41, project_id: 'PROJ-041', status: 'PAUSED', copied_bytes: 0, total_bytes: 0, file_count: 1, files_succeeded: 0, files_failed: 0 },
      { id: 42, project_id: 'PROJ-042', status: 'PENDING', copied_bytes: 0, total_bytes: 0, file_count: 1, files_succeeded: 0, files_failed: 0 },
      {
        id: 44,
        project_id: 'PROJ-044',
        status: 'COMPLETED',
        copied_bytes: 10,
        total_bytes: 10,
        file_count: 1,
        files_succeeded: 1,
        files_failed: 0,
        files_timed_out: 0,
        drive: {
          id: 5,
          manufacturer: 'Acme',
          product_name: 'Vault',
          current_state: 'IN_USE',
          is_mounted: true,
        },
      },
    ])
    mocks.getShares.mockResolvedValue([
      { id: 12, status: 'MOUNTED', project_id: 'PROJ-043', related_job: { job_id: 43, status: 'COMPLETED', custody_status: 'PENDING_HANDOFF' } },
      { id: 14, status: 'MOUNTED', project_id: 'PROJ-044', related_job: { job_id: 44, status: 'COMPLETED', custody_status: 'HANDOFF_RECORDED' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.needsAttention'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionBlocked'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionWaitingToStart'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionWaitingForCustody'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionReadyForEject'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepReviewFailedFiles'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepReviewAndStart'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepPrepareEject'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepOpenDetail'))

    const jobLinks = wrapper.findAll('.cell-link').map((node) => node.text())
    expect(jobLinks).toContain('40')
    expect(jobLinks).toContain('41')
    expect(jobLinks).toContain('42')
    expect(jobLinks).toContain('43')
    expect(jobLinks).toContain('44')

    const needsAttentionRows = wrapper.findAll('.row-stub').slice(0, 5)
    expect(needsAttentionRows[0].find('.dashboard-job-id-cell').text()).toBe('40')
    expect(needsAttentionRows[0].find('.dashboard-source-context').text()).toContain(i18n.global.t('dashboard.sourceMount'))
    expect(needsAttentionRows[0].find('.dashboard-source-context').text()).toContain(i18n.global.t('jobs.sourcePath'))
  })

  it('uses job custody status for archived custody-closeout guidance even when shares have no related job', async () => {
    mocks.listAllJobs.mockResolvedValue([
      {
        id: 70,
        project_id: 'PROJ-070',
        status: 'ARCHIVED',
        custody_status: 'PENDING_HANDOFF',
        files_failed: 0,
        files_timed_out: 0,
      },
    ])
    mocks.getShares.mockResolvedValue([
      { id: 13, status: 'MOUNTED', project_id: 'PROJ-070', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.attentionWaitingForCustody'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepOpenDetail'))
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.nextStepReviewVerificationAndHandoff'))
  })

  it('does not classify pending jobs that are still analyzing as waiting to start', async () => {
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.getShares.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.needsAttention'))
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.attentionWaitingToStart'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.noNeedsAttention'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepAwaitAnalysis'))
  })

  it('shows monitor guidance for active jobs', async () => {
    mocks.listAllJobs.mockResolvedValue([
      {
        id: 61,
        project_id: 'PROJ-061',
        status: 'RUNNING',
        copied_bytes: 100,
        total_bytes: 1000,
        file_count: 10,
        files_succeeded: 1,
        files_failed: 0,
      },
    ])
    mocks.getShares.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.nextStepMonitorProgress'))
  })

  it('renders trusted dashboard row context and safe fallbacks for triage', async () => {
    mocks.listAllJobs.mockResolvedValue([
      {
        id: 62,
        project_id: 'PROJ-062',
        status: 'RUNNING',
        source_path: '/case/subfolder',
        created_at: '2026-05-10T10:00:00Z',
        started_at: '2026-05-10T10:05:00Z',
        copy_started_at: '2026-05-10T10:05:05Z',
        copied_bytes: 10 * 1024 * 1024,
        total_bytes: 20 * 1024 * 1024,
        file_count: 10,
        files_succeeded: 5,
        files_failed: 0,
        files_timed_out: 0,
        active_duration_seconds: 10,
        drive: {
          id: 7,
          manufacturer: 'Apricorn',
          product_name: 'Aegis',
          port_number: 4,
        },
      },
      {
        id: 63,
        project_id: 'PROJ-063',
        status: 'FAILED',
        source_path: '',
        completed_at: '2026-05-10T11:20:00Z',
        copied_bytes: 0,
        total_bytes: 100,
        file_count: 4,
        files_succeeded: 1,
        files_failed: 2,
        files_timed_out: 1,
      },
    ])
    mocks.getShares.mockResolvedValue([
      { id: 16, status: 'MOUNTED', remote_path: '//server/case-062', project_id: 'PROJ-062', related_job: { job_id: 62, status: 'RUNNING', custody_status: 'PENDING_HANDOFF' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.sourceMount'))
    expect(wrapper.text()).toContain(i18n.global.t('shares.redactedValue'))
    expect(wrapper.text()).not.toContain('//server/case-062')
    expect(wrapper.text()).toContain('/case/subfolder')
    expect(wrapper.text()).toContain(i18n.global.t('jobs.destinationDrive'))
    expect(wrapper.text()).toContain('Apricorn Aegis - Port 4')
    expect(wrapper.text()).toContain(i18n.global.t('jobs.copyRate'))
    expect(wrapper.text()).toContain(i18n.global.t('jobs.timeRemaining'))
    expect(wrapper.text()).toContain(i18n.global.t('jobs.estimatedCompletion'))
    expect(wrapper.text()).toContain(i18n.global.t('jobs.filesFailed'))
    expect(wrapper.text()).toContain(i18n.global.t('jobs.filesTimedOut'))

    const notAvailable = i18n.global.t('common.labels.notAvailable')
    expect(wrapper.text()).toContain(`${i18n.global.t('dashboard.sourceMount')}${notAvailable}`)
    expect(wrapper.text()).toContain(`${i18n.global.t('jobs.sourcePath')}${notAvailable}`)
    expect(wrapper.text()).toContain(`${i18n.global.t('jobs.destinationDrive')}${notAvailable}`)

    const rows = wrapper.findAll('.row-stub')
    const activeRow = rows.find((node) => node.text().includes('62'))
    expect(activeRow.find('.active-jobs-job-id-cell').text()).toBe('62')
    expect(activeRow.find('.active-jobs-project-meta').text()).toContain(i18n.global.t('dashboard.sourceMount'))
    expect(activeRow.find('.active-jobs-project-meta').text()).toContain(i18n.global.t('jobs.sourcePath'))
    expect(activeRow.find('.active-jobs-project-meta').text()).toContain(i18n.global.t('jobs.destinationDrive'))
    expect(activeRow.find('.dashboard-status-icon').attributes('aria-label')).toBe('RUNNING')
  })

  it('keeps active job next-step and progress metadata separately addressable for mobile compaction', async () => {
    mocks.listAllJobs.mockResolvedValue([
      {
        id: 65,
        project_id: 'PROJ-065',
        status: 'RUNNING',
        source_path: '/evidence',
        copy_started_at: '2026-05-10T10:05:05Z',
        copied_bytes: 10 * 1024 * 1024,
        total_bytes: 20 * 1024 * 1024,
        file_count: 10,
        files_succeeded: 5,
        files_failed: 2,
        files_timed_out: 1,
        active_duration_seconds: 10,
      },
    ])
    mocks.getShares.mockResolvedValue([
      { id: 18, status: 'MOUNTED', remote_path: '//server/case-065', project_id: 'PROJ-065', related_job: { job_id: 65, status: 'RUNNING', custody_status: 'PENDING_HANDOFF' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const row = wrapper.findAll('.row-stub').find((node) => node.text().includes('65'))

    expect(row.find('.active-jobs-next-step-meta').text()).toContain(i18n.global.t('jobs.filesFailed'))
    expect(row.find('.active-jobs-next-step-meta').text()).toContain(i18n.global.t('jobs.filesTimedOut'))
    expect(row.find('.active-jobs-progress-meta').text()).toContain(i18n.global.t('jobs.copyRate'))
    expect(row.find('.active-jobs-progress-meta').text()).toContain(i18n.global.t('jobs.timeRemaining'))
    expect(row.find('.dashboard-progress-mobile-label').text()).toBe('50%')
  })

  it('hides copy-phase metrics while a job is still preparing', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-10T10:06:00Z'))

    mocks.listAllJobs.mockResolvedValue([
      {
        id: 64,
        project_id: 'PROJ-064',
        status: 'PREPARING',
        source_path: '/case/preparing',
        started_at: '2026-05-10T10:05:00Z',
        copied_bytes: 0,
        total_bytes: 20 * 1024 * 1024,
        file_count: 10,
        files_succeeded: 0,
        files_failed: 0,
        files_timed_out: 0,
        active_duration_seconds: 0,
      },
    ])
    mocks.getShares.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.copyRate'))
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.timeRemaining'))
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.estimatedCompletion'))

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('renders dashboard tables with the real column order used by mobile selectors', async () => {
    mocks.listAllJobs.mockResolvedValue([
      {
        id: 67,
        project_id: 'PROJ-067',
        status: 'FAILED',
        copied_bytes: 0,
        total_bytes: 100,
        file_count: 1,
        files_succeeded: 0,
        files_failed: 1,
      },
      {
        id: 66,
        project_id: 'PROJ-066',
        status: 'RUNNING',
        copied_bytes: 100,
        total_bytes: 200,
        file_count: 2,
        files_succeeded: 1,
        files_failed: 0,
      },
    ])
    mocks.getShares.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const tables = wrapper.findAll('table.data-table-stub')
    const needsAttentionHeaders = tables[0].findAll('th').map((node) => node.text())
    const activeJobsHeaders = tables[1].findAll('th').map((node) => node.text())

    expect(needsAttentionHeaders.slice(0, 2)).toEqual([
      i18n.global.t('dashboard.jobId'),
      i18n.global.t('dashboard.project'),
    ])
    expect(activeJobsHeaders.slice(0, 3)).toEqual([
      i18n.global.t('dashboard.jobId'),
      i18n.global.t('dashboard.project'),
      i18n.global.t('common.labels.status'),
    ])
  })

  it('shows raw source mount paths only to admin and manager roles', async () => {
    mocks.authStore.hasRole.mockImplementation((role) => role === 'manager')
    mocks.listAllJobs.mockResolvedValue([
      {
        id: 64,
        project_id: 'PROJ-064',
        status: 'RUNNING',
        source_path: '/evidence',
        copied_bytes: 0,
        total_bytes: 100,
        file_count: 1,
        files_succeeded: 0,
        files_failed: 0,
      },
    ])
    mocks.getShares.mockResolvedValue([
      { id: 17, status: 'MOUNTED', remote_path: '//server/case-064', project_id: 'PROJ-064', related_job: { job_id: 64, status: 'RUNNING', custody_status: 'PENDING_HANDOFF' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('//server/case-064')
    expect(wrapper.text()).not.toContain(i18n.global.t('shares.redactedValue'))
  })

  it('shows an empty needs-attention state when no follow-up items are present', async () => {
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getShares.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.noNeedsAttention'))
  })

  it('refreshes jobs, drives, and mounts on the same poll tick as system health', async () => {
    mocks.getSystemHealth.mockResolvedValueOnce({ status: 'ok', database: 'connected', active_jobs: 1 })
    mocks.getDrives.mockResolvedValueOnce([{ id: 1, current_state: 'AVAILABLE' }])
    mocks.getShares.mockResolvedValueOnce([
      { id: 10, status: 'UNMOUNTED', project_id: 'PROJ-000', related_job: { job_id: null, status: 'NO_RELATED_JOB', custody_status: 'NO_RELATED_JOB' } },
    ])
    mocks.listAllJobs.mockResolvedValueOnce([
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
    mocks.getShares.mockResolvedValueOnce([
      { id: 11, status: 'MOUNTED', project_id: 'PROJ-001', related_job: { job_id: 31, status: 'PENDING', custody_status: 'PENDING_HANDOFF' } },
    ])
    mocks.listAllJobs.mockResolvedValueOnce([])

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
    expect(mocks.getShares).toHaveBeenCalledTimes(2)
    expect(mocks.listAllJobs).toHaveBeenCalledTimes(2)
  })

  it('keeps running progress aligned with finished file counts', async () => {
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([])
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
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getShares.mockResolvedValue([
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

    expect(wrapper.text()).toContain(i18n.global.t('dashboard.sharesSummary'))

    const summaryRows = wrapper
      .findAll('.summary-link')
      .map((row) => row.text())
      .filter((text) => text.includes(i18n.global.t('dashboard.mountUnassigned'))
        || text.includes(i18n.global.t('dashboard.mountAssigned'))
        || text.includes(i18n.global.t('dashboard.mountActive'))
        || text.includes(i18n.global.t('dashboard.mountBlocked'))
        || text.includes(i18n.global.t('dashboard.mountCustodyPending'))
        || text.includes(i18n.global.t('dashboard.mountCompleted'))
        || text.includes(i18n.global.t('dashboard.mountUnavailable')))
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountUnassigned')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountAssigned')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountActive')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountBlocked')}2`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountCustodyPending')}1`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountCompleted')}2`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountUnavailable')}1`)
  })

  it('keeps completed and archived pending-handoff mounts out of the completed bucket', async () => {
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getShares.mockResolvedValue([
      { id: 24, status: 'MOUNTED', project_id: 'PROJ-024', related_job: { job_id: 44, status: 'COMPLETED', custody_status: 'PENDING_HANDOFF' } },
      { id: 25, status: 'MOUNTED', project_id: 'PROJ-025', related_job: { job_id: 45, status: 'ARCHIVED', custody_status: 'PENDING_HANDOFF' } },
      { id: 26, status: 'MOUNTED', project_id: 'PROJ-026', related_job: { job_id: 46, status: 'COMPLETED', custody_status: 'HANDOFF_RECORDED' } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const summaryRows = wrapper
      .findAll('.summary-link')
      .map((row) => row.text())
      .filter((text) => text.includes(i18n.global.t('dashboard.mountCustodyPending')) || text.includes(i18n.global.t('dashboard.mountCompleted')))
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountCustodyPending')}2`)
    expect(summaryRows).toContain(`${i18n.global.t('dashboard.mountCompleted')}1`)
  })

  it('shows unavailable mounts explicitly instead of silently dropping them', async () => {
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getShares.mockResolvedValue([
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
    mocks.getShares.mockRejectedValue(new Error('mounts unavailable'))
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([
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
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.sharesSummary'))
    expect(wrapper.text()).not.toContain(i18n.global.t('dashboard.needsAttention'))
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.activeJobs'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.systemHealth'))
  })

  it('renders the Job ID cell as a link to Job Detail for active jobs', async () => {
    mocks.listAllJobs.mockResolvedValue([
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
    mocks.listAllJobs.mockResolvedValue([
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
