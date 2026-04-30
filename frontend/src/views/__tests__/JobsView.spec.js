import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import i18n from '@/i18n/index.js'
import JobsView from '@/views/JobsView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  listJobs: vi.fn(),
  hasArchivedJobs: vi.fn(),
  createJob: vi.fn(),
  startJob: vi.fn(),
  pauseJob: vi.fn(),
  getDrives: vi.fn(),
  getMounts: vi.fn(),
  hasAnyRole: vi.fn(),
}))

const viewportState = vi.hoisted(() => ({
  mobile: false,
}))

const matchMediaListeners = vi.hoisted(() => new Set())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: (...args) => mocks.hasAnyRole(...args),
  }),
}))

vi.mock('@/api/jobs.js', () => ({
  listJobs: (...args) => mocks.listJobs(...args),
  hasArchivedJobs: (...args) => mocks.hasArchivedJobs(...args),
  createJob: (...args) => mocks.createJob(...args),
  startJob: (...args) => mocks.startJob(...args),
  pauseJob: (...args) => mocks.pauseJob(...args),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
}))

function buildDrive(overrides = {}) {
  return {
    id: 1,
    device_identifier: 'USB-001',
    port_system_path: '2-1',
    current_state: 'AVAILABLE',
    current_project_id: null,
    mount_path: '/mnt/ecube/1',
    ...overrides,
  }
}

function buildMount(overrides = {}) {
  return {
    id: 11,
    project_id: 'PROJ-001',
    status: 'MOUNTED',
    remote_path: '//server/project-001',
    local_mount_point: '/nfs/project-001',
    ...overrides,
  }
}

function mountView() {
  return mount(JobsView, {
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        DataTable: {
          props: ['columns', 'rows'],
          template: `
            <div>
              <div class="columns-stub">{{ columns.map((column) => column.label).join('|') }}</div>
              <div class="rows-stub">{{ rows.length }}</div>
              <div v-for="row in rows" :key="row.id" class="row-stub">
                <div class="row-values-stub">
                  <span v-for="column in columns" :key="column.key" class="cell-stub">
                    <slot :name="'cell-' + column.key" :row="row" :value="row[column.key]" :column="column">{{ row[column.key] ?? '-' }}</slot>
                  </span>
                </div>
                <div class="row-progress-stub">
                  <slot name="cell-progress" :row="row">{{ row.progress }}</slot>
                </div>
                <div class="row-actions-stub">
                  <slot name="cell-actions" :row="row" />
                </div>
              </div>
            </div>
          `,
        },
        Pagination: true,
        StatusBadge: {
          props: ['status', 'label'],
          template: '<span>{{ label || status }}</span>',
        },
      },
    },
  })
}

function installMatchMediaMock() {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation(() => ({
      matches: viewportState.mobile,
      media: '(max-width: 768px)',
      addEventListener: (_event, listener) => matchMediaListeners.add(listener),
      removeEventListener: (_event, listener) => matchMediaListeners.delete(listener),
    })),
  })
}

