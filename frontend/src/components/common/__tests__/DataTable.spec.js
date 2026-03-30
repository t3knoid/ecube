import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DataTable from '@/components/common/DataTable.vue'
import i18n from '@/i18n'

const columns = [
  { key: 'id', label: 'ID', align: 'right', sortable: true },
  { key: 'name', label: 'Name', sortable: true },
]

const rows = [
  { id: 1, name: 'Alpha' },
  { id: 2, name: 'Beta' },
]

describe('DataTable', () => {
  it('renders provided rows', () => {
    const wrapper = mount(DataTable, {
      props: { columns, rows },
      global: { plugins: [i18n] },
    })

    expect(wrapper.text()).toContain('Alpha')
    expect(wrapper.text()).toContain('Beta')
  })

  it('emits sort-change on sortable header click', async () => {
    const wrapper = mount(DataTable, {
      props: { columns, rows, sortable: true, sortKey: 'name', sortDir: 'asc' },
      global: { plugins: [i18n] },
    })

    const buttons = wrapper.findAll('th .sort-button')
    await buttons[1].trigger('click')

    expect(wrapper.emitted('sort-change')?.[0]).toEqual([{ key: 'name', dir: 'desc' }])
  })

  it('sets aria-sort on sortable columns and hides indicator from screen readers', () => {
    const wrapper = mount(DataTable, {
      props: { columns, rows, sortable: true, sortKey: 'name', sortDir: 'asc' },
      global: { plugins: [i18n] },
    })

    const ths = wrapper.findAll('th')
    // Active ascending sort column
    expect(ths[1].attributes('aria-sort')).toBe('ascending')
    // Inactive sortable column
    expect(ths[0].attributes('aria-sort')).toBe('none')
    // Sort indicator glyph is hidden from AT
    expect(ths[1].find('.sort-indicator').attributes('aria-hidden')).toBe('true')
  })

  it('emits page-change and update:page when Pagination component triggers page navigation', async () => {
    const wrapper = mount(DataTable, {
      props: {
        columns,
        rows,
        page: 1,
        pageSize: 1,
        total: 3,
      },
      global: { plugins: [i18n] },
    })

    const nextButton = wrapper.findAll('.pagination-wrap .btn')[1]
    await nextButton.trigger('click')

    expect(wrapper.emitted('update:page')?.[0]).toEqual([2])
    expect(wrapper.emitted('page-change')?.[0]).toEqual([2])
  })
})
