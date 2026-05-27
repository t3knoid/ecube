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
    expect(wrapper.find('.page-window-next').attributes('aria-label')).toBe('Next 10 pages')

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

  it('supports a 5-page shortcut window', async () => {
    const wrapper = mount(Pagination, {
      props: {
        page: 1,
        pageSize: 40,
        total: 480,
        showPageWindow: true,
        windowSize: 5,
        jumpSize: 5,
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.findAll('.page-number-btn').map((node) => node.text())).toEqual([
      '1', '2', '3', '4', '5',
    ])
    expect(wrapper.find('.page-window-prev').attributes('aria-label')).toBe('Previous 5 pages')
    expect(wrapper.find('.page-window-next').attributes('aria-label')).toBe('Next 5 pages')

    await wrapper.find('.page-window-next').trigger('click')

    expect(wrapper.emitted('update:page')?.[0]).toEqual([6])
  })

  it('supports explicit first and last shortcuts when enabled', async () => {
    const wrapper = mount(Pagination, {
      props: {
        page: 6,
        pageSize: 40,
        total: 480,
        showPageWindow: true,
        showBoundaryShortcuts: true,
      },
      global: { plugins: [i18n] },
    })

    const firstButton = wrapper.find('.page-boundary-first')
    const lastButton = wrapper.find('.page-boundary-last')

    expect(firstButton.text()).toBe('First')
    expect(lastButton.text()).toBe('Last')

    await firstButton.trigger('click')
    await lastButton.trigger('click')

    expect(wrapper.emitted('update:page')).toEqual([[1], [12]])
  })

  it('disables explicit first and last shortcuts at the pagination boundaries', () => {
    const firstPageWrapper = mount(Pagination, {
      props: {
        page: 1,
        pageSize: 40,
        total: 480,
        showPageWindow: true,
        showBoundaryShortcuts: true,
      },
      global: { plugins: [i18n] },
    })

    expect(firstPageWrapper.find('.page-boundary-first').attributes('disabled')).toBeDefined()
    expect(firstPageWrapper.find('.page-boundary-last').attributes('disabled')).toBeUndefined()

    const lastPageWrapper = mount(Pagination, {
      props: {
        page: 12,
        pageSize: 40,
        total: 480,
        showPageWindow: true,
        showBoundaryShortcuts: true,
      },
      global: { plugins: [i18n] },
    })

    expect(lastPageWrapper.find('.page-boundary-first').attributes('disabled')).toBeUndefined()
    expect(lastPageWrapper.find('.page-boundary-last').attributes('disabled')).toBeDefined()
  })
})