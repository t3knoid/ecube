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
    nfs_client_version: '4.1',
    db_pool_size: 5,
    db_pool_max_overflow: 10,
    db_pool_recycle_seconds: -1,
    startup_analysis_batch_size: 500,
    copy_job_timeout: 3600,
    job_detail_files_page_size: 40,
    callback_default_url: null,
    callback_proxy_url: null,
    callback_payload_fields: null,
    callback_payload_field_map: null,
    callback_hmac_secret_configured: false,
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

  it('loads and saves the startup analysis batch size', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ startup_analysis_batch_size: 250 }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['startup_analysis_batch_size'],
    })

    const wrapper = mountView()
    await flushPromises()

    const batchSizeInput = wrapper.find('#cfg-startup-analysis-batch-size')
    expect(batchSizeInput.element.value).toBe('250')
  expect(batchSizeInput.attributes('max')).toBe('5000')

    await batchSizeInput.setValue('125')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({ startup_analysis_batch_size: 125 })
  })

  it('loads and saves the system-wide callback default URL', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ callback_default_url: 'https://example.com/default-webhook' }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['callback_default_url'],
    })

    const wrapper = mountView()
    await flushPromises()

    const callbackInput = wrapper.find('#cfg-callback-default-url')
    expect(callbackInput.element.value).toBe('https://example.com/default-webhook')

    await callbackInput.setValue('https://example.com/updated-default-webhook')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      callback_default_url: 'https://example.com/updated-default-webhook',
    })
  })

  it('loads and saves the outbound callback proxy URL', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ callback_proxy_url: 'http://proxy.example.com:8080' }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['callback_proxy_url'],
    })

    const wrapper = mountView()
    await flushPromises()

    const proxyInput = wrapper.find('#cfg-callback-proxy-url')
    expect(proxyInput.element.value).toBe('http://proxy.example.com:8080')

    await proxyInput.setValue('https://proxy.example.com:8443')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      callback_proxy_url: 'https://proxy.example.com:8443',
    })
  })

  it('loads and saves callback payload field selection and mapping as JSON', async () => {
    mocks.getConfiguration.mockResolvedValue(
      buildResponse({
        callback_payload_fields: ['event', 'project_id', 'completion_result'],
        callback_payload_field_map: {
          type: 'event',
          summary: 'project=${project_id};result=${completion_result}',
        },
      }),
    )
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['callback_payload_fields', 'callback_payload_field_map'],
    })

    const wrapper = mountView()
    await flushPromises()

    const fieldsInput = wrapper.find('#cfg-callback-payload-fields')
    const mappingInput = wrapper.find('#cfg-callback-payload-field-map')

    expect(fieldsInput.element.value).toContain('"event"')
    expect(mappingInput.element.value).toContain('"type": "event"')

    await fieldsInput.setValue('["event","status"]')
    await mappingInput.setValue('{"kind":"event","state":"status"}')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      callback_payload_fields: ['event', 'status'],
      callback_payload_field_map: {
        kind: 'event',
        state: 'status',
      },
    })
  })

  it('shows a validation error when callback payload JSON is invalid', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse())

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('#cfg-callback-payload-field-map').setValue('{bad json')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(i18n.global.t('configuration.fields.callback_payload_field_map.invalidJson'))
  })

  it('sends a new callback signing secret without reloading the current value', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ callback_hmac_secret_configured: true }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['callback_hmac_secret'],
    })

    const wrapper = mountView()
    await flushPromises()

    const secretInput = wrapper.find('#cfg-callback-hmac-secret')
    expect(secretInput.element.value).toBe('')
    expect(wrapper.text()).toContain(i18n.global.t('configuration.fields.callback_hmac_secret.statusConfigured'))

    await secretInput.setValue('rotated-secret')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      callback_hmac_secret: 'rotated-secret',
    })
    expect(secretInput.element.value).toBe('')
  })

  it('clears the stored callback signing secret when requested', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ callback_hmac_secret_configured: true }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['callback_hmac_secret'],
    })

    const wrapper = mountView()
    await flushPromises()

    const clearCheckbox = wrapper.find('#cfg-clear-callback-hmac-secret')
    expect(clearCheckbox.attributes('disabled')).toBeUndefined()

    await clearCheckbox.setValue(true)
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({
      clear_callback_hmac_secret: true,
    })
  })

  it('loads and saves the default NFS client version', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ nfs_client_version: '4.1' }))
    mocks.updateConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['nfs_client_version'],
    })

    const wrapper = mountView()
    await flushPromises()

    const versionSelect = wrapper.find('#cfg-nfs-client-version')
    expect(versionSelect.element.value).toBe('4.1')

    await versionSelect.setValue('4.2')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateConfiguration).toHaveBeenCalledWith({ nfs_client_version: '4.2' })
  })

  it('shows the default NFS client version in the Shares panel instead of Logging', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse({ nfs_client_version: '4.1' }))

    const wrapper = mountView()
    await flushPromises()

    const panelTitles = wrapper.findAll('.panel > h2').map((node) => node.text())
    expect(panelTitles).toContain(i18n.global.t('configuration.sections.shares'))

    const sharesTitle = wrapper.findAll('.panel > h2').find((node) => node.text() === i18n.global.t('configuration.sections.shares'))
    const loggingTitle = wrapper.findAll('.panel > h2').find((node) => node.text() === i18n.global.t('configuration.sections.logging'))

    expect(sharesTitle).toBeTruthy()
    expect(loggingTitle).toBeTruthy()
    expect(sharesTitle.element.parentElement?.querySelector('#cfg-nfs-client-version')).not.toBeNull()
    expect(loggingTitle.element.parentElement?.querySelector('#cfg-nfs-client-version')).toBeNull()
  })

  it('keeps copy jobs beside database settings until the layout stacks', async () => {
    mocks.getConfiguration.mockResolvedValue(buildResponse())

    const wrapper = mountView()
    await flushPromises()

    const settingsGrids = wrapper.findAll('.settings-grid')
    expect(settingsGrids).toHaveLength(1)

    const panelTitles = wrapper.findAll('.panel > h2').map((node) => node.text())
    expect(panelTitles).toEqual([
      i18n.global.t('configuration.sections.logging'),
      i18n.global.t('configuration.sections.shares'),
      i18n.global.t('configuration.sections.databasePool'),
      i18n.global.t('configuration.sections.copyJobs'),
      i18n.global.t('configuration.sections.webhooks'),
    ])

    expect(wrapper.find('.warning-panel').exists()).toBe(false)
  })
})
