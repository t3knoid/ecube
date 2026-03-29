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

  it('emits page-change and update:page from pagination controls', async () => {
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

    const nextButton = wrapper.findAll('.table-pagination .btn')[1]
    await nextButton.trigger('click')

    expect(wrapper.emitted('update:page')?.[0]).toEqual([2])
    expect(wrapper.emitted('page-change')?.[0]).toEqual([2])
  })
})
