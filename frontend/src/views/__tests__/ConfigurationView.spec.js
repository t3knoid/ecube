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
    log_file: '/var/log/ecube/app.log',
    mkfs_exfat_cluster_size: '4K',
    drive_format_timeout_seconds: 900,
    drive_mount_timeout_seconds: 120,
    network_mount_timeout_seconds: 120,
    mount_share_discovery_timeout_seconds: 60,
    copy_job_timeout: 3600,
    startup_analysis_small_file_max_bytes: 65_536,
    startup_analysis_large_file_min_bytes: 8_388_608,
    copy_chunk_size_bytes: 4_194_304,
    copy_progress_flush_bytes: 67_108_864,
    copy_default_thread_count: 12,
    copy_file_fsync_enabled: false,
    copy_hashing_separate_thread_enabled: true,
    usb_discovery_interval: 30,
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
      i18n.global.t('configuration.sections.backgroundOperations'),
      i18n.global.t('configuration.sections.networkMountOperations'),
      i18n.global.t('configuration.sections.copyAndJobWorkflow'),
    ])
    const logFileInput = wrapper.find('#cfg-log-file')
    expect(logFileInput.exists()).toBe(true)
    expect(logFileInput.element.value).toBe('app.log')
    expect(logFileInput.attributes('readonly')).toBeDefined()
    expect(wrapper.find('#cfg-log-file-enabled').exists()).toBe(false)
    expect(wrapper.find('#cfg-copy-hashing-separate-thread-enabled').exists()).toBe(true)
    expect(wrapper.find('#cfg-startup-analysis-small-file-max-bytes').exists()).toBe(true)
    expect(wrapper.find('#cfg-startup-analysis-large-file-min-bytes').exists()).toBe(true)
    expect(wrapper.find('#cfg-callback-allow-private-ips').exists()).toBe(false)
    expect(wrapper.find('#cfg-policy-minlen').exists()).toBe(false)
    expect(mocks.getPasswordPolicy).not.toHaveBeenCalled()
  })

  it('loads and saves the separate hashing toggle from the configuration copy workflow panel', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({ copy_hashing_separate_thread_enabled: true }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['copy_hashing_separate_thread_enabled'],
    })

    const wrapper = mountView()
    await flushPromises()

    const checkbox = wrapper.find('#cfg-copy-hashing-separate-thread-enabled')
    expect(checkbox.exists()).toBe(true)
    expect(checkbox.element.checked).toBe(true)

    await checkbox.setValue(false)
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      copy_hashing_separate_thread_enabled: false,
    })
  })

  it('coerces boolean-like hashing values from the API before binding the checkbox', async () => {
    mocks.getConfiguration.mockResolvedValue(
      buildManagerResponse({ copy_hashing_separate_thread_enabled: 'true' }),
    )

    const wrapper = mountView()
    await flushPromises()

    const checkbox = wrapper.find('#cfg-copy-hashing-separate-thread-enabled')
    expect(checkbox.exists()).toBe(true)
    expect(checkbox.element.checked).toBe(true)
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

  it('loads and saves startup-analysis bucket thresholds', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({
      startup_analysis_small_file_max_bytes: 131_072,
      startup_analysis_large_file_min_bytes: 16_777_216,
    }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: [
        'startup_analysis_small_file_max_bytes',
        'startup_analysis_large_file_min_bytes',
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const smallInput = wrapper.find('#cfg-startup-analysis-small-file-max-bytes')
    const largeInput = wrapper.find('#cfg-startup-analysis-large-file-min-bytes')
    expect(smallInput.element.value).toBe('131072')
    expect(largeInput.element.value).toBe('16777216')

    await smallInput.setValue('262144')
    await largeInput.setValue('33554432')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      startup_analysis_small_file_max_bytes: 262144,
      startup_analysis_large_file_min_bytes: 33554432,
    })
  })

  it('rejects inverted startup-analysis thresholds before save', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({
      startup_analysis_small_file_max_bytes: 131_072,
      startup_analysis_large_file_min_bytes: 16_777_216,
    }))

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('#cfg-startup-analysis-small-file-max-bytes').setValue('16777216')
    await wrapper.find('#cfg-startup-analysis-large-file-min-bytes').setValue('131072')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).not.toHaveBeenCalled()
    expect(wrapper.find('.error-banner').text()).toBe(
      'Startup Analysis Small-File Max Bytes must stay below Startup Analysis Large-File Min Bytes.',
    )
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

  it('loads and saves the auto USB discovery interval', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse({ usb_discovery_interval: 0 }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['usb_discovery_interval'],
    })

    const wrapper = mountView()
    await flushPromises()

    const intervalInput = wrapper.find('#cfg-usb-discovery-interval')
    expect(intervalInput.element.value).toBe('0')

    await intervalInput.setValue('45')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({ usb_discovery_interval: 45 })
  })

  it('applies a greedy copy profile and saves the tuned values', async () => {
    mocks.getConfiguration.mockResolvedValue(buildManagerResponse())
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: [
        'copy_chunk_size_bytes',
        'copy_progress_flush_bytes',
        'copy_default_thread_count',
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('.chip-button')[3].trigger('click')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      copy_chunk_size_bytes: 16_777_216,
      copy_progress_flush_bytes: 268_435_456,
    })
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