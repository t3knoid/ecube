import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import i18n from '@/i18n/index.js'
import AppSidebar from '@/components/layout/AppSidebar.vue'

const authState = vi.hoisted(() => ({
  roles: [],
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => ({
    hasAnyRole: (requiredRoles) => requiredRoles.some((role) => authState.roles.includes(role)),
  }),
}))

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

function mountSidebar(props = {}) {
  return mount(AppSidebar, {
    props: { sidebarOpen: true, ...props },
    global: {
      plugins: [i18n],
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a><slot /></a>',
        },
      },
    },
  })
}

describe('AppSidebar', () => {
  beforeEach(() => {
    authState.roles = []
  })

  it('hides the closed sidebar from assistive technology on mobile', async () => {
    mockMatchMedia(true)

    const wrapper = mountSidebar({ sidebarOpen: false })
    await nextTick()

    expect(wrapper.attributes('aria-hidden')).toBe('true')
    expect(wrapper.attributes()).toHaveProperty('inert')
  })

  it('keeps the sidebar available when opened on mobile', async () => {
    mockMatchMedia(true)

    const wrapper = mountSidebar({ sidebarOpen: true })
    await nextTick()

    expect(wrapper.attributes('aria-hidden')).toBeUndefined()
    expect(wrapper.attributes('inert')).toBeUndefined()
  })

  it('keeps the sidebar available on desktop when closed', async () => {
    mockMatchMedia(false)

    const wrapper = mountSidebar({ sidebarOpen: false })
    await nextTick()

    expect(wrapper.attributes('aria-hidden')).toBeUndefined()
    expect(wrapper.attributes('inert')).toBeUndefined()
  })

  it('shows Configuration for managers without Admin or Users', () => {
    authState.roles = ['manager']

    const wrapper = mountSidebar()
    expect(wrapper.text()).toContain(i18n.global.t('nav.configuration'))
    expect(wrapper.text()).not.toContain(i18n.global.t('nav.admin'))
    expect(wrapper.text()).not.toContain(i18n.global.t('nav.users'))
  })

  it('shows Configuration, Admin, and Users for admins', () => {
    authState.roles = ['admin']

    const wrapper = mountSidebar()
    expect(wrapper.text()).toContain(i18n.global.t('nav.configuration'))
    expect(wrapper.text()).toContain(i18n.global.t('nav.admin'))
    expect(wrapper.text()).toContain(i18n.global.t('nav.users'))
  })

  it('hides Configuration and Admin for processors', () => {
    authState.roles = ['processor']

    const wrapper = mountSidebar()
    expect(wrapper.text()).not.toContain(i18n.global.t('nav.configuration'))
    expect(wrapper.text()).not.toContain(i18n.global.t('nav.admin'))
  })
})