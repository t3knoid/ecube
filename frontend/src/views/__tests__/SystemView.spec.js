import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import SystemView from '@/views/SystemView.vue'

const mocks = vi.hoisted(() => ({
  hasRole: vi.fn(),
  routerPush: vi.fn(),
  getSystemHealth: vi.fn(),
  runSystemHealthAction: vi.fn(),
  getUsbTopology: vi.fn(),
  getBlockDevices: vi.fn(),
  getSystemMounts: vi.fn(),
  reconcileManagedMounts: vi.fn(),
  getLogFiles: vi.fn(),
  getLogLines: vi.fn(),
  downloadLogFile: vi.fn(),
  mobileViewportMatches: false,
}))

function setMobileViewport(matches) {
  mocks.mobileViewportMatches = matches
}

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn(() => ({
    matches: mocks.mobileViewportMatches,
    media: '(max-width: 768px)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
})

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasRole: mocks.hasRole,
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: mocks.routerPush,
  }),
}))

vi.mock('@/api/introspection.js', () => ({
  getSystemHealth: mocks.getSystemHealth,
  runSystemHealthAction: mocks.runSystemHealthAction,
  getUsbTopology: mocks.getUsbTopology,
  getBlockDevices: mocks.getBlockDevices,
  getSystemMounts: mocks.getSystemMounts,
  reconcileManagedMounts: mocks.reconcileManagedMounts,
}))

