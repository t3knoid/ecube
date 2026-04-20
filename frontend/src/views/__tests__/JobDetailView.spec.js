import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import JobDetailView from '@/views/JobDetailView.vue'

const mocks = vi.hoisted(() => ({
  getJob: vi.fn(),
  getJobFiles: vi.fn(),
  startJob: vi.fn(),
  verifyJob: vi.fn(),
  generateManifest: vi.fn(),
  updateJob: vi.fn(),
  completeJob: vi.fn(),
  deleteJob: vi.fn(),
  getJobDebug: vi.fn(),
  getDrives: vi.fn(),
  getMounts: vi.fn(),
  getFileHashes: vi.fn(),
  compareFiles: vi.fn(),
  hasAnyRole: vi.fn(),
  routerPush: vi.fn(),
  pollerStart: vi.fn(),
  pollerStop: vi.fn(),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '6' } }),
  useRouter: () => ({ push: (...args) => mocks.routerPush(...args) }),
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: (...args) => mocks.hasAnyRole(...args),
  }),
}))

vi.mock('@/api/jobs.js', () => ({
  getJob: (...args) => mocks.getJob(...args),
  getJobFiles: (...args) => mocks.getJobFiles(...args),
  startJob: (...args) => mocks.startJob(...args),
  verifyJob: (...args) => mocks.verifyJob(...args),
  generateManifest: (...args) => mocks.generateManifest(...args),
  updateJob: (...args) => mocks.updateJob(...args),
  completeJob: (...args) => mocks.completeJob(...args),
  deleteJob: (...args) => mocks.deleteJob(...args),
}))

vi.mock('@/api/introspection.js', () => ({
  getJobDebug: (...args) => mocks.getJobDebug(...args),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: (...args) => mocks.getDrives(...args),
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: (...args) => mocks.getMounts(...args),
}))

vi.mock('@/api/files.js', () => ({
  getFileHashes: (...args) => mocks.getFileHashes(...args),
  compareFiles: (...args) => mocks.compareFiles(...args),
}))

vi.mock('@/composables/usePolling.js', () => ({
  usePolling: (tick) => ({
    tick,
    start: (...args) => mocks.pollerStart(...args),
    stop: (...args) => mocks.pollerStop(...args),
  }),
}))

function mountView() {
  return mount(JobDetailView, {
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        DataTable: {
          props: ['rows'],
          template: '<div class="rows-stub">{{ rows.length }}</div>',
        },
        StatusBadge: {
          props: ['status'],
          template: '<span>{{ status }}</span>',
        },
        ProgressBar: {
          props: ['value', 'total', 'label', 'fullWidth', 'active'],
          template: '<div class="progressbar-stub">{{ value }}|{{ total }}|{{ label }}|{{ fullWidth }}|{{ active }}</div>',
        },
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
      },
    },
  })
}

