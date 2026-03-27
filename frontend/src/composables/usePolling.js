import { onBeforeUnmount, ref } from 'vue'

export function usePolling(fetchFn, options = {}) {
  const {
    intervalMs = 3000,
    isTerminal = () => false,
    immediate = true,
  } = options

  const isPolling = ref(false)
  const lastResponse = ref(null)
  const lastError = ref(null)

  let timer = null

  async function tick() {
    try {
      const response = await fetchFn()
      lastResponse.value = response
      lastError.value = null

      if (isTerminal(response)) {
        stop()
      }

      return response
    } catch (error) {
      lastError.value = error
      throw error
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