vi.mock('@/api/admin.js', () => ({
  getLogFiles: mocks.getLogFiles,
  getLogLines: mocks.getLogLines,
  downloadLogFile: mocks.downloadLogFile,
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

function setScrollMetrics(element, { scrollTop, scrollHeight = 400, clientHeight = 100 }) {
  Object.defineProperty(element, 'scrollHeight', {
    configurable: true,
    value: scrollHeight,
  })
  Object.defineProperty(element, 'clientHeight', {
    configurable: true,
    value: clientHeight,
  })
  Object.defineProperty(element, 'scrollTop', {
    configurable: true,
    writable: true,
    value: scrollTop,
  })
}

function mountView(options = {}) {
  return mount(SystemView, {
    ...options,
    global: {
      plugins: [i18n],
      stubs: {
        DataTable: {
          props: ['rows', 'columns'],
          template: `
            <div>
              <div class="columns-stub">{{ (columns || []).map((column) => column.label).join('|') }}</div>
              <div v-for="row in rows" :key="row.name || row.id || row.device" class="row-stub">
                <span v-for="column in columns" :key="column.key" class="cell-stub">
                  <slot :name="'cell-' + column.key" :row="row" :value="row[column.key]" :column="column">{{ row[column.key] ?? '' }}</slot>
                </span>
              </div>
            </div>
          `,
        },
        Pagination: {
          template: '<div />',
        },
        StatusBadge: {
          template: '<span><slot /></span>',
        },
        ConfirmDialog: {
          props: ['modelValue', 'title', 'message', 'confirmLabel', 'cancelLabel', 'busy'],
          template: `
            <div v-if="modelValue" class="confirm-dialog-stub">
              <h2 class="confirm-dialog-title">{{ title }}</h2>
              <p class="confirm-dialog-message">{{ message }}</p>
              <button class="confirm-dialog-cancel" @click="$emit('update:modelValue', false); $emit('cancel')">{{ cancelLabel }}</button>
              <button class="confirm-dialog-confirm" :disabled="busy" @click="$emit('confirm')">{{ confirmLabel }}</button>
            </div>
          `,
        },
      },
    },
  })
}

describe('SystemView USB topology tab', () => {
  beforeEach(() => {
    mocks.hasRole.mockReset()
    mocks.routerPush.mockReset()
    mocks.getSystemHealth.mockReset()
    mocks.runSystemHealthAction.mockReset()
    mocks.getUsbTopology.mockReset()
    mocks.getBlockDevices.mockReset()
    mocks.getSystemMounts.mockReset()
    mocks.reconcileManagedMounts.mockReset()
    mocks.getLogFiles.mockReset()
    mocks.getLogLines.mockReset()
    mocks.downloadLogFile.mockReset()
    setMobileViewport(false)

    mocks.hasRole.mockImplementation((role) => role === 'admin')
    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 0 })
    mocks.runSystemHealthAction.mockResolvedValue({ code: 'load_exfat_kernel_module', status: 'ok', message: 'Loaded exFAT runtime support.' })
    mocks.getBlockDevices.mockResolvedValue({ block_devices: [] })
    mocks.getSystemMounts.mockResolvedValue({ mounts: [] })
    mocks.reconcileManagedMounts.mockResolvedValue({
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 0,
      network_mounts_corrected: 0,
      usb_mounts_checked: 0,
      usb_mounts_corrected: 0,
      failure_count: 0,
    })
    mocks.getLogFiles.mockResolvedValue({ log_files: [] })
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'INFO ok' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    })
  })

  it('hides USB topology, block devices, and mounts tabs for auditors', async () => {
    mocks.hasRole.mockReturnValue(false)

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((button) => button.text())
    expect(labels).toContain(i18n.global.t('system.tabs.health'))
    expect(labels).not.toContain(i18n.global.t('system.tabs.usb'))
    expect(labels).not.toContain(i18n.global.t('system.tabs.block'))
    expect(labels).not.toContain(i18n.global.t('system.tabs.mounts'))
    expect(labels).not.toContain(i18n.global.t('system.tabs.logs'))
  })

  it('renders host metrics and ECUBE process diagnostics separately', async () => {
    mocks.getSystemHealth.mockResolvedValue({
      status: 'ok',
      database: 'connected',
      active_jobs: 1,
      cpu_percent: 18.5,
      physical_cores: 4,
      logical_cpus: 8,
      memory_percent: 41.2,
      memory_used_bytes: 4096,
      memory_total_bytes: 8192,
      disk_read_bytes: 1024,
      disk_write_bytes: 2048,
      worker_queue_size: 2,
      ecube_process: {
        cpu_percent: 6.5,
        cpu_time_seconds: 3.5,
        memory_rss_bytes: 4096,
        memory_vms_bytes: 8192,
        thread_count: 7,
        active_copy_thread_count: 1,
        active_copy_threads: [
          {
            job_id: 42,
            project_id: 'proj-42',
            job_status: 'RUNNING',
            configured_thread_count: 3,
            worker_label: 'copy-job-42_0',
            elapsed_seconds: 5.5,
            cpu_time_seconds: 1.0,
          },
        ],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.hostMetrics'))
    expect(wrapper.text()).toContain(i18n.global.t('system.physicalCores'))
    expect(wrapper.text()).toContain(i18n.global.t('system.logicalCpus'))
    expect(wrapper.text()).toContain('4')
    expect(wrapper.text()).toContain('8')
    expect(wrapper.text()).toContain(i18n.global.t('system.ecubeProcessTitle'))
    expect(wrapper.text()).toContain('copy-job-42_0')
    expect(wrapper.text()).toContain('PROJ-42')
    expect(wrapper.text()).toContain('RUNNING')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).not.toContain('Memory Usage')
    expect(wrapper.text()).not.toContain('Metrics Note')
  })

  it('renders a grouped thread timeline with one lane per configured thread', async () => {
    mocks.getSystemHealth.mockResolvedValue({
      status: 'ok',
      database: 'connected',
      active_jobs: 1,
      ecube_process: {
        active_copy_thread_count: 2,
        active_copy_threads: [
          {
            job_id: 42,
            project_id: 'proj-42',
            job_status: 'RUNNING',
            configured_thread_count: 3,
            worker_label: 'copy-job-42_0',
            elapsed_seconds: 5.5,
            cpu_time_seconds: 1.0,
          },
          {
            job_id: 42,
            project_id: 'proj-42',
            job_status: 'RUNNING',
            configured_thread_count: 3,
            worker_label: 'copy-job-42_2',
            elapsed_seconds: 5.5,
            cpu_time_seconds: 1.0,
          },
        ],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.threadTimelineTitle'))
    expect(wrapper.findAll('.thread-timeline-job')).toHaveLength(1)
    expect(wrapper.findAll('.thread-timeline-lane-row')).toHaveLength(3)
    expect(wrapper.text()).toContain('copy-job-42_1')
  })

  it('shows waiting timeline segments when thread status is preparing', async () => {
    mocks.getSystemHealth.mockResolvedValue({
      status: 'ok',
      database: 'connected',
      active_jobs: 1,
      ecube_process: {
        active_copy_thread_count: 1,
        active_copy_threads: [
          {
            job_id: 15,
            project_id: 'proj-15',
            job_status: 'PREPARING',
            configured_thread_count: 1,
            worker_label: 'copy-job-15_0',
            elapsed_seconds: 1.2,
            cpu_time_seconds: 0.2,
          },
        ],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const waitingSegments = wrapper.findAll('.thread-timeline-segment--waiting')
    expect(waitingSegments.length).toBeGreaterThan(0)
  })

  it('shows a timeline unavailable state when active jobs exist without thread samples', async () => {
    mocks.getSystemHealth.mockResolvedValue({
      status: 'degraded',
      database: 'connected',
      active_jobs: 2,
      ecube_process: {
        active_copy_thread_count: 0,
        active_copy_threads: [],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.threadTimelineUnavailable'))
  })

  it('polls system health while the health tab remains active', async () => {
    vi.useFakeTimers()
    try {
      mocks.getSystemHealth.mockResolvedValue({
        status: 'ok',
        database: 'connected',
        active_jobs: 0,
        ecube_process: {
          active_copy_thread_count: 0,
          active_copy_threads: [],
        },
      })

      const wrapper = mountView()
      await flushPromises()
      expect(mocks.getSystemHealth).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(2100)
      await flushPromises()

      expect(mocks.getSystemHealth).toHaveBeenCalledTimes(2)
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders explicit system-health warnings when the backend returns them', async () => {
    mocks.getSystemHealth.mockResolvedValue({
      status: 'degraded',
      database: 'connected',
      active_jobs: 0,
      warnings: [
        {
          code: 'exfat_runtime_kernel_mismatch',
          severity: 'warning',
          component: 'filesystem_runtime',
          message: 'exFAT formatting tools are available, but runtime mount support for exFAT is unavailable on this host.',
          remediation: 'Verify exFAT runtime support for the current kernel, then retry the mount.',
          actions: [
            {
              code: 'load_exfat_kernel_module',
              label: 'Load exFAT runtime support',
              description: 'Load the exFAT kernel module.',
              confirm_title: 'Load exFAT runtime support?',
              confirm_message: 'Run the host repair action?',
            },
          ],
        },
      ],
      ecube_process: {
        active_copy_thread_count: 0,
        active_copy_threads: [],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.healthWarnings'))
    expect(wrapper.text()).toContain('exFAT formatting tools are available, but runtime mount support for exFAT is unavailable on this host.')
    expect(wrapper.text()).toContain(`${i18n.global.t('system.warningRemediation')}: Verify exFAT runtime support for the current kernel, then retry the mount.`)
    expect(wrapper.text()).toContain(`${i18n.global.t('system.warningComponent')}: filesystem_runtime`)
    expect(wrapper.text()).toContain(`${i18n.global.t('system.warningCode')}: exfat_runtime_kernel_mismatch`)
    expect(wrapper.text()).toContain('Load exFAT runtime support')
  })

  it('does not render runtime repair actions for non-admin users when the backend omits them', async () => {
    mocks.hasRole.mockImplementation((role) => role === 'manager')
    mocks.getSystemHealth.mockResolvedValue({
      status: 'degraded',
      database: 'connected',
      active_jobs: 0,
      warnings: [
        {
          code: 'exfat_runtime_kernel_mismatch',
          severity: 'warning',
          component: 'filesystem_runtime',
          message: 'exFAT formatting tools are available, but runtime mount support for exFAT is unavailable on this host.',
          remediation: 'Verify exFAT runtime support for the current kernel, then retry the mount.',
          actions: [],
        },
      ],
      ecube_process: {
        active_copy_thread_count: 0,
        active_copy_threads: [],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Load exFAT runtime support')
  })

  it('confirms and runs a system-health repair action, then refreshes health', async () => {
    mocks.getSystemHealth
      .mockResolvedValueOnce({
        status: 'degraded',
        database: 'connected',
        active_jobs: 0,
        warnings: [
          {
            code: 'exfat_runtime_kernel_mismatch',
            severity: 'warning',
            component: 'filesystem_runtime',
            message: 'exFAT formatting tools are available, but runtime mount support for exFAT is unavailable on this host.',
            remediation: 'Verify exFAT runtime support for the current kernel, then retry the mount.',
            actions: [
              {
                code: 'load_exfat_kernel_module',
                label: 'Load exFAT runtime support',
                description: 'Load the exFAT kernel module.',
                confirm_title: 'Load exFAT runtime support?',
                confirm_message: 'Run the host repair action?',
              },
            ],
          },
        ],
        ecube_process: {
          active_copy_thread_count: 0,
          active_copy_threads: [],
        },
      })
      .mockResolvedValueOnce({
        status: 'ok',
        database: 'connected',
        active_jobs: 0,
        warnings: [],
        ecube_process: {
          active_copy_thread_count: 0,
          active_copy_threads: [],
        },
      })
    mocks.runSystemHealthAction.mockResolvedValue({
      code: 'load_exfat_kernel_module',
      status: 'ok',
      message: 'Loaded exFAT runtime support.',
    })

    const wrapper = mountView()
    await flushPromises()

    const actionButton = wrapper.findAll('button').find((button) => button.text() === 'Load exFAT runtime support')
    expect(actionButton).toBeTruthy()
    await actionButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-dialog-title').text()).toBe('Load exFAT runtime support?')
    expect(wrapper.find('.confirm-dialog-message').text()).toBe('Run the host repair action?')

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.runSystemHealthAction).toHaveBeenCalledWith('load_exfat_kernel_module')
    expect(mocks.getSystemHealth).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Loaded exFAT runtime support.')
  })

  it('shows a neutral informational banner when a repair action is not needed', async () => {
    mocks.getSystemHealth
      .mockResolvedValueOnce({
        status: 'degraded',
        database: 'connected',
        active_jobs: 0,
        warnings: [
          {
            code: 'exfat_runtime_kernel_mismatch',
            severity: 'warning',
            component: 'filesystem_runtime',
            message: 'exFAT formatting tools are available, but runtime mount support for exFAT is unavailable on this host.',
            remediation: 'Verify exFAT runtime support for the current kernel, then retry the mount.',
            actions: [
              {
                code: 'load_exfat_kernel_module',
                label: 'Load exFAT runtime support',
                description: 'Load the exFAT kernel module.',
                confirm_title: 'Load exFAT runtime support?',
                confirm_message: 'Run the host repair action?',
              },
            ],
          },
        ],
        ecube_process: {
          active_copy_thread_count: 0,
          active_copy_threads: [],
        },
      })
      .mockResolvedValueOnce({
        status: 'ok',
        database: 'connected',
        active_jobs: 0,
        warnings: [],
        ecube_process: {
          active_copy_thread_count: 0,
          active_copy_threads: [],
        },
      })
    mocks.runSystemHealthAction.mockResolvedValue({
      code: 'load_exfat_kernel_module',
      status: 'not_needed',
      message: 'exFAT runtime support is already available on this host.',
    })

    const wrapper = mountView()
    await flushPromises()

    const actionButton = wrapper.findAll('button').find((button) => button.text() === 'Load exFAT runtime support')
    expect(actionButton).toBeTruthy()
    await actionButton.trigger('click')
    await flushPromises()

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('exFAT runtime support is already available on this host.')
    expect(wrapper.find('.info-banner').exists()).toBe(true)
    expect(wrapper.find('.success-banner').exists()).toBe(false)
  })

  it('shows a clear empty state when no ECUBE copy threads are active', async () => {
    mocks.getSystemHealth.mockResolvedValue({
      status: 'ok',
      database: 'connected',
      active_jobs: 0,
      ecube_process: {
        active_copy_thread_count: 0,
        active_copy_threads: [],
      },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.noActiveCopyThreads'))
  })

  it('hides devices only if Serial Number, Manufacturer, Product, Speed, Vendor ID, and Product ID are all empty, and sorts by device column', async () => {
    const usbDevices = [
      { device: '', manufacturer: '', product: '', idVendor: '', idProduct: '' },
      { device: 'usb3', manufacturer: 'B', product: 'Y', idVendor: '1234', idProduct: '5678' },
      { device: null, manufacturer: null, product: null, idVendor: null, idProduct: null },
      { device: 'usb1', manufacturer: 'A', product: 'X', idVendor: '0001', idProduct: '0002' },
      { device: 'usb2', manufacturer: '', product: '', idVendor: '', idProduct: '' },
      { device: 'usb4', manufacturer: '', product: '', idVendor: '', idProduct: '1' },
      { device: 'usb5', manufacturer: '', product: 'Z', idVendor: '', idProduct: '' },
      { device: 'usb6', serial: 'SER-USB-006', manufacturer: '', product: '', idVendor: '', idProduct: '' },
      { device: 'usb7', manufacturer: '', product: '', speed: '480', idVendor: '', idProduct: '' },
    ]
    mocks.getUsbTopology.mockResolvedValue({ devices: usbDevices })

    const wrapper = mountView({ attachTo: document.body })
    await flushPromises()

    const usbButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.usb'))
    expect(usbButton).toBeTruthy()
    await usbButton.trigger('click')
    await flushPromises()

    const text = wrapper.text()
    const idx1 = text.indexOf('usb1')
    const idx3 = text.indexOf('usb3')
    const idx4 = text.indexOf('usb4')
    const idx5 = text.indexOf('usb5')
    const idx6 = text.indexOf('usb6')
    const idx7 = text.indexOf('usb7')
    expect(idx1).toBeGreaterThan(-1)
    expect(idx3).toBeGreaterThan(-1)
    expect(idx4).toBeGreaterThan(-1)
    expect(idx5).toBeGreaterThan(-1)
    expect(idx6).toBeGreaterThan(-1)
    expect(idx7).toBeGreaterThan(-1)
    expect(idx1).toBeLessThan(idx3)
    expect(idx3).toBeLessThan(idx4)
    expect(idx4).toBeLessThan(idx5)
    expect(idx5).toBeLessThan(idx6)
    expect(idx6).toBeLessThan(idx7)
    expect(text).not.toMatch(/^\s*$/m)
  })

  it('shows serial number and speed columns in USB topology', async () => {
    mocks.getUsbTopology.mockResolvedValue({
      devices: [{
        device: '2-1',
        serial: 'SER-USB-001',
        manufacturer: 'ECUBE',
        product: 'Evidence Drive',
        speed: '5000',
        idVendor: 'abcd',
        idProduct: '1234',
      }],
    })

    const wrapper = mountView()
    await flushPromises()

    const usbButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.usb'))
    expect(usbButton).toBeTruthy()
    await usbButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.serialNumber'))
    expect(wrapper.text()).toContain('SER-USB-001')
    expect(wrapper.text()).toContain(i18n.global.t('system.speed'))
    expect(wrapper.text()).toContain('5000 Mbps')
  })

  it('uses a compact USB topology table with overflow details on mobile', async () => {
    setMobileViewport(true)
    mocks.getUsbTopology.mockResolvedValue({
      devices: [{
        device: '2-1',
        serial: 'SER-USB-001',
        manufacturer: 'ECUBE',
        product: 'Evidence Drive',
        speed: '480',
        idVendor: 'abcd',
        idProduct: '1234',
      }],
    })

    const wrapper = mountView()
    await flushPromises()

    const usbButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.usb'))
    expect(usbButton).toBeTruthy()
    await usbButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.columns-stub').text()).toBe([
      i18n.global.t('system.device'),
      i18n.global.t('system.product'),
      '',
    ].join('|'))
    expect(wrapper.find('.usb-topology-menu-toggle-dots').exists()).toBe(true)
    expect(wrapper.find('.usb-product-cell').attributes('title')).toBe('Evidence Drive')
    expect(wrapper.text()).toContain('ECUBE')
    expect(wrapper.text()).toContain('SER-USB-001')
    expect(wrapper.text()).toContain(i18n.global.t('system.speed'))
    expect(wrapper.text()).toContain('480 Mbps')
    expect(wrapper.text()).toContain('abcd')
    expect(wrapper.text()).toContain('1234')
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.manufacturer'))
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.serialNumber'))
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.speed'))
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.vendorId'))
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.productId'))
  })

  it('uses a compact mounts table with overflow details on mobile', async () => {
    setMobileViewport(true)
    mocks.getSystemMounts.mockResolvedValue({
      mounts: [{
        device: '/dev/sdb1',
        mount_point: '/media/ecube/evidence-share',
        fs_type: 'ext4',
        options: 'rw,relatime',
      }],
    })

    const wrapper = mountView()
    await flushPromises()

    const mountsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.mounts'))
    expect(mountsButton).toBeTruthy()
    await mountsButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.columns-stub').text()).toBe([
      i18n.global.t('system.device'),
      i18n.global.t('system.mountPoint'),
      '',
    ].join('|'))
    expect(wrapper.find('.usb-topology-menu-toggle-dots').exists()).toBe(true)
    expect(wrapper.find('.mount-point-cell').attributes('title')).toBe('/media/ecube/evidence-share')
    expect(wrapper.text()).toContain('ext4')
    expect(wrapper.text()).toContain('rw,relatime')
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.fsType'))
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('system.options'))
  })
})

describe('SystemView logs tab', () => {
  beforeEach(() => {
    mocks.hasRole.mockReset()
    mocks.routerPush.mockReset()
    mocks.getSystemHealth.mockReset()
    mocks.runSystemHealthAction.mockReset()
    mocks.getUsbTopology.mockReset()
    mocks.getBlockDevices.mockReset()
    mocks.getSystemMounts.mockReset()
    mocks.reconcileManagedMounts.mockReset()
    mocks.getLogFiles.mockReset()
    mocks.getLogLines.mockReset()
    mocks.downloadLogFile.mockReset()

    mocks.hasRole.mockImplementation((role) => role === 'admin')
    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 0 })
    mocks.getUsbTopology.mockResolvedValue({ devices: [] })
    mocks.getBlockDevices.mockResolvedValue({ block_devices: [] })
    mocks.getSystemMounts.mockResolvedValue({ mounts: [] })
    mocks.reconcileManagedMounts.mockResolvedValue({
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 0,
      network_mounts_corrected: 0,
      usb_mounts_checked: 0,
      usb_mounts_corrected: 0,
      failure_count: 0,
    })
    mocks.getLogFiles.mockResolvedValue({ log_files: [{ name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' }] })
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app.log', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'ERROR password=[REDACTED]' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    })
  })

  it('shows logs tab for admin and loads redacted lines', async () => {
    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    expect(logsButton).toBeTruthy()
    await logsButton.trigger('click')
    await flushPromises()

    expect(mocks.getLogLines).toHaveBeenCalled()
    const lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.source).toBe('app.log')
    expect(lastCallArgs.reverse).toBe(true)
    expect(wrapper.text()).toContain('[REDACTED]')
    expect(wrapper.text()).toContain('app.log')
  })

  it('refreshes with search filter', async () => {
    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    const searchInput = wrapper.find('#log-search')
    await searchInput.setValue('error')
    await searchInput.trigger('keyup.enter')
    await flushPromises()

    const lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.search).toBe('error')
  })

  it('shows user-friendly message when logs are unavailable', async () => {
    mocks.getLogFiles.mockRejectedValue({ response: { status: 404 } })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.logsNotConfigured'))
  })

  it('shows an explicit message when no log files are available at the configured path', async () => {
    mocks.getLogFiles.mockResolvedValue({ log_files: [] })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    expect(mocks.getLogLines).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(i18n.global.t('system.logsEmpty'))
  })

  it('shows a distinct message when log access is configured but unavailable', async () => {
    mocks.getLogFiles.mockRejectedValue({ response: { status: 503 } })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.logsUnavailable'))
  })

  it('keeps the selected source options when log line fetch fails', async () => {
    mocks.getLogFiles.mockResolvedValue({
      log_files: [{ name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' }],
    })
    mocks.getLogLines.mockRejectedValue({ response: { status: 503 } })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    expect(mocks.getLogFiles).toHaveBeenCalled()
    expect(mocks.getLogLines).toHaveBeenCalled()
    expect(wrapper.find('#log-source').text()).toContain('app.log')
  })

  it('shows a source-specific message when a selected rollover file is missing', async () => {
    mocks.getLogFiles.mockResolvedValue({
      log_files: [
        { name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' },
        { name: 'app.log.1', size: 32, modified: '2026-04-08T11:00:00Z' },
      ],
    })
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'INFO current healthy', source_path: 'app.log' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 0,
      })
      .mockRejectedValueOnce({ response: { status: 404, data: { message: 'Unknown log source' } } })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    const sourceSelect = wrapper.find('#log-source')
    await sourceSelect.setValue('app.log.1')
    await flushPromises()

    expect(wrapper.text()).toContain('Unknown log source')
    expect(wrapper.text()).not.toContain(i18n.global.t('system.logsNotConfigured'))
  })

  it('clears stale log lines when paging to an older page fails', async () => {
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })
      .mockRejectedValueOnce({ response: { status: 404, data: { message: 'Unknown log source' } } })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('line 200')

    const olderButton = wrapper.findAll('button').find((button) => button.text() === i18n.global.t('system.logLoadOlder'))
    expect(olderButton.element.disabled).toBe(false)
    await olderButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(mocks.getLogLines).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Unknown log source')
    expect(wrapper.text()).not.toContain('line 200')
    expect(wrapper.text()).toContain(i18n.global.t('system.logViewerEmpty'))

    const newerButton = wrapper.findAll('button').find((button) => button.text() === i18n.global.t('system.logLoadNewer'))
    expect(newerButton.element.disabled).toBe(true)
  })

  it('restores the newer-page offset when paging to a newer page fails', async () => {
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 199', source_path: 'app.log' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 1,
      })
      .mockRejectedValueOnce({ response: { status: 503 } })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:02Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()
    await flushPromises()

    const olderButton = wrapper.findAll('button').find((button) => button.text() === i18n.global.t('system.logLoadOlder'))
    await olderButton.trigger('click')
    await flushPromises()
    await flushPromises()

    let newerButton = wrapper.findAll('button').find((button) => button.text() === i18n.global.t('system.logLoadNewer'))
    expect(newerButton.element.disabled).toBe(false)

    await newerButton.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.logsUnavailable'))
    expect(wrapper.text()).toContain(i18n.global.t('system.logViewerEmpty'))

    newerButton = wrapper.findAll('button').find((button) => button.text() === i18n.global.t('system.logLoadNewer'))
    expect(newerButton.element.disabled).toBe(false)

    await newerButton.trigger('click')
    await flushPromises()
    await flushPromises()

    const lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.offset).toBe(0)
    expect(wrapper.text()).toContain('line 200')
    expect(wrapper.text()).not.toContain('line 199')
  })

  it('renders basename only when API returns an absolute source path', async () => {
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app', path: '/var/log/ecube/app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'INFO ok' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('app.log')
    expect(wrapper.text()).not.toContain('/var/log/ecube/app.log')
  })

  it('labels log lines with rollover source names when viewing a log family', async () => {
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app.log', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [
        { content: 'ERROR newer', source_path: 'app.log' },
        { content: 'ERROR older', source_path: 'app.log.1' },
      ],
      returned: 2,
      has_more: false,
      limit: 200,
      offset: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('ERROR newer')
    expect(wrapper.text()).not.toContain('[app.log] ERROR newer')
    expect(wrapper.text()).toContain('[app.log.1] ERROR older')
  })

  it('offers rollover files in the source selector and requests the selected file', async () => {
    mocks.getLogFiles.mockResolvedValue({
      log_files: [
        { name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' },
        { name: 'app.log.1', size: 32, modified: '2026-04-08T11:00:00Z' },
      ],
    })
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app.log.1', path: 'app.log.1' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:00:00Z',
      lines: [{ content: 'ERROR older', source_path: 'app.log.1' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    const sourceSelect = wrapper.find('#log-source')
    expect(sourceSelect.text()).toContain('app.log')
    expect(sourceSelect.text()).toContain('app.log.1')
    expect(sourceSelect.text()).not.toContain('app.log*')

    await sourceSelect.setValue('app.log.1')
    await flushPromises()

    const lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.source).toBe('app.log.1')
  })

  it('loads older log lines when more content is available', async () => {
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 199', source_path: 'app.log' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 1,
      })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    const viewer = wrapper.find('.log-viewer')
    setScrollMetrics(viewer.element, { scrollTop: 300 })

    await viewer.trigger('scroll')
    await flushPromises()

    const lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.offset).toBe(1)
    expect(wrapper.text()).toContain('line 199')
    expect(wrapper.text()).not.toContain('line 200')
  })

  it('does not immediately page again from the programmatic scroll reposition after loading older lines', async () => {
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 199', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 1,
      })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    const viewer = wrapper.find('.log-viewer')
    setScrollMetrics(viewer.element, { scrollTop: 300 })
    await viewer.trigger('scroll')
    await flushPromises()

    setScrollMetrics(viewer.element, { scrollTop: 24 })
    await viewer.trigger('scroll')
    await flushPromises()

    expect(mocks.getLogLines).toHaveBeenCalledTimes(2)
  })

  it('loads newer log lines without retaining every older page in memory', async () => {
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 199', source_path: 'app.log' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 1,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:02Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    const viewer = wrapper.find('.log-viewer')
    setScrollMetrics(viewer.element, { scrollTop: 300 })
    await viewer.trigger('scroll')
    await flushPromises()

    setScrollMetrics(viewer.element, { scrollTop: 0 })
    await viewer.trigger('scroll')
    await flushPromises()

    const lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.offset).toBe(0)
    expect(wrapper.text()).toContain('line 200')
    expect(wrapper.text()).not.toContain('line 199')
  })

  it('offers keyboard-operable buttons for newer and older log pages', async () => {
    mocks.getLogLines
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:00Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:01Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 199', source_path: 'app.log' }],
        returned: 1,
        has_more: false,
        limit: 200,
        offset: 1,
      })
      .mockResolvedValueOnce({
        source: { source: 'app.log', path: 'app.log' },
        fetched_at: '2026-04-08T12:00:02Z',
        file_modified_at: '2026-04-08T11:59:00Z',
        lines: [{ content: 'line 200', source_path: 'app.log' }],
        returned: 1,
        has_more: true,
        limit: 200,
        offset: 0,
      })

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()
    await flushPromises()

    const pagingButtons = wrapper
      .findAll('button')
      .filter(
        (button) =>
          button.text() === i18n.global.t('system.logLoadOlder') || button.text() === i18n.global.t('system.logLoadNewer'),
      )

    const newerButton = pagingButtons.find((button) => button.text() === i18n.global.t('system.logLoadNewer'))
    const olderButton = pagingButtons.find((button) => button.text() === i18n.global.t('system.logLoadOlder'))

    expect(newerButton.element.disabled).toBe(true)
    expect(olderButton.element.disabled).toBe(false)

    await olderButton.trigger('click')
    await flushPromises()

    let lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.offset).toBe(1)

    await newerButton.trigger('click')
    await flushPromises()

    lastCallArgs = mocks.getLogLines.mock.calls.at(-1)?.[0] || {}
    expect(lastCallArgs.offset).toBe(0)
  })

  it('downloads the currently selected log file from the toolbar button', async () => {
    mocks.getLogFiles.mockResolvedValue({
      log_files: [
        { name: 'app.log', size: 64, modified: '2026-04-08T11:59:00Z' },
        { name: 'app.log.1', size: 32, modified: '2026-04-08T11:00:00Z' },
      ],
    })
    mocks.downloadLogFile.mockResolvedValue({
      data: new Blob(['test']),
      headers: { 'content-type': 'text/plain' },
    })

    const appendChildSpy = vi.spyOn(document.body, 'appendChild')
    const removeChildSpy = vi.spyOn(document.body, 'removeChild')
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    const wrapper = mountView()
    await flushPromises()

    const logsButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.logs'))
    await logsButton.trigger('click')
    await flushPromises()

    await wrapper.find('#log-source').setValue('app.log.1')

    const downloadButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.download'))
    await downloadButton.trigger('click')
    await flushPromises()

    expect(mocks.downloadLogFile).toHaveBeenCalledWith('app.log.1')

    appendChildSpy.mockRestore()
    removeChildSpy.mockRestore()
    createObjectURLSpy.mockRestore()
    revokeObjectURLSpy.mockRestore()
  })

  it('shows logs tab for manager users', async () => {
    mocks.hasRole.mockImplementation((role) => role === 'manager')

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels).toContain(i18n.global.t('system.tabs.logs'))
    expect(labels).not.toContain(i18n.global.t('system.download'))
  })

  it('hides logs tab for users without admin or manager roles', async () => {
    mocks.hasRole.mockReturnValue(false)

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels).not.toContain(i18n.global.t('system.tabs.logs'))
  })
})

