import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import MountsView from '@/views/MountsView.vue'

const mocks = vi.hoisted(() => ({
  getMounts: vi.fn(),
  createMount: vi.fn(),
  deleteMount: vi.fn(),
  validateAllMounts: vi.fn(),
  validateMount: vi.fn(),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
  createMount: (...args) => mocks.createMount(...args),
  deleteMount: (...args) => mocks.deleteMount(...args),
  validateAllMounts: (...args) => mocks.validateAllMounts(...args),
  validateMount: (...args) => mocks.validateMount(...args),
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
          props: ['rows'],
          template: `
            <div>
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
          template: '<div class="directory-browser-stub" />',
        },
      },
    },
  })
}

describe('MountsView removal flow', () => {
  beforeEach(() => {
    mocks.getMounts.mockReset()
    mocks.createMount.mockReset()
    mocks.deleteMount.mockReset()
    mocks.validateAllMounts.mockReset()
    mocks.validateMount.mockReset()

    mocks.createMount.mockResolvedValue({})
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

  it('submits the selected project when adding a mount', async () => {
    mocks.getMounts.mockResolvedValue([])

    const wrapper = mountView()
    await flushPromises()

    const addButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.add'))
    expect(addButton).toBeTruthy()

    await addButton.trigger('click')
    await flushPromises()

    await wrapper.find('#mount-remote-path').setValue('//server/new-share')
    await wrapper.find('#mount-project-id').setValue('PROJ-NEW')
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
})
