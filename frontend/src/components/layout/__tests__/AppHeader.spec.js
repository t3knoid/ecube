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
      attachTo: document.body,
      global: {
        plugins: [i18n, pinia],
        stubs: {
          ThemeSwitcher: true,
        },
      },
    })
  }

  function populateHelpFrame(wrapper) {
    const iframe = wrapper.get('iframe.help-frame').element
    const frameDocument = document.implementation.createHTMLDocument('help-frame')
    let frameActiveElement = frameDocument.body

    Object.defineProperty(iframe, 'contentDocument', {
      configurable: true,
      value: frameDocument,
    })

    Object.defineProperty(frameDocument, 'activeElement', {
      configurable: true,
      get() {
        return frameActiveElement
      },
    })

    frameDocument.body.innerHTML = `
      <a href="#toc" id="frame-first">Table of Contents</a>
      <a href="#top" id="frame-last">Back to top</a>
    `

    frameDocument.body.focus = () => {
      frameActiveElement = frameDocument.body
    }

    for (const focusable of frameDocument.querySelectorAll('a, button, input, select, textarea, [tabindex]')) {
      focusable.focus = () => {
        frameActiveElement = focusable
      }
    }

    iframe.dispatchEvent(new Event('load'))

    return {
      iframe,
      frameDocument,
      firstLink: frameDocument.getElementById('frame-first'),
      lastLink: frameDocument.getElementById('frame-last'),
    }
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

  it('cycles focus between the help content and close button', async () => {
    const wrapper = mountHeader()

    await wrapper.find('.btn-help').trigger('click')
    const { firstLink } = populateHelpFrame(wrapper)
    await wrapper.vm.$nextTick()

    const closeButton = wrapper.get('.btn-help-close').element
    expect(document.activeElement).toBe(closeButton)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    expect(firstLink).toBeTruthy()
    expect(firstLink.ownerDocument.activeElement).toBe(firstLink)

    firstLink.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }))
    expect(document.activeElement).toBe(closeButton)

    wrapper.unmount()
  })

  it('returns focus to the help trigger after closing from the iframe', async () => {
    const wrapper = mountHeader()
    const helpTrigger = wrapper.get('.btn-help')

    helpTrigger.element.focus()
    await helpTrigger.trigger('click')
    const { firstLink } = populateHelpFrame(wrapper)
    await wrapper.vm.$nextTick()

    firstLink.focus()
    firstLink.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(document.activeElement).toBe(helpTrigger.element)

    wrapper.unmount()
  })

  it('emits a sidebar toggle request from the hamburger button', async () => {
    const wrapper = mountHeader()

    await wrapper.get('.btn-sidebar-toggle').trigger('click')

    expect(wrapper.emitted('toggle-sidebar')?.[0]).toEqual([])
    wrapper.unmount()
  })
})