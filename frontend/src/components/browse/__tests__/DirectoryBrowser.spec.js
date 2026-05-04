import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import i18n from '@/i18n/index.js'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'

const mocks = vi.hoisted(() => ({
  getDirectory: vi.fn(),
  getDirectoryByMountId: vi.fn(),
}))

vi.mock('@/api/browse.js', () => ({
  getDirectory: (...args) => mocks.getDirectory(...args),
  getDirectoryByMountId: (...args) => mocks.getDirectoryByMountId(...args),
}))

function mountView(props = {}) {
  return mount(DirectoryBrowser, {
    props: {
      mountPath: '/mnt/ecube/1',
      rootLabel: '',
      ...props,
    },
    global: {
      plugins: [i18n],
    },
  })
}

describe('DirectoryBrowser', () => {
  beforeEach(() => {
    mocks.getDirectory.mockReset()
    mocks.getDirectoryByMountId.mockReset()
    mocks.getDirectory.mockImplementation((_mountPath, subdir) => {
      if (subdir === 'DCIM') {
        return Promise.resolve({
          entries: [
            { name: 'IMG_0001.JPG', type: 'file', size_bytes: 1024, modified_at: '2026-05-03T12:00:00Z' },
          ],
          has_more: false,
        })
      }

      return Promise.resolve({
        entries: [
          { name: 'DCIM', type: 'directory', size_bytes: null, modified_at: '2026-05-03T12:00:00Z' },
        ],
        has_more: false,
      })
    })
  })

  it('hides the root crumb at the drive root when the root label is intentionally blank', async () => {
    const wrapper = mountView()
    await flushPromises()

    const breadcrumbButtons = wrapper.findAll('.breadcrumb > .crumb-btn')
    expect(breadcrumbButtons).toHaveLength(0)
  })

  it('shows a slash root crumb at the root when explicitly requested', async () => {
    const wrapper = mountView({ showRootCrumbAtRoot: true })
    await flushPromises()

    const breadcrumbButtons = wrapper.findAll('.breadcrumb > .crumb-btn')
    expect(breadcrumbButtons).toHaveLength(1)
    expect(breadcrumbButtons[0].text()).toBe('/')
  })

  it('shows a slash root crumb after navigating into a subdirectory and allows returning to root', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.entry-nav-btn').trigger('click')
    await flushPromises()

    const breadcrumbButtons = wrapper.findAll('.breadcrumb > button.crumb-btn')
    expect(breadcrumbButtons).toHaveLength(1)
    expect(breadcrumbButtons[0].text()).toBe('/')
    expect(wrapper.find('.crumb-current').text()).toBe('DCIM')

    await breadcrumbButtons[0].trigger('click')
    await flushPromises()

    expect(wrapper.find('.crumb-current').exists()).toBe(false)
    expect(wrapper.findAll('.breadcrumb > button.crumb-btn')).toHaveLength(0)
    expect(mocks.getDirectory).toHaveBeenLastCalledWith('/mnt/ecube/1', '', 1, 100)
  })

  it('renders a single leading slash in breadcrumbs for mount-id browsing with a blank root label', async () => {
    mocks.getDirectoryByMountId.mockImplementation((_mountId, subdir) => {
      if (subdir === 'ev1') {
        return Promise.resolve({
          entries: [
            { name: 'VOL1', type: 'directory', size_bytes: null, modified_at: '2026-05-03T12:00:00Z' },
          ],
          has_more: false,
        })
      }

      if (subdir === 'ev1/VOL1') {
        return Promise.resolve({
          entries: [
            { name: 'DATA', type: 'directory', size_bytes: null, modified_at: '2026-05-03T12:00:00Z' },
          ],
          has_more: false,
        })
      }

      return Promise.resolve({
        entries: [
          { name: 'ev1', type: 'directory', size_bytes: null, modified_at: '2026-05-03T12:00:00Z' },
        ],
        has_more: false,
      })
    })

    const wrapper = mountView({ mountPath: '', mountId: 11, rootLabel: '' })
    await flushPromises()

    await wrapper.find('.entry-nav-btn').trigger('click')
    await flushPromises()
    await wrapper.find('.entry-nav-btn').trigger('click')
    await flushPromises()

    const breadcrumbText = wrapper.find('.breadcrumb').text()
    expect(breadcrumbText.startsWith('//')).toBe(false)
    expect(breadcrumbText).toBe('/ev1/VOL1')
  })
})