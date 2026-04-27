import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '@/i18n/index.js'
import AppSidebar from '@/components/layout/AppSidebar.vue'

function mockMatchMedia(matches) {
  const listeners = new Set()

  const implementation = vi.fn().mockImplementation(() => ({
    matches,
    addEventListener: (_eventName, handler) => listeners.add(handler),
    removeEventListener: (_eventName, handler) => listeners.delete(handler),
  }))

  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: implementation,
  })

  return implementation
}

describe('AppSidebar', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mountSidebar(props = {}) {
    const pinia = createPinia()
    setActivePinia(pinia)

    return mount(AppSidebar, {
      props,
      global: {
        plugins: [i18n, pinia],
        stubs: {
          RouterLink: RouterLinkStub,
        },
      },
    })
  }

  it('hides the closed sidebar from assistive technology on mobile', async () => {
    mockMatchMedia(true)
    const wrapper = mountSidebar({ sidebarOpen: false })
    await nextTick()

    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.attributes()).toHaveProperty('inert')

    wrapper.unmount()
  })

  it('keeps the sidebar available when opened on mobile', () => {
    mockMatchMedia(true)
    const wrapper = mountSidebar({ sidebarOpen: true })

    expect(wrapper.attributes('aria-hidden')).toBeUndefined()
    expect(wrapper.attributes('inert')).toBeUndefined()

    wrapper.unmount()
  })

  it('keeps the sidebar available on desktop when closed', () => {
    mockMatchMedia(false)
    const wrapper = mountSidebar({ sidebarOpen: false })

    expect(wrapper.attributes('aria-hidden')).toBeUndefined()
    expect(wrapper.attributes('inert')).toBeUndefined()

    wrapper.unmount()
  })
})