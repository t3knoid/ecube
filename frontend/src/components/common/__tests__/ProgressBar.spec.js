import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProgressBar from '@/components/common/ProgressBar.vue'

describe('ProgressBar', () => {
  it('computes percent from value and total', () => {
    const wrapper = mount(ProgressBar, { props: { value: 25, total: 100 } })
    expect(wrapper.text()).toContain('25%')
    expect(wrapper.find('.progress-bar').attributes('style')).toContain('25%')
  })

  it('clamps percentage to 100', () => {
    const wrapper = mount(ProgressBar, { props: { value: 200, total: 100 } })
    expect(wrapper.text()).toContain('100%')
  })

  it('renders custom label', () => {
    const wrapper = mount(ProgressBar, { props: { value: 1, total: 3, label: 'Copying' } })
    expect(wrapper.text()).toContain('Copying')
  })
})
