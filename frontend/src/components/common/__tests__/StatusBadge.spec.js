import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StatusBadge from '@/components/common/StatusBadge.vue'

describe('StatusBadge', () => {
  it('renders success style for completed status', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'COMPLETED' } })
    expect(wrapper.text()).toContain('COMPLETED')
    expect(wrapper.classes()).toContain('badge-success')
  })

  it('renders warning style for running status', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'RUNNING' } })
    expect(wrapper.classes()).toContain('badge-warning')
  })

  it('renders danger style for failed status', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'FAILED' } })
    expect(wrapper.classes()).toContain('badge-danger')
  })

  it('uses custom label when provided', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'RUNNING', label: 'In Progress' } })
    expect(wrapper.text()).toContain('In Progress')
  })
})
