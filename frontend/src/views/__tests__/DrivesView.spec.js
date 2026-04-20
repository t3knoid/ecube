import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DrivesView from '@/views/DrivesView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getDrives: vi.fn(),
  refreshDrives: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
  refreshDrives: (...args) => mocks.refreshDrives(...args),
}))

function buildDrive(overrides = {}) {
  return {
    id: 1,
    device_identifier: 'USB-001',
    port_system_path: '2-1',
    serial_number: 'SN-001',
    filesystem_type: 'ext4',
    capacity_bytes: 1024,
    // mount_path removed
    current_state: 'AVAILABLE',
    current_project_id: null,
    ...overrides,
  }
}

function mountView() {
  return mount(DrivesView, {
    global: {
      plugins: [i18n],
      stubs: {
        DataTable: {
          props: ['rows', 'columns', 'emptyText'],
          template: `
            <div>
              <div class="column-labels">{{ (columns || []).map((column) => column.label).join(' ') }}</div>
              <div v-for="row in rows" :key="row.id" class="row-stub">
                <span class="row-device">{{ row.port_system_path || '-' }}</span>
                <span class="row-serial">{{ row.serial_number || '-' }}</span>
                <slot name="cell-current_project_id" :row="row" />
                <slot name="cell-actions" :row="row" />
              </div>
              <div class="rows-count">{{ rows.length }}</div>
            </div>
          `,
        },
        Pagination: true,
        StatusBadge: {
          props: ['label'],
          template: '<span>{{ label }}</span>',
        },
        DirectoryBrowser: true,
      },
    },
  })
}

describe('DrivesView rescan and filter loading', () => {
  beforeEach(() => {
    mocks.push.mockReset()
    mocks.getDrives.mockReset()
    mocks.refreshDrives.mockReset()

    mocks.getDrives.mockResolvedValue([buildDrive()])
    mocks.refreshDrives.mockResolvedValue({ ok: true })
  })

  it('loads the default AVAILABLE view without requesting disconnected drives', async () => {
    mountView()
    await flushPromises()

    expect(mocks.getDrives).toHaveBeenCalledWith({})
  })

  it('requests disconnected drives when switching the filter to All', async () => {
    const wrapper = mountView()
    await flushPromises()

    const selects = wrapper.findAll('select')
    await selects[0].setValue('ALL')
    await flushPromises()

    expect(mocks.getDrives).toHaveBeenLastCalledWith({ include_disconnected: true })
  })

  it('rescans and reloads using the All filter payload', async () => {
    const wrapper = mountView()
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const rescanButton = buttons.find((node) => node.text() === i18n.global.t('drives.rescan'))

    await rescanButton.trigger('click')
    await flushPromises()

    expect(mocks.refreshDrives).toHaveBeenCalledTimes(1)
    expect(mocks.getDrives).toHaveBeenLastCalledWith({ include_disconnected: true })
    expect(wrapper.find('select').element.value).toBe('ALL')
  })

  it('resets the filter to All when Refresh is clicked', async () => {
    const wrapper = mountView()
    await flushPromises()

    const selects = wrapper.findAll('select')
    await selects[0].setValue('IN_USE')
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const refreshButton = buttons.find((node) => node.text() === i18n.global.t('common.actions.refresh'))

    await refreshButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('select').element.value).toBe('ALL')
    expect(mocks.getDrives).toHaveBeenLastCalledWith({ include_disconnected: true })
  })

  it('renders project IDs in uppercase even when the data arrives mixed-case', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'proj-123' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('PROJ-123')
    expect(wrapper.text()).not.toContain('proj-123')
  })

  it('shows port-based device and serial number in separate columns', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        device_identifier: 'SER-ONLY',
        port_system_path: '2-4',
        serial_number: 'SER-ONLY',
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.device'))
    expect(wrapper.text()).toContain(i18n.global.t('drives.serialNumber'))
    expect(wrapper.text()).toContain('2-4')
    expect(wrapper.text()).toContain('SER-ONLY')
  })

  it('does not show the removed Browse action for a mounted available drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'AVAILABLE' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).not.toContain(i18n.global.t('drives.browse'))
  })
})