describe('JobDetailView start action', () => {
  beforeEach(() => {
    mocks.getJob.mockReset()
    mocks.getJobFiles.mockReset()
    mocks.startJob.mockReset()
    mocks.verifyJob.mockReset()
    mocks.generateManifest.mockReset()
    mocks.updateJob.mockReset()
    mocks.completeJob.mockReset()
    mocks.deleteJob.mockReset()
    mocks.getJobDebug.mockReset()
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.getFileHashes.mockReset()
    mocks.compareFiles.mockReset()
    mocks.hasAnyRole.mockReset()
    mocks.routerPush.mockReset()
    mocks.pollerStart.mockReset()
    mocks.pollerStop.mockReset()

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'PENDING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      drive: { id: 1 },
    })
    mocks.getJobFiles.mockResolvedValue({ files: [] })
    mocks.getDrives.mockResolvedValue([
      { id: 1, device_identifier: 'USB-001', current_project_id: 'PROJ-001', current_state: 'AVAILABLE', mount_path: '/mnt/ecube/1' },
    ])
    mocks.getMounts.mockResolvedValue([
      { id: 4, project_id: 'PROJ-001', status: 'MOUNTED', remote_path: 'server:/exports/project-001', local_mount_point: '/nfs/project-001' },
    ])
    mocks.updateJob.mockResolvedValue({ id: 6, status: 'PENDING', project_id: 'PROJ-001', evidence_number: 'EV-UPDATED', thread_count: 4, copied_bytes: 0, total_bytes: 0, source_path: '/nfs/project-001/updated', target_mount_path: '/mnt/ecube/1' })
    mocks.completeJob.mockResolvedValue({ id: 6, status: 'COMPLETED', project_id: 'PROJ-001', evidence_number: 'EV-006', thread_count: 4, copied_bytes: 0, total_bytes: 0 })
    mocks.deleteJob.mockResolvedValue({ status: 'deleted' })
  })

  it('shows the validation detail instead of a generic conflict message', async () => {
    mocks.startJob.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: [{ loc: ['body'], msg: 'Field required' }],
        },
      },
    })

    const wrapper = mountView()
    await flushPromises()

    const startButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.start'))
    await startButton.trigger('click')
    await flushPromises()

    expect(mocks.startJob).toHaveBeenCalledWith(6, { thread_count: 4 })
    expect(wrapper.text()).toContain('body: Field required')
    expect(wrapper.text()).not.toContain(i18n.global.t('common.errors.requestConflict'))
  })

  it('shows the failure summary when the job has failed', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'FAILED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10,
      total_bytes: 100,
      files_failed: 1,
      completed_at: '2026-04-18T10:22:33Z',
      error_summary: '1 file failed: Permission denied (/evidence/report.pdf)',
      failure_log_entry: '2026-04-18T10:22:33+00:00 [ERROR] app.services.copy_engine: JOB_FAILED job_id=6 error_count=1 reason=1 file failed: Permission denied (/evidence/report.pdf)',
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Source')
    expect(wrapper.text()).toContain('Destination')
    expect(wrapper.text()).toContain('/nfs/project-001/evidence')
    expect(wrapper.text()).toContain('/mnt/ecube/1')
    expect(wrapper.text()).toContain('Failure reason')
    expect(wrapper.text()).toContain('Job ID')
    expect(wrapper.text()).toContain('Failed at')
    expect(wrapper.text()).toContain('Related log entry')
    expect(wrapper.text()).toContain('JOB_FAILED job_id=6 error_count=1')
    expect(wrapper.text()).toContain('1 file failed: Permission denied (/evidence/report.pdf)')
  })

  it('passes a full-width active progress label while the job is running', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 25,
      total_bytes: 100,
      file_count: 4,
      files_succeeded: 1,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.progressbar-stub').text()).toContain('25%')
    expect(wrapper.find('.progressbar-stub').text()).toContain('1/4')
    expect(wrapper.find('.progressbar-stub').text()).toContain('true|true')
  })

  it('uses conservative file progress when bytes hit 100% before all files finish', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 100,
      total_bytes: 100,
      file_count: 5,
      files_succeeded: 2,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const progress = wrapper.find('.progressbar-stub').text()
    expect(progress).toContain('40%')
    expect(progress).toContain('2/5')
    expect(progress).not.toContain('100% • 2/5')
    expect(wrapper.text()).toContain('40 B / 100 B')
    expect(wrapper.text()).not.toContain('100 B / 100 B')
  })

  it('formats the byte summary using human-readable units', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 1536,
      total_bytes: 506464540,
      file_count: 4,
      files_succeeded: 1,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('1.5 KB / 483 MB')
  })

  it('shows a completion summary with start time, copy threads, and transfer metrics', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10485760,
      total_bytes: 10485760,
      file_count: 4,
      files_succeeded: 4,
      files_failed: 0,
      started_at: '2026-04-18T10:00:00Z',
      completed_at: '2026-04-18T10:00:02Z',
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Completion summary')
    expect(wrapper.text()).toContain('Started at')
    expect(wrapper.text()).toContain('4/18/2026')
    expect(wrapper.text()).toContain('Copy threads')
    expect(wrapper.text()).toContain('4')
    expect(wrapper.text()).toContain('Files copied')
    expect(wrapper.text()).toContain('4 of 4')
    expect(wrapper.text()).toContain('Total copied')
    expect(wrapper.text()).toContain('10 MB')
    expect(wrapper.text()).toContain('Duration')
    expect(wrapper.text()).toContain('2s')
    expect(wrapper.text()).toContain('Copy rate')
    expect(wrapper.text()).toContain('5.0 MB/s')
  })

  it('shows a success banner after generating a manifest', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10485760,
      total_bytes: 10485760,
    })

    const wrapper = mountView()
    await flushPromises()

    const manifestButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.manifest'))
    expect(manifestButton).toBeTruthy()
    await manifestButton.trigger('click')
    await flushPromises()

    expect(mocks.generateManifest).toHaveBeenCalledWith(6)
    expect(wrapper.text()).toContain('Manifest generated successfully.')
    expect(wrapper.text()).toContain('/mnt/ecube/1/manifest_6.json')
  })

  it('uses accumulated active duration after pause and resume cycles', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'PAUSED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10485760,
      total_bytes: 10485760,
      file_count: 4,
      files_succeeded: 3,
      files_failed: 0,
      started_at: '2026-04-18T10:05:00Z',
      completed_at: null,
      active_duration_seconds: 125,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Completion summary')
    expect(wrapper.text()).toContain('2m 5s')
    expect(wrapper.text()).toContain('0.1 MB/s')
  })

  it('opens an edit form with pre-populated job values and submits updates', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'PENDING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()
    await editButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#job-evidence').element.value).toBe('EV-006')
    await wrapper.find('#job-evidence').setValue('EV-UPDATED')
    await wrapper.find('#job-mount').setValue('4')
    await wrapper.find('#job-drive').setValue('1')
    await wrapper.find('#job-source-path').setValue('/updated/folder')
    await wrapper.find('#job-submit').trigger('click')
    await flushPromises()

    expect(mocks.updateJob).toHaveBeenCalledWith(6, expect.objectContaining({
      evidence_number: 'EV-UPDATED',
      source_path: '/updated/folder',
    }))
  })

  it('shows complete and pending-delete controls and confirms deletion', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'PENDING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
      drive: { id: 1 },
    })

    const wrapper = mountView()
    await flushPromises()

    const completeButton = wrapper.findAll('button').find((node) => node.text() === 'Complete')
    expect(completeButton).toBeTruthy()
    await completeButton.trigger('click')
    await flushPromises()
    expect(mocks.completeJob).toHaveBeenCalledWith(6)

    const deleteButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.delete'))
    expect(deleteButton).toBeTruthy()
    await deleteButton.trigger('click')
    await flushPromises()
    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(true)
    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.deleteJob).toHaveBeenCalledWith(6)
    expect(mocks.routerPush).toHaveBeenCalled()
  })
})
