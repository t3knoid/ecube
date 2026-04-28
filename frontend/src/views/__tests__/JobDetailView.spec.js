import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import JobDetailView from '@/views/JobDetailView.vue'

const mocks = vi.hoisted(() => ({
  analyzeJob: vi.fn(),
  archiveJob: vi.fn(),
  getJob: vi.fn(),
  getJobFiles: vi.fn(),
  startJob: vi.fn(),
  retryFailedJob: vi.fn(),
  verifyJob: vi.fn(),
  pauseJob: vi.fn(),
  generateManifest: vi.fn(),
  downloadManifest: vi.fn(),
  updateJob: vi.fn(),
  completeJob: vi.fn(),
  deleteJob: vi.fn(),
  clearJobStartupAnalysisCache: vi.fn(),
  getDrives: vi.fn(),
  getMounts: vi.fn(),
  getFileHashes: vi.fn(),
  compareFiles: vi.fn(),
  hasAnyRole: vi.fn(),
  routerPush: vi.fn(),
  pollerStart: vi.fn(),
  pollerStop: vi.fn(),
  pollerTick: null,
  mobileViewportMatches: false,
}))

function setMobileViewport(matches) {
  mocks.mobileViewportMatches = matches
}

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn(() => ({
    matches: mocks.mobileViewportMatches,
    media: '(max-width: 768px)',
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
})

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
  analyzeJob: (...args) => mocks.analyzeJob(...args),
  archiveJob: (...args) => mocks.archiveJob(...args),
  getJob: (...args) => mocks.getJob(...args),
  getJobFiles: (...args) => mocks.getJobFiles(...args),
  startJob: (...args) => mocks.startJob(...args),
  retryFailedJob: (...args) => mocks.retryFailedJob(...args),
  verifyJob: (...args) => mocks.verifyJob(...args),
  pauseJob: (...args) => mocks.pauseJob(...args),
  generateManifest: (...args) => mocks.generateManifest(...args),
  downloadManifest: (...args) => mocks.downloadManifest(...args),
  updateJob: (...args) => mocks.updateJob(...args),
  completeJob: (...args) => mocks.completeJob(...args),
  deleteJob: (...args) => mocks.deleteJob(...args),
  clearJobStartupAnalysisCache: (...args) => mocks.clearJobStartupAnalysisCache(...args),
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
  usePolling: (tick) => {
    mocks.pollerTick = tick
    return {
      tick,
    start: (...args) => mocks.pollerStart(...args),
    stop: (...args) => mocks.pollerStop(...args),
    }
  },
}))

