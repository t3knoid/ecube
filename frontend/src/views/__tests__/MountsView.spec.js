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
  validateMount: vi.fn(),
}))

const authState = vi.hoisted(() => ({
  roles: ['admin', 'manager'],
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
  createMount: (...args) => mocks.createMount(...args),
  updateMount: (...args) => mocks.updateMount(...args),
  deleteMount: (...args) => mocks.deleteMount(...args),
  validateAllMounts: (...args) => mocks.validateAllMounts(...args),
  validateMount: (...args) => mocks.validateMount(...args),
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

describe('MountsView removal flow', () => {
  beforeEach(() => {
    authState.roles = ['admin', 'manager']
    mocks.getMounts.mockReset()
    mocks.createMount.mockReset()
    mocks.updateMount.mockReset()
    mocks.deleteMount.mockReset()
    mocks.validateAllMounts.mockReset()
    mocks.validateMount.mockReset()

    mocks.createMount.mockResolvedValue({})
    mocks.updateMount.mockResolvedValue({})
    mocks.deleteMount.mockResolvedValue({})
    mocks.validateAllMounts.mockResolvedValue([])
    mocks.validateMount.mockResolvedValue(buildMount())
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

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.create')).trigger('click')
    await flushPromises()

    expect(mocks.createMount).toHaveBeenCalledWith({
      type: 'SMB',
      remote_path: '//server/new-share',
      project_id: 'PROJ-NEW',
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

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await wrapper.find('#mount-project-id').setValue('proj-updated')

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(mocks.updateMount).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
    })
    expect(mocks.createMount).not.toHaveBeenCalled()
  })

  it('lets the operator explicitly clear stored credentials during edit', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.updateMount.mockResolvedValue(buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD', status: 'MOUNTED' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.clearStoredCredentials')).trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.save')).trigger('click')
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

  it('keeps the dialog open and shows actionable backend text when edit fails', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.updateMount.mockRejectedValue({ response: { data: { detail: 'A mount for this remote source is already configured.' } } })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('already configured')
  })

  it('keeps the dialog open when the update returns an error-status mount record', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.updateMount.mockResolvedValue(buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD', status: 'ERROR' }))

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()

    await editButton.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.save')).trigger('click')
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
})
