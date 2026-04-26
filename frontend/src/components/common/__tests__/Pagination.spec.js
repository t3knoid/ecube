import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import Pagination from '@/components/common/Pagination.vue'
import i18n from '@/i18n'

describe('Pagination', () => {
  it('jumps to the next 10-page window when page-window mode is enabled', async () => {
    const wrapper = mount(Pagination, {
      props: {
        page: 1,
        pageSize: 40,
        total: 480,
        showPageWindow: true,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.findAll('.page-number-btn').map((node) => node.text())).toEqual([
      '1', '2', '3', '4', '5', '6', '7', '8', '9', '10',
    ])

    await wrapper.find('.page-window-next').trigger('click')

    expect(wrapper.emitted('update:page')?.[0]).toEqual([11])
  })

  it('renders the active 10-page window for the current page', () => {
    const wrapper = mount(Pagination, {
      props: {
        page: 12,
        pageSize: 40,
        total: 800,
        showPageWindow: true,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.findAll('.page-number-btn').map((node) => node.text())).toEqual([
      '11', '12', '13', '14', '15', '16', '17', '18', '19', '20',
    ])
    expect(wrapper.find('.page-number-btn--active').text()).toBe('12')
    expect(wrapper.find('.page-number-btn--active').attributes('aria-current')).toBe('page')
  })
})