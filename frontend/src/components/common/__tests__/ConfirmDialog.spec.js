import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

describe('ConfirmDialog', () => {
  it('renders title and message when open', () => {
    const wrapper = mount(ConfirmDialog, {
      props: {
        modelValue: true,
        title: 'Delete item?',
        message: 'This action cannot be undone.',
        confirmLabel: 'Delete',
        cancelLabel: 'Cancel',
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Delete item?')
    expect(wrapper.text()).toContain('This action cannot be undone.')
    wrapper.unmount()
  })

  it('emits confirm when confirm button is clicked', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: {
        modelValue: true,
        title: 'Confirm',
        confirmLabel: 'Yes',
        cancelLabel: 'No',
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    await wrapper.findAll('button')[1].trigger('click')
    expect(wrapper.emitted('confirm')).toBeTruthy()
    wrapper.unmount()
  })

  it('emits update:modelValue false on cancel click', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: {
        modelValue: true,
        title: 'Confirm',
        confirmLabel: 'Yes',
        cancelLabel: 'No',
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
    wrapper.unmount()
  })

  it('closes via Escape when dialog is open on initial mount', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: {
        modelValue: true,
        title: 'Confirm',
        confirmLabel: 'Yes',
        cancelLabel: 'No',
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    await nextTick()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
    wrapper.unmount()
  })

  it('still allows cancel dismissal while busy', async () => {
    const wrapper = mount(ConfirmDialog, {
      props: {
        modelValue: true,
        title: 'Confirm',
        confirmLabel: 'Yes',
        cancelLabel: 'No',
        busy: true,
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([false])
    wrapper.unmount()
  })

  it('traps focus inside the dialog when tabbing', async () => {
    const wrapper = mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        modelValue: true,
        title: 'Confirm',
        confirmLabel: 'Yes',
        cancelLabel: 'No',
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    await nextTick()

    const buttons = wrapper.findAll('button')
    expect(document.activeElement).toBe(buttons[0].element)

    buttons[1].element.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(buttons[0].element)

    buttons[0].element.focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(buttons[1].element)

    wrapper.unmount()
  })

  it('restores focus to the triggering element when closed', async () => {
    const trigger = document.createElement('button')
    trigger.textContent = 'Open dialog'
    document.body.appendChild(trigger)
    trigger.focus()

    const wrapper = mount(ConfirmDialog, {
      attachTo: document.body,
      props: {
        modelValue: true,
        title: 'Confirm',
        confirmLabel: 'Yes',
        cancelLabel: 'No',
      },
      global: {
        stubs: {
          teleport: true,
        },
      },
    })

    await nextTick()
    await wrapper.findAll('button')[0].trigger('click')
    await wrapper.setProps({ modelValue: false })
    await nextTick()

    expect(document.activeElement).toBe(trigger)

    wrapper.unmount()
    trigger.remove()
  })
})
