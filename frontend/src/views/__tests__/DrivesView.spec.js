import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DrivesView from '@/views/DrivesView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getDrives: vi.fn(),
  listAllJobs: vi.fn(),
  refreshDrives: vi.fn(),
}))

const viewportState = vi.hoisted(() => ({
  mobile: false,
}))

const matchMediaListeners = vi.hoisted(() => new Set())

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
  refreshDrives: (...args) => mocks.refreshDrives(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  listAllJobs: (...args) => mocks.listAllJobs(...args),
}))

function buildDrive(overrides = {}) {
  return {
    id: 1,
    device_identifier: 'USB-001',
    display_device_label: 'SanDisk Ultra - Port 1',
    manufacturer: 'SanDisk',
    product_name: 'Ultra',
    port_number: 1,
    port_system_path: '2-1',
    serial_number: 'SN-001',
    filesystem_type: 'ext4',
    capacity_bytes: 1024,
    mount_path: null,
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
                <span class="row-device">{{ row.display_device_label || row.port_system_path || '-' }}</span>
                <span class="row-serial">{{ row.serial_number || '-' }}</span>
                <span class="row-evidence">{{ row.current_project_evidence_number || '-' }}</span>
                <slot name="cell-current_state" :row="row" />
                <slot name="cell-current_project_id" :row="row" />
                <slot name="cell-current_project_evidence_number" :row="row" />
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

describe('DrivesView rescan and filter loading', () => {
  beforeEach(() => {
    viewportState.mobile = false
    matchMediaListeners.clear()
    installMatchMediaMock()
    mocks.push.mockReset()
    mocks.getDrives.mockReset()
    mocks.listAllJobs.mockReset()
    mocks.refreshDrives.mockReset()

    mocks.getDrives.mockResolvedValue([buildDrive()])
    mocks.listAllJobs.mockResolvedValue([])
    mocks.refreshDrives.mockResolvedValue({ ok: true })
  })

  it('loads all drives by default including disconnected drives', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getDrives).toHaveBeenCalledWith({ include_disconnected: true })
    expect(wrapper.findAll('select')[0].text()).not.toContain('Archived')
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

  it('shows the readable device label and serial number in separate columns', async () => {
    mocks.listAllJobs.mockResolvedValue([{ id: 9, project_id: 'PROJ-001', evidence_number: 'EV-009' }])
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        device_identifier: 'SER-ONLY',
        display_device_label: 'Kingston DataTraveler - Port 4',
        manufacturer: 'Kingston',
        product_name: 'DataTraveler',
        port_number: 4,
        port_system_path: '2-4',
        serial_number: 'SER-ONLY',
        current_project_id: 'PROJ-001',
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.device'))
    expect(wrapper.text()).toContain(i18n.global.t('drives.serialNumber'))
    expect(wrapper.text()).toContain(i18n.global.t('jobs.evidence'))
    expect(wrapper.text()).toContain('Kingston DataTraveler - Port 4')
    expect(wrapper.text()).toContain('SER-ONLY')
    expect(wrapper.text()).toContain('EV-009')
  })

  it('shows the Browse action for a mounted available drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'AVAILABLE', mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).toContain(i18n.global.t('drives.browse'))
  })

  it('routes compact row action menu buttons to details and browse behavior', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    const detailsButton = wrapper.find('.row-action-menu-details')
    expect(detailsButton.exists()).toBe(true)

    await detailsButton.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'drive-detail', params: { id: 1 } })

    const browseButton = wrapper.find('.row-action-menu-browse')
    expect(browseButton.exists()).toBe(true)

    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('browse.browseContents'))
  })

  it('omits serial, filesystem, and size columns in mobile view while keeping compact status and row action controls', async () => {
    viewportState.mobile = true
    installMatchMediaMock()
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('drives.serialNumber'))
    expect(labels).not.toContain(i18n.global.t('drives.filesystem'))
    expect(labels).not.toContain(i18n.global.t('common.labels.size'))
    expect(wrapper.find('.drive-status-icon').attributes('aria-label')).toBe(i18n.global.t('drives.states.available'))
    expect(wrapper.find('.row-actions-toggle-dots').exists()).toBe(true)
  })

  it('removes the filesystem column and shows project evidence in the list', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'PROJ-123' })])
    mocks.listAllJobs.mockResolvedValue([
      { id: 12, project_id: 'PROJ-123', evidence_number: 'EV-123' },
      { id: 11, project_id: 'PROJ-123', evidence_number: 'EV-OLDER' },
    ])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('drives.filesystem'))
    expect(labels).toContain(i18n.global.t('jobs.evidence'))
    expect(wrapper.find('.row-evidence').text()).toBe('EV-123')
  })

  it('links the project and evidence values to the related job detail', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'PROJ-123' })])
    mocks.listAllJobs.mockResolvedValue([
      { id: 44, project_id: 'PROJ-123', evidence_number: 'EV-123', drive: { id: 1 } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const linkedCells = wrapper.findAll('.cell-link')
    expect(linkedCells.map((node) => node.text())).toContain('PROJ-123')
    expect(linkedCells.map((node) => node.text())).toContain('EV-123')

    await linkedCells[0].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 44 } })

    await linkedCells[1].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenLastCalledWith({ name: 'job-detail', params: { id: 44 } })
  })

  it('uses the assigned drive job instead of the latest project job when multiple drives share a project', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({ id: 1, current_project_id: 'PROJ-123', display_device_label: 'Drive 1 - Port 1' }),
      buildDrive({ id: 2, current_project_id: 'PROJ-123', display_device_label: 'Drive 2 - Port 2' }),
    ])
    mocks.listAllJobs.mockResolvedValue([
      { id: 7, project_id: 'PROJ-123', evidence_number: 'EV-007', drive: { id: 1 } },
      { id: 4, project_id: 'PROJ-123', evidence_number: 'EV-004', drive: { id: 2 } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const rows = wrapper.findAll('.row-stub')
    const driveOneLinks = rows[0].findAll('.cell-link')
    const driveTwoLinks = rows[1].findAll('.cell-link')

    expect(driveOneLinks.map((node) => node.text())).toEqual(['PROJ-123', 'EV-007'])
    expect(driveTwoLinks.map((node) => node.text())).toEqual(['PROJ-123', 'EV-004'])

    await driveTwoLinks[0].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenLastCalledWith({ name: 'job-detail', params: { id: 4 } })
  })

  it('uses jobs beyond the first backend page when deriving related evidence links', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ id: 2, current_project_id: 'PROJ-123', display_device_label: 'Drive 2 - Port 2' })])
    mocks.listAllJobs.mockResolvedValue([
      { id: 7, project_id: 'PROJ-123', evidence_number: 'EV-007', drive: { id: 1 } },
      { id: 4, project_id: 'PROJ-123', evidence_number: 'EV-004', drive: { id: 2 } },
    ])

    const wrapper = mountView()
    await flushPromises()

    const linkedCells = wrapper.findAll('.cell-link')
    expect(linkedCells.map((node) => node.text())).toEqual(['PROJ-123', 'EV-004'])
  })

  it('does not show stale project evidence or job links for a formatted drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ id: 7, current_project_id: null })])
    mocks.listAllJobs.mockResolvedValue([
      { id: 44, project_id: 'PROJ-OLD', evidence_number: 'EV-OLD', drive: { id: 7 } },
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-evidence').text()).toBe('-')
    expect(wrapper.text()).not.toContain('EV-OLD')
    expect(wrapper.find('.cell-link').exists()).toBe(false)
  })

  it('sorts by project in ascending and descending order and keeps that sort after refresh', async () => {
    mocks.getDrives
      .mockResolvedValueOnce([
        buildDrive({ id: 1, current_project_id: 'proj-200', display_device_label: 'Drive C - Port 1', port_system_path: '2-1' }),
        buildDrive({ id: 2, current_project_id: 'PROJ-050', display_device_label: 'Drive A - Port 2', port_system_path: '2-2' }),
        buildDrive({ id: 3, current_project_id: 'PROJ-100', display_device_label: 'Drive B - Port 3', port_system_path: '2-3' }),
      ])
      .mockResolvedValueOnce([
        buildDrive({ id: 4, current_project_id: 'proj-300', display_device_label: 'Drive C - Port 4', port_system_path: '2-4' }),
        buildDrive({ id: 5, current_project_id: 'PROJ-150', display_device_label: 'Drive A - Port 5', port_system_path: '2-5' }),
        buildDrive({ id: 6, current_project_id: 'PROJ-250', display_device_label: 'Drive B - Port 6', port_system_path: '2-6' }),
      ])

    const wrapper = mountView()
    await flushPromises()

    const selects = wrapper.findAll('select')
    await selects[1].setValue('current_project_id')
    await flushPromises()

    let rows = wrapper.findAll('.row-stub')
    expect(rows.map((row) => row.find('.row-device').text())).toEqual(['Drive A - Port 2', 'Drive B - Port 3', 'Drive C - Port 1'])

    const sortButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.sortAsc'))
    await sortButton.trigger('click')
    await flushPromises()

    rows = wrapper.findAll('.row-stub')
    expect(rows.map((row) => row.find('.row-device').text())).toEqual(['Drive C - Port 1', 'Drive B - Port 3', 'Drive A - Port 2'])

    const refreshButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.refresh'))
    await refreshButton.trigger('click')
    await flushPromises()

    expect(wrapper.findAll('select')[1].element.value).toBe('current_project_id')
    rows = wrapper.findAll('.row-stub')
    expect(rows.map((row) => row.find('.row-device').text())).toEqual(['Drive C - Port 4', 'Drive B - Port 6', 'Drive A - Port 5'])
  })

  it('renders the readable device label instead of the raw port path when available', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        display_device_label: 'Kingston DataTraveler - Port 7',
        manufacturer: 'Kingston',
        product_name: 'DataTraveler',
        port_number: 7,
        port_system_path: '2-7',
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-device').text()).toBe('Kingston DataTraveler - Port 7')
    expect(wrapper.text()).not.toContain('2-7')
  })
})
