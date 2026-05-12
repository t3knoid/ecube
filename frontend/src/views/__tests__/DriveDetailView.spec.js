import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DriveDetailView from '@/views/DriveDetailView.vue'

const mocks = vi.hoisted(() => ({
  hasAnyRole: vi.fn(),
  push: vi.fn(),
  getPublicAuthConfig: vi.fn(),
  getDrives: vi.fn(),
  getJobChainOfCustody: vi.fn(),
  listJobs: vi.fn(),
  getMounts: vi.fn(),
  formatDrive: vi.fn(),
  initializeDrive: vi.fn(),
  mountDrive: vi.fn(),
  prepareEjectDrive: vi.fn(),
  refreshDrives: vi.fn(),
  testDriveThroughput: vi.fn(),
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

vi.mock('@/api/auth.js', () => ({
  getPublicAuthConfig: (...args) => mocks.getPublicAuthConfig(...args),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
  formatDrive: (...args) => mocks.formatDrive(...args),
  initializeDrive: (...args) => mocks.initializeDrive(...args),
  mountDrive: (...args) => mocks.mountDrive(...args),
  prepareEjectDrive: (...args) => mocks.prepareEjectDrive(...args),
  refreshDrives: (...args) => mocks.refreshDrives(...args),
  testDriveThroughput: (...args) => mocks.testDriveThroughput(...args),
}))

vi.mock('@/api/jobs.js', () => ({
  getJobChainOfCustody: (...args) => mocks.getJobChainOfCustody(...args),
  listJobs: (...args) => mocks.listJobs(...args),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
}))

vi.mock('@/api/admin.js', () => ({
  enablePort: (...args) => mocks.enablePort(...args),
}))

function buildDrive(overrides = {}) {
  return {
    id: 7,
    device_identifier: 'USB-DETAIL-007',
    display_device_label: 'General USB Flash Disk - Port 2',
    serial_number: 'SN-0007-DETAIL',
    manufacturer: 'General USB',
    vendor_id: 'abcd',
    product_id: '1234',
    speed: '5000',
    product_name: 'Flash Disk',
    port_number: 2,
    filesystem_path: '/dev/sdb1',
    filesystem_type: 'ext4',
    mount_path: null,
    current_state: 'AVAILABLE',
    current_project_id: 'PROJ-007',
    capacity_bytes: 1024,
    available_bytes: 512,
    port_id: 1,
    throughput_write_mbps: null,
    throughput_tested_at: null,
    related_job: {
      job_id: null,
      evidence_number: null,
      custody_status: 'NO_RELATED_JOB',
      delivery_time: null,
    },
    ...overrides,
  }
}

function mountView() {
  return mount(DriveDetailView, {
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        ConfirmDialog: {
          props: ['modelValue', 'confirmLabel', 'cancelLabel', 'busy'],
          emits: ['update:modelValue', 'confirm', 'cancel'],
          template: `
            <div v-if="modelValue" class="confirm-dialog-stub">
              <slot />
              <button class="confirm-dialog-cancel" @click="$emit('update:modelValue', false); $emit('cancel')">{{ cancelLabel }}</button>
              <button class="confirm-dialog-confirm" :disabled="busy" @click="$emit('confirm')">{{ confirmLabel }}</button>
            </div>
          `,
        },
        DirectoryBrowser: {
          props: ['mountPath', 'rootLabel'],
          template: '<div class="directory-browser-stub">{{ rootLabel }}|{{ mountPath }}</div>',
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
    mocks.getPublicAuthConfig.mockReset()
    mocks.getDrives.mockReset()
    mocks.getJobChainOfCustody.mockReset()
    mocks.listJobs.mockReset()
    mocks.getMounts.mockReset()
    mocks.formatDrive.mockReset()
    mocks.initializeDrive.mockReset()
    mocks.mountDrive.mockReset()
    mocks.prepareEjectDrive.mockReset()
    mocks.refreshDrives.mockReset()
    mocks.testDriveThroughput.mockReset()
    mocks.enablePort.mockReset()

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.getPublicAuthConfig.mockResolvedValue({
      drive_mount_timeout_seconds: 120,
    })
    mocks.getDrives.mockResolvedValue([buildDrive()])
    mocks.getJobChainOfCustody.mockResolvedValue({ selector_mode: 'JOB', reports: [] })
    mocks.listJobs.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([
      { id: 1, status: 'MOUNTED', project_id: 'PROJ-007' },
      { id: 2, status: 'MOUNTED', project_id: 'PROJ-999' },
      { id: 3, status: 'MOUNTED', project_id: 'PROJ-007' },
      { id: 4, status: 'UNMOUNTED', project_id: 'PROJ-HIDDEN' },
    ])
    mocks.mountDrive.mockResolvedValue(buildDrive({}))
    mocks.testDriveThroughput.mockResolvedValue(buildDrive({ throughput_write_mbps: 143.2, throughput_tested_at: '2026-05-11T18:10:00Z' }))
  })

  it('shows the last known available space and handles zero bytes safely', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ available_bytes: 0 })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Available Space')
    expect(wrapper.text()).toContain('0.0 B')
  })

  it('shows the drive serial, manufacturer, speed, vendor id, and product id', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Serial Number')
    expect(wrapper.text()).toContain('SN-0007-DETAIL')
    expect(wrapper.text()).toContain('Manufacturer')
    expect(wrapper.text()).toContain('General USB')
    expect(wrapper.text()).toContain('Speed')
    expect(wrapper.text()).toContain('5000 Mbps')
    expect(wrapper.text()).toContain('Vendor ID')
    expect(wrapper.text()).toContain('abcd')
    expect(wrapper.text()).toContain('Product ID')
    expect(wrapper.text()).toContain('1234')
  })

  it('shows a safe fallback when drive speed is unavailable', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ speed: null })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toMatch(/Speed\s*-/)
  })

  it('shows the latest measured write speed and runs the throughput test for managers', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7', throughput_write_mbps: 101.1, throughput_tested_at: '2026-05-11T17:00:00Z' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.latestWriteSpeed'))
    expect(wrapper.text()).toContain('101.1 MB/s')

    const testButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.testThroughput'))
    expect(testButton).toBeTruthy()

    await testButton.trigger('click')
    await flushPromises()

    expect(mocks.testDriveThroughput).toHaveBeenCalledWith(7, { timeout: 0 })
    expect(wrapper.text()).toContain(i18n.global.t('drives.throughputTestSuccess'))
    expect(wrapper.text()).toContain('143.2 MB/s')
  })

  it('shows the Mount action for managers and updates the mount point after success', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({})])

    const wrapper = mountView()
    await flushPromises()

    const mountButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.mount'))
    expect(mountButton).toBeTruthy()

    await mountButton.trigger('click')
    await flushPromises()

    expect(mocks.getPublicAuthConfig).toHaveBeenCalledTimes(1)
    expect(mocks.mountDrive).toHaveBeenCalledWith(7, { timeout: 120000 })
    expect(wrapper.text()).toContain(i18n.global.t('drives.mountSuccess'))
    expect(wrapper.text()).not.toContain('/mnt/ecube/7')
    expect(wrapper.text()).not.toContain('USB-DETAIL-007')
    expect(wrapper.text()).not.toContain('/dev/sdb1')

    const statusBanner = wrapper.find('.ok-banner')
    expect(statusBanner.attributes('role')).toBe('status')
    expect(statusBanner.attributes('aria-live')).toBe('polite')
  })

  it('uses the configured drive mount timeout from the backend configuration', async () => {
    mocks.getPublicAuthConfig.mockResolvedValue({
      drive_mount_timeout_seconds: 300,
    })

    const wrapper = mountView()
    await flushPromises()

    const mountButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.mount'))
    expect(mountButton).toBeTruthy()

    await mountButton.trigger('click')
    await flushPromises()

    expect(mocks.mountDrive).toHaveBeenCalledWith(7, { timeout: 300000 })
  })

  it('falls back to the default mount timeout when configuration lookup fails', async () => {
    mocks.getPublicAuthConfig.mockRejectedValue(new Error('network error'))

    const wrapper = mountView()
    await flushPromises()

    const mountButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.mount'))
    expect(mountButton).toBeTruthy()

    await mountButton.trigger('click')
    await flushPromises()

    expect(mocks.mountDrive).toHaveBeenCalledWith(7, { timeout: 120000 })
    expect(wrapper.text()).toContain(i18n.global.t('drives.mountSuccess'))
  })

  it('hides the Mount action when the drive is already mounted', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).not.toContain(i18n.global.t('drives.mount'))
  })

  it('hides browse drive content for auditors', async () => {
    mocks.hasAnyRole.mockImplementation((roles) => roles.includes('auditor'))
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const buttonLabels = wrapper.findAll('button').map((node) => node.text())
    expect(buttonLabels).not.toContain(i18n.global.t('drives.testThroughput'))

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).not.toContain(i18n.global.t('drives.browse'))
    expect(wrapper.find('.directory-browser-stub').exists()).toBe(false)
  })

  it('shows Prepare Eject for a mounted available drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'AVAILABLE', mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).toContain(i18n.global.t('drives.prepareEject'))
  })

  it('keeps recovery actions consistent when enable reloads a mounted in-use drive', async () => {
    mocks.getDrives
      .mockResolvedValueOnce([buildDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdb1', port_id: 1 })])
      .mockResolvedValueOnce([buildDrive({ current_state: 'IN_USE', mount_path: '/mnt/ecube/7', filesystem_path: '/dev/sdb1', current_project_id: null })])
    mocks.enablePort.mockResolvedValue({ id: 1, enabled: true })
    mocks.refreshDrives.mockResolvedValue({ ok: true })

    const wrapper = mountView()
    await flushPromises()

    const enableButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.enable'))
    expect(enableButton).toBeTruthy()

    await enableButton.trigger('click')
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(wrapper.text()).toContain(i18n.global.t('drives.enableInUse'))
    expect(labels).not.toContain(i18n.global.t('drives.mount'))
    expect(labels).toContain(i18n.global.t('drives.browse'))
    expect(labels).toContain(i18n.global.t('drives.prepareEject'))

    const formatButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.format'))
    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))

    expect(formatButton.attributes('disabled')).toBeDefined()
    expect(initializeButton.attributes('disabled')).toBeDefined()
    expect(ejectButton.attributes('disabled')).toBeUndefined()
  })

  it('shows Disabled for a physically present disabled drive', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'DISABLED', filesystem_path: '/dev/sdb1', port_id: 1 })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.states.disabled'))
    expect(wrapper.text()).toContain(i18n.global.t('drives.enable'))

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).not.toContain(i18n.global.t('drives.mount'))
  })

  it('disables the Format action when the drive is mounted', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'AVAILABLE', mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const formatButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.format'))
    expect(formatButton).toBeTruthy()
    expect(formatButton.attributes('disabled')).toBeDefined()
  })

  it('shows the Browse control when the drive has a mount path', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.browse'))

    const browseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.browse'))
    expect(browseButton).toBeTruthy()

    await browseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Browse General USB Flash Disk - Port 2 Contents')
    expect(wrapper.find('.directory-browser-stub').text()).toBe('|/mnt/ecube/7')
  })

  it('shows the evidence number for the drive assigned job when multiple drives share a project', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_project_id: 'PROJ-007',
        mount_path: '/mnt/ecube/7',
        related_job: {
          job_id: 20,
          evidence_number: 'EV-007',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.evidence'))
    expect(wrapper.text()).toContain('EV-007')
    expect(wrapper.text()).not.toContain('EV-OTHER-DRIVE')
  })

  it('shows the related job ID for the drive assigned job and links to Job Detail', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_project_id: 'PROJ-007',
        mount_path: '/mnt/ecube/7',
        related_job: {
          job_id: 20,
          evidence_number: 'EV-007',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.jobId'))
    const jobLink = wrapper.find('.cell-link')
    expect(jobLink.exists()).toBe(true)
    expect(jobLink.text()).toBe('20')

    await jobLink.trigger('click')
    await flushPromises()

    expect(mocks.push).toHaveBeenCalledWith({ name: 'job-detail', params: { id: 20 } })
  })

  it('requests trusted related job custody data when loading drive detail', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'PROJ-007', mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getDrives).toHaveBeenCalledWith({
      include_disconnected: true,
      include_related_job_custody: true,
    })
  })

  it('does not show stale evidence after format clears the drive project binding', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: null, mount_path: null })])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain('EV-STALE')
    expect(wrapper.text()).toContain(`${i18n.global.t('jobs.evidence')}-`)
    expect(wrapper.text()).toContain(`${i18n.global.t('jobs.jobId')}-`)
    expect(wrapper.text()).toContain(i18n.global.t('drives.custodyStatusNone'))
  })

  it('clears stale evidence immediately after formatting without leaving the page', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_project_id: 'PROJ-007',
        mount_path: null,
        related_job: {
          job_id: 44,
          evidence_number: 'EV-STALE',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])
    mocks.formatDrive.mockResolvedValue(buildDrive({ current_project_id: null, mount_path: null }))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('EV-STALE')
    expect(wrapper.text()).toContain('44')
    expect(wrapper.find('.cell-link').exists()).toBe(true)

    const formatButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.format'))
    expect(formatButton).toBeTruthy()

    await formatButton.trigger('click')
    await flushPromises()

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.formatDrive).toHaveBeenCalledWith(7, { filesystem_type: 'ext4' }, { timeout: 0 })
    expect(wrapper.text()).not.toContain('EV-STALE')
    expect(wrapper.text()).toContain(`${i18n.global.t('jobs.evidence')}-`)
    expect(wrapper.text()).not.toContain('44')
    expect(wrapper.text()).toContain(`${i18n.global.t('jobs.jobId')}-`)
    expect(wrapper.text()).toContain(i18n.global.t('drives.custodyStatusNone'))
    expect(wrapper.find('.cell-link').exists()).toBe(false)
  })

  it('shows pending handoff when trusted backend data reports incomplete custody', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        related_job: {
          job_id: 44,
          evidence_number: 'EV-007',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.custodyStatusPending'))
  })

  it('shows recorded handoff and delivery time when trusted backend data confirms custody handoff', async () => {
    const recordedAt = '2026-05-02T18:30:00Z'
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        related_job: {
          job_id: 44,
          evidence_number: 'EV-007',
          custody_status: 'HANDOFF_RECORDED',
          delivery_time: recordedAt,
        },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.custodyStatusRecorded'))
    expect(wrapper.text()).toContain(i18n.global.t('drives.custodyStatusRecordedAt', {
      timestamp: new Date(recordedAt).toLocaleString(),
    }))
  })

  it('shows status unavailable when trusted backend data cannot provide custody state', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        related_job: {
          job_id: 44,
          evidence_number: 'EV-007',
          custody_status: 'STATUS_UNAVAILABLE',
          delivery_time: null,
        },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.custodyStatusUnavailable'))
  })

  it('shows sanitized backend detail when drive formatting fails', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'PROJ-007', mount_path: null })])
    mocks.formatDrive.mockRejectedValue({
      response: {
        status: 500,
        data: {
          detail: 'Format timed out after 900s',
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const formatButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.format'))
    expect(formatButton).toBeTruthy()

    await formatButton.trigger('click')
    await flushPromises()

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Format timed out after 900s')
    expect(wrapper.text()).not.toContain(i18n.global.t('common.errors.requestConflict'))
  })

  it('hides Enable Drive when the drive is disconnected and not physically detected', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'DISCONNECTED', filesystem_path: null })])

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).not.toContain(i18n.global.t('drives.enable'))
  })

  it('populates initialize options from distinct mounted share projects', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    expect(initializeButton).toBeTruthy()

    await initializeButton.trigger('click')
    await flushPromises()

    const options = wrapper.findAll('#project-id option').map((node) => node.text())
    expect(options).toContain('PROJ-007')
    expect(options).toContain('PROJ-999')
    expect(options.filter((text) => text === 'PROJ-007')).toHaveLength(1)
  })

  it('shows mounted-drive context and leaves state unchanged when initialize is canceled', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_project_id: 'PROJ-007', mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    expect(initializeButton).toBeTruthy()

    await initializeButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.initializeMountedDestination', {
      mount: i18n.global.t('common.labels.protected'),
    }))

    const cancelButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.cancel'))
    expect(cancelButton).toBeTruthy()

    await cancelButton.trigger('click')
    await flushPromises()

    expect(mocks.initializeDrive).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('PROJ-007')
    expect(wrapper.find('#project-id').exists()).toBe(false)

    const labels = wrapper.findAll('button').map((node) => node.text())
    expect(labels).toContain(i18n.global.t('drives.initialize'))
  })

  it('shows the empty helper and disables initialize submission when no mounted project exists', async () => {
    mocks.getMounts.mockResolvedValue([])
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    expect(initializeButton).toBeTruthy()

    await initializeButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.initializeNoProjects'))
    const submitButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize') && node.attributes('disabled') !== undefined)
    expect(submitButton).toBeTruthy()
  })

  it('moves focus into the initialize dialog and closes it on Escape', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    expect(initializeButton).toBeTruthy()

    await initializeButton.trigger('click')
    await flushPromises()

    const projectSelect = wrapper.find('#project-id')
    expect(projectSelect.exists()).toBe(true)
    expect(document.activeElement?.id).toBe('project-id')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.find('#project-id').exists()).toBe(false)
  })

  it('does not dismiss the initialize dialog when the overlay is clicked', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    expect(initializeButton).toBeTruthy()

    await initializeButton.trigger('click')
    await flushPromises()

    await wrapper.find('.dialog-overlay').trigger('click')
    await flushPromises()

    expect(wrapper.find('#project-id').exists()).toBe(true)
  })

  it('marks the initialize project selection as required', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ mount_path: '/mnt/ecube/7' })])

    const wrapper = mountView()
    await flushPromises()

    const initializeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.initialize'))
    expect(initializeButton).toBeTruthy()

    await initializeButton.trigger('click')
    await flushPromises()

    const projectSelect = wrapper.find('#project-id')
    expect(projectSelect.attributes('required')).toBeDefined()
    expect(projectSelect.attributes('aria-required')).toBe('true')
  })

  it('closes the prepare-eject dialog and shows the backend detail when eject fails', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'IN_USE' })])
    mocks.prepareEjectDrive.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: 'Drive is busy; close any shell, file browser, or process using the mounted drive and retry prepare-eject' },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()
    expect(mocks.listJobs).toHaveBeenLastCalledWith({
      drive_id: 7,
      statuses: ['PREPARING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'],
      limit: 1,
    }, {
      timeout: 5000,
    })
    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(true)

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.prepareEjectDrive).toHaveBeenCalledWith(7, { confirm_incomplete: false })
    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('Drive is busy; close any shell, file browser, or process using the mounted drive and retry prepare-eject')
  })

  it('requires explicit operator confirmation when backend reports incomplete files before eject', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'IN_USE' })])
    mocks.prepareEjectDrive
      .mockRejectedValueOnce({
        response: {
          status: 409,
          data: { detail: 'EJECT_CONFIRM_REQUIRED: This drive has 2 incomplete file(s) (timed out or failed) in active assignments. Confirm eject to continue.' },
        },
      })
      .mockResolvedValueOnce(buildDrive({ current_state: 'AVAILABLE', mount_path: null }))

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.prepareEjectDrive).toHaveBeenNthCalledWith(1, 7, { confirm_incomplete: false })
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectIncompleteConfirmAction'))

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.prepareEjectDrive).toHaveBeenNthCalledWith(2, 7, { confirm_incomplete: true })
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectSuccess'))
  })

  it('suppresses the CoC prompt after prepare eject when a stored job CoC snapshot already exists', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_state: 'IN_USE',
        related_job: {
          job_id: 44,
          evidence_number: 'EV-007',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])
    mocks.prepareEjectDrive.mockResolvedValue(buildDrive({ current_state: 'AVAILABLE', mount_path: null }))
    mocks.getJobChainOfCustody.mockResolvedValue({ selector_mode: 'JOB', reports: [{}] })

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.getJobChainOfCustody).toHaveBeenCalledWith(44)
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectSuccess'))
    expect(wrapper.text()).not.toContain(i18n.global.t('drives.cocPrompt'))
    expect(wrapper.findAll('button').some((node) => node.text() === i18n.global.t('drives.openCocReport'))).toBe(false)
  })

  it('shows the CoC prompt when the related job has no stored snapshot and routes Open CoC Report to job detail', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_state: 'IN_USE',
        related_job: {
          job_id: 44,
          evidence_number: 'EV-007',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])
    mocks.prepareEjectDrive.mockResolvedValue(buildDrive({ current_state: 'AVAILABLE', mount_path: null }))
    mocks.getJobChainOfCustody.mockRejectedValue({ response: { status: 404 } })

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('drives.cocPrompt'))

    const openCocButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.openCocReport'))
    expect(openCocButton).toBeTruthy()

    await openCocButton.trigger('click')

    expect(mocks.push).toHaveBeenCalledWith({
      name: 'job-detail',
      params: { id: 44 },
      query: { coc: '1' },
    })
  })

  it('keeps the CoC prompt available after prepare eject when the CoC lookup fails unexpectedly', async () => {
    mocks.getDrives.mockResolvedValue([
      buildDrive({
        current_state: 'IN_USE',
        related_job: {
          job_id: 44,
          evidence_number: 'EV-007',
          custody_status: 'PENDING_HANDOFF',
          delivery_time: null,
        },
      }),
    ])
    mocks.prepareEjectDrive.mockResolvedValue(buildDrive({ current_state: 'AVAILABLE', mount_path: null }))
    mocks.getJobChainOfCustody.mockRejectedValue({ response: { status: 500 } })

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()
    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.getJobChainOfCustody).toHaveBeenCalledWith(44)
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectSuccess'))
    expect(wrapper.text()).toContain(i18n.global.t('drives.cocPrompt'))
    expect(wrapper.findAll('button').some((node) => node.text() === i18n.global.t('drives.openCocReport'))).toBe(true)
  })

  it('blocks prepare eject when the drive has an active running job', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'IN_USE' })])
    mocks.listJobs.mockResolvedValue([{ id: 44, status: 'RUNNING' }])

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()

    expect(mocks.listJobs).toHaveBeenCalledWith({
      drive_id: 7,
      statuses: ['PREPARING', 'RUNNING', 'PAUSING', 'PAUSED', 'VERIFYING'],
      limit: 1,
    }, { timeout: 5000 })
    expect(mocks.prepareEjectDrive).not.toHaveBeenCalled()
    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectBlockedActiveJob', { jobId: 44 }))

    const cancelButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.cancel'))
    expect(cancelButton).toBeTruthy()

    await cancelButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(false)
    expect(wrapper.text()).not.toContain(i18n.global.t('drives.ejectBlockedActiveJob', { jobId: 44 }))
  })

  it('blocks prepare eject when the drive has an active verifying job', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'IN_USE' })])
    mocks.listJobs.mockResolvedValue([{ id: 45, status: 'VERIFYING' }])

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()

    expect(mocks.prepareEjectDrive).not.toHaveBeenCalled()
    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectBlockedActiveJob', { jobId: 45 }))
  })

  it('blocks prepare eject when the drive has an active paused job', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'IN_USE' })])
    mocks.listJobs.mockResolvedValue([{ id: 46, status: 'PAUSED' }])

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()

    expect(mocks.prepareEjectDrive).not.toHaveBeenCalled()
    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain(i18n.global.t('drives.ejectBlockedActiveJob', { jobId: 46 }))
  })

  it('surfaces a preflight error and does not open the eject dialog when the jobs request fails', async () => {
    mocks.getDrives.mockResolvedValue([buildDrive({ current_state: 'IN_USE' })])
    mocks.listJobs.mockRejectedValue({})

    const wrapper = mountView()
    await flushPromises()

    const ejectButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('drives.prepareEject'))
    expect(ejectButton).toBeTruthy()

    await ejectButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(false)
    expect(mocks.prepareEjectDrive).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(i18n.global.t('common.errors.networkError'))
  })
})
