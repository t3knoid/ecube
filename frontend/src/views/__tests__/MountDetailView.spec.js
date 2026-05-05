import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import MountDetailView from '@/views/MountDetailView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getMounts: vi.fn(),
  updateMount: vi.fn(),
  deleteMount: vi.fn(),
  validateMount: vi.fn(),
  getPublicAuthConfig: vi.fn(),
  listAllJobs: vi.fn(),
}))

const authState = vi.hoisted(() => ({
  roles: ['admin', 'manager'],
}))

const routeState = vi.hoisted(() => ({
  id: '11',
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: routeState }),
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
  updateMount: (...args) => mocks.updateMount(...args),
  deleteMount: (...args) => mocks.deleteMount(...args),
  validateMount: (...args) => mocks.validateMount(...args),
}))

vi.mock('@/api/auth.js', () => ({
  getPublicAuthConfig: (...args) => mocks.getPublicAuthConfig(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  listAllJobs: (...args) => mocks.listAllJobs(...args),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: (roles) => roles.some((role) => authState.roles.includes(role)),
  }),
}))

function buildMount(overrides = {}) {
  return {
    id: 11,
    type: 'SMB',
    project_id: 'PROJ-011',
    nfs_client_version: null,
    remote_path: '//server/share',
    local_mount_point: '/smb/project2',
    status: 'MOUNTED',
    last_checked_at: null,
    ...overrides,
  }
}

function mountView() {
  return mount(MountDetailView, {
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        ConfirmDialog: {
          props: ['modelValue', 'title', 'message', 'confirmLabel', 'cancelLabel', 'busy'],
          emits: ['update:modelValue', 'confirm'],
          template: `
            <div v-if="modelValue" class="confirm-dialog-stub">
              <h2>{{ title }}</h2>
              <p>{{ message }}</p>
              <button class="confirm-btn" :disabled="busy" @click="$emit('confirm')">{{ confirmLabel }}</button>
              <button class="cancel-btn" @click="$emit('update:modelValue', false)">{{ cancelLabel }}</button>
            </div>
          `,
        },
        DirectoryBrowser: {
          props: ['mountPath', 'mountId', 'rootLabel', 'showRootCrumbAtRoot'],
          template: '<div class="directory-browser-stub">{{ mountId ?? mountPath }}|{{ rootLabel }}|{{ showRootCrumbAtRoot }}</div>',
        },
        StatusBadge: {
          props: ['status'],
          template: '<span class="status-badge-stub">{{ status }}</span>',
        },
      },
    },
  })
}

function findDialogButton(wrapper, label) {
  return wrapper.find('.dialog-actions').findAll('button').find((node) => node.text() === label)
}

describe('MountDetailView', () => {
  beforeEach(() => {
    authState.roles = ['admin', 'manager']
    routeState.id = '11'
    mocks.push.mockReset()
    mocks.getMounts.mockReset()
    mocks.updateMount.mockReset()
    mocks.deleteMount.mockReset()
    mocks.validateMount.mockReset()
    mocks.getPublicAuthConfig.mockReset()
    mocks.listAllJobs.mockReset()

    mocks.getMounts.mockResolvedValue([buildMount()])
    mocks.updateMount.mockResolvedValue(buildMount())
    mocks.deleteMount.mockResolvedValue({})
    mocks.validateMount.mockResolvedValue(buildMount({ status: 'MOUNTED' }))
    mocks.listAllJobs.mockResolvedValue([])
    mocks.getPublicAuthConfig.mockResolvedValue({
      demo_mode_enabled: false,
      default_nfs_client_version: '4.1',
      network_mount_timeout_seconds: 180,
      nfs_client_version_options: ['4.2', '4.1', '4.0', '3'],
    })
  })

  it('shows mount metadata, browse access, and the related Job ID link', async () => {
    mocks.listAllJobs.mockResolvedValue([{ id: 27, project_id: 'PROJ-011', evidence_number: 'EV-027' }])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('mounts.detail'))
    expect(wrapper.text()).toContain('//server/share')
    expect(wrapper.text()).toContain('/smb/project2')
    expect(wrapper.text()).toContain('PROJ-011')
    expect(wrapper.text()).toContain(i18n.global.t('common.labels.status'))

    const jobLink = wrapper.find('.cell-link')
    expect(jobLink.exists()).toBe(true)
    expect(jobLink.text()).toBe('27')

    await jobLink.trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 27 } })

    const browseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.browse'))
    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Browse mount PROJ-011 contents')
    expect(wrapper.find('.directory-browser-stub').text()).toBe('11||true')
  })

  it('opens the edit dialog prefilled and submits updates through validateMount and updateMount', async () => {
    mocks.getMounts
      .mockResolvedValueOnce([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD', local_mount_point: '/smb/original-share' })])
      .mockResolvedValueOnce([buildMount({ id: 42, remote_path: '//server/updated-share', project_id: 'PROJ-UPDATED', local_mount_point: '/smb/original-share' })])
    routeState.id = '42'

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    await editButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#edit-mount-dialog-title').text()).toBe(i18n.global.t('mounts.editDialogTitle'))
    expect(wrapper.find('#mount-local-path').element.value).toBe('/smb/original-share')
    expect(wrapper.find('#mount-local-path').attributes('readonly')).toBeDefined()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await wrapper.find('#mount-project-id').setValue('proj-updated')
    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.clearStoredCredentials')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(mocks.validateMount).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
      username: null,
      password: null,
      credentials_file: null,
    }, { timeout: 180000 })
    expect(mocks.updateMount).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
      username: null,
      password: null,
      credentials_file: null,
    }, { timeout: 180000 })
    expect(wrapper.text()).toContain(i18n.global.t('mounts.updateSuccess'))
  })

  it('keeps the edit dialog open and shows actionable backend text when update fails', async () => {
    mocks.getMounts.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateMount.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))
    mocks.updateMount.mockRejectedValue({ response: { data: { detail: 'A mount for this remote source is already configured.' } } })
    routeState.id = '42'

    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('mounts.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('already configured')
  })

  it('requires confirmation before removing a mounted mount and then returns to the list', async () => {
    const wrapper = mountView()
    await flushPromises()

    const removeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.remove'))
    await removeButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('mounts.removeConfirmTitle'))

    await wrapper.find('.confirm-btn').trigger('click')
    await flushPromises()

    expect(mocks.deleteMount).toHaveBeenCalledWith(11)
    expect(mocks.push).toHaveBeenCalledWith({ name: 'mounts' })
  })

  it('hides edit and remove actions for read-only roles', async () => {
    authState.roles = ['auditor']

    const wrapper = mountView()
    await flushPromises()

    const buttonTexts = wrapper.findAll('button').map((node) => node.text())
    expect(buttonTexts).toContain(i18n.global.t('mounts.browse'))
    expect(buttonTexts).not.toContain(i18n.global.t('common.actions.edit'))
    expect(buttonTexts).not.toContain(i18n.global.t('mounts.remove'))
    expect(wrapper.text()).not.toContain('//server/share')
    expect(wrapper.text()).not.toContain('/smb/project2')
    expect(wrapper.text()).toContain(i18n.global.t('mounts.redactedValue'))

    const browseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('mounts.browse'))
    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.directory-browser-stub').text()).toBe('11||true')
  })
})