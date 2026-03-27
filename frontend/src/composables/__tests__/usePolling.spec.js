import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { usePolling } from '@/composables/usePolling.js'

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('calls fetch immediately and at interval', async () => {
    const fetchFn = vi.fn().mockResolvedValue({ state: 'RUNNING' })

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, { intervalMs: 3000 })
        polling.start()
        return {}
      },
    })

    mount(Comp)

    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(2)
  })

  it('auto-stops on terminal response', async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce({ state: 'RUNNING' })
      .mockResolvedValueOnce({ state: 'COMPLETED' })
      .mockResolvedValue({ state: 'COMPLETED' })

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, {
          intervalMs: 3000,
          isTerminal: (response) => response?.state === 'COMPLETED',
        })
        polling.start()
        return { polling }
      },
    })

    const wrapper = mount(Comp)
    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(2)

    expect(wrapper.vm.polling.isPolling.value).toBe(false)
  })

  it('cleans up interval on unmount', async () => {
    const fetchFn = vi.fn().mockResolvedValue({ state: 'RUNNING' })

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, { intervalMs: 3000 })
        polling.start()
        return { polling }
      },
    })

    const wrapper = mount(Comp)
    await Promise.resolve()
    expect(wrapper.vm.polling.isPolling.value).toBe(true)

    wrapper.unmount()

    await vi.advanceTimersByTimeAsync(9000)
    expect(fetchFn).toHaveBeenCalledTimes(1)
  })
})