function mountView() {
  return mount(JobDetailView, {
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: {
        teleport: true,
        DataTable: {
          props: ['rows', 'columns', 'rowClass'],
          template: `
            <div>
              <div class="columns-stub">{{ (columns || []).map((column) => column.label).join('|') }}</div>
              <div class="rows-stub">{{ rows.length }}</div>
              <div
                v-for="(row, index) in rows"
                :key="row.id"
                class="row-stub"
                :class="typeof rowClass === 'function' ? rowClass(row, index) : rowClass"
              >
                <span v-for="column in columns" :key="column.key" class="cell-stub">
                  <slot :name="'cell-' + column.key" :row="row" :value="row[column.key]" :column="column">{{ row[column.key] }}</slot>
                </span>
              </div>
            </div>
          `,
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
          props: ['modelValue', 'title', 'message', 'confirmLabel', 'cancelLabel', 'busy'],
          emits: ['update:modelValue', 'confirm', 'cancel'],
          template: `
            <div v-if="modelValue" class="confirm-dialog-stub">
              <h2 class="confirm-dialog-title">{{ title }}</h2>
              <p class="confirm-dialog-message">{{ message }}</p>
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
    mocks.analyzeJob.mockReset()
    mocks.archiveJob.mockReset()
    mocks.getJobFiles.mockReset()
    mocks.startJob.mockReset()
    mocks.retryFailedJob.mockReset()
    mocks.verifyJob.mockReset()
    mocks.pauseJob.mockReset()
    mocks.generateManifest.mockReset()
    mocks.downloadManifest.mockReset()
    mocks.updateJob.mockReset()
    mocks.completeJob.mockReset()
    mocks.deleteJob.mockReset()
    mocks.clearJobStartupAnalysisCache.mockReset()
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.getFileHashes.mockReset()
    mocks.compareFiles.mockReset()
    mocks.hasAnyRole.mockReset()
    mocks.routerPush.mockReset()
    mocks.pollerStart.mockReset()
    mocks.pollerStop.mockReset()
    mocks.pollerTick = null
    setMobileViewport(false)

    mocks.hasAnyRole.mockReturnValue(true)
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'PENDING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
      startup_analysis_status: 'NOT_ANALYZED',
      startup_analysis_ready: false,
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      drive: { id: 1 },
    })
    mocks.analyzeJob.mockResolvedValue({
      id: 6,
      status: 'PENDING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
      startup_analysis_status: 'ANALYZING',
      startup_analysis_cached: true,
      startup_analysis_ready: false,
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      drive: { id: 1 },
    })
    mocks.getJobFiles.mockResolvedValue({ files: [], total_files: 0, returned_files: 0, page: 1, page_size: 40 })
    mocks.getDrives.mockResolvedValue([
      { id: 1, device_identifier: 'USB-001', port_system_path: '2-1', current_project_id: 'PROJ-001', current_state: 'AVAILABLE', mount_path: '/mnt/ecube/1' },
    ])
    mocks.getMounts.mockResolvedValue([
      { id: 4, project_id: 'PROJ-001', status: 'MOUNTED', remote_path: 'server:/exports/project-001', local_mount_point: '/nfs/project-001' },
    ])
    mocks.updateJob.mockResolvedValue({ id: 6, status: 'PENDING', project_id: 'PROJ-001', evidence_number: 'EV-UPDATED', thread_count: 4, copied_bytes: 0, total_bytes: 0, source_path: '/nfs/project-001/updated', target_mount_path: '/mnt/ecube/1' })
    mocks.pauseJob.mockResolvedValue({ id: 6, status: 'PAUSING', project_id: 'PROJ-001', evidence_number: 'EV-006', thread_count: 4, copied_bytes: 0, total_bytes: 0, source_path: '/nfs/project-001/evidence', target_mount_path: '/mnt/ecube/1' })
    mocks.retryFailedJob.mockResolvedValue({ id: 6, status: 'RUNNING', project_id: 'PROJ-001', evidence_number: 'EV-006', thread_count: 4, copied_bytes: 10, total_bytes: 20, files_failed: 0, files_timed_out: 0, source_path: '/nfs/project-001/evidence', target_mount_path: '/mnt/ecube/1' })
    mocks.completeJob.mockResolvedValue({ id: 6, status: 'COMPLETED', project_id: 'PROJ-001', evidence_number: 'EV-006', thread_count: 4, copied_bytes: 0, total_bytes: 0 })
    mocks.archiveJob.mockResolvedValue({ id: 6, status: 'ARCHIVED', project_id: 'PROJ-001', evidence_number: 'EV-006', thread_count: 4, copied_bytes: 0, total_bytes: 0, source_path: '/nfs/project-001/evidence', target_mount_path: '/mnt/ecube/1' })
    mocks.deleteJob.mockResolvedValue({ status: 'deleted' })
    mocks.clearJobStartupAnalysisCache.mockResolvedValue({ id: 6, status: 'FAILED', project_id: 'PROJ-001', evidence_number: 'EV-006', thread_count: 4, copied_bytes: 0, total_bytes: 0, startup_analysis_cached: false })
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

  it('shows startup-analysis status details and starts analysis for eligible jobs', async () => {
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
      startup_analysis_status: 'READY',
      startup_analysis_last_analyzed_at: '2026-04-24T15:00:00Z',
      startup_analysis_file_count: 3,
      startup_analysis_total_bytes: 24 * 1024 * 1024,
      startup_analysis_share_read_mbps: 120.4,
      startup_analysis_drive_write_mbps: 98.2,
      startup_analysis_estimated_duration_seconds: 2,
      startup_analysis_ready: true,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Analysis status')
    expect(wrapper.text()).toContain('Ready')
    expect(wrapper.text()).toContain('Discovered files')
    expect(wrapper.text()).toContain('3')
    expect(wrapper.text()).toContain('Estimated total bytes')
    expect(wrapper.text()).toContain('24 MB')
    expect(wrapper.text()).not.toContain('Estimated copy rate')
    expect(wrapper.text()).not.toContain('Estimated duration')
    expect(wrapper.text()).toContain('Ready to start')
    expect(wrapper.text()).toContain('Yes')

    const analyzeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.analyze'))
    expect(analyzeButton).toBeTruthy()
    await analyzeButton.trigger('click')
    await flushPromises()

    expect(mocks.analyzeJob).toHaveBeenCalledWith(6, {})
    expect(wrapper.text()).toContain(i18n.global.t('jobs.startupAnalysisCompleted'))
  })

  it('replaces the started banner when polling observes analysis completion', async () => {
    mocks.getJob
      .mockResolvedValueOnce({
        id: 6,
        status: 'PENDING',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        thread_count: 4,
        copied_bytes: 0,
        total_bytes: 0,
        startup_analysis_status: 'NOT_ANALYZED',
        startup_analysis_cached: true,
        startup_analysis_ready: false,
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        drive: { id: 1 },
      })
      .mockResolvedValueOnce({
        id: 6,
        status: 'PENDING',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        thread_count: 4,
        copied_bytes: 0,
        total_bytes: 0,
        startup_analysis_status: 'ANALYZING',
        startup_analysis_cached: true,
        startup_analysis_ready: false,
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        drive: { id: 1 },
      })
      .mockResolvedValueOnce({
        id: 6,
        status: 'PENDING',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        thread_count: 4,
        copied_bytes: 0,
        total_bytes: 0,
        startup_analysis_status: 'READY',
        startup_analysis_cached: true,
        startup_analysis_ready: true,
        startup_analysis_last_analyzed_at: '2026-04-24T15:00:00Z',
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        drive: { id: 1 },
      })

    const wrapper = mountView()
    await flushPromises()

    const analyzeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.analyze'))
    expect(analyzeButton).toBeTruthy()
    const editButton = wrapper.findAll('.actions button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()
    const startButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.start'))
    expect(startButton).toBeTruthy()
    const completeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.complete'))
    expect(completeButton).toBeTruthy()
    const deleteButton = wrapper.findAll('.actions button').find((node) => node.text() === i18n.global.t('common.actions.delete'))
    expect(deleteButton).toBeTruthy()
    const cleanupButton = wrapper.findAll('.actions button').find((node) => node.text() === i18n.global.t('jobs.clearStartupAnalysis'))
    expect(cleanupButton).toBeTruthy()

    await analyzeButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.startupAnalysisStarted'))
    expect(editButton.attributes('disabled')).toBeDefined()
    expect(analyzeButton.attributes('disabled')).toBeDefined()
    expect(startButton.attributes('disabled')).toBeDefined()
    expect(completeButton.attributes('disabled')).toBeDefined()
    expect(deleteButton.attributes('disabled')).toBeDefined()
    expect(cleanupButton.attributes('disabled')).toBeDefined()

    await mocks.pollerTick()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.startupAnalysisCompleted'))
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.startupAnalysisStarted'))
    expect(editButton.attributes('disabled')).toBeUndefined()
    expect(analyzeButton.attributes('disabled')).toBeUndefined()
    expect(startButton.attributes('disabled')).toBeUndefined()
    expect(completeButton.attributes('disabled')).toBeUndefined()
    expect(deleteButton.attributes('disabled')).toBeUndefined()
    expect(cleanupButton.attributes('disabled')).toBeUndefined()
  })

  it('shows analyze failure details and allows start when analysis is already ready', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'FAILED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 128,
      startup_analysis_status: 'FAILED',
      startup_analysis_failure_reason: 'Analysis failure reason: Startup analysis failed',
      startup_analysis_ready: false,
    })
    mocks.startJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 128,
      file_count: 2,
      files_succeeded: 0,
      files_failed: 0,
      startup_analysis_status: 'READY',
      startup_analysis_last_analyzed_at: '2026-04-24T15:00:00Z',
      startup_analysis_file_count: 2,
      startup_analysis_total_bytes: 128,
      startup_analysis_ready: true,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Failed')
  expect(wrapper.text()).toContain('Analysis failure reason: Startup analysis failed')
  expect(wrapper.text()).not.toContain('Analysis failure reason: Analysis failure reason:')

    const startButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.start'))
    expect(startButton).toBeTruthy()
    await startButton.trigger('click')
    await flushPromises()

    expect(mocks.startJob).toHaveBeenCalledWith(6, { thread_count: 4 })
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

    expect(wrapper.text()).toContain('Destination')
    expect(wrapper.text()).toContain('2-1')
    expect(wrapper.text()).not.toContain('/mnt/ecube/1')
    expect(wrapper.text()).toContain('Failure reason')
    expect(wrapper.text()).toContain('Job ID')
    expect(wrapper.text()).toContain('Failed at')
    expect(wrapper.text()).toContain('Related log entry')
    expect(wrapper.text()).toContain('JOB_FAILED job_id=6 error_count=1')
    expect(wrapper.text()).toContain('1 file failed: Permission denied (/evidence/report.pdf)')
  })

  it('shows retry failed files for partial-success jobs and calls the retry endpoint', async () => {
    mocks.getJob
      .mockResolvedValueOnce({
        id: 6,
        status: 'COMPLETED',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        thread_count: 4,
        copied_bytes: 10,
        total_bytes: 20,
        file_count: 2,
        files_succeeded: 1,
        files_failed: 1,
        files_timed_out: 0,
        startup_analysis_status: 'READY',
      })
      .mockResolvedValueOnce({
        id: 6,
        status: 'RUNNING',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        thread_count: 4,
        copied_bytes: 10,
        total_bytes: 20,
        file_count: 2,
        files_succeeded: 1,
        files_failed: 0,
        files_timed_out: 0,
        startup_analysis_status: 'READY',
      })

    const wrapper = mountView()
    await flushPromises()

    const retryButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.retryFailedFiles'))
    expect(retryButton).toBeTruthy()

    await retryButton.trigger('click')
    await flushPromises()

    expect(mocks.retryFailedJob).toHaveBeenCalledWith(6)
    expect(wrapper.text()).toContain('RUNNING')
  })

  it('archives a completed job only after confirmation', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10,
      total_bytes: 10,
      file_count: 1,
      files_succeeded: 1,
      files_failed: 0,
      files_timed_out: 0,
      startup_analysis_status: 'READY',
    })

    const wrapper = mountView()
    await flushPromises()

    const archiveButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.archive'))
    expect(archiveButton).toBeTruthy()

    await archiveButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.archiveConfirmTitle'))

    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.archiveJob).toHaveBeenCalledWith(6, { confirm: true })
  })

  it('requires the related drive to be ejected before archive is available', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10,
      total_bytes: 10,
      file_count: 1,
      files_succeeded: 1,
      files_failed: 0,
      files_timed_out: 0,
      startup_analysis_status: 'READY',
      drive: { id: 1, current_state: 'AVAILABLE', is_mounted: true },
    })

    const wrapper = mountView()
    await flushPromises()

    const archiveButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.archive'))
    expect(archiveButton).toBeTruthy()
    expect(archiveButton.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain(i18n.global.t('jobs.archiveRequiresEject'))
  })

  it('enables archive after the related drive is available and unmounted', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10,
      total_bytes: 10,
      file_count: 1,
      files_succeeded: 1,
      files_failed: 0,
      files_timed_out: 0,
      startup_analysis_status: 'READY',
      drive: { id: 1, current_state: 'AVAILABLE', is_mounted: false },
    })

    const wrapper = mountView()
    await flushPromises()

    const archiveButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.archive'))
    expect(archiveButton).toBeTruthy()
    expect(archiveButton.attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.archiveRequiresEject'))
  })

  it('shows archived jobs with lifecycle actions disabled', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'ARCHIVED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10,
      total_bytes: 10,
      file_count: 1,
      files_succeeded: 1,
      files_failed: 0,
      files_timed_out: 0,
      startup_analysis_status: 'READY',
    })

    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    const analyzeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.analyze'))
    const startButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.start'))

    expect(editButton).toBeTruthy()
    expect(analyzeButton).toBeTruthy()
    expect(startButton).toBeTruthy()
    expect(editButton.attributes('disabled')).toBeDefined()
    expect(analyzeButton.attributes('disabled')).toBeDefined()
    expect(startButton.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').some((node) => node.text() === i18n.global.t('jobs.archive'))).toBe(false)
  })

  it('keeps the files panel collapsed by default and pages through file rows with a 5-page window', async () => {
    setMobileViewport(true)
    mocks.getJobFiles.mockImplementation((_jobId, params = {}) => {
      if (params.page === 6) {
        return Promise.resolve({
          files: [{ id: 201, relative_path: 'doc/201.txt', status: 'DONE', checksum: 'sha256:201' }],
          total_files: 480,
          returned_files: 40,
          page: 6,
          page_size: 40,
        })
      }
      return Promise.resolve({
        files: [{ id: 1, relative_path: 'doc/001.txt', status: 'DONE', checksum: 'sha256:001' }],
        total_files: 480,
        returned_files: 40,
        page: 1,
        page_size: 40,
      })
    })

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getJobFiles.mock.calls).toContainEqual([6, { page: 1 }])

    const toggle = wrapper.find('.files-panel-toggle')
    expect(toggle.exists()).toBe(true)
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('#job-files-panel').exists()).toBe(false)

    await toggle.trigger('click')
    await flushPromises()

    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('jobs.checksum'))
    expect(wrapper.find('.columns-stub').text()).not.toContain(i18n.global.t('common.actions.edit'))
    expect(wrapper.findAll('.page-number-btn').map((node) => node.text())).toEqual(['1', '2', '3', '4', '5'])

    await wrapper.find('.page-window-next').trigger('click')
    await flushPromises()

    expect(mocks.getJobFiles.mock.calls).toContainEqual([6, { page: 6 }])
    expect(wrapper.findAll('.page-number-btn').map((node) => node.text())).toEqual(['6', '7', '8', '9', '10'])

    await toggle.trigger('click')
    await flushPromises()
    expect(toggle.attributes('aria-expanded')).toBe('false')

    await toggle.trigger('click')
    await flushPromises()
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.page-number-btn--active').text()).toBe('6')
  })

  it('renders compact accessible status icons in the files panel', async () => {
    setMobileViewport(true)
    mocks.getJobFiles.mockResolvedValue({
      files: [{ id: 1, relative_path: 'doc/001.txt', status: 'DONE' }],
      total_files: 1,
      returned_files: 1,
      page: 1,
      page_size: 40,
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()

    const statusIcon = wrapper.find('.file-status-icon')
    expect(statusIcon.exists()).toBe(true)
    expect(statusIcon.attributes('aria-label')).toBe('DONE')
    expect(statusIcon.attributes('title')).toBe('DONE')
    expect(statusIcon.text()).toBe('✓')
  })

  it('opens the hash viewer dialog when a file path is clicked', async () => {
    mocks.getJobFiles.mockResolvedValue({
      files: [{ id: 1, relative_path: 'evidence/2026/04/device-images/doc/001.txt', status: 'DONE' }],
      total_files: 1,
      returned_files: 1,
      page: 1,
      page_size: 40,
    })
    mocks.getFileHashes.mockResolvedValue({
      file_id: 1,
      md5: 'abc123',
      sha256: 'def456',
      size_bytes: 2048,
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()

    const filePathButton = wrapper.find('.file-path-button')
    expect(filePathButton.exists()).toBe(true)
  expect(filePathButton.attributes('title')).toBe('evidence/2026/04/device-images/doc/001.txt')
  expect(filePathButton.attributes('aria-label')).toBe('evidence/2026/04/device-images/doc/001.txt')
    await filePathButton.trigger('click')
    await flushPromises()

    expect(mocks.getFileHashes).toHaveBeenCalledWith(1)
    expect(wrapper.text()).toContain(i18n.global.t('jobs.hashViewer'))
    expect(wrapper.text()).toContain('abc123')
    expect(wrapper.text()).toContain('def456')
  })

  it('shows failed file details in a dialog and emphasizes only failed rows', async () => {
    const longError = 'Copy failed because the destination file could not be written after multiple safe retries. Review destination availability and retry the failed file set.'
    mocks.getJobFiles.mockResolvedValue({
      files: [
        { id: 1, relative_path: 'failed/doc-001.txt', status: 'FAILED', error_message: longError },
        { id: 2, relative_path: 'done/doc-002.txt', status: 'DONE', error_message: '' },
      ],
      total_files: 2,
      returned_files: 2,
      page: 1,
      page_size: 40,
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()

    const rows = wrapper.findAll('.row-stub')
    expect(rows[0].classes()).toContain('job-file-row-error')
    expect(rows[1].classes()).not.toContain('job-file-row-error')

    const columns = wrapper.find('.columns-stub').text()
    expect(columns).toContain(i18n.global.t('common.labels.status'))
    expect(columns).not.toContain(i18n.global.t('jobs.details'))

    const detailButtons = wrapper.findAll('.file-status-button')
    expect(detailButtons).toHaveLength(1)

    await detailButtons[0].trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.fileErrorDetails'))
    expect(wrapper.text()).toContain(longError)

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.close')).trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.fileErrorDetailsEmpty'))
  })

  it('does not show a file error affordance when the current page has no file errors', async () => {
    mocks.getJobFiles.mockResolvedValue({
      files: [{ id: 1, relative_path: 'done/doc-001.txt', status: 'DONE', error_message: '' }],
      total_files: 1,
      returned_files: 1,
      page: 1,
      page_size: 40,
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()

    expect(wrapper.find('.file-status-button').exists()).toBe(false)
    expect(wrapper.find('.job-file-row-error').exists()).toBe(false)
  })

  it('prefers the persisted job-level failure reason when present', async () => {
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
      failure_reason: 'Copy job timed out before all files completed',
      error_summary: '1 file failed: Permission denied (/evidence/report.pdf)',
      failure_log_entry: '2026-04-18T10:22:33+00:00 [ERROR] app.services.copy_engine: JOB_FAILED job_id=6 reason=Copy job timed out before all files completed',
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Copy job timed out before all files completed')
    expect(wrapper.text()).not.toContain('1 file failed: Permission denied (/evidence/report.pdf)')
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

  it('shows live copy rate and estimated completion for active jobs', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-24T15:01:00Z'))

    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 60 * 1024 * 1024,
      total_bytes: 120 * 1024 * 1024,
      file_count: 4,
      files_succeeded: 2,
      files_failed: 0,
      started_at: '2026-04-24T15:00:00Z',
      active_duration_seconds: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Live copy summary')
    expect(wrapper.text()).toContain('Duration')
    expect(wrapper.text()).toContain('1m 0s')
    expect(wrapper.text()).toContain('Copy rate')
    expect(wrapper.text()).toContain('1.0 MB/s')
    expect(wrapper.text()).toContain('Time remaining')
    expect(wrapper.text()).toContain('Estimated completion')
    expect(wrapper.text()).toContain(new Date('2026-04-24T15:02:00Z').toLocaleString())

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('does not show live copy summary while the job is verifying', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'VERIFYING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 60 * 1024 * 1024,
      total_bytes: 120 * 1024 * 1024,
      file_count: 4,
      files_succeeded: 2,
      files_failed: 0,
      started_at: '2026-04-24T15:00:00Z',
      active_duration_seconds: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Live copy summary')
  })

  it('does not show 100% while a running job is still below 1%', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 136 * 1024 * 1024,
      total_bytes: 27 * 1024 * 1024 * 1024,
      file_count: 5000,
      files_succeeded: 0,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const progress = wrapper.find('.progressbar-stub').text()
    expect(progress).toContain('0|100|')
    expect(progress).not.toContain('100|100|')
    expect(wrapper.text()).toContain('136 MB / 27 GB')
  })

  it('shows a preparing indicator while an active job is still calculating totals', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
      file_count: 0,
      files_succeeded: 0,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const progress = wrapper.find('.progressbar-stub').text()
    expect(progress).toContain(`0|100|${i18n.global.t('jobs.progressPreparing')}`)
    expect(progress).toContain('true|true')
    expect(wrapper.text()).toContain(i18n.global.t('jobs.progressPreparingDetail'))
  })

  it('keeps verify and manifest disabled until the job reaches 100%', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 50,
      total_bytes: 100,
      file_count: 2,
      files_succeeded: 1,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const verifyButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.verify'))
    const manifestButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.manifest'))

    expect(verifyButton).toBeTruthy()
    expect(manifestButton).toBeTruthy()
    expect(verifyButton.attributes('disabled')).toBeDefined()
    expect(manifestButton.attributes('disabled')).toBeDefined()
  })

  it('keeps verify and manifest disabled for completed jobs with failed files', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 100,
      total_bytes: 100,
      file_count: 2,
      files_succeeded: 1,
      files_failed: 1,
      files_timed_out: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const verifyButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.verify'))
    const manifestButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.manifest'))

    expect(verifyButton).toBeTruthy()
    expect(manifestButton).toBeTruthy()
    expect(verifyButton.attributes('disabled')).toBeDefined()
    expect(manifestButton.attributes('disabled')).toBeDefined()
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
    expect(wrapper.find('.completion-summary').classes()).not.toContain('completion-summary--danger')
  })

  it('uses a danger background for the completion summary when file copy failures are present', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 5242880,
      total_bytes: 10485760,
      file_count: 4,
      files_succeeded: 3,
      files_failed: 1,
      files_timed_out: 0,
      started_at: '2026-04-18T10:00:00Z',
      completed_at: '2026-04-18T10:00:02Z',
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('Completion summary')
    expect(wrapper.find('.completion-summary').classes()).toContain('completion-summary--danger')
  })

  it('uses source and destination terminology for file comparison', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 100,
      total_bytes: 100,
      file_count: 1,
      files_succeeded: 1,
      files_failed: 0,
    })
    mocks.getJobFiles.mockImplementation((_jobId, params = {}) => {
      if (params.page === 1) {
        return Promise.resolve({
          files: [
            { id: 7, relative_path: 'source.txt', status: 'DONE', checksum: 'src' },
            { id: 9, relative_path: 'doc.txt', status: 'DONE', checksum: 'abc' },
          ],
          total_files: 1,
          returned_files: 2,
          page: 1,
          page_size: 100,
        })
      }
      return Promise.resolve({ files: [], total_files: 0, returned_files: 0, page: 1, page_size: 40 })
    })
    mocks.compareFiles.mockResolvedValue({
      match: true,
      hash_match: true,
      size_match: true,
      path_match: true,
      file_a: { file_id: 7, relative_path: 'source.txt', size_bytes: 12, sha256: 'abc' },
      file_b: { file_id: 9, relative_path: 'doc.txt', size_bytes: 12, sha256: 'abc' },
    })

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getJobFiles.mock.calls).toContainEqual([6, { page: 1 }])

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()
    await wrapper.findAll('.file-path-button')[1].trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Source')
    expect(wrapper.text()).toContain('Destination')
    expect(wrapper.text()).not.toContain('File A')
    expect(wrapper.text()).not.toContain('File B')

    await wrapper.find('#compare-file-source').setValue('7')
    const compareButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.compare'))
    expect(compareButton).toBeTruthy()
    await compareButton.trigger('click')
    await flushPromises()

    expect(mocks.compareFiles).toHaveBeenCalledWith({ file_id_a: 7, file_id_b: 9 })
    expect(wrapper.text()).toContain('source.txt')
    expect(wrapper.text()).toContain('doc.txt')
  })

  it('limits compare source options to the current files page', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'COMPLETED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 100,
      total_bytes: 100,
      file_count: 150,
      files_succeeded: 150,
      files_failed: 0,
    })
    mocks.getJobFiles.mockImplementation((_jobId, params = {}) => {
      if (params.page === 4) {
        return Promise.resolve({
          files: [{ id: 150, relative_path: 'doc-150.txt', status: 'DONE', checksum: 'def' }],
          total_files: 150,
          returned_files: 30,
          page: 4,
          page_size: 40,
        })
      }
      return Promise.resolve({
        files: [{ id: 9, relative_path: 'doc-009.txt', status: 'DONE', checksum: 'abc' }],
        total_files: 150,
        returned_files: 40,
        page: 1,
        page_size: 40,
      })
    })
    mocks.compareFiles.mockResolvedValue({
      match: true,
      hash_match: true,
      size_match: true,
      path_match: true,
      file_a: { file_id: 150, relative_path: 'doc-150.txt', size_bytes: 12, sha256: 'def' },
      file_b: { file_id: 9, relative_path: 'doc-009.txt', size_bytes: 12, sha256: 'abc' },
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()

    await wrapper.find('.file-path-button').trigger('click')
    await flushPromises()

    expect(wrapper.find('#compare-file-source').text()).toContain('doc-009.txt')
    expect(wrapper.find('#compare-file-source').text()).not.toContain('doc-150.txt')

    await wrapper.findAll('.page-number-btn').find((node) => node.text() === '4').trigger('click')
    await flushPromises()

    expect(wrapper.find('#compare-file-source').text()).toContain('doc-150.txt')
    expect(wrapper.find('#compare-file-source').text()).not.toContain('doc-009.txt')

    await wrapper.find('#compare-file-source').setValue('150')
    const compareButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.compare'))
    expect(compareButton).toBeTruthy()
    expect(compareButton.attributes('disabled')).toBeUndefined()
    await compareButton.trigger('click')
    await flushPromises()

    expect(mocks.getJobFiles.mock.calls).toContainEqual([6, { page: 4 }])
    expect(mocks.compareFiles).toHaveBeenCalledWith({ file_id_a: 150, file_id_b: 9 })
    expect(wrapper.text()).toContain('doc-150.txt')
  })

  it('does not reload files during background polling but still reloads them on manual refresh', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 50,
      total_bytes: 100,
      file_count: 2,
      files_succeeded: 1,
      files_failed: 0,
    })
    mocks.getJobFiles.mockResolvedValue({ files: [{ id: 9, relative_path: 'doc.txt', status: 'DONE', checksum: 'abc' }] })

    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getJobFiles).toHaveBeenCalledTimes(1)
    expect(typeof mocks.pollerTick).toBe('function')

    await mocks.pollerTick()
    await flushPromises()

    expect(mocks.getJobFiles).toHaveBeenCalledTimes(1)

    const refreshButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.refresh'))
    expect(refreshButton).toBeTruthy()
    await refreshButton.trigger('click')
    await flushPromises()

    expect(mocks.getJobFiles).toHaveBeenCalledTimes(2)
  })

  it('shows a pause-in-progress dialog after pausing a running job', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 50,
      total_bytes: 100,
      file_count: 2,
      files_succeeded: 1,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const pauseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.pause'))
    expect(pauseButton).toBeTruthy()
    await pauseButton.trigger('click')
    await flushPromises()

    expect(mocks.pauseJob).toHaveBeenCalledWith(6)
    expect(wrapper.text()).toContain('Pause in progress')
  })

  it('moves focus into the edit dialog and closes it on Escape', async () => {
    const wrapper = mountView()
    await flushPromises()

    const editButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.edit'))
    expect(editButton).toBeTruthy()
    await editButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('#job-evidence').exists()).toBe(true)
    expect(document.activeElement?.id).toBe('job-evidence')

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.find('#job-evidence').exists()).toBe(false)
  })

  it('moves focus into the pause dialog and closes it on Escape', async () => {
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 50,
      total_bytes: 100,
      file_count: 2,
      files_succeeded: 1,
      files_failed: 0,
    })

    const wrapper = mountView()
    await flushPromises()

    const pauseButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.pause'))
    expect(pauseButton).toBeTruthy()
    await pauseButton.trigger('click')
    await flushPromises()

    const closeButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('common.actions.close'))
    expect(closeButton).toBeTruthy()
    expect(document.activeElement?.textContent).toContain(i18n.global.t('common.actions.close'))

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()

    expect(wrapper.text()).not.toContain('Pause in progress')
  })

  it('shows a success banner after generating a manifest', async () => {
    const createObjectUrl = vi.fn(() => 'blob:manifest')
    const revokeObjectUrl = vi.fn()
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const originalCreateObjectUrl = URL.createObjectURL
    const originalRevokeObjectUrl = URL.revokeObjectURL
    URL.createObjectURL = createObjectUrl
    URL.revokeObjectURL = revokeObjectUrl

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
    mocks.downloadManifest.mockResolvedValue({
      data: new Blob(['{"job_id":6}'], { type: 'application/json' }),
      headers: {
        'content-type': 'application/json',
        'content-disposition': 'attachment; filename="manifest.json"',
      },
    })

    try {
      const wrapper = mountView()
      await flushPromises()

      const manifestButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.manifest'))
      expect(manifestButton).toBeTruthy()
      await manifestButton.trigger('click')
      await flushPromises()

      expect(mocks.generateManifest).toHaveBeenCalledWith(6)
      expect(mocks.downloadManifest).toHaveBeenCalledWith(6)
      expect(createObjectUrl).toHaveBeenCalledTimes(1)
      expect(clickSpy).toHaveBeenCalledTimes(1)
      expect(revokeObjectUrl).toHaveBeenCalledWith('blob:manifest')
      expect(wrapper.text()).toContain('Manifest generated successfully.')
      expect(wrapper.text()).toContain('/mnt/ecube/1/manifest.json')
    } finally {
      URL.createObjectURL = originalCreateObjectUrl
      URL.revokeObjectURL = originalRevokeObjectUrl
      clickSpy.mockRestore()
    }
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
    const driveOptions = wrapper.find('#job-drive').findAll('option').map((node) => node.text())
    expect(wrapper.text()).toContain(i18n.global.t('jobs.selectDrive'))
    expect(driveOptions.join(' ')).toContain('2-1')
    expect(driveOptions.join(' ')).not.toContain('#1 -')
    expect(driveOptions.join(' ')).not.toContain('USB-001')
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

  it('keeps pending-job edit analyze and start as primary buttons and moves the rest into overflow', async () => {
    setMobileViewport(true)
    const wrapper = mountView()
    await flushPromises()

    const primaryButtons = wrapper.findAll('.actions > button')
    expect(primaryButtons.map((button) => button.text())).toEqual([
      i18n.global.t('common.actions.edit'),
      i18n.global.t('jobs.analyze'),
      i18n.global.t('jobs.start'),
    ])

    expect(wrapper.find('.actions-menu').exists()).toBe(true)
    expect(wrapper.find('.detail-action-menu-complete').exists()).toBe(true)
    expect(wrapper.find('.detail-action-menu-delete').exists()).toBe(true)
  })

  it('keeps pause primary for running jobs and moves the rest into overflow', async () => {
    setMobileViewport(true)
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'RUNNING',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 10,
      total_bytes: 20,
      startup_analysis_status: 'READY',
      startup_analysis_ready: true,
      drive: { id: 1 },
    })

    const wrapper = mountView()
    await flushPromises()

    const primaryButtons = wrapper.findAll('.actions > button')
    expect(primaryButtons.map((button) => button.text())).toEqual([
      i18n.global.t('jobs.pause'),
    ])
    expect(wrapper.find('.detail-action-menu-edit').exists()).toBe(true)

    await primaryButtons[0].trigger('click')
    await flushPromises()

    expect(mocks.pauseJob).toHaveBeenCalledWith(6)
  })

  it('keeps desktop job detail actions expanded and files pagination wide', async () => {
    mocks.getJobFiles.mockResolvedValue({
      files: [{ id: 1, relative_path: 'doc/001.txt', status: 'DONE' }],
      total_files: 480,
      returned_files: 40,
      page: 1,
      page_size: 40,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.actions-menu').exists()).toBe(false)
    expect(wrapper.findAll('.actions > button').map((button) => button.text())).toEqual([
      i18n.global.t('common.actions.edit'),
      i18n.global.t('jobs.analyze'),
      i18n.global.t('jobs.start'),
      i18n.global.t('jobs.retryFailedFiles'),
      i18n.global.t('jobs.pause'),
      i18n.global.t('jobs.complete'),
      i18n.global.t('jobs.verify'),
      i18n.global.t('jobs.manifest'),
      i18n.global.t('jobs.archive'),
      i18n.global.t('common.actions.delete'),
    ])

    await wrapper.find('.files-panel-toggle').trigger('click')
    await flushPromises()

    expect(wrapper.find('.file-status-icon').exists()).toBe(false)
    expect(wrapper.text()).toContain('DONE')
    expect(wrapper.findAll('.page-number-btn').map((node) => node.text())).toEqual([
      '1', '2', '3', '4', '5', '6', '7', '8', '9', '10',
    ])
  })

  it('shows the startup-analysis cleanup control for manager roles and confirms cleanup', async () => {
    mocks.hasAnyRole.mockImplementation((roles) => roles.includes('manager') || roles.includes('auditor'))
    mocks.getJob
      .mockResolvedValueOnce({
        id: 6,
        status: 'FAILED',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        thread_count: 4,
        copied_bytes: 0,
        total_bytes: 0,
        startup_analysis_cached: true,
      })
      .mockResolvedValue({
        id: 6,
        status: 'FAILED',
        project_id: 'PROJ-001',
        evidence_number: 'EV-006',
        source_path: '/nfs/project-001/evidence',
        target_mount_path: '/mnt/ecube/1',
        thread_count: 4,
        copied_bytes: 0,
        total_bytes: 0,
        startup_analysis_cached: false,
      })

    const wrapper = mountView()
    await flushPromises()

    const cleanupButton = wrapper.findAll('button').find((node) => node.text() === i18n.global.t('jobs.clearStartupAnalysis'))
    expect(cleanupButton).toBeTruthy()
    await cleanupButton.trigger('click')
    await flushPromises()

    expect(wrapper.find('.confirm-dialog-stub').exists()).toBe(true)
    await wrapper.find('.confirm-dialog-confirm').trigger('click')
    await flushPromises()

    expect(mocks.clearJobStartupAnalysisCache).toHaveBeenCalledWith(6, { confirm: true })
    expect(wrapper.text()).toContain(i18n.global.t('jobs.startupAnalysisCacheCleared'))
  })

  it('hides the startup-analysis cleanup control from processor-only roles', async () => {
    mocks.hasAnyRole.mockImplementation((roles) => roles.includes('processor'))
    mocks.getJob.mockResolvedValue({
      id: 6,
      status: 'FAILED',
      project_id: 'PROJ-001',
      evidence_number: 'EV-006',
      source_path: '/nfs/project-001/evidence',
      target_mount_path: '/mnt/ecube/1',
      thread_count: 4,
      copied_bytes: 0,
      total_bytes: 0,
      startup_analysis_cached: true,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.clearStartupAnalysis'))
  })

  it('shows the analyze control for processor roles', async () => {
    mocks.hasAnyRole.mockImplementation((roles) => roles.includes('processor'))
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
      startup_analysis_status: 'NOT_ANALYZED',
      startup_analysis_ready: false,
    })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('jobs.analyze'))
    expect(wrapper.text()).not.toContain(i18n.global.t('jobs.clearStartupAnalysis'))
  })
})
