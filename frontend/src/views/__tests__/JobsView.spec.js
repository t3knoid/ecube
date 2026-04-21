import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import JobsView from '@/views/JobsView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  listJobs: vi.fn(),
  createJob: vi.fn(),
  startJob: vi.fn(),
  pauseJob: vi.fn(),
  getDrives: vi.fn(),
  getMounts: vi.fn(),
  hasAnyRole: vi.fn(),
}))

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

describe('JobsView grouped create dialog', () => {
  beforeEach(() => {
    mocks.push.mockReset()
    mocks.listJobs.mockReset()
    mocks.createJob.mockReset()
    mocks.startJob.mockReset()
    mocks.pauseJob.mockReset()
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.hasAnyRole.mockReset()

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.listJobs.mockResolvedValue([])
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

    expect(wrapper.find('#job-project').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('#job-evidence').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-notes').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-thread-count').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-mount').attributes('disabled')).toBeDefined()
    expect(wrapper.find('#job-source-path').attributes('disabled')).toBeDefined()
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
    })
    expect(mocks.startJob).toHaveBeenCalledWith(44)
    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 44 } })
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
