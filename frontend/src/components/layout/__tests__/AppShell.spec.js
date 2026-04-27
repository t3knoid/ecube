import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AppShell from '@/components/layout/AppShell.vue'

describe('AppShell responsive sidebar', () => {
  function mockMatchMedia(matches) {
    const listeners = new Set()
    const mediaQuery = {
      matches,
      addEventListener: (_eventName, handler) => listeners.add(handler),
      removeEventListener: (_eventName, handler) => listeners.delete(handler),
    }

    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation(() => mediaQuery),
    })

    return {
      setMatches(nextMatches) {
        mediaQuery.matches = nextMatches
        for (const listener of listeners) {
          listener(mediaQuery)
        }
      },
    }
  }

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mountShell() {
    return mount(AppShell, {
      global: {
        stubs: {
          AppHeader: {
            props: ['sidebarOpen'],
            emits: ['toggle-sidebar'],
            template: '<button class="header-toggle" @click="$emit(\'toggle-sidebar\')">toggle</button>',
          },
          AppSidebar: {
            props: ['sidebarOpen'],
            emits: ['close-sidebar'],
            template: '<aside class="sidebar-stub" :data-open="String(sidebarOpen)"></aside>',
          },
          AppFooter: true,
          RouterView: true,
        },
      },
    })
  }

  it('opens the mobile sidebar backdrop when the header toggles it', async () => {
    mockMatchMedia(true)
    const wrapper = mountShell()

    await wrapper.get('.header-toggle').trigger('click')

    expect(wrapper.get('.shell-backdrop').classes()).toContain('shell-backdrop-open')
    expect(wrapper.get('.sidebar-stub').attributes('data-open')).toBe('true')

    wrapper.unmount()
  })

  it('closes the mobile sidebar when the backdrop is clicked', async () => {
    mockMatchMedia(true)
    const wrapper = mountShell()

    await wrapper.get('.header-toggle').trigger('click')
    await wrapper.get('.shell-backdrop').trigger('click')

    expect(wrapper.get('.shell-backdrop').classes()).not.toContain('shell-backdrop-open')
    expect(wrapper.get('.sidebar-stub').attributes('data-open')).toBe('false')

    wrapper.unmount()
  })

  it('hides the shell content from assistive technology while the mobile sidebar is open', async () => {
    mockMatchMedia(true)
    const wrapper = mountShell()

    await wrapper.get('.header-toggle').trigger('click')

    expect(wrapper.get('.shell-content').attributes('aria-hidden')).toBe('true')
    expect(wrapper.get('.shell-content').attributes()).toHaveProperty('inert')

    wrapper.unmount()
  })

  it('closes the mobile sidebar and restores body scrolling after resizing to desktop', async () => {
    const viewport = mockMatchMedia(true)
    const wrapper = mountShell()

    await wrapper.get('.header-toggle').trigger('click')
    expect(document.body.style.overflow).toBe('hidden')

    viewport.setMatches(false)
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.sidebar-stub').attributes('data-open')).toBe('false')
    expect(wrapper.get('.shell-backdrop').classes()).not.toContain('shell-backdrop-open')
    expect(document.body.style.overflow).toBe('')

    wrapper.unmount()
  })
})