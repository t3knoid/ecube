import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import ShareDetailView from '@/views/ShareDetailView.vue'

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  getShares: vi.fn(),
  updateShare: vi.fn(),
  deleteShare: vi.fn(),
  testShareThroughput: vi.fn(),
  validateShare: vi.fn(),
  getPublicAuthConfig: vi.fn(),
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

vi.mock('@/api/shares.js', () => ({
  getShares: (...args) => mocks.getShares(...args),
  updateShare: (...args) => mocks.updateShare(...args),
  deleteShare: (...args) => mocks.deleteShare(...args),
  testShareThroughput: (...args) => mocks.testShareThroughput(...args),
  validateShare: (...args) => mocks.validateShare(...args),
}))

vi.mock('@/api/auth.js', () => ({
  getPublicAuthConfig: (...args) => mocks.getPublicAuthConfig(...args),
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
    throughput_read_mbps: null,
    throughput_tested_at: null,
    related_job: { job_id: 27, status: 'RUNNING' },
    ...overrides,
  }
}

function mountView() {
  return mount(ShareDetailView, {
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
          props: ['status', 'label'],
          template: '<span class="status-badge-stub">{{ label || status }}</span>',
        },
      },
    },
  })
}

function findDialogButton(wrapper, label) {
  return wrapper.find('.dialog-actions').findAll('button').find((node) => node.text() === label)
}