describe('SystemView managed-mount reconciliation action', () => {
  beforeEach(() => {
    mocks.hasRole.mockReset()
    mocks.routerPush.mockReset()
    mocks.getSystemHealth.mockReset()
    mocks.runSystemHealthAction.mockReset()
    mocks.getUsbTopology.mockReset()
    mocks.getBlockDevices.mockReset()
    mocks.getSystemMounts.mockReset()
    mocks.reconcileManagedMounts.mockReset()
    mocks.getLogFiles.mockReset()
    mocks.getLogLines.mockReset()
    mocks.downloadLogFile.mockReset()

    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 0 })
    mocks.getUsbTopology.mockResolvedValue({ devices: [] })
    mocks.getBlockDevices.mockResolvedValue({ block_devices: [] })
    mocks.getSystemMounts.mockResolvedValue({ mounts: [] })
    mocks.reconcileManagedMounts.mockResolvedValue({
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 2,
      network_mounts_corrected: 1,
      usb_mounts_checked: 1,
      usb_mounts_corrected: 1,
      failure_count: 0,
    })
    mocks.getLogFiles.mockResolvedValue({ log_files: [] })
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'INFO ok' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    })
  })

  it('shows the reconcile action for admins and managers only', async () => {
    mocks.hasRole.mockImplementation((role) => role === 'admin')
    let wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain(i18n.global.t('system.reconcileManagedMounts'))

    wrapper.unmount()
    mocks.hasRole.mockImplementation((role) => role === 'manager')
    wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain(i18n.global.t('system.reconcileManagedMounts'))

    wrapper.unmount()
    mocks.hasRole.mockImplementation((role) => role === 'auditor')
    wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).not.toContain(i18n.global.t('system.reconcileManagedMounts'))
  })

  it('runs manual reconciliation and navigates to results page', async () => {
    mocks.hasRole.mockImplementation((role) => role === 'manager')

    const wrapper = mountView()
    await flushPromises()

    const button = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('system.reconcileManagedMounts'))
    expect(button).toBeTruthy()

    await button.trigger('click')
    await flushPromises()

    expect(mocks.reconcileManagedMounts).toHaveBeenCalledTimes(1)
    expect(mocks.routerPush).toHaveBeenCalledWith(expect.objectContaining({
      name: 'reconciliation-results',
      state: expect.objectContaining({
        reconciliationResult: expect.objectContaining({
          status: 'ok',
          scope: 'managed_mounts_only',
        }),
      }),
    }))
  })
})
