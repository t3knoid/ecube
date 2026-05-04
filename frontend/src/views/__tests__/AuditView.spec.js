import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import AuditView from '@/views/AuditView.vue'

const fixedNow = new Date('2026-04-02T10:15:00.000Z')

function installMatchMedia(matches = false) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation(() => ({
      matches,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    })),
  })
}

const mocks = vi.hoisted(() => ({
  getAudit: vi.fn(),
  getAuditOptions: vi.fn(),
  settingsStore: { downloadRevokeDelayMs: 0, auditExportFilename: 'audit-log' },
}))

vi.mock('@/api/audit.js', () => ({
  getAudit: (...args) => mocks.getAudit(...args),
  getAuditOptions: (...args) => mocks.getAuditOptions(...args),
}))

vi.mock('@/stores/settings.js', () => ({
  useSettingsStore: () => mocks.settingsStore,
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

function mountView() {
  return mount(AuditView, {
    global: {
      plugins: [i18n],
      stubs: {
        DataTable: {
          props: ['rows', 'columns'],
          template: '<div class="data-table-shell"><slot v-for="row in rows" name="cell-details" :row="row" /><slot /></div>',
        },
        Pagination: {
          props: ['page', 'pageSize', 'total', 'showPageWindow', 'windowSize', 'jumpSize'],
          emits: ['update:page'],
          template: '<div class="pagination" :data-total="total" :data-show-page-window="showPageWindow" :data-window-size="windowSize" :data-jump-size="jumpSize"><button class="next-page" @click="$emit(\'update:page\', page + 1)">next</button></div>',
        },
        StatusBadge: { props: ['status'], template: '<span class="status-badge">{{ status }}</span>' },
      },
    },
  })
}

describe('AuditView audit log page', () => {
  beforeEach(() => {
    installMatchMedia(false)
    vi.useFakeTimers()
    vi.setSystemTime(fixedNow)
    mocks.getAudit.mockReset()
    mocks.getAuditOptions.mockReset()
    mocks.getAudit.mockResolvedValue({
      entries: [
        {
          id: 10,
          timestamp: '2026-04-01T13:00:00.000Z',
          user: 'auditor-user',
          action: 'JOB_CREATED',
          job_id: 12,
          client_ip: '127.0.0.1',
          details: { project_id: 'PRJ-001' },
        },
      ],
      total: 41,
      limit: 20,
      offset: 0,
      has_more: true,
    })
    mocks.getAuditOptions.mockResolvedValue({
      actions: ['JOB_CREATED'],
      users: ['auditor-user'],
      job_ids: [12],
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the audit log view without chain-of-custody controls', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(mocks.getAuditOptions).toHaveBeenCalledTimes(1)
    expect(mocks.getAudit).toHaveBeenCalledWith(expect.objectContaining({ limit: 20, offset: 0, include_total: true }))
    expect(wrapper.find('.pagination').attributes('data-show-page-window')).toBe('true')
    expect(wrapper.find('.pagination').attributes('data-window-size')).toBe('10')
    expect(wrapper.find('.pagination').attributes('data-jump-size')).toBe('10')
    expect(wrapper.text()).toContain(i18n.global.t('audit.title'))
    expect(wrapper.text()).toContain(i18n.global.t('audit.exportAuditCsv'))
    expect(wrapper.text()).not.toContain(i18n.global.t('audit.chainTitle'))
    expect(wrapper.text()).not.toContain(i18n.global.t('audit.loadCoc'))
    expect(wrapper.text()).toContain(i18n.global.t('audit.showDetails'))
  })

  it('uses 5-page shortcuts on smaller screens', async () => {
    installMatchMedia(true)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.pagination').attributes('data-window-size')).toBe('5')
    expect(wrapper.find('.pagination').attributes('data-jump-size')).toBe('5')
  })

  it('applies server-backed filters and paginates with backend offsets', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find(`select[aria-label="${i18n.global.t('audit.userFilter')}"]`).setValue('auditor-user')
    await wrapper.find(`select[aria-label="${i18n.global.t('audit.actionFilter')}"]`).setValue('JOB_CREATED')
    await wrapper.find(`select[aria-label="${i18n.global.t('audit.jobIdFilter')}"]`).setValue('12')
    await wrapper.find(`input[aria-label="${i18n.global.t('audit.searchFilter')}"]`).setValue('PRJ-001')
    const dateInputs = wrapper.findAll('input[type="datetime-local"]')
    await dateInputs[0].setValue('2026-04-01T08:00')
    await dateInputs[1].setValue('2026-04-01T09:00')

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('audit.applyFilters')).trigger('click')
    await flushPromises()

    expect(mocks.getAuditOptions).toHaveBeenCalledTimes(1)
    expect(mocks.getAudit).toHaveBeenLastCalledWith(expect.objectContaining({
      user: 'auditor-user',
      action: 'JOB_CREATED',
      job_id: 12,
      search: 'PRJ-001',
      offset: 0,
      limit: 20,
      include_total: true,
    }))

    await wrapper.find('.next-page').trigger('click')
    await flushPromises()

    expect(mocks.getAudit).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20, limit: 20, include_total: false }))
    expect(wrapper.find('.pagination').attributes('data-total')).toBe('41')
  })

  it('exports the filtered audit result set by paging the backend', async () => {
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:audit')
    const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    mocks.getAudit.mockReset()
    mocks.getAudit.mockResolvedValueOnce({
      entries: [
        {
          id: 10,
          timestamp: '2026-04-01T13:00:00.000Z',
          user: 'auditor-user',
          action: 'JOB_CREATED',
          job_id: 12,
          client_ip: '127.0.0.1',
          details: { project_id: 'PRJ-001' },
        },
      ],
      total: 2,
      limit: 20,
      offset: 0,
      has_more: false,
    })
    mocks.getAudit.mockResolvedValueOnce({
      entries: [
        {
          id: 10,
          timestamp: '2026-04-01T13:00:00.000Z',
          user: 'auditor-user',
          action: 'JOB_CREATED',
          job_id: 12,
          client_ip: '127.0.0.1',
          details: { project_id: 'PRJ-001' },
        },
      ],
      total: 2,
      limit: 500,
      offset: 0,
      has_more: true,
    })
    mocks.getAudit.mockResolvedValueOnce({
      entries: [
        {
          id: 11,
          timestamp: '2026-04-01T14:00:00.000Z',
          user: 'auditor-user',
          action: 'JOB_COMPLETED',
          job_id: 12,
          client_ip: '127.0.0.1',
          details: { project_id: 'PRJ-001' },
        },
      ],
      total: 2,
      limit: 500,
      offset: 1,
      has_more: false,
    })

    const wrapper = mountView()
    await flushPromises()

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('audit.exportAuditCsv')).trigger('click')
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)
    expect(mocks.getAudit).toHaveBeenNthCalledWith(2, expect.objectContaining({ limit: 500, offset: 0 }))
    expect(mocks.getAudit).toHaveBeenNthCalledWith(3, expect.objectContaining({ limit: 500, offset: 1 }))

    clickSpy.mockRestore()
    createObjectURLSpy.mockRestore()
    revokeObjectURLSpy.mockRestore()
  })
})