import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import ConfigurationView from '@/views/ConfigurationView.vue'

const mocks = vi.hoisted(() => ({
  getConfiguration: vi.fn(),
  updateConfiguration: vi.fn(),
  restartConfigurationService: vi.fn(),
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('@/api/configuration.js', () => ({
  getConfiguration: (...args) => mocks.getConfiguration(...args),
  updateConfiguration: (...args) => mocks.updateConfiguration(...args),
  restartConfigurationService: (...args) => mocks.restartConfigurationService(...args),
}))

vi.mock('@/composables/useToast.js', () => ({
  useToast: () => mocks.toast,
}))

function buildResponse(overrides = {}) {
  const values = {
    log_level: 'INFO',
    log_format: 'text',
    log_file: '/var/log/ecube/app.log',
    log_file_max_bytes: 10485760,
    log_file_backup_count: 5,
    db_pool_size: 5,
    db_pool_max_overflow: 10,
    db_pool_recycle_seconds: -1,
    copy_job_timeout: 3600,
    job_detail_files_page_size: 40,
    ...overrides,
  }

  return {
    settings: Object.entries(values).map(([key, value]) => ({
      key,
      value,
      requires_restart: key === 'db_pool_recycle_seconds',
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

describe('ConfigurationView logging defaults', () => {
  beforeEach(() => {
    mocks.getConfiguration.mockReset()
    mocks.updateConfiguration.mockReset()
    mocks.restartConfigurationService.mockReset()
    mocks.toast.success.mockReset()
    mocks.toast.warning.mockReset()
    mocks.toast.error.mockReset()
    mocks.toast.info.mockReset()
  })

  it('shows file logging enabled on first load when the backend exposes the default log path', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse())

    const wrapper = mountView()
    await flushPromises()

    const enabled = wrapper.find('#cfg-log-file-enabled')
    const logFile = wrapper.find('#cfg-log-file')

    expect(enabled.element.checked).toBe(true)
    expect(logFile.element.value).toBe('/var/log/ecube/app.log')
    expect(logFile.attributes('disabled')).toBeUndefined()
  })

  it('loads and saves the configured Job Detail files page size', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ job_detail_files_page_size: 60 }))
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
  })
})
