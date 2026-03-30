import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import i18n from '@/i18n'
import ProgressBar from '@/components/common/ProgressBar.vue'

describe('ProgressBar', () => {
  it('computes percent from value and total', () => {
    const wrapper = mount(ProgressBar, { props: { value: 25, total: 100 }, global: { plugins: [i18n] } })
    expect(wrapper.text()).toContain('25%')
    expect(wrapper.find('.progress-bar').attributes('style')).toContain('25%')
  })

  it('clamps percentage to 100', () => {
    const wrapper = mount(ProgressBar, { props: { value: 200, total: 100 }, global: { plugins: [i18n] } })
    expect(wrapper.text()).toContain('100%')
  })

  it('renders custom label', () => {
    const wrapper = mount(ProgressBar, { props: { value: 1, total: 3, label: 'Copying' }, global: { plugins: [i18n] } })
    expect(wrapper.text()).toContain('Copying')
  })

  it('uses localized default aria-label when ariaLabel prop is omitted', () => {
    const wrapper = mount(ProgressBar, { props: { value: 50, total: 100 }, global: { plugins: [i18n] } })
    expect(wrapper.find('[role="progressbar"]').attributes('aria-label')).toBe('Progress')
  })

  it('uses caller-supplied ariaLabel over the default', () => {
    const wrapper = mount(ProgressBar, { props: { value: 50, total: 100, ariaLabel: 'File copy progress' }, global: { plugins: [i18n] } })
    expect(wrapper.find('[role="progressbar"]').attributes('aria-label')).toBe('File copy progress')
  })
})
