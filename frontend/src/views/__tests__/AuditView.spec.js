import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import AuditView from '@/views/AuditView.vue'

const fixedNow = new Date('2026-04-02T10:15:00.000Z')

const mocks = vi.hoisted(() => ({
  getAudit: vi.fn(),
  settingsStore: { downloadRevokeDelayMs: 0, auditExportFilename: 'audit-log' },
}))

vi.mock('@/api/audit.js', () => ({
  getAudit: (...args) => mocks.getAudit(...args),
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
        Pagination: { template: '<div class="pagination" />' },
        StatusBadge: { props: ['status'], template: '<span class="status-badge">{{ status }}</span>' },
      },
    },
  })
}

describe('AuditView audit log page', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(fixedNow)
    mocks.getAudit.mockReset()
    mocks.getAudit.mockResolvedValue([
      {
        id: 10,
        timestamp: '2026-04-01T13:00:00.000Z',
        user: 'auditor-user',
        action: 'JOB_CREATED',
        job_id: 12,
        client_ip: '127.0.0.1',
        details: { project_id: 'PRJ-001' },
      },
    ])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the audit log view without chain-of-custody controls', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('audit.title'))
    expect(wrapper.text()).toContain(i18n.global.t('audit.exportAuditCsv'))
    expect(wrapper.text()).not.toContain(i18n.global.t('audit.chainTitle'))
    expect(wrapper.text()).not.toContain(i18n.global.t('audit.loadCoc'))
    expect(wrapper.text()).toContain(i18n.global.t('audit.showDetails'))
  })

  it('loads audit log filters and exports audit CSV', async () => {
    const createObjectURLSpy = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:audit')
    const revokeObjectURLSpy = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const wrapper = mountView()
    await flushPromises()

    const [userInput, actionInput, sinceInput, untilInput] = wrapper.findAll('input')
    await userInput.setValue('auditor-user')
    await actionInput.setValue('JOB_CREATED')
    await sinceInput.setValue('2026-04-01T08:00')
    await untilInput.setValue('2026-04-01T09:00')

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('audit.applyFilters')).trigger('click')
    await flushPromises()

    expect(mocks.getAudit).toHaveBeenLastCalledWith(expect.objectContaining({
      user: 'auditor-user',
      action: 'JOB_CREATED',
    }))

    await wrapper.findAll('button').find((node) => node.text() === i18n.global.t('audit.exportAuditCsv')).trigger('click')
    expect(createObjectURLSpy).toHaveBeenCalledTimes(1)

    clickSpy.mockRestore()
    createObjectURLSpy.mockRestore()
    revokeObjectURLSpy.mockRestore()
  })
})