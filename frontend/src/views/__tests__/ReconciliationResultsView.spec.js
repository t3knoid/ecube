import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import i18n from '@/i18n/index.js'
import ReconciliationResultsView from '@/views/ReconciliationResultsView.vue'

const mockRouter = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/reconciliation-results',
      name: 'reconciliation-results',
      component: ReconciliationResultsView,
    },
  ],
})

const mocks = vi.hoisted(() => ({
  getDrives: vi.fn(),
  getMounts: vi.fn(),
}))

vi.mock('@/api/drives.js', () => ({
  getDrives: mocks.getDrives,
}))

vi.mock('@/api/mounts.js', () => ({
  getMounts: mocks.getMounts,
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

function mountView(options = {}) {
  return mount(ReconciliationResultsView, {
    ...options,
    global: {
      plugins: [i18n, mockRouter],
      stubs: {
        DataTable: {
          props: ['rows', 'columns'],
          template: '<div><tr v-for="col in columns" :key="col.key">{{ col.label }}</tr><tr v-for="row in rows" :key="row.id">{{ row.id }}</tr></div>',
        },
        Pagination: {
          template: '<div />',
        },
        StatusBadge: {
          props: ['status'],
          template: '<span>{{ status }}<slot /></span>',
        },
      },
    },
  })
}

describe('ReconciliationResultsView', () => {
  beforeEach(() => {
    mocks.getDrives.mockReset()
    mocks.getMounts.mockReset()
    mocks.getDrives.mockResolvedValue([
      {
        id: 1,
        display_device_label: 'Drive 1',
        serial_number: 'SER-001',
        filesystem_type: 'ext4',
        capacity_bytes: 1073741824,
        current_state: 'AVAILABLE',
        current_project_id: 'PROJ-001',
      },
    ])
    mocks.getMounts.mockResolvedValue([
      {
        id: 1,
        type: 'NFS',
        project_id: 'PROJ-001',
        status: 'MOUNTED',
        local_mount_point: '/mnt/share',
      },
    ])
  })

  it('displays reconciliation summary when result is available', async () => {
    const reconciliationResult = {
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 2,
      network_mounts_corrected: 1,
      usb_mounts_checked: 1,
      usb_mounts_corrected: 1,
      failure_count: 0,
    }

    const wrapper = mountView({
      props: {
        reconciliationResult,
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.reconciliationResults'))
    expect(wrapper.text()).toContain(i18n.global.t('system.reconciliationSummary'))
    expect(wrapper.text()).toContain('2')
    expect(wrapper.text()).toContain('1')
    expect(wrapper.text()).toContain('0')
  })

  it('displays USB mounts panel with drive data', async () => {
    const reconciliationResult = {
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 0,
      network_mounts_corrected: 0,
      usb_mounts_checked: 1,
      usb_mounts_corrected: 1,
      failure_count: 0,
    }

    const wrapper = mountView({
      props: {
        reconciliationResult,
      },
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain(i18n.global.t('system.reconciledUsbMounts'))
    expect(mocks.getDrives).toHaveBeenCalled()
  })

  it('displays shared mounts panel with mount data', async () => {
    const reconciliationResult = {
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 1,
      network_mounts_corrected: 1,
      usb_mounts_checked: 0,
      usb_mounts_corrected: 0,
      failure_count: 0,
    }

    const wrapper = mountView({
      props: {
        reconciliationResult,
      },
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain(i18n.global.t('system.reconciledSharedMounts'))
    expect(mocks.getMounts).toHaveBeenCalled()
  })

  it('shows warning status badge for partial results', async () => {
    const reconciliationResult = {
      status: 'partial',
      scope: 'managed_mounts_only',
      network_mounts_checked: 2,
      network_mounts_corrected: 1,
      usb_mounts_checked: 1,
      usb_mounts_corrected: 0,
      failure_count: 1,
    }

    const wrapper = mountView({
      props: {
        reconciliationResult,
      },
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    // Check for the i18n-translated text for partial status
    expect(wrapper.text()).toContain(i18n.global.t('system.reconcileStatuses.partial'))
  })

  it('shows back button for navigation', async () => {
    const reconciliationResult = {
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 0,
      network_mounts_corrected: 0,
      usb_mounts_checked: 0,
      usb_mounts_corrected: 0,
      failure_count: 0,
    }

    const wrapper = mountView({
      props: {
        reconciliationResult,
      },
    })

    const backButton = wrapper.findAll('button').find((b) => b.text() === i18n.global.t('common.actions.back'))
    expect(backButton).toBeTruthy()
  })

  it('shows error when no reconciliation result', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain(i18n.global.t('system.reconciliationResultsNotAvailable'))
  })

  it('shows message when no data is available', async () => {
    mocks.getDrives.mockResolvedValue([])
    mocks.getMounts.mockResolvedValue([])

    const reconciliationResult = {
      status: 'ok',
      scope: 'managed_mounts_only',
      network_mounts_checked: 0,
      network_mounts_corrected: 0,
      usb_mounts_checked: 0,
      usb_mounts_corrected: 0,
      failure_count: 0,
    }

    const wrapper = mountView({
      props: {
        reconciliationResult,
      },
    })

    await flushPromises()
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain(i18n.global.t('system.reconciliationNoData'))
  })
})
