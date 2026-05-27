import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DrivesView from '@/views/DrivesView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getDrives: vi.fn(),
  refreshDrives: vi.fn(),
}))

const routeState = vi.hoisted(() => ({
  current: null,
}))

const authState = vi.hoisted(() => ({
  roles: ['admin', 'manager'],
}))

const viewportState = vi.hoisted(() => ({
  mobile: false,
}))

const matchMediaListeners = vi.hoisted(() => new Set())

vi.mock('vue-router', async () => {
  const { reactive } = await vi.importActual('vue')

  routeState.current = reactive({ query: {} })

  return {
    useRoute: () => routeState.current,
    useRouter: () => ({ push: mocks.push }),
  }
})

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
  refreshDrives: (...args) => mocks.refreshDrives(...args),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: (roles) => roles.some((role) => authState.roles.includes(role)),
  }),
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
                <span class="row-id"><slot name="cell-id" :row="row" /></span>
                <span class="row-device"><slot name="cell-display_device_label" :row="row">{{ row.display_device_label || row.port_system_path || '-' }}</slot></span>
                <span class="row-project"><slot name="cell-current_project_id" :row="row" /></span>
                <span class="row-job-id"><slot name="cell-current_project_job_id" :row="row" /></span>
                <slot name="cell-current_state" :row="row" />
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
        DirectoryBrowser: {
          props: ['mountPath', 'rootLabel'],
          template: '<div class="directory-browser-stub">{{ rootLabel }}|{{ mountPath }}</div>',
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

describe('DrivesView rescan and filter loading', () => {
  beforeEach(() => {
    authState.roles = ['admin', 'manager']
    viewportState.mobile = false
    routeState.current.query = {}
    matchMediaListeners.clear()
    installMatchMediaMock()
    mocks.push.mockReset()
    mocks.getDrives.mockReset()
    mocks.refreshDrives.mockReset()

    mocks.getDrives.mockResolvedValue([buildDrive()])
    mocks.refreshDrives.mockResolvedValue({ ok: true })
  })

  it('loads drives by default without disconnected rows', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getDrives).toHaveBeenCalledWith({ include_related_job_custody: true })
    expect(wrapper.findAll('select')[0].text()).not.toContain('Archived')
    expect(wrapper.findAll('select')[0].text()).toContain(i18n.global.t('drives.states.disabled'))
    expect(wrapper.findAll('select')[0].text()).not.toContain('UNMOUNTED')
  })

  it('requests disconnected drives when Show Disconnected drives is enabled', async () => {
    const wrapper = mountView()
    await flushPromises()

    const checkbox = wrapper.find('input[type="checkbox"]')
    await checkbox.setValue(true)
    await flushPromises()

    expect(mocks.getDrives).toHaveBeenLastCalledWith({
      include_disconnected: true,
      include_related_job_custody: true,
    })
  })

  it('preselects the disconnected filter from the route query and loads disconnected rows', async () => {
    routeState.current.query = { state: 'DISCONNECTED' }
    mocks.getDrives.mockResolvedValue([
      buildDrive({ id: 1, current_state: 'DISCONNECTED' }),
      buildDrive({ id: 2, current_state: 'AVAILABLE' }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const checkbox = wrapper.find('input[type="checkbox"]')
    const stateSelect = wrapper.findAll('select')[0]

    expect(mocks.getDrives).toHaveBeenCalledWith({
      include_disconnected: true,
      include_related_job_custody: true,
    })
    expect(stateSelect.element.value).toBe('DISCONNECTED')
    expect(checkbox.element.checked).toBe(true)
    expect(wrapper.find('.rows-count').text()).toBe('1')
  })

  it('clears the disconnected handoff when the route query changes to a different state', async () => {
    routeState.current.query = { state: 'DISCONNECTED' }
    mocks.getDrives
      .mockResolvedValueOnce([
        buildDrive({ id: 1, current_state: 'DISCONNECTED' }),
        buildDrive({ id: 2, current_state: 'AVAILABLE' }),
      ])
      .mockResolvedValueOnce([
        buildDrive({ id: 3, current_state: 'AVAILABLE' }),
      ])

    const wrapper = mountView()
    await flushPromises()

    routeState.current.query = { state: 'AVAILABLE' }
    await flushPromises()

    const checkbox = wrapper.find('input[type="checkbox"]')
    const stateSelect = wrapper.findAll('select')[0]

    expect(stateSelect.element.value).toBe('AVAILABLE')
    expect(checkbox.element.checked).toBe(false)
    expect(mocks.getDrives).toHaveBeenLastCalledWith({ include_related_job_custody: true })
    expect(wrapper.find('.rows-count').text()).toBe('1')
  })

  it('rescans and reloads using the All filter payload', async () => {
    const wrapper = mountView()
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const rescanButton = buttons.find((node) => node.text() === i18n.global.t('drives.rescan'))

    await rescanButton.trigger('click')
    await flushPromises()

    expect(mocks.refreshDrives).toHaveBeenCalledTimes(1)
    expect(mocks.getDrives).toHaveBeenLastCalledWith({ include_related_job_custody: true })
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
    expect(mocks.getDrives).toHaveBeenLastCalledWith({ include_related_job_custody: true })
  })

  it('hides the rescan action from processor-only roles', async () => {
    authState.roles = ['processor']

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).toContain(i18n.global.t('common.actions.refresh'))
    expect(labels).not.toContain(i18n.global.t('drives.rescan'))
  })

  it('shows the readable device label, project, and related job ID in the list', async () => {
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
        related_job: { job_id: 9 },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.device'))
    expect(wrapper.text()).toContain(i18n.global.t('dashboard.project'))
    expect(wrapper.text()).toContain(i18n.global.t('jobs.jobId'))
    expect(wrapper.text()).toContain('Kingston DataTraveler - Port 4')
    expect(wrapper.text()).toContain('PROJ-001')
    expect(wrapper.text()).toContain('9')
    expect(wrapper.find('.column-labels').text()).not.toContain(i18n.global.t('common.labels.size'))
  })

  it('does not infer a job ID from another drive on the same project', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        id: 1,
        display_device_label: 'Assigned Drive - Port 1',
        current_project_id: 'PROJ-LEAK-001',
        related_job: { job_id: 19 },
      }),
      buildDrive({
        id: 2,
        display_device_label: 'Spare Drive - Port 2',
        port_system_path: '2-2',
        current_project_id: 'PROJ-LEAK-001',
        related_job: { job_id: null },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const rows = wrapper.findAll('.row-stub')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('19')
    expect(rows[1].text()).not.toContain('19')
    expect(rows[1].text()).toContain('-')
  })

  it('does not match drives by serial number once the serial control is removed', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        id: 1,
        display_device_label: 'Kingston DataTraveler - Port 4',
        serial_number: 'SER-ONLY',
        current_project_id: 'PROJ-001',
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const searchInput = wrapper.find('input[type="text"]')
    await searchInput.setValue('SER-ONLY')
    await flushPromises()

    expect(wrapper.find('.rows-count').text()).toBe('0')

    await searchInput.setValue('PROJ-001')
    await flushPromises()

    expect(wrapper.find('.rows-count').text()).toBe('1')
  })

  it('uses the device label as the browse entry point for a mounted drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'AVAILABLE', mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    const deviceButton = wrapper.find('.drive-device-link')
    expect(deviceButton.exists()).toBe(true)
    expect(deviceButton.text()).toContain('SanDisk Ultra - Port 1')
    expect(deviceButton.attributes('title')).toBe('Browse drive')

    await deviceButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Browse SanDisk Ultra - Port 1 Contents')
    expect(wrapper.find('.directory-browser-stub').text()).toBe('|/mnt/ecube/1')
  })

  it('does not expose drive browsing for a disabled drive carrying a stale mount path', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({ current_state: 'DISABLED', mount_path: '/media/legacy-evidence' }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.drive-device-link').exists()).toBe(false)
    expect(wrapper.text()).toContain('SanDisk Ultra - Port 1')
    expect(wrapper.find('.directory-browser-stub').exists()).toBe(false)
  })

  it('links the drive ID value to the drive detail page', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    const linkedCells = wrapper.findAll('.drive-id-link')
    expect(linkedCells).toHaveLength(1)
    expect(linkedCells[0].text()).toBe('1')
    expect(linkedCells[0].attributes('title')).toBe('Show details of drive 1')

    await linkedCells[0].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'drive-detail', params: { id: 1 } })
  })

  it('does not render a separate browse action button when the device label is clickable', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('drives.browse'))
    expect(wrapper.find('.drive-device-link').exists()).toBe(true)
  })

  it('keeps the size column absent in mobile view while preserving compact status and device-label browsing', async () => {
    viewportState.mobile = true
    installMatchMediaMock()
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/1' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('drives.filesystem'))
    expect(labels).not.toContain(i18n.global.t('common.labels.size'))
    expect(wrapper.find('.drive-status-icon').attributes('aria-label')).toBe(i18n.global.t('drives.states.available'))
    expect(wrapper.find('.drive-device-link').exists()).toBe(true)
  })

  it('shows project and job ID columns while keeping filesystem and evidence absent from the list', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_project_id: 'PROJ-123',
        related_job: { job_id: 12 },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.find('.column-labels').text()
    expect(labels).not.toContain(i18n.global.t('drives.filesystem'))
    expect(labels).not.toContain(i18n.global.t('jobs.evidence'))
    expect(labels).toContain(i18n.global.t('dashboard.project'))
    expect(labels).toContain(i18n.global.t('jobs.jobId'))
    expect(wrapper.find('.row-project').text()).toBe('PROJ-123')
    expect(wrapper.find('.row-job-id').text()).toBe('12')
  })

  it('shows the bound project even when no related job is available', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'PROJ-777' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-project').text()).toBe('PROJ-777')
    expect(wrapper.find('.row-job-id').text()).toBe('-')
  })

  it('links the job ID value to the related job detail', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_project_id: 'PROJ-123',
        related_job: { job_id: 44 },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const linkedCells = wrapper.findAll('.row-job-id .cell-link')
    expect(linkedCells).toHaveLength(1)
    expect(linkedCells[0].text()).toBe('44')
    expect(linkedCells[0].attributes('title')).toBe('Show job ID 44')

    await linkedCells[0].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenLastCalledWith({ name: 'job-detail', params: { id: 44 } })
  })

  it('uses the per-drive related job payload when multiple drives share a project', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        id: 1,
        current_project_id: 'PROJ-123',
        display_device_label: 'Drive 1 - Port 1',
        related_job: { job_id: 7 },
      }),
      buildDrive({
        id: 2,
        current_project_id: 'PROJ-123',
        display_device_label: 'Drive 2 - Port 2',
        related_job: { job_id: 4 },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const rows = wrapper.findAll('.row-stub')
    const driveOneLinks = rows[0].findAll('.row-job-id .cell-link')
    const driveTwoLinks = rows[1].findAll('.row-job-id .cell-link')

    expect(driveOneLinks.map((node) => node.text())).toEqual(['7'])
    expect(driveTwoLinks.map((node) => node.text())).toEqual(['4'])

    await driveTwoLinks[0].trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenLastCalledWith({ name: 'job-detail', params: { id: 4 } })
  })

  it('uses the related job payload directly without a separate jobs lookup', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        id: 2,
        current_project_id: 'PROJ-123',
        display_device_label: 'Drive 2 - Port 2',
        related_job: { job_id: 4 },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const linkedCells = wrapper.findAll('.row-job-id .cell-link')
    expect(linkedCells.map((node) => node.text())).toEqual(['4'])
  })

  it('keeps the job column empty when the backend reports no related job', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        id: 7,
        current_project_id: 'PROJ-007',
        display_device_label: 'Drive 7 - Port 7',
        related_job: { job_id: null },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const linkedCells = wrapper.findAll('.row-job-id .cell-link')
    expect(linkedCells).toHaveLength(0)
    expect(wrapper.find('.row-project').text()).toBe('PROJ-007')
    expect(wrapper.find('.row-job-id').text()).toBe('-')
  })

  it('does not show a stale job link for a formatted drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ id: 7, current_project_id: null })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.row-project').text()).toBe('-')
    expect(wrapper.find('.row-job-id').text()).toBe('-')
    expect(wrapper.find('.row-job-id .cell-link').exists()).toBe(false)
  })

  it('sorts by related job ID in ascending and descending order and keeps that sort after refresh', async () => {
    mocks.getDrives
      .mockResolvedValueOnce([
        buildDrive({ id: 1, current_project_id: 'proj-200', display_device_label: 'Drive C - Port 1', port_system_path: '2-1', related_job: { job_id: 200 } }),
        buildDrive({ id: 2, current_project_id: 'PROJ-050', display_device_label: 'Drive A - Port 2', port_system_path: '2-2', related_job: { job_id: 50 } }),
        buildDrive({ id: 3, current_project_id: 'PROJ-100', display_device_label: 'Drive B - Port 3', port_system_path: '2-3', related_job: { job_id: 100 } }),
      ])
      .mockResolvedValueOnce([
        buildDrive({ id: 4, current_project_id: 'proj-300', display_device_label: 'Drive C - Port 4', port_system_path: '2-4', related_job: { job_id: 300 } }),
        buildDrive({ id: 5, current_project_id: 'PROJ-150', display_device_label: 'Drive A - Port 5', port_system_path: '2-5', related_job: { job_id: 150 } }),
        buildDrive({ id: 6, current_project_id: 'PROJ-250', display_device_label: 'Drive B - Port 6', port_system_path: '2-6', related_job: { job_id: 250 } }),
      ])

    const wrapper = mountView()
    await flushPromises()

    const selects = wrapper.findAll('select')
    await selects[1].setValue('current_project_job_id')
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

    expect(wrapper.findAll('select')[1].element.value).toBe('current_project_job_id')
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
