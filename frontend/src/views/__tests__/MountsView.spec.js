import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import MountsView from '@/views/MountsView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getMounts: vi.fn(),
  listAllJobs: vi.fn(),
  createMount: vi.fn(),
  updateMount: vi.fn(),
  deleteMount: vi.fn(),
  validateAllMounts: vi.fn(),
  validateMountCandidate: vi.fn(),
  validateMount: vi.fn(),
  discoverMountShares: vi.fn(),
  getPublicAuthConfig: vi.fn(),
}))

const authState = vi.hoisted(() => ({
  roles: ['admin', 'manager'],
}))

const viewportState = vi.hoisted(() => ({
  mobile: false,
}))

const matchMediaListeners = vi.hoisted(() => new Set())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
  createMount: (...args) => mocks.createMount(...args),
  updateMount: (...args) => mocks.updateMount(...args),
  deleteMount: (...args) => mocks.deleteMount(...args),
  validateAllMounts: (...args) => mocks.validateAllMounts(...args),
  validateMountCandidate: (...args) => mocks.validateMountCandidate(...args),
  validateMount: (...args) => mocks.validateMount(...args),
  discoverMountShares: (...args) => mocks.discoverMountShares(...args),
}))

vi.mock('@/api/auth.js', () => ({
  getPublicAuthConfig: (...args) => mocks.getPublicAuthConfig(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  listAllJobs: (...args) => mocks.listAllJobs(...args),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: (roles) => roles.some((role) => authState.roles.includes(role)),
  }),
}))

function buildMount(overrides = {}) {
  return {
    id: 11,
    type: 'SMB',
    project_id: 'PROJ-011',
    nfs_client_version: null,
    remote_path: '//server/share',
    local_mount_point: '/smb/project2',
    status: 'UNMOUNTED',
    last_checked_at: null,
    ...overrides,
  }
}

