import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '@/i18n/index.js'
import AppHeader from '@/components/layout/AppHeader.vue'
import { useAuthStore } from '@/stores/auth.js'

describe('AppHeader help modal', () => {
  let pinia

  beforeEach(() => {
    vi.useFakeTimers()
    pinia = createPinia()
    setActivePinia(pinia)

    const authStore = useAuthStore()
    authStore.username = 'processor01'
    authStore.roles = ['processor']
    authStore.expiresAt = Date.now() + 10 * 60 * 1000
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  function mountHeader() {
    return mount(AppHeader, {
      global: {
        plugins: [i18n, pinia],
        stubs: {
          ThemeSwitcher: true,
        },
      },
    })
  }

  it('shows a help trigger and opens the modal iframe', async () => {
    const wrapper = mountHeader()

    await wrapper.find('.btn-help').trigger('click')

    const dialog = wrapper.get('[role="dialog"]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    const iframe = wrapper.get('iframe.help-frame')
    expect(iframe.attributes('src')).toBe('/help/manual.html')
    wrapper.unmount()
  })

  it('closes the help modal on Escape', async () => {
    const wrapper = mountHeader()

    await wrapper.find('.btn-help').trigger('click')
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })
})