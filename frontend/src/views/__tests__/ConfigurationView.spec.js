import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import ConfigurationView from '@/views/ConfigurationView.vue'

const mocks = vi.hoisted(() => ({
  getConfiguration: vi.fn(),
  getAdminConfiguration: vi.fn(),
  getPasswordPolicy: vi.fn(),
  updateConfiguration: vi.fn(),
  updateAdminConfiguration: vi.fn(),
  updatePasswordPolicy: vi.fn(),
  restartConfigurationService: vi.fn(),
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

vi.mock('@/api/configuration.js', () => ({
  getConfiguration: (...args) => mocks.getConfiguration(...args),
  getAdminConfiguration: (...args) => mocks.getAdminConfiguration(...args),
  updateConfiguration: (...args) => mocks.updateConfiguration(...args),
  updateAdminConfiguration: (...args) => mocks.updateAdminConfiguration(...args),
  restartConfigurationService: (...args) => mocks.restartConfigurationService(...args),
}))

vi.mock('@/api/admin.js', () => ({
  getPasswordPolicy: (...args) => mocks.getPasswordPolicy(...args),
  updatePasswordPolicy: (...args) => mocks.updatePasswordPolicy(...args),
}))

vi.mock('@/composables/useToast.js', () => ({
  useToast: () => mocks.toast,
}))

function buildManagerResponse(overrides = {}) {
  const values = {
    log_level: 'INFO',
    mkfs_exfat_cluster_size: '4K',
    drive_format_timeout_seconds: 900,
    drive_mount_timeout_seconds: 120,
    network_mount_timeout_seconds: 120,
    mount_share_discovery_timeout_seconds: 60,
    copy_job_timeout: 3600,
    job_detail_files_page_size: 40,
    ...overrides,
  }

  return {
    settings: Object.entries(values).map(([key, value]) => ({
      key,
      value,
      requires_restart: false,
    })),
  }
}

function mountView() {
  return mount(ConfigurationView, {
    global: {
      plugins: [i18n],
      stubs: {
        ConfirmDialog: true,
      },
    },
  })
}

describe('ConfigurationView', () => {
  beforeEach(() => {
    mocks.getConfiguration.mockReset()
    mocks.getAdminConfiguration.mockReset()
    mocks.getPasswordPolicy.mockReset()
    mocks.updateConfiguration.mockReset()
    mocks.updateAdminConfiguration.mockReset()
    mocks.updatePasswordPolicy.mockReset()
    mocks.restartConfigurationService.mockReset()
    mocks.toast.success.mockReset()
    mocks.toast.warning.mockReset()
  })

  it('renders only manager sections and does not load admin-only data', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse())

    const wrapper = mountView()
    await flushPromises()

    const panelTitles = wrapper.findAll('.panel > h2').map((node) => node.text())
    expect(panelTitles).toEqual([
      i18n.global.t('configuration.sections.troubleshooting'),
      i18n.global.t('configuration.sections.driveOperations'),
      i18n.global.t('configuration.sections.networkMountOperations'),
      i18n.global.t('configuration.sections.copyAndJobWorkflow'),
    ])
    expect(wrapper.find('#cfg-log-file').exists()).toBe(false)
    expect(wrapper.find('#cfg-policy-minlen').exists()).toBe(false)
    expect(mocks.getPasswordPolicy).not.toHaveBeenCalled()
  })

  it('loads and saves the configured Job Detail files page size', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({ job_detail_files_page_size: 60 }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['job_detail_files_page_size'],
    })

    const wrapper = mountView()
    await flushPromises()

    const pageSizeInput = wrapper.find('#cfg-job-detail-files-page-size')
    expect(pageSizeInput.element.value).toBe('60')

    await pageSizeInput.setValue('80')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({ job_detail_files_page_size: 80 })
    expect(mocks.updateAdminConfiguration).not.toHaveBeenCalled()
  })

  it('loads and saves the drive mount timeout', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({ drive_mount_timeout_seconds: 300 }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['drive_mount_timeout_seconds'],
    })

    const wrapper = mountView()
    await flushPromises()

    const timeoutInput = wrapper.find('#cfg-drive-mount-timeout-seconds')
    expect(timeoutInput.element.value).toBe('300')

    await timeoutInput.setValue('480')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({ drive_mount_timeout_seconds: 480 })
  })

  it('loads and saves log level without exposing admin-only controls', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({ log_level: 'DEBUG' }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['log_level'],
    })

    const wrapper = mountView()
    await flushPromises()

    const levelSelect = wrapper.find('#cfg-log-level')
    expect(levelSelect.element.value).toBe('DEBUG')

    await levelSelect.setValue('ERROR')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({ log_level: 'ERROR' })
    expect(wrapper.find('#cfg-callback-default-url').exists()).toBe(false)
  })
})