describe('JobsView grouped create dialog', () => {
  beforeEach(() => {
    vi.useRealTimers()
    viewportState.mobile = false
    matchMediaListeners.clear()
    installMatchMediaMock()
    mocks.push.mockReset()
    mocks.listJobs.mockReset()
    mocks.hasArchivedJobs.mockReset()
    mocks.createJob.mockReset()
    mocks.startJob.mockReset()
    mocks.pauseJob.mockReset()
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.hasAnyRole.mockReset()

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.listJobs.mockResolvedValue([])
    mocks.hasArchivedJobs.mockResolvedValue(false)
    mocks.createJob.mockResolvedValue({ id: 44, project_id: 'PROJ-001', status: 'PENDING' })
    mocks.startJob.mockResolvedValue({ id: 44, project_id: 'PROJ-001', status: 'RUNNING' })
    mocks.pauseJob.mockResolvedValue({ id: 45, project_id: 'PROJ-001', status: 'PAUSING' })
    mocks.getDrives.mockResolvedValue([
      buildDrive({ id: 1, current_project_id: 'PROJ-001' }),
      buildDrive({ id: 2, current_project_id: null }),
      buildDrive({ id: 3, current_project_id: 'PROJ-999' }),
      buildDrive({ id: 4, device_identifier: 'USB-004', port_system_path: '2-4', current_state: 'IN_USE', current_project_id: 'PROJ-001' }),
      buildDrive({ id: 5, current_project_id: 'PROJ-001', mount_path: null }),
    ])
    mocks.getMounts.mockResolvedValue([
      buildMount({ id: 11, project_id: 'PROJ-001', status: 'MOUNTED' }),
      buildMount({ id: 12, project_id: 'PROJ-002', status: 'MOUNTED' }),
      buildMount({ id: 13, project_id: 'PROJ-001', status: 'UNMOUNTED' }),
    ])
  })

  it('shows a page message when startup analysis finishes while the list is open', async () => {
    vi.useFakeTimers()
    mocks.hasArchivedJobs.mockResolvedValueOnce(false).mockResolvedValueOnce(true)
    mocks.listJobs
      .mockResolvedValueOnce([
        {
          id: 61,
          project_id: 'PROJ-001',
          evidence_number: 'EV-061',
          status: 'PENDING',
          source_path: '/nfs/project-001',
          startup_analysis_status: 'ANALYZING',
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 61,
          project_id: 'PROJ-001',
          evidence_number: 'EV-061',
          status: 'PENDING',
          source_path: '/nfs/project-001',
          startup_analysis_status: 'READY',
        },
      ])

    const wrapper = mountView()
    await flushPromises()

    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()

    expect(mocks.listJobs).toHaveBeenCalledTimes(2)
    expect(mocks.hasArchivedJobs).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Startup analysis finished for job #61 with status Ready.')
    expect(wrapper.find('#jobs-show-archived').exists()).toBe(true)

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('excludes archived jobs by default and reloads them when requested', async () => {
    mocks.hasArchivedJobs.mockResolvedValue(true)
    mocks.listJobs
      .mockResolvedValueOnce([
        {
          id: 61,
          project_id: 'PROJ-001',
          evidence_number: 'EV-ACTIVE-001',
          status: 'COMPLETED',
          source_path: '/nfs/project-001/active',
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 61,
          project_id: 'PROJ-001',
          evidence_number: 'EV-ACTIVE-001',
          status: 'COMPLETED',
          source_path: '/nfs/project-001/active',
        },
        {
          id: 62,
          project_id: 'PROJ-001',
          evidence_number: 'EV-ARCHIVED-001',
          status: 'ARCHIVED',
          source_path: '/nfs/project-001/archived',
        },
      ])

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.listJobs).toHaveBeenNthCalledWith(1, { limit: 200, include_archived: false })
    expect(mocks.hasArchivedJobs).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('EV-ACTIVE-001')
    expect(wrapper.text()).not.toContain('EV-ARCHIVED-001')
    expect(wrapper.find('select').text()).not.toContain(i18n.global.t('jobs.statuses.archived'))

    const checkbox = wrapper.find('#jobs-show-archived')
    expect(checkbox.exists()).toBe(true)

    await checkbox.setValue(true)
    await flushPromises()

    expect(mocks.listJobs).toHaveBeenNthCalledWith(2, { limit: 200, include_archived: true })
    expect(wrapper.text()).toContain('EV-ARCHIVED-001')
  })

  it('hides the archived toggle when no archived jobs exist', async () => {
    mocks.hasArchivedJobs.mockResolvedValue(false)
    mocks.listJobs.mockResolvedValueOnce([
      {
        id: 71,
        project_id: 'PROJ-001',
        evidence_number: 'EV-ACTIVE-ONLY-001',
        status: 'COMPLETED',
        source_path: '/nfs/project-001/active-only',
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.listJobs).toHaveBeenNthCalledWith(1, { limit: 200, include_archived: false })
    expect(mocks.hasArchivedJobs).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#jobs-show-archived').exists()).toBe(false)
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.showArchivedJobs'))
  })

  it('keeps the archived toggle available when the archived probe fails', async () => {
    mocks.hasArchivedJobs.mockRejectedValueOnce(new Error('probe failed'))
    mocks.listJobs.mockResolvedValueOnce([
      {
        id: 72,
        project_id: 'PROJ-001',
        evidence_number: 'EV-ACTIVE-PROBE-FAIL-001',
        status: 'COMPLETED',
        source_path: '/nfs/project-001/active-probe-fail',
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.listJobs).toHaveBeenNthCalledWith(1, { limit: 200, include_archived: false })
    expect(mocks.hasArchivedJobs).toHaveBeenCalledTimes(1)
    expect(wrapper.find('#jobs-show-archived').exists()).toBe(true)
  })

  it('opens a grouped dialog with only the project field active initially', async () => {
    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#job-project').exists()).toBe(true)
    expect(wrapper.text()).toContain('Job details')
    expect(wrapper.text()).toContain('Source')
    expect(wrapper.text()).toContain('Destination')
    expect(wrapper.text()).toContain('Execution')
    expect(wrapper.find('.job-create-summary').exists()).toBe(true)
    expect(wrapper.find('.job-create-scroll-region').exists()).toBe(true)

    expect(wrapper.find('#job-project').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#job-evidence').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-notes').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-thread-count').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-mount').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-source-path').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-source-path').element.value).toBe('/')
    expect(wrapper.find('#job-drive').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-run-immediately').attributes('disabled')).toBeDefined()
  })

  it('filters eligible drives and mounts after the project is selected', async () => {
    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()

    const driveOptions = wrapper.find('#job-drive').findAll('option').map((node) => node.text())
    const mountOptions = wrapper.find('#job-mount').findAll('option').map((node) => node.text())

    expect(wrapper.text()).toContain(i18n.global.t('jobs.selectDrive'))
    expect(driveOptions.join(' ')).toContain('2-1')
    expect(driveOptions.join(' ')).toContain('2-4')
    expect(driveOptions.join(' ')).not.toContain('#1 -')
    expect(driveOptions.join(' ')).not.toContain('#4 -')
    expect(driveOptions.join(' ')).not.toContain('USB-001')
    expect(driveOptions.join(' ')).not.toContain('USB-004')
    expect(driveOptions.join(' ')).not.toContain('#3')
    expect(driveOptions.join(' ')).not.toContain('#5')

    expect(mountOptions.join(' ')).toContain('project-001')
    expect(mountOptions.join(' ')).not.toContain('project-002')
  })

  it('creates and optionally starts the job from the grouped dialog', async () => {
    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-77')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('folder/subfolder')
    await wrapper.find('#job-drive').setValue('1')
    await wrapper.find('#job-thread-count').setValue('3')
    await wrapper.find('#job-notes').setValue('Operator note')
    await wrapper.find('#job-callback-url').setValue('https://example.com/ecube/webhook')
    await wrapper.find('#job-run-immediately').setValue(true)

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).toHaveBeenCalledWith({
      project_id: 'PROJ-001',
      evidence_number: 'EVID-77',
      mount_id: 11,
      source_path: 'folder/subfolder',
      drive_id: 1,
      thread_count: 3,
      notes: 'Operator note',
      callback_url: 'https://example.com/ecube/webhook',
    })
    expect(mocks.startJob).toHaveBeenCalledWith(44)
    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 44 } })
  })

  it('omits callback_url when no webhook endpoint is entered', async () => {
    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-80')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('folder')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).toHaveBeenCalledWith({
      project_id: 'PROJ-001',
      evidence_number: 'EVID-80',
      mount_id: 11,
      source_path: 'folder',
      drive_id: 1,
      thread_count: 4,
      notes: undefined,
      callback_url: undefined,
    })
  })

  it('keeps slash-prefixed source paths within the selected mount', async () => {
    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-78')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('/folder/subfolder')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).toHaveBeenCalledWith({
      project_id: 'PROJ-001',
      evidence_number: 'EVID-78',
      mount_id: 11,
      source_path: '/folder/subfolder',
      drive_id: 1,
      thread_count: 4,
      notes: undefined,
    })
  })

  it('treats slash-only source input as the selected mount root', async () => {
    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-79')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('/')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).toHaveBeenCalledWith({
      project_id: 'PROJ-001',
      evidence_number: 'EVID-79',
      mount_id: 11,
      source_path: '/',
      drive_id: 1,
      thread_count: 4,
      notes: undefined,
    })
  })

  it('surfaces a specific backend conflict instead of a generic validation message', async () => {
    mocks.createJob.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Assigned drive is not mounted' },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-77')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('folder')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Assigned drive is not mounted')
  })

  it('rejects an overlapping source path in the UI before submitting create job', async () => {
    mocks.listJobs
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: 55,
          project_id: 'PROJ-001',
          evidence_number: 'EV-055',
          status: 'RUNNING',
          source_path: '/nfs/project-001/Evidence1',
          drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
        },
      ])

    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-OVERLAP')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('Evidence1')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).not.toHaveBeenCalled()
    expect(mocks.listJobs).toHaveBeenLastCalledWith({
      limit: 1000,
      offset: 0,
      drive_id: 1,
      statuses: ['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'],
    })
    expect(wrapper.text()).toContain('A job is already copying from this exact source path to the selected drive (job #55).')
  })

  it('keeps the create-dialog warning visible after a jobs refresh', async () => {
    mocks.listJobs
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: 55,
          project_id: 'PROJ-001',
          evidence_number: 'EV-055',
          status: 'RUNNING',
          source_path: '/nfs/project-001/Evidence1',
          drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
        },
      ])
      .mockResolvedValueOnce([])

    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-OVERLAP')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('Evidence1')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    const refreshButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.refresh'))
    await refreshButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.dialog-error-banner').text()).toContain('A job is already copying from this exact source path to the selected drive (job #55).')
  })

  it('does not show a loading message during manual refresh', async () => {
    let resolveRefresh
    const refreshPromise = new Promise((resolve) => {
      resolveRefresh = resolve
    })

    mocks.listJobs
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => refreshPromise)

    const wrapper = mountView()
    await flushPromises()

    const refreshButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.refresh'))
    expect(refreshButton).toBeTruthy()

    await refreshButton.trigger('click')
    await nextTick()

    expect(wrapper.text()).not.toContain(i18n.global.t('common.labels.loading'))

    resolveRefresh([])
    await flushPromises()
  })

  it('checks additional overlap pages before allowing create submission', async () => {
    const firstOverlapPage = Array.from({ length: 1000 }, (_, index) => ({
      id: index + 1,
      project_id: 'PROJ-001',
      evidence_number: `EV-BATCH-${index + 1}`,
      status: 'RUNNING',
      source_path: `/nfs/project-001/Evidence${index + 2}`,
      drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
    }))

    mocks.listJobs
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce(firstOverlapPage)
      .mockResolvedValueOnce([
        {
          id: 5001,
          project_id: 'PROJ-001',
          evidence_number: 'EV-BATCH-CONFLICT',
          status: 'PAUSED',
          source_path: '/nfs/project-001/Evidence1',
          drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
        },
      ])

    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-PAGED-OVERLAP')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('Evidence1')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).not.toHaveBeenCalled()
    expect(mocks.listJobs).toHaveBeenNthCalledWith(2, {
      limit: 1000,
      offset: 0,
      drive_id: 1,
      statuses: ['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'],
    })
    expect(mocks.listJobs).toHaveBeenNthCalledWith(3, {
      limit: 1000,
      offset: 1000,
      drive_id: 1,
      statuses: ['PENDING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'],
    })
    expect(wrapper.text()).toContain('A job is already copying from this exact source path to the selected drive (job #5001).')
  })

  it('treats paused jobs as overlap conflicts in the UI before submitting create job', async () => {
    mocks.listJobs
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          id: 56,
          project_id: 'PROJ-001',
          evidence_number: 'EV-056',
          status: 'PAUSED',
          source_path: '/nfs/project-001/Evidence1',
          drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
        },
      ])

    const wrapper = mountView()
    await flushPromises()

    const createButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.create'))
    await createButton.trigger('click')
    await flushPromises()

    await wrapper.find('#job-project').setValue('PROJ-001')
    await flushPromises()
    await wrapper.find('#job-evidence').setValue('EVID-PAUSED-OVERLAP')
    await wrapper.find('#job-mount').setValue('11')
    await wrapper.find('#job-source-path').setValue('Evidence1')
    await wrapper.find('#job-drive').setValue('1')

    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.createJob).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('A job is already copying from this exact source path to the selected drive (job #56).')
  })

  it('keeps running list progress aligned with completed file counts', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 15,
        project_id: 'PROJ-001',
        evidence_number: 'EV-015',
        status: 'RUNNING',
        source_path: '/nfs/project-001',
        total_bytes: 1000,
        copied_bytes: 1000,
        file_count: 5,
        files_succeeded: 2,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-progress-stub').text()).toContain('40%')
    expect(wrapper.find('.row-progress-stub').text()).not.toContain('100%')
  })

  it('does not show 100% when running progress rounds down to 0%', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 16,
        project_id: 'PROJ-001',
        evidence_number: 'EV-016',
        status: 'RUNNING',
        source_path: '/nfs/project-001',
        total_bytes: 27 * 1024 * 1024 * 1024,
        copied_bytes: 136 * 1024 * 1024,
        file_count: 5000,
        files_succeeded: 0,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-progress-stub').text()).toContain('0%')
    expect(wrapper.find('.row-progress-stub').text()).not.toContain('100%')
  })

  it('shows a preparing indicator while a running job is still calculating totals', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 17,
        project_id: 'PROJ-001',
        evidence_number: 'EV-017',
        status: 'RUNNING',
        source_path: '/nfs/project-001',
        total_bytes: 0,
        copied_bytes: 0,
        file_count: 0,
        files_succeeded: 0,
        files_failed: 0,
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-progress-stub').text()).toContain(i18n.global.t('jobs.progressPreparingShort'))
    expect(wrapper.find('.row-progress-stub').text()).not.toContain('100%')
  })

  it('uses Details as the row action label', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 44,
        project_id: 'PROJ-001',
        evidence_number: 'EV-044',
        status: 'PENDING',
        source_path: '/nfs/project-001',
        drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.columns-stub').text().split('|')).toEqual([
      'ID',
      'Project',
      'Evidence',
      'Device',
      'Status',
      'Progress',
      '',
    ])
    expect(wrapper.find('.row-values-stub').text()).toContain('2-1')
    expect(wrapper.find('.row-values-stub').text()).not.toContain('USB-001')
    expect(wrapper.text()).toContain('Details')
    expect(wrapper.text()).not.toContain('Open')
  })

  it('omits evidence and progress columns in mobile view while keeping compact status and row actions', async () => {
    viewportState.mobile = true
    installMatchMediaMock()
    mocks.listJobs.mockResolvedValue([
      {
        id: 44,
        project_id: 'PROJ-001',
        evidence_number: 'EV-044',
        status: 'PENDING',
        source_path: '/nfs/project-001',
        drive: { id: 1, port_system_path: '2-1', device_identifier: 'USB-001' },
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.columns-stub').text().split('|')).toEqual([
      'ID',
      'Project',
      'Device',
      'Status',
      '',
    ])
    expect(wrapper.find('.job-status-icon').attributes('aria-label')).toBe(i18n.global.t('jobs.statuses.pending'))
    expect(wrapper.find('.row-actions-toggle-dots').exists()).toBe(true)
  })

  it('routes compact row actions through the existing detail, start, and pause handlers', async () => {
    viewportState.mobile = true
    installMatchMediaMock()
    mocks.listJobs.mockResolvedValue([
      { id: 44, project_id: 'PROJ-001', evidence_number: 'EV-044', status: 'PENDING', source_path: '/nfs/project-001', thread_count: 4 },
    ])

    const startWrapper = mountView()
    await flushPromises()

    const detailsButton = startWrapper.findAll('.row-action-menu-details')[0]
    await detailsButton.trigger('click')
    await flushPromises()
    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 44 } })

    const startButton = startWrapper.findAll('.row-action-menu-start')[0]
    await startButton.trigger('click')
    await flushPromises()
    expect(mocks.startJob).toHaveBeenCalledWith(44, { thread_count: 4 })

    mocks.listJobs.mockReset()
    mocks.listJobs.mockResolvedValue([
      { id: 45, project_id: 'PROJ-001', evidence_number: 'EV-045', status: 'RUNNING', source_path: '/nfs/project-001', thread_count: 2 },
    ])

    const pauseWrapper = mountView()
    await flushPromises()

    const pauseButton = pauseWrapper.findAll('.row-action-menu-pause')[0]
    await pauseButton.trigger('click')
    await flushPromises()
    expect(mocks.pauseJob).toHaveBeenCalledWith(45)
  })

  it('does not fall back to the drive serial when the device value is missing', async () => {
    mocks.listJobs.mockResolvedValue([
      {
        id: 44,
        project_id: 'PROJ-001',
        evidence_number: 'EV-044',
        status: 'PENDING',
        source_path: '/nfs/project-001',
        drive: { id: 1, port_system_path: null, device_identifier: 'USB-001' },
      },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-values-stub').text()).toContain('-')
    expect(wrapper.find('.row-values-stub').text()).not.toContain('USB-001')
  })

  it('shows Start and Pause controls with state-aware availability', async () => {
    mocks.listJobs.mockResolvedValue([
      { id: 44, project_id: 'PROJ-001', evidence_number: 'EV-044', status: 'PENDING', source_path: '/nfs/project-001' },
      { id: 45, project_id: 'PROJ-001', evidence_number: 'EV-045', status: 'RUNNING', source_path: '/nfs/project-001' },
      { id: 46, project_id: 'PROJ-001', evidence_number: 'EV-046', status: 'PAUSING', source_path: '/nfs/project-001' },
      { id: 47, project_id: 'PROJ-001', evidence_number: 'EV-047', status: 'PAUSED', source_path: '/nfs/project-001' },
      { id: 48, project_id: 'PROJ-001', evidence_number: 'EV-048', status: 'COMPLETED', source_path: '/nfs/project-001' },
    ])

    const wrapper = mountView()
    await flushPromises()

    const rowActions = wrapper.findAll('.row-actions-stub')

    const pendingButtons = rowActions[0].findAll('button')
    expect(pendingButtons.map((button) => button.text())).toEqual(['Details', 'Start', 'Pause'])
    expect(pendingButtons[1].attributes('disabled')).toBeUndefined()
    expect(pendingButtons[2].attributes('disabled')).toBeDefined()

    const runningButtons = rowActions[1].findAll('button')
    expect(runningButtons[1].attributes('disabled')).toBeDefined()
    expect(runningButtons[2].attributes('disabled')).toBeUndefined()

    const pausingButtons = rowActions[2].findAll('button')
    expect(pausingButtons[1].attributes('disabled')).toBeDefined()
    expect(pausingButtons[2].attributes('disabled')).toBeDefined()

    const pausedButtons = rowActions[3].findAll('button')
    expect(pausedButtons[1].attributes('disabled')).toBeUndefined()
    expect(pausedButtons[2].attributes('disabled')).toBeDefined()

    const completedButtons = rowActions[4].findAll('button')
    expect(completedButtons[1].attributes('disabled')).toBeDefined()
    expect(completedButtons[2].attributes('disabled')).toBeDefined()
  })

  it('shows a waiting dialog while a pause request is completing', async () => {
    mocks.listJobs
      .mockResolvedValueOnce([
        { id: 45, project_id: 'PROJ-001', evidence_number: 'EV-045', status: 'RUNNING', source_path: '/nfs/project-001', thread_count: 2 },
      ])
      .mockResolvedValueOnce([
        { id: 45, project_id: 'PROJ-001', evidence_number: 'EV-045', status: 'PAUSING', source_path: '/nfs/project-001', thread_count: 2 },
      ])

    const wrapper = mountView()
    await flushPromises()

    const runningButtons = wrapper.findAll('.row-actions-stub')[0].findAll('button')
    await runningButtons[2].trigger('click')
    await flushPromises()

    expect(mocks.pauseJob).toHaveBeenCalledWith(45)
    expect(wrapper.text()).toContain('Pause in progress')
    expect(wrapper.text()).toContain('Waiting for active copy threads to finish')

    const refreshedButtons = wrapper.findAll('.row-actions-stub')[0].findAll('button')
    expect(refreshedButtons[1].attributes('disabled')).toBeDefined()
    expect(refreshedButtons[2].attributes('disabled')).toBeDefined()
  })

  it('starts and pauses a selected job from the list', async () => {
    mocks.listJobs.mockResolvedValue([
      { id: 44, project_id: 'PROJ-001', evidence_number: 'EV-044', status: 'PENDING', source_path: '/nfs/project-001', thread_count: 4 },
      { id: 45, project_id: 'PROJ-001', evidence_number: 'EV-045', status: 'RUNNING', source_path: '/nfs/project-001', thread_count: 2 },
    ])

    const wrapper = mountView()
    await flushPromises()

    const rowActions = wrapper.findAll('.row-actions-stub')
    const pendingButtons = rowActions[0].findAll('button')
    const runningButtons = rowActions[1].findAll('button')

    await pendingButtons[1].trigger('click')
    await flushPromises()
    expect(mocks.startJob).toHaveBeenCalledWith(44, { thread_count: 4 })

    await runningButtons[2].trigger('click')
    await flushPromises()
    expect(mocks.pauseJob).toHaveBeenCalledWith(45)
    expect(mocks.listJobs).toHaveBeenCalledTimes(3)
  })
})
