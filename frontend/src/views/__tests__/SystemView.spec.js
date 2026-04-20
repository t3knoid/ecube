describe('SystemView USB topology tab', () => {
  beforeEach(() => {
    mocks.hasRole.mockReset()
    mocks.getSystemHealth.mockReset()
    mocks.getUsbTopology.mockReset()
    mocks.getBlockDevices.mockReset()
    mocks.getSystemMounts.mockReset()
    mocks.getJobDebug.mockReset()
    mocks.getLogFiles.mockReset()
    mocks.getLogLines.mockReset()
    mocks.downloadLogFile.mockReset()
    mocks.listJobs.mockReset()

    mocks.hasRole.mockImplementation((role) => role === 'admin')
    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 0 })
    mocks.getBlockDevices.mockResolvedValue({ block_devices: [] })
    mocks.getSystemMounts.mockResolvedValue({ mounts: [] })
    mocks.getJobDebug.mockResolvedValue(null)
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
    mocks.listJobs.mockResolvedValue([])
  })

  it('hides devices only if Manufacturer, Product, Vendor ID, and Product ID are all empty, and sorts by device column', async () => {
    // Mix of empty and non-empty devices, out of order
    const usbDevices = [
      { device: '', manufacturer: '', product: '', idVendor: '', idProduct: '' }, // should be hidden
      { device: 'usb3', manufacturer: 'B', product: 'Y', idVendor: '1234', idProduct: '5678' }, // shown
      { device: null, manufacturer: null, product: null, idVendor: null, idProduct: null }, // should be hidden
      { device: 'usb1', manufacturer: 'A', product: 'X', idVendor: '0001', idProduct: '0002' }, // shown
      { device: 'usb2', manufacturer: '', product: '', idVendor: '', idProduct: '' }, // should be hidden (all 4 fields empty)
      { device: 'usb4', manufacturer: '', product: '', idVendor: '', idProduct: '1' }, // shown (idProduct present)
      { device: 'usb5', manufacturer: '', product: 'Z', idVendor: '', idProduct: '' }, // shown (product present)
    ]
    mocks.getUsbTopology.mockResolvedValue({ devices: usbDevices })

    const wrapper = mountView()
    await flushPromises()

    const usbButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('system.tabs.usb'))
    expect(usbButton).toBeTruthy()
    await usbButton.trigger('click')
    await flushPromises()

    // Only devices where all 4 fields are empty should be hidden
    // DataTable stub renders: row.name || row.id || row.device || ""
    const text = wrapper.text()
    // Should include usb1, usb3, usb4, usb5 in order
    const idx1 = text.indexOf('usb1')
    const idx3 = text.indexOf('usb3')
    const idx4 = text.indexOf('usb4')
    const idx5 = text.indexOf('usb5')
    expect(idx1).toBeGreaterThan(-1)
    expect(idx3).toBeGreaterThan(-1)
    expect(idx4).toBeGreaterThan(-1)
    expect(idx5).toBeGreaterThan(-1)
    expect(idx1).toBeLessThan(idx3)
    expect(idx3).toBeLessThan(idx4)
    expect(idx4).toBeLessThan(idx5)
    // Should not include rows where all 4 fields are empty
    expect(text).not.toMatch(/^\s*$/m)
  })
})
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import SystemView from '@/views/SystemView.vue'

const mocks = vi.hoisted(() => ({
  hasRole: vi.fn(),
  getSystemHealth: vi.fn(),
  getUsbTopology: vi.fn(),
  getBlockDevices: vi.fn(),
  getSystemMounts: vi.fn(),
  getJobDebug: vi.fn(),
  getLogFiles: vi.fn(),
  getLogLines: vi.fn(),
  downloadLogFile: vi.fn(),
  listJobs: vi.fn(),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasRole: mocks.hasRole,
  }),
}))

vi.mock('@/api/introspection.js', () => ({
  getSystemHealth: mocks.getSystemHealth,
  getUsbTopology: mocks.getUsbTopology,
  getBlockDevices: mocks.getBlockDevices,
  getSystemMounts: mocks.getSystemMounts,
  getJobDebug: mocks.getJobDebug,
}))

vi.mock('@/api/admin.js', () => ({
  getLogFiles: mocks.getLogFiles,
  getLogLines: mocks.getLogLines,
  downloadLogFile: mocks.downloadLogFile,
}))

vi.mock('@/api/jobs.js', () => ({
  listJobs: mocks.listJobs,
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

function mountView() {
  return mount(SystemView, {
    global: {
      plugins: [i18n],
      stubs: {
        DataTable: {
          props: ['rows'],
          template: '<div>{{ (rows || []).map((row) => row.name || row.id || row.device || "").join(" ") }}<slot /></div>',
        },
        Pagination: {
          template: '<div />',
        },
        StatusBadge: {
          template: '<span><slot /></span>',
        },
      },
    },
  })
}

describe('SystemView logs tab', () => {
  beforeEach(() => {
    mocks.hasRole.mockReset()
    mocks.getSystemHealth.mockReset()
    mocks.getUsbTopology.mockReset()
    mocks.getBlockDevices.mockReset()
    mocks.getSystemMounts.mockReset()
    mocks.getJobDebug.mockReset()
    mocks.getLogFiles.mockReset()
    mocks.getLogLines.mockReset()
    mocks.downloadLogFile.mockReset()
    mocks.listJobs.mockReset()

    mocks.hasRole.mockImplementation((role) => role === 'admin')
    mocks.getSystemHealth.mockResolvedValue({ status: 'ok', database: 'connected', active_jobs: 0 })
    mocks.getUsbTopology.mockResolvedValue({ devices: [] })
    mocks.getBlockDevices.mockResolvedValue({ block_devices: [] })
    mocks.getSystemMounts.mockResolvedValue({ mounts: [] })
    mocks.getJobDebug.mockResolvedValue(null)
    mocks.getLogFiles.mockResolvedValue({ log_files: [] })
    mocks.getLogLines.mockResolvedValue({
      source: { source: 'app', path: 'app.log' },
      fetched_at: '2026-04-08T12:00:00Z',
      file_modified_at: '2026-04-08T11:59:00Z',
      lines: [{ content: 'ERROR password=[REDACTED]' }],
      returned: 1,
      has_more: false,
      limit: 200,
      offset: 0,
    })
    mocks.listJobs.mockResolvedValue([])
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

  it('still shows downloadable log files when log line fetch fails', async () => {
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
    expect(wrapper.text()).toContain('app.log')
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

  it('hides logs tab for non-admin users', async () => {
    mocks.hasRole.mockReturnValue(false)

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((b) => b.text())
    expect(labels).not.toContain(i18n.global.t('system.tabs.logs'))
  })
})
