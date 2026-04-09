import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import UsersView from '@/views/UsersView.vue'

const mocks = vi.hoisted(() => ({
  getUsers: vi.fn(),
  setUserRoles: vi.fn(),
  deleteUserRoles: vi.fn(),
  createOsUser: vi.fn(),
  getOsUsers: vi.fn(),
  resetOsUserPassword: vi.fn(),
}))

vi.mock('@/api/users.js', () => ({
  getUsers: (...args) => mocks.getUsers(...args),
  setUserRoles: (...args) => mocks.setUserRoles(...args),
  deleteUserRoles: (...args) => mocks.deleteUserRoles(...args),
}))

vi.mock('@/api/admin.js', () => ({
  createOsUser: (...args) => mocks.createOsUser(...args),
  getOsUsers: (...args) => mocks.getOsUsers(...args),
  resetOsUserPassword: (...args) => mocks.resetOsUserPassword(...args),
}))

function mountView() {
  return mount(UsersView, {
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        DataTable: {
          template: '<div class="datatable-stub"><slot /></div>',
        },
        Pagination: {
          template: '<div class="pagination-stub" />',
        },
      },
    },
  })
}

function findDialogPanelByTitle(wrapper, title) {
  return wrapper.findAll('.dialog-panel').find((panel) => panel.text().includes(title))
}

describe('UsersView existing OS-user confirmation flow', () => {
  beforeEach(() => {
    mocks.getUsers.mockReset()
    mocks.setUserRoles.mockReset()
    mocks.deleteUserRoles.mockReset()
    mocks.createOsUser.mockReset()
    mocks.getOsUsers.mockReset()
    mocks.resetOsUserPassword.mockReset()

    mocks.getUsers.mockResolvedValue({ users: [] })
    mocks.getOsUsers.mockResolvedValue({ users: [] })
    mocks.resetOsUserPassword.mockResolvedValue({ message: 'ok' })
  })

  it('shows confirmation dialog and confirms sync for existing OS user', async () => {
    mocks.createOsUser
      .mockResolvedValueOnce({
        status: 'confirmation_required',
        username: 'existing',
      })
      .mockResolvedValueOnce({
        status: 'synced_existing_user',
        username: 'existing',
        user: {
          username: 'existing',
          uid: 1001,
          gid: 1001,
          home: '/home/existing',
          shell: '/bin/bash',
          groups: ['ecube-admins', 'existing'],
        },
      })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button.btn.btn-primary').trigger('click')
    await wrapper.find('#create-user-username').setValue('existing')
    await wrapper.find('#create-user-password').setValue('ignored-pass')

    const createPanel = findDialogPanelByTitle(wrapper, i18n.global.t('users.createOsUser'))
    expect(createPanel).toBeTruthy()
    const createButtons = createPanel.findAll('.dialog-actions button')
    await createButtons[1].trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('users.existingOsUserConfirmMessage'))

    const confirmPanel = findDialogPanelByTitle(wrapper, i18n.global.t('users.existingOsUserConfirmTitle'))
    expect(confirmPanel).toBeTruthy()
    const confirmButton = confirmPanel
      .findAll('.dialog-actions button')
      .find((node) => node.text() === i18n.global.t('users.existingOsUserConfirmAction'))
    expect(confirmButton).toBeTruthy()

    await confirmButton.trigger('click')
    await flushPromises()

    expect(mocks.createOsUser).toHaveBeenNthCalledWith(1, {
      username: 'existing',
      password: 'ignored-pass',
      roles: ['processor'],
    })
    expect(mocks.createOsUser).toHaveBeenNthCalledWith(2, {
      username: 'existing',
      password: 'ignored-pass',
      roles: ['processor'],
      confirm_existing_os_user: true,
    })
    expect(wrapper.text()).not.toContain(i18n.global.t('users.existingOsUserConfirmMessage'))
  })

  it('records cancel decision and keeps create form unchanged', async () => {
    mocks.createOsUser
      .mockResolvedValueOnce({
        status: 'confirmation_required',
        username: 'existing',
      })
      .mockResolvedValueOnce({
        status: 'canceled',
        username: 'existing',
      })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('button.btn.btn-primary').trigger('click')
    await wrapper.find('#create-user-username').setValue('existing')
    await wrapper.find('#create-user-password').setValue('ignored-pass')

    const createPanel = findDialogPanelByTitle(wrapper, i18n.global.t('users.createOsUser'))
    expect(createPanel).toBeTruthy()
    const createButtons = createPanel.findAll('.dialog-actions button')
    await createButtons[1].trigger('click')
    await flushPromises()

    const confirmPanel = findDialogPanelByTitle(wrapper, i18n.global.t('users.existingOsUserConfirmTitle'))
    expect(confirmPanel).toBeTruthy()
    const cancelButton = confirmPanel
      .findAll('.dialog-actions button')
      .find((node) => node.text() === i18n.global.t('common.actions.cancel'))
    expect(cancelButton).toBeTruthy()

    await cancelButton.trigger('click')
    await flushPromises()

    expect(mocks.createOsUser).toHaveBeenNthCalledWith(2, {
      username: 'existing',
      roles: ['processor'],
      confirm_existing_os_user: false,
    })

    expect(wrapper.find('#create-user-username').element.value).toBe('existing')
    expect(wrapper.find('#create-user-password').element.value).toBe('ignored-pass')
  })
})
