import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import SetupWizardView from '@/views/SetupWizardView.vue'

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  authStore: {
    isAuthenticated: false,
  },
  getSetupStatus: vi.fn(),
  getDatabaseProvisionStatus: vi.fn(),
  getSystemInfo: vi.fn(),
  connectDatabase: vi.fn(),
  provisionDatabase: vi.fn(),
  initializeSetup: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    replace: mocks.replace,
    push: mocks.push,
  }),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => mocks.authStore,
}))

vi.mock('@/api/setup.js', () => ({
  getSetupStatus: (...args) => mocks.getSetupStatus(...args),
  getDatabaseProvisionStatus: (...args) => mocks.getDatabaseProvisionStatus(...args),
  getSystemInfo: (...args) => mocks.getSystemInfo(...args),
  connectDatabase: (...args) => mocks.connectDatabase(...args),
  provisionDatabase: (...args) => mocks.provisionDatabase(...args),
  initializeSetup: (...args) => mocks.initializeSetup(...args),
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

function mountView() {
  return mount(SetupWizardView, {
    global: {
      plugins: [i18n],
    },
  })
}

describe('SetupWizardView existing admin reconciliation', () => {
  beforeEach(() => {
    mocks.replace.mockReset()
    mocks.push.mockReset()
    mocks.authStore.isAuthenticated = false
    mocks.getSetupStatus.mockReset()
    mocks.getDatabaseProvisionStatus.mockReset()
    mocks.getSystemInfo.mockReset()
    mocks.connectDatabase.mockReset()
    mocks.provisionDatabase.mockReset()
    mocks.initializeSetup.mockReset()

    mocks.getSystemInfo.mockResolvedValue({
      in_docker: false,
    })
    mocks.getSetupStatus.mockResolvedValue({ initialized: false })
    mocks.getDatabaseProvisionStatus.mockResolvedValue({ provisioned: false })
    mocks.connectDatabase.mockResolvedValue({})
    mocks.provisionDatabase.mockResolvedValue({})
  })

  it('shows reconciliation success text when setup syncs an existing OS admin user', async () => {
    mocks.initializeSetup.mockResolvedValue({
      status: 'reconciled_existing_user',
      message: 'Setup complete. Existing OS admin user was reconciled, added to ecube-admins, and synced to ECUBE as an admin.',
      username: 'admin',
      groups_created: [],
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('#db-admin-user').setValue('postgres')
    await wrapper.find('#db-admin-pass').setValue('DbAdmin#123')
    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('setup.connectDatabase')).trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.next')).trigger('click')
    await flushPromises()

    await wrapper.find('#app-db-pass').setValue('AppDb#123')
    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('setup.provisionDb')).trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.next')).trigger('click')
    await flushPromises()

    await wrapper.find('#admin-password').setValue('Admin#123')
    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('setup.createAdmin')).trigger('click')
    await flushPromises()

    expect(mocks.initializeSetup).toHaveBeenCalledWith({
      username: 'admin',
      password: 'Admin#123',
    })
    expect(wrapper.text()).toContain('Existing OS admin user was reconciled')
    expect(wrapper.text()).not.toContain(i18n.global.t('setup.adminCreated'))
  })
})
