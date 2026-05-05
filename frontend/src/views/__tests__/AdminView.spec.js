import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import AdminView from '@/views/AdminView.vue'

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

function buildAdminResponse(overrides = {}) {
  const values = {
    log_format: 'text',
    log_file: '/var/log/ecube/app.log',
    log_file_max_bytes: 10485760,
    log_file_backup_count: 5,
    db_pool_size: 5,
    db_pool_max_overflow: 10,
    db_pool_recycle_seconds: -1,
    callback_default_url: null,
    callback_proxy_url: null,
    callback_payload_fields: null,
    callback_payload_field_map: null,
    callback_hmac_secret_configured: false,
    nfs_client_version: '4.1',
    startup_analysis_batch_size: 500,
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

function buildPasswordPolicyResponse(overrides = {}) {
  return {
    minlen: 14,
    minclass: 3,
    maxrepeat: 3,
    maxsequence: 4,
    maxclassrepeat: 0,
    dictcheck: 1,
    usercheck: 1,
    difok: 5,
    retry: 3,
    ...overrides,
  }
}

const ConfirmDialogStub = {
  props: ['modelValue'],
  emits: ['update:modelValue', 'confirm'],
  template: '<div v-if="modelValue"><button class="confirm-stub" @click="$emit(\'confirm\')">confirm</button></div>',
}

function mountView() {
  return mount(AdminView, {
    global: {
      plugins: [i18n],
      stubs: {
        ConfirmDialog: ConfirmDialogStub,
      },
    },
  })
}

describe('AdminView', () => {
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
    mocks.getPasswordPolicy.mockResolvedValue(buildPasswordPolicyResponse())
  })

  it('renders only admin sections', async () => {
    mocks.getAdminConfiguration.mockResolvedValue(buildAdminResponse())

    const wrapper = mountView()
    await flushPromises()

    const panelTitles = wrapper.findAll('.panel > h2').map((node) => node.text())
    expect(panelTitles).toEqual([
      i18n.global.t('adminPage.sections.loggingInfrastructure'),
      i18n.global.t('adminPage.sections.databaseRuntime'),
      i18n.global.t('configuration.sections.passwordPolicy'),
      i18n.global.t('configuration.sections.webhooks'),
      i18n.global.t('adminPage.sections.platformIntegration'),
      i18n.global.t('adminPage.sections.serviceControl'),
    ])
    expect(wrapper.find('#cfg-drive-mount-timeout-seconds').exists()).toBe(false)
    expect(wrapper.find('#cfg-policy-minlen').exists()).toBe(true)
    expect(wrapper.find('#cfg-log-file').element.value).toBe('app.log')
  })

  it('saves default log-directory filenames back as full paths', async () => {
    mocks.getAdminConfiguration.mockResolvedValue(buildAdminResponse({ log_file: '/var/log/ecube/app.log.2' }))
    mocks.updateAdminConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['log_file'],
    })

    const wrapper = mountView()
    await flushPromises()

    const logFileInput = wrapper.find('#cfg-log-file')
    expect(logFileInput.element.value).toBe('app.log.2')

    await logFileInput.setValue('app.log.3')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateAdminConfiguration).toHaveBeenCalledWith({ log_file: '/var/log/ecube/app.log.3' })
  })

  it('loads and saves password policy values', async () => {
    mocks.getAdminConfiguration.mockResolvedValue(buildAdminResponse())
    mocks.getPasswordPolicy.mockResolvedValue(buildPasswordPolicyResponse({ minlen: 16, retry: 4 }))
    mocks.updatePasswordPolicy.mockResolvedValue(buildPasswordPolicyResponse({ minlen: 18, retry: 5 }))

    const wrapper = mountView()
    await flushPromises()

    const minlenInput = wrapper.find('#cfg-policy-minlen')
    expect(minlenInput.element.value).toBe('16')

    await minlenInput.setValue('18')
    await wrapper.find('#cfg-policy-retry').setValue('5')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updatePasswordPolicy).toHaveBeenCalledWith({ minlen: 18, retry: 5 })
    expect(mocks.updateConfiguration).not.toHaveBeenCalled()
  })

  it('sends a new callback signing secret without reloading the current value', async () => {
    mocks.getAdminConfiguration.mockResolvedValue(buildAdminResponse({ callback_hmac_secret_configured: true }))
    mocks.updateAdminConfiguration.mockResolvedValue({
      restart_required: false,
      restart_required_settings: [],
      applied_immediately: ['callback_hmac_secret'],
    })

    const wrapper = mountView()
    await flushPromises()

    const secretInput = wrapper.find('#cfg-callback-hmac-secret')
    expect(secretInput.element.value).toBe('')

    await secretInput.setValue('rotated-secret')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    expect(mocks.updateAdminConfiguration).toHaveBeenCalledWith({ callback_hmac_secret: 'rotated-secret' })
    expect(secretInput.element.value).toBe('')
  })

  it('keeps restart confirmation and restart action on Admin only', async () => {
    mocks.getAdminConfiguration.mockResolvedValue(buildAdminResponse())
    mocks.updateAdminConfiguration.mockResolvedValue({
      restart_required: true,
      restart_required_settings: ['db_pool_recycle_seconds'],
      applied_immediately: [],
    })
    mocks.restartConfigurationService.mockResolvedValue({ status: 'restart_requested', service: 'ecube' })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('#cfg-db-pool-recycle').setValue('120')
    await wrapper.find('.action-row .btn.btn-primary').trigger('click')
    await flushPromises()

    const restartButton = wrapper.find('.panel.warning-panel .btn.btn-primary')
    expect(restartButton.exists()).toBe(true)

    await restartButton.trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-stub').trigger('click')
    await flushPromises()

    expect(mocks.restartConfigurationService).toHaveBeenCalledWith({ confirm: true })
  })
})