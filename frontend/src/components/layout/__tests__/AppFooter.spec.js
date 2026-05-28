import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import AppFooter from '@/components/layout/AppFooter.vue'

const mocks = vi.hoisted(() => ({
  getVersion: vi.fn(),
  getSystemHealth: vi.fn(),
}))

vi.mock('@/api/introspection.js', () => ({
  getVersion: mocks.getVersion,
  getSystemHealth: mocks.getSystemHealth,
}))

async function flushPromises() {
  await Promise.resolve()
  await Promise.resolve()
}

describe('AppFooter', () => {
  beforeEach(() => {
    mocks.getVersion.mockReset()
    mocks.getSystemHealth.mockReset()
    mocks.getVersion.mockResolvedValue({ version: '0.2.0', build_timestamp: '2026-05-27T21:18:00Z' })
    mocks.getSystemHealth.mockResolvedValue({ database: 'connected', active_jobs: 3 })
  })

  it('shows version, build date, database status, and active job count', async () => {
    const wrapper = mount(AppFooter, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('ECUBE 0.2.0')
    expect(wrapper.text()).toContain('Build Date: 2026-05-27 21:18 UTC')
    expect(wrapper.text()).toContain('DB: ● Connected')
    expect(wrapper.text()).toContain('Active Jobs: 3')

    wrapper.unmount()
  })

  it('omits build date when the version endpoint does not provide one', async () => {
    mocks.getVersion.mockResolvedValue({ version: '0.2.0', build_timestamp: null })

    const wrapper = mount(AppFooter, {
      global: {
        plugins: [i18n],
      },
    })

    await flushPromises()

    expect(wrapper.text()).not.toContain('Build Date:')

    wrapper.unmount()
  })
})