describe('ShareDetailView', () => {
  beforeEach(() => {
    authState.roles = ['admin', 'manager']
    routeState.id = '11'
    mocks.push.mockReset()
    mocks.getShares.mockReset()
    mocks.updateShare.mockReset()
    mocks.deleteShare.mockReset()
    mocks.testShareThroughput.mockReset()
    mocks.validateShare.mockReset()
    mocks.getPublicAuthConfig.mockReset()

    mocks.getShares.mockResolvedValue([buildMount()])
    mocks.updateShare.mockResolvedValue(buildMount())
    mocks.deleteShare.mockResolvedValue({})
    mocks.testShareThroughput.mockResolvedValue(buildMount({ throughput_read_mbps: 87.4, throughput_tested_at: '2026-05-11T18:20:00Z' }))
    mocks.validateShare.mockResolvedValue(buildMount({ status: 'MOUNTED' }))
    mocks.getPublicAuthConfig.mockResolvedValue({
      demo_mode_enabled: false,
      default_nfs_client_version: '4.1',
      network_mount_timeout_seconds: 180,
      nfs_client_version_options: ['4.2', '4.1', '4.0', '3'],
    })
  })

  it('shows mount metadata, browse access, and the related Job ID link', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('shares.detail'))
    expect(wrapper.text()).toContain('//server/share')
    expect(wrapper.text()).toContain('/smb/project2')
    expect(wrapper.text()).toContain('PROJ-011')
    expect(wrapper.text()).toContain(i18n.global.t('common.labels.status'))

    const jobLink = wrapper.find('.cell-link')
    expect(jobLink.exists()).toBe(true)
    expect(jobLink.text()).toBe('27')
    expect(wrapper.text()).toContain(i18n.global.t('shares.jobStatus'))
    expect(wrapper.text()).toContain('RUNNING')

    await jobLink.trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 27 } })

    const browseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('shares.browse'))
    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Browse mount PROJ-011 contents')
    expect(wrapper.find('.directory-browser-stub').text()).toBe('11||true')
  })

  it('shows safe fallback text when no related job exists', async () => {
    mocks.getShares.mockResolvedValue([buildMount({ related_job: { job_id: null, status: 'NO_RELATED_JOB' } })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('shares.noRelatedJob'))
    expect(wrapper.find('.cell-link').exists()).toBe(false)
  })

  it('shows safe fallback text when related job status is unavailable', async () => {
    mocks.getShares.mockResolvedValue([buildMount({ related_job: { job_id: 27, status: 'STATUS_UNAVAILABLE' } })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('shares.jobStatusUnavailable'))
    expect(wrapper.find('.cell-link').text()).toBe('27')
  })

  it('shows the latest measured read speed and runs the throughput test for managers', async () => {
    mocks.getShares.mockResolvedValue([buildMount({ throughput_read_mbps: 64.2, throughput_tested_at: '2026-05-11T17:45:00Z' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('shares.latestReadSpeed'))
    expect(wrapper.text()).toContain('64.2 Mb/s')

    const testButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('shares.testThroughput'))
    expect(testButton).toBeTruthy()

    await testButton.trigger('click')
    await flushPromises()

    expect(mocks.testShareThroughput).toHaveBeenCalledWith(11, { timeout: 0 })
    expect(wrapper.text()).toContain(i18n.global.t('shares.throughputTestSuccess'))
    expect(wrapper.text()).toContain('87.4 Mb/s')
  })

  it('opens the edit dialog prefilled and submits updates through validateShare and updateShare', async () => {
    mocks.getShares
      .mockResolvedValueOnce([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD', local_mount_point: '/smb/original-share' })])
      .mockResolvedValueOnce([buildMount({ id: 42, remote_path: '//server/updated-share', project_id: 'PROJ-UPDATED', local_mount_point: '/smb/original-share' })])
    routeState.id = '42'

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    await editButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#edit-mount-dialog-title').text()).toBe(i18n.global.t('shares.editDialogTitle'))
    expect(wrapper.find('#mount-local-path').element.value).toBe('/smb/original-share')
    expect(wrapper.find('#mount-local-path').attributes('readonly')).toBeDefined()

    await wrapper.find('#mount-remote-path').setValue('//server/updated-share')
    await wrapper.find('#mount-project-id').setValue('proj-updated')
    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('shares.clearStoredCredentials')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('shares.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(mocks.validateShare).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
      username: null,
      password: null,
      credentials_file: null,
    }, { timeout: 180000 })
    expect(mocks.updateShare).toHaveBeenCalledWith(42, {
      type: 'SMB',
      remote_path: '//server/updated-share',
      project_id: 'PROJ-UPDATED',
      username: null,
      password: null,
      credentials_file: null,
    }, { timeout: 180000 })
    expect(wrapper.text()).toContain(i18n.global.t('shares.updateSuccess'))
  })

  it('keeps the edit dialog open and shows actionable backend text when update fails', async () => {
    mocks.getShares.mockResolvedValue([buildMount({ id: 42, remote_path: '//server/original-share', project_id: 'PROJ-OLD' })])
    mocks.validateShare.mockResolvedValue(buildMount({ id: 42, status: 'MOUNTED' }))
    mocks.updateShare.mockRejectedValue({ response: { data: { detail: 'A mount for this remote source is already configured.' } } })
    routeState.id = '42'

    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('shares.test')).trigger('click')
    await flushPromises()

    await findDialogButton(wrapper, i18n.global.t('common.actions.save')).trigger('click')
    await flushPromises()

    expect(wrapper.find('#mount-type').exists()).toBe(true)
    expect(wrapper.find('.error-banner').text()).toContain('already configured')
  })

  it('requires confirmation before removing a mounted mount and then returns to the list', async () => {
    const wrapper = mountView()
    await flushPromises()

    const removeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('shares.remove'))
    await removeButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('shares.removeConfirmTitle'))

    await wrapper.find('.confirm-btn').trigger('click')
    await flushPromises()

    expect(mocks.deleteShare).toHaveBeenCalledWith(11)
    expect(mocks.push).toHaveBeenCalledWith({ name: 'shares' })
  })

  it('hides edit and remove actions for read-only roles', async () => {
    authState.roles = ['auditor']

    const wrapper = mountView()
    await flushPromises()

    const buttonTexts = wrapper.findAll('button').map((node) => node.text())
    expect(buttonTexts).not.toContain(i18n.global.t('shares.browse'))
    expect(buttonTexts).not.toContain(i18n.global.t('shares.testThroughput'))
    expect(buttonTexts).not.toContain(i18n.global.t('common.actions.edit'))
    expect(buttonTexts).not.toContain(i18n.global.t('shares.remove'))
    expect(wrapper.text()).not.toContain('//server/share')
    expect(wrapper.text()).not.toContain('/smb/project2')
    expect(wrapper.text()).toContain(i18n.global.t('shares.redactedValue'))
    expect(wrapper.find('.directory-browser-stub').exists()).toBe(false)
  })
})