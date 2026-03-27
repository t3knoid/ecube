import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { usePolling } from '@/composables/usePolling.js'

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
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

  it('skips interval tick when a fetch is already in flight (single-flight default)', async () => {
    let resolveFirst
    const first = new Promise((r) => (resolveFirst = r))
    const fetchFn = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValue({ state: 'RUNNING' })

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, { intervalMs: 3000 })
        polling.start()
        return {}
      },
    })

    mount(Comp)

    // First tick is in flight (unresolved).
    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Interval fires while first tick is still in flight — should be skipped.
    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Resolve the first fetch; next interval should proceed normally.
    resolveFirst({ state: 'RUNNING' })
    await Promise.resolve()

    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(2)
  })

  it('allows overlapping fetches and drops stale responses when allowOverlap is true', async () => {
    let resolveFirst
    const first = new Promise((r) => (resolveFirst = r))
    const second = Promise.resolve({ state: 'SECOND' })
    const fetchFn = vi.fn().mockReturnValueOnce(first).mockReturnValueOnce(second)

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, { intervalMs: 3000, allowOverlap: true })
        polling.start()
        return { polling }
      },
    })

    const wrapper = mount(Comp)

    // Immediate first tick; in flight and unresolved.
    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Interval fires — overlap allowed so second fetch starts.
    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(2)

    // Let the second resolve first.
    await Promise.resolve()
    expect(wrapper.vm.polling.lastResponse.value).toEqual({ state: 'SECOND' })

    // Resolve the first (stale — lower seq) — lastResponse must NOT regress.
    resolveFirst({ state: 'FIRST' })
    await Promise.resolve()
    expect(wrapper.vm.polling.lastResponse.value).toEqual({ state: 'SECOND' })
  })

  it('does not commit in-flight response after stop', async () => {
    let resolveFirst
    const first = new Promise((r) => (resolveFirst = r))
    const fetchFn = vi.fn().mockReturnValueOnce(first)

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
    expect(fetchFn).toHaveBeenCalledTimes(1)

    wrapper.vm.polling.stop()
    expect(wrapper.vm.polling.isPolling.value).toBe(false)

    resolveFirst({ state: 'RUNNING' })
    await Promise.resolve()

    expect(wrapper.vm.polling.lastResponse.value).toBeNull()
    expect(wrapper.vm.polling.lastError.value).toBeNull()
  })

  it('can restart even if previous run has unresolved in-flight request', async () => {
    let resolveFirst
    const first = new Promise((r) => (resolveFirst = r))
    const fetchFn = vi
      .fn()
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce({ state: 'RUNNING' })

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, { intervalMs: 3000 })
        return { polling }
      },
    })

    const wrapper = mount(Comp)

    wrapper.vm.polling.start()
    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    // Stop while the first run is still in-flight.
    wrapper.vm.polling.stop()
    expect(wrapper.vm.polling.isPolling.value).toBe(false)

    // Restart should not be blocked by the old unresolved request.
    wrapper.vm.polling.start()
    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(2)

    resolveFirst({ state: 'OLD' })
    await Promise.resolve()

    expect(wrapper.vm.polling.lastResponse.value).toEqual({ state: 'RUNNING' })
  })

  it('stops overlap polling interval when stopped', async () => {
    const fetchFn = vi.fn().mockResolvedValue({ state: 'RUNNING' })

    const Comp = defineComponent({
      template: '<div />',
      setup() {
        const polling = usePolling(fetchFn, { intervalMs: 3000, allowOverlap: true })
        polling.start()
        return { polling }
      },
    })

    const wrapper = mount(Comp)

    await Promise.resolve()
    expect(fetchFn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(3000)
    expect(fetchFn).toHaveBeenCalledTimes(2)

    wrapper.vm.polling.stop()
    expect(wrapper.vm.polling.isPolling.value).toBe(false)

    await vi.advanceTimersByTimeAsync(9000)
    expect(fetchFn).toHaveBeenCalledTimes(2)
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
