import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppShell from '@/components/layout/AppShell.vue'

describe('AppShell responsive sidebar', () => {
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
    const wrapper = mountShell()

    await wrapper.get('.header-toggle').trigger('click')

    expect(wrapper.get('.shell-backdrop').classes()).toContain('shell-backdrop-open')
    expect(wrapper.get('.sidebar-stub').attributes('data-open')).toBe('true')

    wrapper.unmount()
  })

  it('closes the mobile sidebar when the backdrop is clicked', async () => {
    const wrapper = mountShell()

    await wrapper.get('.header-toggle').trigger('click')
    await wrapper.get('.shell-backdrop').trigger('click')

    expect(wrapper.get('.shell-backdrop').classes()).not.toContain('shell-backdrop-open')
    expect(wrapper.get('.sidebar-stub').attributes('data-open')).toBe('false')

    wrapper.unmount()
  })
})