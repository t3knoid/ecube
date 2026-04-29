import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import MountsView from '@/views/MountsView.vue'

const mocks = vi.hoisted(() => ({
  getMounts: vi.fn(),
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
                <slot name="cell-status" :row="row" />
                <slot name="cell-actions" :row="row" />
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
          props: ['mountPath', 'rootLabel'],
          template: '<div class="directory-browser-stub">{{ rootLabel || mountPath }}</div>',
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
    mocks.getMounts.mockReset()
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

  it('removes an unmounted entry immediately without showing confirmation', async () => {
    mocks.getMounts
      .mockResolvedValueOnce([buildMount({ status: 'UNMOUNTED' })])
      .mockResolvedValueOnce([])

    const wrapper = mountView()
    await flushPromises()

    const removeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.remove'))
    expect(removeButton).toBeTruthy()

    await removeButton.trigger('click')
    await flushPromises()

    expect(mocks.deleteMount).toHaveBeenCalledWith(11)
    expect(wrapper.text()).not.toContain(i18n.global.t('mounts.removeConfirmTitle'))
  })

  it('still shows confirmation before removing an active mounted entry', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ status: 'MOUNTED' })])

    const wrapper = mountView()
    await flushPromises()

    const removeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.remove'))
    expect(removeButton).toBeTruthy()

    await removeButton.trigger('click')
    await flushPromises()

    expect(mocks.deleteMount).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(i18n.global.t('mounts.removeConfirmTitle'))
  })

  it('forwards compact row action menu buttons to the existing browse and remove handlers', async () => {
    mocks.getMounts
      .mockResolvedValueOnce([buildMount({ status: 'MOUNTED', local_mount_point: '/smb/demo-case-002' })])
      .mockResolvedValueOnce([])

    const wrapper = mountView()
    await flushPromises()

    const browseButton = wrapper.find('.row-action-menu-browse')
    expect(browseButton.exists()).toBe(true)

    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.directory-browser-stub').exists()).toBe(true)

    const removeButton = wrapper.find('.row-action-menu-remove')
    expect(removeButton.exists()).toBe(true)

    await removeButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('mounts.removeConfirmTitle'))
  })

  it('omits wide metadata columns in mobile view while keeping compact status and the row menu trigger', async () => {
    viewportState.mobile = true
    installMatchMediaMock()
    mocks.getMounts.mockResolvedValue([buildMount({ status: 'MOUNTED' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('common.labels.type'))
    expect(labels).not.toContain(i18n.global.t('mounts.lastChecked'))
    expect(wrapper.find('.mount-status-icon').attributes('aria-label')).toBe('MOUNTED')
    expect(wrapper.find('.row-actions-toggle-dots').exists()).toBe(true)
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

    const browseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.browse'))
    expect(browseButton).toBeTruthy()
    expect(browseButton.attributes('aria-label')).not.toContain('/smb/project2')

    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('/smb/demo-case-002')
    expect(wrapper.find('.directory-browser-stub').text()).toContain('demo-case-002')
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

  it('opens the existing dialog in edit mode with the selected mount prefilled', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ project_id: 'PROJ-EDIT', remote_path: '//server/edit-share', local_mount_point: '/smb/edit-share' })])

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    expect(wrapper.find(`#${'add-mount-dialog-title'}`).text()).toBe(i18n.global.t('mounts.editDialogTitle'))
    expect(wrapper.find('#mount-remote-path').element.value).toBe('//server/edit-share')
    expect(wrapper.find('#mount-project-id').element.value).toBe('PROJ-EDIT')
    expect(wrapper.find('#mount-local-path').element.value).toBe('/smb/edit-share')
    expect(wrapper.find('#mount-local-path').attributes('readonly')).toBeDefined()
  })

  it('submits edit mode through updateMount without creating a new mount', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await wrapper.find('#mount-project-id').setValue('proj-updated')

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(mocks.validateMount).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
    })
    expect(mocks.updateMount).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
    })
    expect(mocks.createMount).not.toHaveBeenCalled()
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

  it('lets the operator explicitly clear stored credentials during edit', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))
    mocks.updateMount.mockResolvedValue(buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD', status: 'MOUNTED' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.clearStoredCredentials')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(mocks.updateMount).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/original-share',
      project_id: 'PROJ-OLD',
      username: null,
      password: null,
      credentials_file: null,
    })
  })

  it('requires a passing in-dialog test before edited values can be saved', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await wrapper.find('#mount-project-id').setValue('proj-updated')

    const saveButton = () => findDialogButton(wrapper, i18n.global.t('common.actions.save'))
    const testButton = () => findDialogButton(wrapper, i18n.global.t('mounts.test'))

    expect(saveButton().attributes('disabled')).toBeDefined()

    await testButton().trigger('click')
    await flushPromises()

    expect(saveButton().attributes('disabled')).toBeUndefined()
    expect(findDialogSuccessBanner(wrapper).text()).toContain(i18n.global.t('mounts.testSuccess'))

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share-2')
    await flushPromises()

    expect(saveButton().attributes('disabled')).toBeDefined()
  })

  it('keeps the edit dialog footer reachable by using an internal scroll region after test success', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    const dialog = wrapper.find('.mount-dialog-panel')
    const scrollRegion = wrapper.find('.mount-dialog-scroll-region')
    const footer = wrapper.find('.dialog-footer')

    expect(dialog.exists()).toBe(true)
    expect(scrollRegion.exists()).toBe(true)
    expect(footer.exists()).toBe(true)
    expect(findDialogSuccessBanner(wrapper).text()).toContain(i18n.global.t('mounts.testSuccess'))
  })

  it('clears the test success banner when the edit dialog is cancelled', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    expect(findDialogSuccessBanner(wrapper).text()).toContain(i18n.global.t('mounts.testSuccess'))

    await findDialogButton(wrapper, i18n.global.t('common.actions.cancel')).trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('mounts.testSuccess'))
  })

  it('keeps the edit dialog open and shows feedback when the in-dialog test fails', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockRejectedValue({ response: { data: { detail: 'Authentication failed for edited share.' } } })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('Authentication failed for edited share.')
    expect(findDialogButton(wrapper, i18n.global.t('common.actions.save')).attributes('disabled')).toBeDefined()
    expect(mocks.updateMount).not.toHaveBeenCalled()
  })

  it('keeps the dialog open and shows actionable backend text when edit fails', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))
    mocks.updateMount.mockRejectedValue({ response: { data: { detail: 'A mount for this remote source is already configured.' } } })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('already configured')
  })

  it('keeps the dialog open when the update returns an error-status mount record', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))
    mocks.updateMount.mockResolvedValue(buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD', status: 'ERROR' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain(i18n.global.t('mounts.updateFailed'))
    expect(wrapper.text()).not.toContain(i18n.global.t('mounts.updateSuccess'))
  })

  it('does not render manager-only row actions for non-manager roles', async () => {
    authState.roles = ['auditor']
    mocks.getMounts.mockResolvedValue([buildMount()])

    const wrapper = mountView()
    await flushPromises()

    const buttonTexts = wrapper.findAll('button').map((node) => node.text())

    expect(buttonTexts).not.toContain(i18n.global.t('mounts.test'))
    expect(buttonTexts).not.toContain(i18n.global.t('common.actions.edit'))
    expect(buttonTexts).not.toContain(i18n.global.t('mounts.remove'))
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
