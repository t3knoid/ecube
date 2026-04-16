import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DriveDetailView from '@/views/DriveDetailView.vue'

const mocks = vi.hoisted(() => ({
  hasAnyRole: vi.fn(),
  push: vi.fn(),
  getDrives: vi.fn(),
  formatDrive: vi.fn(),
  initializeDrive: vi.fn(),
  mountDrive: vi.fn(),
  prepareEjectDrive: vi.fn(),
  refreshDrives: vi.fn(),
  enablePort: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '7' } }),
  useRouter: () => ({ push: mocks.push }),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: mocks.hasAnyRole,
  }),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
  formatDrive: (...args) => mocks.formatDrive(...args),
  initializeDrive: (...args) => mocks.initializeDrive(...args),
  mountDrive: (...args) => mocks.mountDrive(...args),
  prepareEjectDrive: (...args) => mocks.prepareEjectDrive(...args),
  refreshDrives: (...args) => mocks.refreshDrives(...args),
}))

vi.mock('@/api/admin.js', () => ({
  enablePort: (...args) => mocks.enablePort(...args),
}))

function buildDrive(overrides = {}) {
  return {
    id: 7,
    device_identifier: 'USB-DETAIL-007',
    filesystem_path: '/dev/sdb1',
    filesystem_type: 'ext4',
    mount_path: null,
    current_state: 'AVAILABLE',
    current_project_id: 'PROJ-007',
    capacity_bytes: 1024,
    port_id: 1,
    ...overrides,
  }
}

function mountView() {
  return mount(DriveDetailView, {
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        ConfirmDialog: {
          template: '<div><slot /></div>',
        },
        DirectoryBrowser: {
          template: '<div class="directory-browser-stub" />',
        },
        StatusBadge: {
          props: ['label'],
          template: '<span>{{ label }}</span>',
        },
      },
    },
  })
}

describe('DriveDetailView mount workflow', () => {
  beforeEach(() => {
    mocks.hasAnyRole.mockReset()
    mocks.push.mockReset()
    mocks.getDrives.mockReset()
    mocks.formatDrive.mockReset()
    mocks.initializeDrive.mockReset()
    mocks.mountDrive.mockReset()
    mocks.prepareEjectDrive.mockReset()
    mocks.refreshDrives.mockReset()
    mocks.enablePort.mockReset()

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.getDrives.mockResolvedValue([buildDrive()])
    mocks.mountDrive.mockResolvedValue(buildDrive({ mount_path: '/mnt/ecube/7' }))
  })

  it('shows the Mount action for managers and updates the mount point after success', async () => {
    const wrapper = mountView()
    await flushPromises()

    const mountButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.mount'))
    expect(mountButton).toBeTruthy()

    await mountButton.trigger('click')
    await flushPromises()

    expect(mocks.mountDrive).toHaveBeenCalledWith(7)
    expect(wrapper.text()).toContain(i18n.global.t('drives.mountSuccess'))
    expect(wrapper.text()).toContain('/mnt/ecube/7')
  })

  it('hides the Mount action when the drive is already mounted', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).not.toContain(i18n.global.t('drives.mount'))
  })
})
