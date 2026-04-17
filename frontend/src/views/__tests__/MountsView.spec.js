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
    remote_path: '//server/share',
    local_mount_point: '/smb/project2',
    status: 'UNMOUNTED',
    last_checked_at: null,
    ...overrides,
  }
}

function mountView() {
  return mount(MountsView, {
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
})