function mountView() {
  return mount(MountsView, {
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        DataTable: {
          props: ['rows', 'columns'],
          template: `
            <div>
              <div class="column-labels">{{ (columns || []).map((column) => column.label).join('|') }}</div>
              <div v-for="row in rows" :key="row.id" class="row-stub">
                <span class="row-id"><slot name="cell-id" :row="row" /></span>
                <span class="row-project">{{ row.project_id || '-' }}</span>
                <span class="row-job-id">{{ row.current_project_job_id || '-' }}</span>
                <slot name="cell-project_id" :row="row" />
                <slot name="cell-current_project_job_id" :row="row" />
                <slot name="cell-status" :row="row" />
                <slot name="cell-last_checked_at" :row="row" />
              </div>
            </div>
          `,
        },
        Pagination: {
          template: '<div class="pagination-stub" />',
        },
        StatusBadge: {
          props: ['status'],
          template: '<span>{{ status }}</span>',
        },
        ConfirmDialog: {
          props: ['modelValue', 'title', 'message', 'confirmLabel', 'cancelLabel'],
          emits: ['update:modelValue', 'confirm'],
          template: `
            <div v-if="modelValue" class="confirm-dialog-stub">
              <h2>{{ title }}</h2>
              <p>{{ message }}</p>
              <button class="confirm-btn" @click="$emit('confirm')">{{ confirmLabel }}</button>
              <button class="cancel-btn" @click="$emit('update:modelValue', false)">{{ cancelLabel }}</button>
            </div>
          `,
        },
        DirectoryBrowser: {
          props: ['mountPath', 'mountId', 'rootLabel', 'showRootCrumbAtRoot'],
          template: '<div class="directory-browser-stub">{{ mountId ?? mountPath }}|{{ rootLabel }}|{{ showRootCrumbAtRoot }}</div>',
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

function findDialogButton(wrapper, label) {
  return wrapper.find('.dialog-actions').findAll('button').find((node) => node.text() === label)
}

function findDialogSuccessBanner(wrapper) {
  return wrapper.find('.dialog-panel .success-banner')
}

describe('MountsView removal flow', () => {
  beforeEach(() => {
    authState.roles = ['admin', 'manager']
    viewportState.mobile = false
    matchMediaListeners.clear()
    installMatchMediaMock()
    mocks.push.mockReset()
    mocks.getMounts.mockReset()
    mocks.listAllJobs.mockReset()
    mocks.createMount.mockReset()
    mocks.updateMount.mockReset()
    mocks.deleteMount.mockReset()
    mocks.validateAllMounts.mockReset()
    mocks.validateMountCandidate.mockReset()
    mocks.validateMount.mockReset()
    mocks.discoverMountShares.mockReset()
    mocks.getPublicAuthConfig.mockReset()

    mocks.createMount.mockResolvedValue({})
    mocks.updateMount.mockResolvedValue({})
    mocks.deleteMount.mockResolvedValue({})
  mocks.listAllJobs.mockResolvedValue([])
    mocks.validateAllMounts.mockResolvedValue([])
    mocks.validateMountCandidate.mockResolvedValue(buildMount({ id: 999, status: 'MOUNTED' }))
    mocks.validateMount.mockResolvedValue(buildMount())
    mocks.discoverMountShares.mockResolvedValue({
      shares: [
        { remote_path: '//server/CaseDrop', display_name: 'CaseDrop' },
        { remote_path: '//server/Review', display_name: 'Review' },
      ],
    })
    mocks.getPublicAuthConfig.mockResolvedValue({
      demo_mode_enabled: false,
      default_nfs_client_version: '4.1',
      nfs_client_version_options: ['4.2', '4.1', '4.0', '3'],
    })
  })

  it('links the mount ID value to the mount detail page', async () => {
    mocks.getMounts.mockResolvedValueOnce([buildMount({ status: 'UNMOUNTED' })])

    const wrapper = mountView()
    await flushPromises()

    const detailButton = wrapper.findAll('.mount-id-link')
    expect(detailButton).toHaveLength(1)
    expect(detailButton[0].text()).toBe('11')

    await detailButton[0].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'mount-detail', params: { id: 11 } })
  })

  it('uses the project value as the browse entry point for a mounted share', async () => {
    mocks.getMounts.mockResolvedValueOnce([buildMount({ status: 'MOUNTED', local_mount_point: '/smb/demo-case-002' })])

    const wrapper = mountView()
    await flushPromises()

    const browseButton = wrapper.findAll('.mount-project-link')
    expect(browseButton).toHaveLength(1)
    expect(browseButton[0].text()).toBe('PROJ-011')

    await browseButton[0].trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Browse mount PROJ-011 contents')
    expect(wrapper.find('.directory-browser-stub').text()).toBe('11||true')
  })

  it('does not expose separate browse, edit, or remove buttons in the desktop list', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ status: 'MOUNTED' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).toContain('11')
    expect(labels).toContain('PROJ-011')
    expect(labels).not.toContain(i18n.global.t('mounts.browse'))
    expect(labels).not.toContain(i18n.global.t('mounts.details'))
    expect(labels).not.toContain(i18n.global.t('common.actions.edit'))
    expect(labels).not.toContain(i18n.global.t('mounts.remove'))
  })

  it('does not render a separate browse action control when the mount ID is clickable', async () => {
    mocks.getMounts.mockResolvedValueOnce([buildMount({ status: 'MOUNTED', local_mount_point: '/smb/demo-case-002' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.mount-id-link').exists()).toBe(true)
    expect(wrapper.find('.mount-project-link').exists()).toBe(true)
    expect(wrapper.text()).not.toContain(i18n.global.t('mounts.browse'))
  })

  it('omits wide metadata columns in mobile view while keeping compact status and mount-id browsing', async () => {
    viewportState.mobile = true
    installMatchMediaMock()
    mocks.getMounts.mockResolvedValue([buildMount({ status: 'MOUNTED' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('common.labels.type'))
    expect(labels).not.toContain(i18n.global.t('mounts.lastChecked'))
    expect(wrapper.find('.mount-status-icon').attributes('aria-label')).toBe('MOUNTED')
    expect(wrapper.find('.mount-id-link').exists()).toBe(true)
    expect(wrapper.find('.mount-project-link').exists()).toBe(true)
  })

  it('shows the related project job ID and links it to Job Detail', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ project_id: 'PROJ-011' })])
    mocks.listAllJobs.mockResolvedValue([
      { id: 27, project_id: 'PROJ-011', evidence_number: 'EV-027' },
    ])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).toContain(i18n.global.t('dashboard.project'))
    expect(labels).toContain(i18n.global.t('jobs.jobId'))

    const jobButton = wrapper
      .findAll('.cell-link')
      .find((node) => node.text() === '27')

    expect(jobButton).toBeTruthy()

    await jobButton.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 27 } })
  })

  it('uppercases the project ID as the operator types and submits it normalized', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/new-share')
    await wrapper.find('#mount-project-id').setValue('proj-new')

    expect(wrapper.find('#mount-project-id').element.value).toBe('PROJ-NEW')

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.create')).trigger('click')
    await flushPromises()

    expect(mocks.validateMountCandidate).toHaveBeenCalledWith({
      type: 'SMB',
      remote_path: '//server/new-share',
      project_id: 'PROJ-NEW',
      username: null,
      password: null,
      credentials_file: null,
    })
    expect(mocks.createMount).toHaveBeenCalledWith({
      type: 'SMB',
      remote_path: '//server/new-share',
      project_id: 'PROJ-NEW',
      username: null,
      password: null,
      credentials_file: null,
    })
  })

  it('shows the configured NFS client version selector and submits the selected version for NFS mounts', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-type').setValue('NFS')
    await wrapper.find('#mount-remote-path').setValue('192.168.20.240:/volume1/demo-case-001')
    await wrapper.find('#mount-project-id').setValue('proj-nfs42')

    const versionSelect = wrapper.find('#mount-nfs-client-version')
    expect(versionSelect.exists()).toBe(true)
    expect(versionSelect.element.value).toBe('')

    await versionSelect.setValue('4.2')
    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.create')).trigger('click')
    await flushPromises()

    expect(mocks.validateMountCandidate).toHaveBeenCalledWith({
      type: 'NFS',
      remote_path: '192.168.20.240:/volume1/demo-case-001',
      project_id: 'PROJ-NFS42',
      nfs_client_version: '4.2',
      username: null,
      password: null,
      credentials_file: null,
    })
    expect(mocks.createMount).toHaveBeenCalledWith({
      type: 'NFS',
      remote_path: '192.168.20.240:/volume1/demo-case-001',
      project_id: 'PROJ-NFS42',
      nfs_client_version: '4.2',
      username: null,
      password: null,
      credentials_file: null,
    })
  })

  it('omits the per-mount NFS version when the dialog is left on the default option', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-type').setValue('NFS')
    await wrapper.find('#mount-remote-path').setValue('192.168.20.240:/volume1/default-share')
    await wrapper.find('#mount-project-id').setValue('proj-default')

    const versionSelect = wrapper.find('#mount-nfs-client-version')
    expect(versionSelect.element.value).toBe('')

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.create')).trigger('click')
    await flushPromises()

    expect(mocks.validateMountCandidate).toHaveBeenCalledWith({
      type: 'NFS',
      remote_path: '192.168.20.240:/volume1/default-share',
      project_id: 'PROJ-DEFAULT',
      username: null,
      password: null,
      credentials_file: null,
    })
    expect(mocks.createMount).toHaveBeenCalledWith({
      type: 'NFS',
      remote_path: '192.168.20.240:/volume1/default-share',
      project_id: 'PROJ-DEFAULT',
      username: null,
      password: null,
      credentials_file: null,
    })
  })

  it('moves focus into the add mount dialog and closes it on Escape', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    const mountTypeSelect = wrapper.find('#mount-type')
    expect(mountTypeSelect.exists()).toBe(true)
    expect(document.activeElement?.id).toBe('mount-type')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(false)
  })

  it('does not dismiss the add mount dialog when the overlay is clicked', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('.dialog-overlay').trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
  })

  it('marks required add-mount fields as required for assistive tech', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    const remotePath = wrapper.find('#mount-remote-path')
    const projectId = wrapper.find('#mount-project-id')

    expect(remotePath.attributes('required')).toBeDefined()
    expect(remotePath.attributes('aria-required')).toBe('true')
    expect(projectId.attributes('required')).toBeDefined()
    expect(projectId.attributes('aria-required')).toBe('true')
  })

  it('announces load errors through an alert live region', async () => {
    mocks.getMounts.mockRejectedValue(new Error('network down'))

    const wrapper = mountView()
    await flushPromises()

    const errorBanner = wrapper.find('.error-banner')
    expect(errorBanner.exists()).toBe(true)
    expect(errorBanner.attributes('role')).toBe('alert')
    expect(errorBanner.attributes('aria-live')).toBe('assertive')
  })

  it('surfaces backend load error details instead of masking them as a network outage', async () => {
    mocks.getMounts.mockRejectedValue({ response: { data: { detail: 'Database schema mismatch detected' } } })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.error-banner').text()).toContain('Database schema mismatch detected')
    expect(wrapper.text()).not.toContain(i18n.global.t('common.errors.networkError'))
  })

  it('does not expose raw mount paths in browse labels', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ status: 'MOUNTED', local_mount_point: '/smb/demo-case-002' })])

    const wrapper = mountView()
    await flushPromises()

    const browseButton = wrapper.findAll('.mount-project-link').at(0)
    expect(browseButton).toBeTruthy()
    expect(browseButton.attributes('aria-label')).not.toContain('/smb/project2')

    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('/smb/demo-case-002')
    expect(wrapper.find('.directory-browser-stub').text()).toBe('11||true')
  })

  it('does not render remote or local path columns in the mounts table', async () => {
    mocks.getMounts.mockResolvedValue([buildMount()])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('mounts.remotePath'))
    expect(labels).not.toContain(i18n.global.t('mounts.localPath'))
  })

  it('clears password and credentials fields when the dialog closes', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-password').setValue('super-secret')
    await wrapper.find('#mount-creds-file').setValue('/tmp/creds.txt')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    await addButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-password').element.value).toBe('')
    expect(wrapper.find('#mount-creds-file').element.value).toBe('')
  })

  it('discovers shares from the add dialog and fills the remote path from the selected share', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server')
    await wrapper.find('#mount-username').setValue('svc-reader')
    await wrapper.find('#mount-password').setValue('top-secret')

    const dialogButtons = wrapper.find('.dialog-actions').findAll('button').map((node) => node.text())
    expect(dialogButtons.indexOf(i18n.global.t('common.actions.cancel'))).toBeLessThan(dialogButtons.indexOf(i18n.global.t('mounts.browseShares')))
    expect(dialogButtons.indexOf(i18n.global.t('mounts.browseShares'))).toBeLessThan(dialogButtons.indexOf(i18n.global.t('common.actions.create')))

    await findDialogButton(wrapper, i18n.global.t('mounts.browseShares')).trigger('click')
    await flushPromises()

    expect(mocks.discoverMountShares).toHaveBeenCalledWith({
      type: 'SMB',
      remote_path: '//server',
      username: 'svc-reader',
      password: 'top-secret',
      credentials_file: null,
    })
    expect(wrapper.text()).toContain(i18n.global.t('mounts.browseSharesTitle'))
    expect(wrapper.find('.share-browser-panel').exists()).toBe(true)
    expect(wrapper.find('.share-discovery-scroll').exists()).toBe(true)

    const selectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.selectShare'))
    expect(selectButton).toBeTruthy()
    await selectButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-remote-path').element.value).toBe('//server/CaseDrop')
    expect(wrapper.text()).not.toContain(i18n.global.t('mounts.browseSharesTitle'))
  })

  it('hides share discovery controls in demo mode', async () => {
    mocks.getMounts.mockResolvedValue([])
    mocks.getPublicAuthConfig.mockResolvedValue({ demo_mode_enabled: true })

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.dialog-actions').text()).not.toContain(i18n.global.t('mounts.browseShares'))
  })

  it('shows actionable guidance when share browsing is unavailable on the host', async () => {
    mocks.getMounts.mockResolvedValue([])
    mocks.discoverMountShares.mockRejectedValue({
      response: {
        data: {
          detail: 'Share browsing requires the host smbclient tool. Install smbclient on the ECUBE host, then try again.',
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server')
    await findDialogButton(wrapper, i18n.global.t('mounts.browseShares')).trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Install smbclient on the ECUBE host, then try again.')
  })

  it('requires a passing in-dialog test before a new share can be created', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/new-share')
    await wrapper.find('#mount-project-id').setValue('proj-new')

    const createButton = () => findDialogButton(wrapper, i18n.global.t('common.actions.create'))
    const testButton = () => findDialogButton(wrapper, i18n.global.t('mounts.test'))

    expect(createButton().attributes('disabled')).toBeDefined()

    await testButton().trigger('click')
    await flushPromises()

    expect(createButton().attributes('disabled')).toBeUndefined()
    expect(findDialogSuccessBanner(wrapper).text()).toContain(i18n.global.t('mounts.testSuccess'))

    await wrapper.find('#mount-remote-path').setValue('//server/new-share-2')
    await flushPromises()

    expect(createButton().attributes('disabled')).toBeDefined()
  })

  it('keeps the add dialog open and shows feedback when the in-dialog test fails', async () => {
    mocks.getMounts.mockResolvedValue([])
    mocks.validateMountCandidate.mockRejectedValue({ response: { data: { detail: 'Authentication failed for new share.' } } })

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/new-share')
    await wrapper.find('#mount-project-id').setValue('proj-new')
    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('Authentication failed for new share.')
    expect(findDialogButton(wrapper, i18n.global.t('common.actions.create')).attributes('disabled')).toBeDefined()
    expect(mocks.createMount).not.toHaveBeenCalled()
  })

  it('does not render manager-only row actions for non-manager roles', async () => {
    authState.roles = ['auditor']
    mocks.getMounts.mockResolvedValue([buildMount({ status: 'MOUNTED' })])

    const wrapper = mountView()
    await flushPromises()

    const buttonTexts = wrapper.findAll('button').map((node) => node.text())

    expect(buttonTexts).not.toContain(i18n.global.t('mounts.test'))
    expect(buttonTexts).not.toContain(i18n.global.t('common.actions.edit'))
    expect(buttonTexts).not.toContain(i18n.global.t('mounts.remove'))
    expect(buttonTexts).not.toContain(i18n.global.t('mounts.details'))
    expect(buttonTexts).toContain('11')
    expect(buttonTexts).toContain('PROJ-011')
    expect(buttonTexts).not.toContain(i18n.global.t('mounts.browse'))
  })

  it('clears the test success banner when the add dialog is cancelled', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/new-share')
    await wrapper.find('#mount-project-id').setValue('proj-new')
    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    expect(findDialogSuccessBanner(wrapper).text()).toContain(i18n.global.t('mounts.testSuccess'))

    await findDialogButton(wrapper, i18n.global.t('common.actions.cancel')).trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('mounts.testSuccess'))
  })
})
