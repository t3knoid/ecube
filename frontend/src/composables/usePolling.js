import { onBeforeUnmount, ref } from 'vue'

export function usePolling(fetchFn, options = {}) {
  const {
    intervalMs = 3000,
    isTerminal = () => false,
    immediate = true,
    allowOverlap = false,
  } = options

  const isPolling = ref(false)
  const lastResponse = ref(null)
  const lastError = ref(null)

  let timer = null
  let inFlight = false
  let seq = 0

  async function tick() {
    if (!allowOverlap && inFlight) return

    const currentSeq = ++seq
    inFlight = true

    try {
      const response = await fetchFn()

      // Discard stale responses when overlap is allowed.
      if (allowOverlap && currentSeq !== seq) return

      lastResponse.value = response
      lastError.value = null

      if (isTerminal(response)) {
        stop()
      }

      return response
    } catch (error) {
      if (!allowOverlap || currentSeq === seq) {
        lastError.value = error
      }
      throw error
    } finally {
      if (!allowOverlap || currentSeq === seq) {
        inFlight = false
      }
    }
  }

  function start() {
    if (isPolling.value) return

    isPolling.value = true

    if (immediate) {
      // Fire and forget initial fetch; callers can use lastError for failures.
      tick().catch(() => {})
    }

    timer = setInterval(() => {
      tick().catch(() => {})
    }, intervalMs)
  }

  function stop() {
    isPolling.value = false
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onBeforeUnmount(stop)

  return {
    start,
    stop,
    tick,
    isPolling,
    lastResponse,
    lastError,
  }
}
