import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
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
})
