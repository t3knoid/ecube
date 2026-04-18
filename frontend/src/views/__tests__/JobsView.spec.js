import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import JobsView from '@/views/JobsView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  listJobs: vi.fn(),
  createJob: vi.fn(),
  startJob: vi.fn(),
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
          props: ['rows'],
          template: '<div class="rows-stub">{{ rows.length }}</div>',
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
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.hasAnyRole.mockReset()

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.listJobs.mockResolvedValue([])
    mocks.createJob.mockResolvedValue({ id: 44, project_id: 'PROJ-001', status: 'PENDING' })
    mocks.startJob.mockResolvedValue({ id: 44, project_id: 'PROJ-001', status: 'RUNNING' })
    mocks.getDrives.mockResolvedValue([
      buildDrive({ id: 1, current_project_id: 'PROJ-001' }),
      buildDrive({ id: 2, current_project_id: null }),
      buildDrive({ id: 3, current_project_id: 'PROJ-999' }),
      buildDrive({ id: 4, device_identifier: 'USB-004', current_state: 'IN_USE', current_project_id: 'PROJ-001' }),
      buildDrive({ id: 5, mount_path: null, current_project_id: 'PROJ-001' }),
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

    expect(driveOptions.join(' ')).toContain('USB-001')
    expect(driveOptions.join(' ')).toContain('USB-004')
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
      source_path: '/nfs/project-001/folder/subfolder',
      drive_id: 1,
      thread_count: 3,
    })
    expect(mocks.startJob).toHaveBeenCalledWith(44)
    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 44 } })
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
})
